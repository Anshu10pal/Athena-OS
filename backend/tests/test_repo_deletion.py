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
from datetime import datetime
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
from app.services.codebase import deletion, registry


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

    def test_LOADBEARING_a_repo_with_no_owner_is_labelled_by_name_alone(
            self, fk_session, tmp_path):
        """Locally-registered repos have an EMPTY owner. An unconditional
        f"{owner}/{name}" made the expected confirmation "/name" while the UI
        displayed "name", so no local repo could be deleted through the dialog.
        Every other test here uses a fixture WITH an owner and passed
        throughout; a browser pass found it."""
        repo = _populate(fk_session, source_kind="local", local_path=str(tmp_path))
        repo.owner = ""
        fk_session.commit()

        assert deletion.repo_label(repo) == "widget"
        # And the label it reports must be the one it accepts.
        report = deletion.delete_repo(fk_session, repo, deletion.repo_label(repo))
        assert report.label == "widget"

    def test_LOADBEARING_the_reported_label_is_always_an_accepted_confirmation(
            self, fk_session, tmp_path):
        """The property the bug violated, stated directly: whatever repo_label
        returns must be what delete_repo accepts. Any future divergence between
        the two breaks the dialog for some class of repo."""
        for owner in ("acme", ""):
            repo = _populate(fk_session, source_kind="local",
                             local_path=str(tmp_path / f"r{owner or 'none'}"))
            repo.owner = owner
            fk_session.commit()
            label = deletion.repo_label(repo)
            deletion.delete_repo(fk_session, repo, label)  # must not raise


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


class TestDeletionAuditIsDurable:
    """The instrumentation that proved its own inadequacy.

    `delete_repo` had no logging; a repo vanished unexplained; a print was
    added; the print then fired for exactly one real deletion and went to a
    stdout nobody captured, leaving the original question -- was delete_repo
    called, and on what? -- exactly as unanswerable as before.

    These pin the distinction that incident taught: "the code path fires" and
    "the output can be read back afterwards" are different claims, and only the
    second is any use at the point somebody notices a repo is missing.
    """

    def test_LOADBEARING_a_deletion_leaves_a_retrievable_record(self, fk_session, tmp_path):
        from app.db.models import RepoDeletionAudit
        repo = _populate(fk_session, source_kind="local", local_path=str(tmp_path))
        repo_id = repo.id
        before = _counts(fk_session, repo_id)

        deletion.delete_repo(fk_session, repo, "acme/widget")

        # Queried fresh, not held from the write -- the claim is retrieval, not
        # that an object stayed in memory.
        audit = (fk_session.query(RepoDeletionAudit)
                 .filter(RepoDeletionAudit.repo_id == repo_id).one())
        assert audit.rows_deleted == before, \
            "the record must hold the BEFORE counts, which is what a later " \
            "reader needs and cannot recompute once the rows are gone"
        assert audit.rows_total == sum(before.values())
        assert audit.reason, "a deletion with no attributable reason is the gap itself"
        assert audit.repo_label
        assert audit.source_kind == "local"

    def test_LOADBEARING_the_record_outlives_the_repo_row(self, fk_session, tmp_path):
        """No ForeignKey to `repos`, deliberately: the row's whole purpose is to
        survive the row it describes. A FK would either block the delete or
        cascade the evidence away."""
        from app.db.models import Repo as RepoModel, RepoDeletionAudit
        repo = _populate(fk_session, source_kind="local", local_path=str(tmp_path))
        repo_id = repo.id
        deletion.delete_repo(fk_session, repo, "acme/widget")

        assert fk_session.get(RepoModel, repo_id) is None
        assert fk_session.query(RepoDeletionAudit).filter(
            RepoDeletionAudit.repo_id == repo_id).count() == 1

    def test_eviction_is_recorded_too_not_only_user_deletions(self, fk_session, tmp_path):
        """An unattended deletion is the case that most needs a record -- there
        is no user to have noticed it happening."""
        from app.db.models import RepoDeletionAudit
        repo = _populate(fk_session, source_kind="clone", local_path=str(tmp_path))
        repo_id = repo.id
        deletion.delete_repo_unconfirmed(fk_session, repo, reason="LRU cache eviction: test")

        audit = (fk_session.query(RepoDeletionAudit)
                 .filter(RepoDeletionAudit.repo_id == repo_id).one())
        assert "eviction" in audit.reason.lower()

    def test_the_audit_survives_a_later_deletion_of_another_repo(self, fk_session, tmp_path):
        """An audit trail a delete can erase is not one."""
        from app.db.models import RepoDeletionAudit
        first = _populate(fk_session, source_kind="local", local_path=str(tmp_path / "a"))
        deletion.delete_repo(fk_session, first, "acme/widget")
        # Keyed on the AUDIT row's own id, not the repo's: SQLite reuses the
        # rowid just freed, so the second repo is handed the same repo_id and a
        # repo_id-based assertion would be testing id reuse rather than
        # survival. That reuse is also exactly why the audit needs its own key.
        first_audit_id = fk_session.query(RepoDeletionAudit).one().id

        second = _populate(fk_session, source_kind="local", local_path=str(tmp_path / "b"))
        deletion.delete_repo(fk_session, second, "acme/widget")

        assert fk_session.query(RepoDeletionAudit).count() == 2
        assert fk_session.get(RepoDeletionAudit, first_audit_id) is not None, \
            "the earlier deletion's record must survive a later deletion"


