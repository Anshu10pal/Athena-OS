"""Phase D: background job execution.

jobs.py deliberately opens its own SessionLocal() inside a daemon thread
(SQLAlchemy sessions aren't thread-safe to share with the request that
started the job). That makes the standard `db_session` fixture unusable here
-- it's a `sqlite:///:memory:` engine, and :memory: SQLite connections are
per-thread-isolated by default (a fresh, empty database per connection), so
a background thread reading through it would see nothing at all. These tests
use a real temp-file-backed engine instead, so cross-thread visibility is
genuinely exercised, not assumed.
"""
import shutil
import time
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import RepoJob
from app.services.codebase import jobs
from app.services.codebase.ingest import ingest_repo
from app.services.codebase.ranking import rank_repo
from app.services.codebase.registry import register_from_path


def _write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


@pytest.fixture()
def job_db(tmp_path, monkeypatch):
    db_path = tmp_path / "job_test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    test_session_local = sessionmaker(bind=engine)
    monkeypatch.setattr("app.services.codebase.jobs.SessionLocal", test_session_local)
    session = test_session_local()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _wait_for(job_db, job_id, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job_db.expire_all()
        job = job_db.get(RepoJob, job_id)
        if job is not None and job.status in ("done", "failed"):
            return job
        time.sleep(0.1)
    raise AssertionError(f"job {job_id} did not finish within {timeout}s")


class TestProgressCallback:
    def test_ingest_calls_on_progress_with_expected_stages(self, db_session, tmp_path):
        root = tmp_path / "repo"
        _write(root / "a.py", "def foo():\n    return 1\n")
        repo = register_from_path(db_session, str(root))

        stages = []
        ingest_repo(db_session, repo, on_progress=lambda stage, cur, total, msg: stages.append(stage))

        assert "discovering" in stages
        assert "parsing" in stages
        assert "resolving" in stages
        assert "ingest_done" in stages

    def test_rank_calls_on_progress_with_expected_stages(self, db_session, tmp_path):
        root = tmp_path / "repo"
        _write(root / "a.py", "def foo():\n    return 1\n")
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)

        stages = []
        rank_repo(db_session, repo, on_progress=lambda stage, cur, total, msg: stages.append(stage))

        assert "ranking_graph" in stages
        assert "ranking_history" in stages
        assert "ranking_scoring" in stages
        assert "ranking_done" in stages

    def test_on_progress_defaults_to_noop(self, db_session, tmp_path):
        root = tmp_path / "repo"
        _write(root / "a.py", "def foo():\n    return 1\n")
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)  # must not raise without an on_progress arg
        rank_repo(db_session, repo)


class TestJobRunner:
    def test_job_runs_to_completion(self, job_db, tmp_path):
        root = tmp_path / "repo"
        _write(root / "a.py", "def foo():\n    return 1\n")
        _write(root / "b.py", "from a import foo\n")
        repo = register_from_path(job_db, str(root))

        job_id = jobs.start_job(repo.id)
        job = _wait_for(job_db, job_id)

        assert job.status == "done"
        assert job.result["files_total"] == 2
        assert job.progress_current == job.progress_total
        assert job.started_at is not None
        assert job.finished_at is not None

    def test_zero_llm_calls_across_the_whole_pipeline(self, job_db, tmp_path, monkeypatch):
        """Acceptance criterion: zero LLM calls, proven end-to-end -- resync
        (skipped for a `local` repo) + ingest + rank, run for real in the
        background thread, with the LLM client patched to blow up on any use.
        A prior test only proved this for ingest_repo() in isolation."""
        root = tmp_path / "repo"
        _write(root / "a.py", "def foo():\n    return 1\n")
        _write(root / "b.py", "from a import foo\n")
        repo = register_from_path(job_db, str(root))

        def _boom(*a, **kw):
            raise AssertionError("LLM was called during a codebase-agent job")

        monkeypatch.setattr("app.core.llm.chat", _boom)
        monkeypatch.setattr("app.core.llm.chat_json", _boom)
        monkeypatch.setattr("app.core.llm.chat_stream", _boom)

        job_id = jobs.start_job(repo.id)
        job = _wait_for(job_db, job_id)

        assert job.status == "done"  # would be "failed" with our _boom's AssertionError if the LLM were ever touched

    def test_job_failure_is_recorded(self, job_db, tmp_path):
        root = tmp_path / "repo"
        root.mkdir()
        repo = register_from_path(job_db, str(root))
        shutil.rmtree(root)  # ingest_repo will raise: "Repo root does not exist"

        job_id = jobs.start_job(repo.id)
        job = _wait_for(job_db, job_id)

        assert job.status == "failed"
        assert job.error

    def test_start_job_does_not_duplicate_an_in_flight_job(self, job_db, tmp_path):
        root = tmp_path / "repo"
        _write(root / "a.py", "def foo():\n    return 1\n")
        repo = register_from_path(job_db, str(root))

        running = RepoJob(repo_id=repo.id, status="running", stage="parsing")
        job_db.add(running)
        job_db.commit()
        job_db.refresh(running)

        job_id = jobs.start_job(repo.id)
        assert job_id == running.id
        count = job_db.query(RepoJob).filter(RepoJob.repo_id == repo.id).count()
        assert count == 1

    def test_start_job_rejects_unknown_repo(self, job_db):
        with pytest.raises(ValueError):
            jobs.start_job(999999)


