"""Phase 1 code health: snapshot writes.

The properties worth pinning are the ones a half-written snapshot would
violate silently: atomicity, immutability, source identity, and refusing to
compare across scoring versions.
"""
from pathlib import Path

import pytest

from app.db.models import CodeFileHealth, CodeHealthSnapshot, Repo
from app.services.codebase import health_snapshots
from app.services.codebase.ast_metrics import ANALYZER_VERSION
from app.services.codebase.git_ops import run_git
from app.services.codebase.graph_structure import persist_graph_structure
from app.services.codebase.health_scoring import THRESHOLDS_VERSION, WEIGHTS_VERSION
from app.services.codebase.health_snapshots import (
    create_snapshot,
    previous_comparable_snapshot,
    trend_delta,
    working_tree_dirty,
)
from app.services.codebase.ingest import ingest_repo
from app.services.codebase.ranking import rank_repo
from app.services.codebase.registry import register_from_path


def _write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _git(cwd: Path, *args):
    result = run_git(list(args), cwd=str(cwd))
    assert result.returncode == 0, f"git {args} failed: {result.stderr}"
    return result


def _make_repo(tmp_path) -> Path:
    root = tmp_path / "repo"
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init")
    _git(root, "config", "user.email", "t@t.com")
    _git(root, "config", "user.name", "T")
    # Each file must clear SUBSTANCE_FLOOR_NLOC (10 non-blank, non-comment
    # lines) or the engine correctly excludes it from Maintainability and the
    # snapshot has nothing to summarise -- which is exactly what an earlier,
    # too-small version of this fixture demonstrated.
    _write(root / "pkg" / "core.py",
           '"""Core."""\n\n\n'
           "def run(a, b):\n"
           "    if a:\n"
           "        return 1\n"
           "    if b:\n"
           "        return 2\n"
           "    return 0\n\n\n"
           "def classify(v):\n"
           "    if v > 10:\n"
           "        return 'high'\n"
           "    elif v > 5:\n"
           "        return 'mid'\n"
           "    return 'low'\n")
    _write(root / "pkg" / "util.py",
           "from pkg.core import run, classify\n\n\n"
           "def helper(x):\n"
           "    value = run(x, False)\n"
           "    label = classify(value)\n"
           "    if label == 'high':\n"
           "        return value * 2\n"
           "    return value\n\n\n"
           "def describe(x):\n"
           "    return f'{x}: {helper(x)}'\n")
    _write(root / "main.py",
           "from pkg.util import helper, describe\n\n\n"
           "def main():\n"
           "    total = 0\n"
           "    for i in range(10):\n"
           "        total += helper(i)\n"
           "    print(describe(total))\n"
           "    return total\n\n\n"
           "if __name__ == '__main__':\n"
           "    main()\n")
    _git(root, "add", "-A")
    _git(root, "-c", "user.name=A", "-c", "user.email=a@t.com", "commit", "-m", "initial")
    return root


def _analysed(db_session, tmp_path) -> Repo:
    repo = register_from_path(db_session, str(_make_repo(tmp_path)))
    ingest_repo(db_session, repo)
    rank_repo(db_session, repo)
    persist_graph_structure(db_session, repo)
    return repo


class TestSnapshotIdentity:
    """Without every one of these fields, two results can be silently compared
    across different working trees or scoring definitions."""

    def test_snapshot_carries_branch_sha_dirty_and_versions(self, db_session, tmp_path):
        repo = _analysed(db_session, tmp_path)
        snap = create_snapshot(db_session, repo)
        assert snap.branch == repo.default_branch
        assert snap.head_sha == repo.last_ingested_sha
        assert snap.working_tree_dirty in (True, False, None)
        assert snap.analyzer_version == ANALYZER_VERSION
        assert snap.thresholds_version == THRESHOLDS_VERSION
        assert snap.weights_version == WEIGHTS_VERSION

    def test_dirty_working_tree_is_detected(self, db_session, tmp_path):
        repo = _analysed(db_session, tmp_path)
        assert working_tree_dirty(repo.local_path) is False
        _write(Path(repo.local_path) / "pkg" / "core.py", "def run(a):\n    return 2\n")
        assert working_tree_dirty(repo.local_path) is True

    def test_dirty_state_is_recorded_on_the_snapshot_itself(self, db_session, tmp_path):
        repo = _analysed(db_session, tmp_path)
        _write(Path(repo.local_path) / "extra.py", "X = 1\n")
        snap = create_snapshot(db_session, repo)
        # HEAD does not describe the analysed bytes here, and the snapshot
        # says so rather than making a false provenance claim.
        assert snap.working_tree_dirty is True


class TestAtomicity:
    def test_a_failure_writes_no_snapshot_at_all(self, db_session, tmp_path, monkeypatch):
        repo = _analysed(db_session, tmp_path)
        before = db_session.query(CodeHealthSnapshot).count()

        real_add = db_session.add
        state = {"n": 0}

        def exploding_add(obj, *a, **kw):
            # Fail partway through the per-file rows, i.e. after the snapshot
            # row already exists in the session.
            if isinstance(obj, CodeFileHealth):
                state["n"] += 1
                if state["n"] == 2:
                    raise RuntimeError("boom")
            return real_add(obj, *a, **kw)

        monkeypatch.setattr(db_session, "add", exploding_add)
        with pytest.raises(RuntimeError):
            create_snapshot(db_session, repo)
        monkeypatch.undo()

        # No half-written snapshot survives -- a trend line must never be able
        # to mistake an incomplete run for a real improvement.
        assert db_session.query(CodeHealthSnapshot).count() == before
        assert db_session.query(CodeFileHealth).count() == 0

    def test_snapshot_and_its_file_rows_are_written_together(self, db_session, tmp_path):
        repo = _analysed(db_session, tmp_path)
        snap = create_snapshot(db_session, repo)
        rows = db_session.query(CodeFileHealth).filter(
            CodeFileHealth.snapshot_id == snap.id).all()
        assert len(rows) == 3
        assert {r.path for r in rows} == {"pkg/core.py", "pkg/util.py", "main.py"}