class TestEvictionDeletesEverything:
    """Item 2. `evict_lru_if_needed` used to call `db.delete(r)` on the Repo row
    alone, and nothing cascades -- so an eviction left the whole analysis behind
    pointing at a repo id that no longer existed. Fixtures only; this never runs
    against the live database."""

    def _clone_with_rows(self, db, tmp_path, name: str, *, mb: int = 1) -> Repo:
        """A `clone` repo whose directory is inside a fake cache root, with at
        least one row in every table deletion has to clear."""
        cache = tmp_path / "cache"
        clone_dir = cache / name
        clone_dir.mkdir(parents=True)
        # Real bytes, so the size-based eviction loop has something to measure.
        (clone_dir / "blob.bin").write_bytes(b"x" * (mb * 1024 * 1024))

        repo = Repo(host="github.com", owner="acme", name=name, source_kind="clone",
                    local_path=str(clone_dir), default_branch="main")
        db.add(repo)
        db.flush()

        f = CodeFile(repo_id=repo.id, path=f"{name}/a.py", language="python",
                     content_sha256="a" * 64)
        db.add(f)
        db.flush()
        sub = CodeSubsystem(repo_id=repo.id, cluster_index=0, algorithm="modularity",
                            member_count=1, top_fan_in_file_id=f.id)
        db.add(sub)
        db.flush()
        f.subsystem_modularity_id = sub.id
        sym = CodeSymbol(file_id=f.id, name="run", kind="function", line_start=1, line_end=2)
        db.add(sym)
        db.flush()
        db.add(CodeImport(repo_id=repo.id, from_file_id=f.id, raw_specifier="x",
                          kind="internal", to_symbol_id=sym.id))
        db.add(CodeFileRank(repo_id=repo.id, file_id=f.id, scorer="legacy", rank=1, score=1.0))
        snap = CodeHealthSnapshot(repo_id=repo.id, branch="main", analyzer_version=1,
                                  thresholds_version=1, weights_version=1)
        db.add(snap)
        db.flush()
        db.add(CodeFileHealth(snapshot_id=snap.id, file_id=f.id, path=f.path, nloc=10))
        db.add(RepoJob(repo_id=repo.id, status="done", stage="done"))
        db.commit()
        return repo

    def test_LOADBEARING_eviction_leaves_zero_rows_in_all_eight_tables(
            self, fk_session, tmp_path, monkeypatch):
        cache = tmp_path / "cache"
        old = self._clone_with_rows(fk_session, tmp_path, "old", mb=2)
        old_id = old.id
        # Ingested long ago, so it is the LRU victim.
        old.last_ingested_at = datetime(2020, 1, 1)
        keep = self._clone_with_rows(fk_session, tmp_path, "keep", mb=2)
        keep_id = keep.id
        keep.last_ingested_at = datetime(2030, 1, 1)
        fk_session.commit()

        monkeypatch.setattr(deletion.registry, "clone_cache_root", lambda: cache)
        # Cap below the pair's total, above one of them: exactly one eviction.
        monkeypatch.setattr(registry.settings, "REPO_CLONE_CACHE_MAX_BYTES", 3 * 1024 * 1024)

        evicted = registry.evict_lru_if_needed(fk_session)

        assert evicted, "nothing was evicted; the cap did not bite"
        after = {name: fk_session.execute(text(sql), {"rid": old_id}).scalar()
                 for name, sql in deletion._COUNT_PLAN}
        assert all(n == 0 for n in after.values()), f"eviction orphaned rows: {after}"
        assert fk_session.get(Repo, old_id) is None
        # The survivor is untouched.
        assert fk_session.get(Repo, keep_id) is not None
        assert fk_session.execute(
            text("select count(*) from code_files where repo_id = :rid"),
            {"rid": keep_id}).scalar() == 1

    def test_LOADBEARING_eviction_still_refuses_a_directory_outside_the_cache(
            self, fk_session, tmp_path, monkeypatch):
        """Eviction is clones-only, but the two-condition guard must still hold:
        skipping the CONFIRMATION must not skip the GUARDS. A repo marked
        `clone` whose path is elsewhere keeps its directory."""
        cache = tmp_path / "cache"
        cache.mkdir()
        elsewhere = tmp_path / "not_the_cache"
        elsewhere.mkdir()
        (elsewhere / "keep.txt").write_bytes(b"y" * (2 * 1024 * 1024))

        repo = Repo(host="github.com", owner="acme", name="stray", source_kind="clone",
                    local_path=str(elsewhere), default_branch="main")
        fk_session.add(repo)
        fk_session.commit()

        monkeypatch.setattr(deletion.registry, "clone_cache_root", lambda: cache)
        monkeypatch.setattr(registry.settings, "REPO_CLONE_CACHE_MAX_BYTES", 1)

        registry.evict_lru_if_needed(fk_session)

        assert elsewhere.exists(), "eviction deleted a directory outside the clone cache"
        assert (elsewhere / "keep.txt").exists()

    def test_eviction_removes_the_clone_directory_it_is_allowed_to(
            self, fk_session, tmp_path, monkeypatch):
        cache = tmp_path / "cache"
        repo = self._clone_with_rows(fk_session, tmp_path, "doomed", mb=2)
        path = Path(repo.local_path)
        assert path.exists()

        monkeypatch.setattr(deletion.registry, "clone_cache_root", lambda: cache)
        monkeypatch.setattr(registry.settings, "REPO_CLONE_CACHE_MAX_BYTES", 1)

        registry.evict_lru_if_needed(fk_session)

        assert not path.exists()

    def test_nothing_is_evicted_under_the_cap(self, fk_session, tmp_path, monkeypatch):
        cache = tmp_path / "cache"
        repo = self._clone_with_rows(fk_session, tmp_path, "small", mb=1)
        repo_id = repo.id
        monkeypatch.setattr(deletion.registry, "clone_cache_root", lambda: cache)
        monkeypatch.setattr(registry.settings, "REPO_CLONE_CACHE_MAX_BYTES", 100 * 1024 * 1024)

        assert registry.evict_lru_if_needed(fk_session) == []
        assert fk_session.get(Repo, repo_id) is not None
