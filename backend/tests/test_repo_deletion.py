"""Deleting a repo: the guard that matters, and the order that only fails in prod.

Two things about this file's fixture, both load-bearing:

`fk_session` turns `PRAGMA foreign_keys = ON`. The shared `db_session` fixture
does not, and neither does the dev database -- SQLite defaults foreign keys OFF,
so every declared constraint is inert and EVERY delete order passes locally. The
production target is Postgres (`psycopg2-binary` is a dependency and the README
documents `DATABASE_URL` as "Point at Postgres in production"), where the same
constraints ARE enforced. Without this pragma these tests would document the
intended order without pinning it -- §15.1's test_DOCUMENTS_INTENT_ case, where
what is wanted is LOADBEARING.

The rmtree test builds a REAL git clone. A synthetic directory tree has no
read-only objects, so it deletes cleanly with or without the error handler and
the test would pass for the wrong reason.
"""
import os
import stat
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from app.db import models  # noqa: F401
from app.db.database import Base
from app.db.models import (
    CodeFile,
    CodeFileHealth,
    CodeFileRank,
    CodeHealthSnapshot,
    CodeImport,
    CodeSubsystem,
    CodeSymbol,
    Repo,
    RepoJob,
)
from app.services.codebase import deletion


@pytest.fixture()
def fk_session():
    """Like db_session, but with foreign keys actually enforced."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_connection, _record):
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _populate(db, *, source_kind: str, local_path: str) -> Repo:
    """A repo with at least one row in every table deletion has to clear,
    including the code_files <-> code_subsystems cycle wired up in both
    directions -- an empty repo would exercise none of the ordering."""
    repo = Repo(host="github.com", owner="acme", name="widget",
                source_kind=source_kind, local_path=local_path, default_branch="main")
    db.add(repo)
    db.flush()

    f = CodeFile(repo_id=repo.id, path="pkg/a.py", language="python", content_sha256="x" * 64)
    g = CodeFile(repo_id=repo.id, path="pkg/b.py", language="python", content_sha256="y" * 64)
    db.add_all([f, g])
    db.flush()

    sub = CodeSubsystem(repo_id=repo.id, cluster_index=0, algorithm="modularity",
                        member_count=2, top_fan_in_file_id=f.id)
    db.add(sub)
    db.flush()
    # The cycle: file -> subsystem AND subsystem -> file.
    f.subsystem_modularity_id = sub.id
    g.subsystem_modularity_id = sub.id

    sym = CodeSymbol(file_id=f.id, name="run", kind="function", line_start=1, line_end=2)
    db.add(sym)
    db.flush()

    db.add(CodeImport(repo_id=repo.id, from_file_id=f.id, to_file_id=g.id,
                      raw_specifier="pkg.b", kind="internal", to_symbol_id=sym.id))
    db.add(CodeFileRank(repo_id=repo.id, file_id=f.id, scorer="legacy", rank=1, score=1.0))
    snap = CodeHealthSnapshot(repo_id=repo.id, branch="main", analyzer_version=1,
                              thresholds_version=1, weights_version=1)
    db.add(snap)
    db.flush()
    db.add(CodeFileHealth(snapshot_id=snap.id, file_id=f.id, path=f.path, nloc=10))
    db.add(RepoJob(repo_id=repo.id, status="done", stage="done"))
    db.commit()
    return repo


def _counts(db, repo_id):
    return {
        name: db.execute(text(sql), {"rid": repo_id}).scalar()
        for name, sql in deletion._COUNT_PLAN
    }


class TestLocalDirectoryGuard:
    """The single most important behaviour here. repo 1 in this project's own
    database is source_kind='local' pointing at the Athena working tree, so a
    bug in this guard deletes the codebase under development."""

    def test_LOADBEARING_a_local_repo_keeps_its_directory(self, fk_session, tmp_path):
        project = tmp_path / "someones_project"
        project.mkdir()
        (project / "important.py").write_text("# the user's own work\n")

        repo = _populate(fk_session, source_kind="local", local_path=str(project))
        report = deletion.delete_repo(fk_session, repo, "acme/widget")

        assert project.exists(), "a registered local directory was deleted"
        assert (project / "important.py").read_text() == "# the user's own work\n"
        assert report.directory_deleted is False
        assert "left untouched" in report.directory_reason
        # Rows still go.
        assert fk_session.get(Repo, report.repo_id) is None

    def test_LOADBEARING_a_clone_outside_the_cache_keeps_its_directory(self, fk_session, tmp_path):
        """Both conditions are required, so a repo CLAIMING to be a clone while
        living somewhere else is still refused. This is the case a single
        source_kind check would delete."""
        elsewhere = tmp_path / "not_the_cache"
        elsewhere.mkdir()
        (elsewhere / "keep.txt").write_text("keep")

        repo = _populate(fk_session, source_kind="clone", local_path=str(elsewhere))
        report = deletion.delete_repo(fk_session, repo, "acme/widget")

        assert elsewhere.exists()
        assert report.directory_deleted is False
        assert "not inside the clone cache" in report.directory_reason

    def test_containment_resolves_dotdot_before_comparing(self, tmp_path, monkeypatch):
        """A naive string prefix test passes for <cache>/../escape. Path.resolve()
        is what makes the check structural rather than textual."""
        cache = tmp_path / "cache"
        cache.mkdir()
        escape = tmp_path / "escape"
        escape.mkdir()
        monkeypatch.setattr(deletion.registry, "clone_cache_root", lambda: cache)

        repo = Repo(host="h", owner="o", name="n", source_kind="clone",
                    local_path=str(cache / ".." / "escape"))
        may, reason = deletion.clone_directory_verdict(repo)

        assert may is False
        assert "not inside the clone cache" in reason


class TestConfirmation:
    def test_LOADBEARING_a_wrong_confirmation_deletes_nothing(self, fk_session, tmp_path):
        repo = _populate(fk_session, source_kind="local", local_path=str(tmp_path))
        before = _counts(fk_session, repo.id)

        with pytest.raises(deletion.RepoDeletionRefused):
            deletion.delete_repo(fk_session, repo, "acme/wrong")

        assert _counts(fk_session, repo.id) == before
        assert fk_session.get(Repo, repo.id) is not None

    def test_the_label_is_owner_slash_name(self, fk_session, tmp_path):
        repo = _populate(fk_session, source_kind="local", local_path=str(tmp_path))
        assert deletion.repo_label(repo) == "acme/widget"


class TestDeleteOrderUnderEnforcedForeignKeys:
    def test_LOADBEARING_every_table_reaches_zero(self, fk_session, tmp_path):
        repo = _populate(fk_session, source_kind="local", local_path=str(tmp_path))
        # Held before the delete: reading repo.id afterwards makes SQLAlchemy
        # refresh a row that no longer exists.
        repo_id = repo.id
        before = _counts(fk_session, repo_id)
        assert all(n > 0 for n in before.values()), f"fixture left a table empty: {before}"

        report = deletion.delete_repo(fk_session, repo, "acme/widget")

        after = _counts(fk_session, repo_id)
        assert all(n == 0 for n in after.values()), f"rows survived: {after}"
        assert report.rows_deleted == before
        assert fk_session.get(Repo, repo_id) is None

    def test_LOADBEARING_the_files_subsystems_cycle_does_not_block_the_delete(
            self, fk_session, tmp_path):
        """code_files.subsystem_*_id and code_subsystems.top_fan_in_file_id point
        at each other, so no order of whole-table deletes satisfies both. The
        plan nulls the file side first. With foreign keys enforced, removing that
        UPDATE makes this raise IntegrityError."""
        repo = _populate(fk_session, source_kind="local", local_path=str(tmp_path))
        both_directions = fk_session.execute(text(
            "select count(*) from code_files f join code_subsystems s "
            "on f.subsystem_modularity_id = s.id and s.top_fan_in_file_id = f.id "
            "where f.repo_id = :rid"), {"rid": repo.id}).scalar()
        assert both_directions > 0, "fixture did not actually create the cycle"

        deletion.delete_repo(fk_session, repo, "acme/widget")

        assert fk_session.execute(text("select count(*) from code_subsystems")).scalar() == 0
        assert fk_session.execute(text("select count(*) from code_files")).scalar() == 0

    def test_another_repos_rows_are_untouched(self, fk_session, tmp_path):
        keep = _populate(fk_session, source_kind="local", local_path=str(tmp_path / "keep"))
        keep.name = "other"
        fk_session.commit()
        target = _populate(fk_session, source_kind="local", local_path=str(tmp_path / "go"))
        keep_before = _counts(fk_session, keep.id)

        deletion.delete_repo(fk_session, target, "acme/widget")

        assert _counts(fk_session, keep.id) == keep_before
        assert fk_session.get(Repo, keep.id) is not None


class TestReadOnlyGitObjects:
    def test_LOADBEARING_rmtree_removes_a_real_clone(self, fk_session, tmp_path, monkeypatch):
        """Built by `git clone`, not by hand: git marks objects read-only, and a
        plain shutil.rmtree fails partway through on them. A synthetic tree has
        no read-only files, so it would pass without the error handler and prove
        nothing."""
        origin = tmp_path / "origin"
        origin.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=origin, check=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=origin, check=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=origin, check=True)
        (origin / "a.py").write_text("x = 1\n")
        subprocess.run(["git", "add", "-A"], cwd=origin, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=origin, check=True)

        cache = tmp_path / "cache"
        cache.mkdir()
        clone = cache / "acme" / "widget"
        clone.parent.mkdir(parents=True)
        subprocess.run(["git", "clone", "-q", str(origin), str(clone)], check=True)

        read_only = [
            p for p in (clone / ".git").rglob("*")
            if p.is_file() and not (p.stat().st_mode & stat.S_IWRITE)
        ]
        if not read_only:
            # Depends on git version and filesystem. Force the condition rather
            # than passing on a tree that never had the property under test --
            # §15.1's inverse clause: a negative result means nothing if the
            # stimulus was never shown to produce the condition.
            victim = next(p for p in (clone / ".git").rglob("*") if p.is_file())
            os.chmod(victim, stat.S_IREAD)
            read_only = [victim]
        assert read_only, "no read-only files in the clone; this test would prove nothing"

        monkeypatch.setattr(deletion.registry, "clone_cache_root", lambda: cache)
        repo = _populate(fk_session, source_kind="clone", local_path=str(clone))

        report = deletion.delete_repo(fk_session, repo, "acme/widget")

        assert report.directory_deleted is True, report.directory_reason
        assert not clone.exists()

    def test_a_missing_directory_is_reported_not_raised(self, fk_session, tmp_path, monkeypatch):
        cache = tmp_path / "cache"
        cache.mkdir()
        monkeypatch.setattr(deletion.registry, "clone_cache_root", lambda: cache)
        repo = _populate(fk_session, source_kind="clone", local_path=str(cache / "gone"))

        report = deletion.delete_repo(fk_session, repo, "acme/widget")

        assert report.directory_deleted is False
        assert "already absent" in report.directory_reason


class TestReport:
    def test_report_names_every_table_and_totals_them(self, fk_session, tmp_path):
        repo = _populate(fk_session, source_kind="local", local_path=str(tmp_path))
        report = deletion.delete_repo(fk_session, repo, "acme/widget")
        payload = report.to_dict()

        assert set(payload["rows_deleted"]) == {name for name, _ in deletion._COUNT_PLAN}
        assert payload["rows_total"] == sum(payload["rows_deleted"].values())
        assert payload["source_kind"] == "local"
        assert payload["directory_reason"], "a reason is always reported, not only on refusal"
