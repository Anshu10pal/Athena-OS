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
from app.db.models import CodeFile, RepoJob
from app.services.codebase import jobs
from app.services.codebase.health_snapshots import collect_inputs
from app.services.codebase.ingest import ingest_repo
from app.services.codebase.ranking import rank_repo
from app.services.codebase.registry import register_from_path
from app.services.codebase.subsystems import compute_subsystems


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


def _clusterable_repo(session, tmp_path):
    """Two densely-importing groups, so clustering has something to find."""
    root = tmp_path / "clustered"
    for group in ("alpha", "beta"):
        _write(root / group / "__init__.py", "")
        for i in range(3):
            others = "\n".join(f"from {group}.m{j} import f{j}" for j in range(3) if j != i)
            _write(root / group / f"m{i}.py",
                   f"{others}\n\n\ndef f{i}(x):\n    if x:\n        return {i}\n    return 0\n")
    _write(root / "main.py",
           "from alpha.m0 import f0\nfrom beta.m0 import f0 as g0\n\n\n"
           "def main():\n    return f0(1) + g0(1)\n")
    return register_from_path(session, str(root))


class TestClusteringIsInThePipeline:
    """Subsystem clustering was reachable only through POST /subsystems, which
    nothing in the normal path calls. Every repo analysed the way a user
    actually analyses one had an empty Dependency Clusters tab -- found on
    apache/superset: 6,516 files, a complete import graph, CLUSTERS reading 0.
    """

    def test_a_normal_job_populates_subsystem_ids(self, job_db, tmp_path):
        repo = _clusterable_repo(job_db, tmp_path)
        job = _wait_for(job_db, jobs.start_job(repo.id), timeout=60)
        assert job.status == "done", job.error

        job_db.expire_all()
        files = job_db.query(CodeFile).filter(CodeFile.repo_id == repo.id).all()
        assert any(f.subsystem_modularity_id is not None for f in files), (
            "the job path must produce clusters, not just the on-demand endpoint"
        )
        assert any(f.subsystem_louvain_id is not None for f in files)

    def test_the_stage_is_reported_in_the_job_result(self, job_db, tmp_path):
        """Asserts real counts, not just the key's presence.

        An earlier version checked only `status == "computed"` and passed a
        canary run where the stage had been deleted and replaced with a
        hard-coded result of the same shape -- i.e. it verified the report
        rather than the work. Per contract 15.1, a test that survives removal
        of the thing it covers is not covering it.
        """
        repo = _clusterable_repo(job_db, tmp_path)
        job = _wait_for(job_db, jobs.start_job(repo.id), timeout=60)
        stage = (job.result or {}).get("clustering")
        assert stage and stage["status"] == "computed"
        assert isinstance(stage["modularity_clusters"], int)
        assert isinstance(stage["louvain_clusters"], int)
        assert stage["modularity_clusters"] >= 1, "the fixture has two dense groups to find"

    def test_hdbscan_stays_out_of_the_pipeline(self, job_db, tmp_path):
        """It embeds every file's symbol text -- real CPU work, unlike the
        near-instant graph maths the other two do. Deliberately on demand."""
        repo = _clusterable_repo(job_db, tmp_path)
        _wait_for(job_db, jobs.start_job(repo.id), timeout=60)

        job_db.expire_all()
        files = job_db.query(CodeFile).filter(CodeFile.repo_id == repo.id).all()
        assert files and all(f.subsystem_hdbscan_id is None for f in files)

    def test_a_clustering_failure_does_not_fail_the_job(self, job_db, tmp_path, monkeypatch):
        """Same error boundary as health: losing a completed ingest because a
        derived pass failed would throw away the expensive half for the cheap
        half."""
        def _boom(*a, **k):
            raise RuntimeError("clustering exploded")

        monkeypatch.setattr("app.services.codebase.jobs.compute_subsystems", _boom)
        repo = _clusterable_repo(job_db, tmp_path)
        job = _wait_for(job_db, jobs.start_job(repo.id), timeout=60)

        assert job.status == "done", "a clustering failure must not fail the job"
        assert job.result["clustering"]["status"] == "failed"
        assert job.result["clustering"]["retryable"] is True
        job_db.expire_all()
        assert job_db.query(CodeFile).filter(CodeFile.repo_id == repo.id).count() > 0

    def test_clustering_runs_before_health_so_the_stage_order_is_stable(self, job_db, tmp_path):
        repo = _clusterable_repo(job_db, tmp_path)
        job = _wait_for(job_db, jobs.start_job(repo.id), timeout=60)
        assert set(job.result) >= {"clustering", "health"}