class TestHealthStageInThePipeline:
    """Health runs last and is isolated. Its failure must never fail the job
    or undo ingest/rank, and it must not manufacture a duplicate snapshot on
    an unchanged working tree."""

    def _repo(self, job_db, tmp_path):
        root = tmp_path / "repo"
        _write(root / "pkg" / "core.py",
               '"""Core."""\n\n\n'
               "def run(a, b):\n"
               "    if a:\n        return 1\n"
               "    if b:\n        return 2\n"
               "    return 0\n\n\n"
               "def classify(v):\n"
               "    if v > 10:\n        return 'high'\n"
               "    return 'low'\n")
        _write(root / "pkg" / "util.py",
               "from pkg.core import run, classify\n\n\n"
               "def helper(x):\n"
               "    value = run(x, False)\n"
               "    label = classify(value)\n"
               "    if label == 'high':\n        return value * 2\n"
               "    return value\n\n\n"
               "def describe(x):\n"
               "    return f'{x}: {helper(x)}'\n")
        return register_from_path(job_db, str(root))

    def test_a_snapshot_is_created_by_the_pipeline(self, job_db, tmp_path):
        from app.db.models import CodeHealthSnapshot

        repo = self._repo(job_db, tmp_path)
        job = _wait_for(job_db, jobs.start_job(repo.id))
        assert job.status == "done"
        assert job.result["health"]["status"] == "created"
        assert job_db.query(CodeHealthSnapshot).filter(
            CodeHealthSnapshot.repo_id == repo.id).count() == 1

    def test_a_second_run_on_unchanged_source_skips_rather_than_duplicating(self, job_db, tmp_path):
        # Otherwise an automatic pipeline fills the trend line with identical
        # points on every run.
        from app.db.models import CodeHealthSnapshot

        repo = self._repo(job_db, tmp_path)
        _wait_for(job_db, jobs.start_job(repo.id))
        job = _wait_for(job_db, jobs.start_job(repo.id))
        assert job.result["health"]["status"] == "skipped"
        assert "unchanged" in job.result["health"]["reason"]
        assert job_db.query(CodeHealthSnapshot).filter(
            CodeHealthSnapshot.repo_id == repo.id).count() == 1

    def test_changed_source_produces_a_second_snapshot(self, job_db, tmp_path):
        from app.db.models import CodeHealthSnapshot

        repo = self._repo(job_db, tmp_path)
        _wait_for(job_db, jobs.start_job(repo.id))
        _write(Path(repo.local_path) / "pkg" / "util.py",
               "from pkg.core import run\n\n\n"
               "def helper(x):\n"
               "    if x > 3:\n        return run(x, True)\n"
               "    if x > 1:\n        return run(x, False)\n"
               "    return 0\n\n\n"
               "def extra(y):\n    return y + 1\n")
        job = _wait_for(job_db, jobs.start_job(repo.id))
        assert job.result["health"]["status"] == "created"
        assert job_db.query(CodeHealthSnapshot).filter(
            CodeHealthSnapshot.repo_id == repo.id).count() == 2

    def test_a_failing_health_stage_does_not_fail_the_job_or_undo_ingest(
            self, job_db, tmp_path, monkeypatch):
        from app.db.models import CodeFile, CodeHealthSnapshot

        repo = self._repo(job_db, tmp_path)

        def _boom(*a, **kw):
            raise RuntimeError("health exploded")

        monkeypatch.setattr("app.services.codebase.jobs.create_snapshot", _boom)
        job = _wait_for(job_db, jobs.start_job(repo.id))

        # The job succeeds: ingest and rank produced real, useful work and it
        # would be wrong to discard it because a scoring pass failed.
        assert job.status == "done"
        assert job.result["health"]["status"] == "failed"
        assert job.result["health"]["retryable"] is True
        assert "health exploded" in job.result["health"]["error"]

        # ingest/rank survived intact, and no partial snapshot exists.
        files = job_db.query(CodeFile).filter(CodeFile.repo_id == repo.id).all()
        assert len(files) == 2
        assert all(f.fan_in is not None for f in files)
        assert job_db.query(CodeHealthSnapshot).filter(
            CodeHealthSnapshot.repo_id == repo.id).count() == 0

    def test_health_stage_makes_no_llm_calls(self, job_db, tmp_path, monkeypatch):
        # The zero-outbound-AI guarantee must survive the new stage.
        repo = self._repo(job_db, tmp_path)

        def _boom(*a, **kw):
            raise AssertionError("LLM was called during the health stage")

        monkeypatch.setattr("app.core.llm.chat", _boom)
        monkeypatch.setattr("app.core.llm.chat_json", _boom)
        monkeypatch.setattr("app.core.llm.chat_stream", _boom)

        job = _wait_for(job_db, jobs.start_job(repo.id))
        assert job.status == "done"
        assert job.result["health"]["status"] == "created"