class TestImmutabilityAndContent:
    def test_re_running_appends_rather_than_mutating(self, db_session, tmp_path):
        repo = _analysed(db_session, tmp_path)
        first = create_snapshot(db_session, repo)
        second = create_snapshot(db_session, repo)
        assert first.id != second.id
        assert db_session.query(CodeHealthSnapshot).count() == 2

    def test_explanations_are_stored_with_the_snapshot(self, db_session, tmp_path):
        # A historical score explainable only by today's thresholds is not
        # auditable.
        repo = _analysed(db_session, tmp_path)
        snap = create_snapshot(db_session, repo)
        row = db_session.query(CodeFileHealth).filter(
            CodeFileHealth.snapshot_id == snap.id,
            CodeFileHealth.path == "pkg/core.py").one()
        assert set(row.explanation) == {"maintainability", "architecture_health", "change_hotspot"}
        markers = row.explanation["maintainability"]["markers"]
        assert any(m["key"] == "complex_method" for m in markers)
        for m in markers:
            assert "deduction" in m and "available" in m

    def test_axis_summary_reports_distribution_not_just_a_mean(self, db_session, tmp_path):
        repo = _analysed(db_session, tmp_path)
        snap = create_snapshot(db_session, repo)
        m = snap.axis_summary["maintainability"]
        for key in ("mean", "median", "p10", "p90", "scored", "na", "na_reasons"):
            assert key in m

    def test_na_axis_stores_null_not_zero(self, db_session, tmp_path):
        # This fixture is a single-commit repo, so churn is degenerate and the
        # whole Change Hotspot axis must be N/A rather than 0.0 points.
        repo = _analysed(db_session, tmp_path)
        snap = create_snapshot(db_session, repo)
        rows = db_session.query(CodeFileHealth).filter(
            CodeFileHealth.snapshot_id == snap.id).all()
        assert all(r.change_hotspot_points is None for r in rows)
        assert all(r.adjusted_exposure is None for r in rows)
        assert snap.axis_summary["change_hotspot"]["scored"] == 0

    def test_architecture_is_presentable_once_sccs_are_persisted(self, db_session, tmp_path):
        repo = _analysed(db_session, tmp_path)
        snap = create_snapshot(db_session, repo)
        rows = db_session.query(CodeFileHealth).filter(
            CodeFileHealth.snapshot_id == snap.id).all()
        assert all(r.architecture_health is not None for r in rows)
        assert snap.axis_summary["architecture_health"]["inputs_complete"] is True

    def test_architecture_is_withheld_when_sccs_were_never_computed(self, db_session, tmp_path):
        from app.db.models import CodeFile
        repo = _analysed(db_session, tmp_path)
        for f in db_session.query(CodeFile).filter(CodeFile.repo_id == repo.id).all():
            f.scc_size = None
        db_session.commit()

        snap = create_snapshot(db_session, repo)
        rows = db_session.query(CodeFileHealth).filter(
            CodeFileHealth.snapshot_id == snap.id).all()
        # Withheld, not a green 10.0 -- the gate is structural.
        assert all(r.architecture_health is None for r in rows)
        assert snap.axis_summary["architecture_health"]["inputs_complete"] is False
        assert rows[0].explanation["architecture_health"]["provisional_value"] is not None


class TestTrendComparability:
    def test_first_snapshot_has_no_baseline_and_says_so(self, db_session, tmp_path):
        repo = _analysed(db_session, tmp_path)
        snap = create_snapshot(db_session, repo)
        t = trend_delta(db_session, snap)
        assert t["comparable"] is False
        assert t["reason"] == "No previous snapshot on this branch."
        assert t["deltas"] == {}

    def test_two_snapshots_at_the_same_versions_are_comparable(self, db_session, tmp_path):
        repo = _analysed(db_session, tmp_path)
        create_snapshot(db_session, repo)
        second = create_snapshot(db_session, repo)
        t = trend_delta(db_session, second)
        assert t["comparable"] is True
        assert "maintainability" in t["deltas"]

    def test_a_threshold_version_change_makes_snapshots_incomparable(self, db_session, tmp_path):
        # Comparing across a scoring change measures the measuring stick, not
        # the code -- so it must refuse rather than silently diff.
        repo = _analysed(db_session, tmp_path)
        old = create_snapshot(db_session, repo)
        old.thresholds_version = THRESHOLDS_VERSION - 1
        db_session.commit()

        new = create_snapshot(db_session, repo)
        assert previous_comparable_snapshot(db_session, new) is None
        t = trend_delta(db_session, new)
        assert t["comparable"] is False
        assert t["reason"] == "Not comparable — scoring changed since the previous snapshot."

    def test_a_different_branch_is_not_a_baseline(self, db_session, tmp_path):
        repo = _analysed(db_session, tmp_path)
        other = create_snapshot(db_session, repo)
        other.branch = "some-other-branch"
        db_session.commit()
        new = create_snapshot(db_session, repo)
        assert previous_comparable_snapshot(db_session, new) is None