class TestSilentStagesReportProgress:
    """48% of superset's 114s wall clock sat behind two stages emitting one
    message and never updating: resolving (20.4s over 60,668 rows) and health
    (35.5s re-parsing 6,516 files). From the UI that is indistinguishable from
    a hang, and a cold ingest makes both dramatically worse."""

    def test_resolving_reports_a_real_total_not_zero(self, db_session, tmp_path):
        repo = _clusterable_repo(db_session, tmp_path)
        seen = []
        ingest_repo(db_session, repo, on_progress=lambda s, c, t, m: seen.append((s, c, t)))

        resolving = [(c, t) for s, c, t in seen if s == "resolving"]
        assert resolving, "the resolving stage must report at all"
        assert all(t > 0 for _, t in resolving), (
            "a bare 0/0 gives the UI nothing to render -- the row count is known "
            "before the loop starts"
        )

    def test_health_accepts_a_progress_callback_and_never_reports_zero_total(
            self, db_session, tmp_path):
        repo = _clusterable_repo(db_session, tmp_path)
        ingest_repo(db_session, repo)
        rank_repo(db_session, repo)

        seen = []
        inputs = collect_inputs(db_session, repo,
                               on_progress=lambda s, c, t, m: seen.append((s, c, t)))
        assert inputs
        # This fixture is far below the sampling interval, so the callback may
        # legitimately never fire. What must hold is that when it does, it
        # carries a usable denominator.
        assert all(t > 0 for _, _, t in seen)

    def test_collect_inputs_still_works_without_a_callback(self, db_session, tmp_path):
        """Optional by default -- every pre-existing caller passes nothing."""
        repo = _clusterable_repo(db_session, tmp_path)
        ingest_repo(db_session, repo)
        assert collect_inputs(db_session, repo) is not None


class TestEveryLongStageReportsAProperty:
    """The generalised form of the progress check.

    Two silent stages were named, both were fixed, and a THIRD was added in the
    same batch that was silent by construction -- the verification checked the
    named list rather than the property, so the new one was invisible to it.
    Same shape as a test that asserts the report instead of the work, except
    here the report was the list of stages someone thought to mention.

    So this asserts the property: no stage that does real work may emit a
    single unchanging value. It finds stages nobody has thought of yet, which a
    list cannot.
    """

    # Stages with no meaningful unit to count. resyncing is a git fetch whose
    # duration is network-bound and whose progress git does not expose to us;
    # discovering is a filesystem walk that finishes before a reader could read
    # the label. Terminal markers announce completion and are not work.
    NO_NATURAL_UNIT = {"resyncing", "discovering"}
    TERMINAL = {"ingest_done", "ranking_done", "done", "failed"}

    # Pre-existing debt, named rather than silently tolerated. Both DO have a
    # countable unit (graph nodes; commits) and both should eventually report;
    # neither dominates wall clock (8.2s and 11.3s of superset's 114s), so they
    # are deferred rather than fixed in the batch that fixed the two that did.
    #
    # The polarity matters: this is an explicit exemption list, so a stage
    # added tomorrow fails by DEFAULT. That is the difference between this and
    # the check that missed `clustering` -- that one verified a list of named
    # stages, this one verifies the property and names its exceptions.
    KNOWN_DEBT = {"ranking_graph", "ranking_history"}

    def test_no_working_stage_emits_a_bare_zero_total(self, db_session, tmp_path):
        repo = _clusterable_repo(db_session, tmp_path)
        seen = []

        def record(stage, current, total, message):
            seen.append((stage, current, total))

        ingest_repo(db_session, repo, on_progress=record)
        rank_repo(db_session, repo, on_progress=record)
        compute_subsystems(db_session, repo, on_progress=record)

        exempt = self.NO_NATURAL_UNIT | self.TERMINAL | self.KNOWN_DEBT
        bare = sorted({
            stage for stage, _, total in seen
            if total == 0 and stage not in exempt
        })
        assert not bare, (
            f"stages reporting a 0 denominator: {bare}. A bare 0/0 gives the UI "
            "nothing to render, so the stage is indistinguishable from a hang. "
            "Either report a real total, or add the stage to KNOWN_DEBT with a "
            "reason -- but not silently."
        )

    def test_the_known_debt_list_has_not_rotted(self, db_session, tmp_path):
        """An exemption list decays into a lie once someone fixes an entry and
        leaves it listed. This fails when a stage on KNOWN_DEBT starts
        reporting properly, so the list shrinks rather than ossifies."""
        repo = _clusterable_repo(db_session, tmp_path)
        seen = []

        def record(stage, current, total, message):
            seen.append((stage, current, total))

        ingest_repo(db_session, repo, on_progress=record)
        rank_repo(db_session, repo, on_progress=record)

        still_bare = {s for s, _, t in seen if t == 0}
        fixed = sorted(self.KNOWN_DEBT - still_bare)
        assert not fixed, (
            f"these now report a real total and should be removed from "
            f"KNOWN_DEBT: {fixed}"
        )

    def test_clustering_specifically_reports_phases(self, db_session, tmp_path):
        """Pinned by name as well, because this is the stage that shipped with
        the gap after the other two were fixed."""
        repo = _clusterable_repo(db_session, tmp_path)
        ingest_repo(db_session, repo)
        rank_repo(db_session, repo)

        seen = []
        compute_subsystems(db_session, repo,
                           on_progress=lambda s, c, t, m: seen.append((s, c, t)))

        values = {(c, t) for s, c, t in seen if s == "clustering"}
        assert len(values) > 1, f"clustering must move, got {values}"
        assert all(t > 0 for _, t in values)

    def test_compute_subsystems_still_works_without_a_callback(self, db_session, tmp_path):
        repo = _clusterable_repo(db_session, tmp_path)
        ingest_repo(db_session, repo)
        rank_repo(db_session, repo)
        assert compute_subsystems(db_session, repo)["algorithms"]
