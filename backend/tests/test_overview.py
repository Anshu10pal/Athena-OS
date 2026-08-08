"""Phase K1: repo overview aggregation, structural health, and hotspots.

The properties worth pinning down here are the HONESTY ones, not the
arithmetic: that an unavailable factor is excluded from the score rather
than scored as zero, and that hotspots refuses to rank rather than ranking
by a constant when churn carries no information. Those are the two places
where a plausible-looking number could otherwise be produced from nothing.
"""
from pathlib import Path

import pytest

from app.api.repos import get_overview
from app.db.models import CodeFile, Repo
from app.services.codebase.git_ops import run_git
from app.services.codebase.ingest import ingest_repo
from app.services.codebase.overview import (
    build_overview, churn_is_degenerate, counts, health, hotspots,
)
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
    _git(root, "config", "user.name", "Test User")
    _write(root / "README.md", "# Demo\n\nA small demo repository.\n")
    _write(root / "pkg" / "core.py", '"""Core module."""\n\n\ndef run():\n    """Run it."""\n    return 1\n')
    _write(root / "pkg" / "util.py", "from pkg.core import run\n\n\ndef helper():\n    return run()\n")
    _write(root / "tests" / "test_core.py", "from pkg.core import run\n\n\ndef test_run():\n    assert run() == 1\n")
    _git(root, "add", "-A")
    _git(root, "-c", "user.name=A", "-c", "user.email=a@t.com", "commit", "-m", "initial")
    return root


def _ranked(db_session, tmp_path) -> Repo:
    root = _make_repo(tmp_path)
    repo = register_from_path(db_session, str(root))
    ingest_repo(db_session, repo)
    rank_repo(db_session, repo)
    return repo


class TestCounts:
    def test_reports_real_sizes_and_shapes(self, db_session, tmp_path):
        repo = _ranked(db_session, tmp_path)
        c = counts(db_session, repo)
        assert c["files"] == 3
        assert c["lines"] > 0
        assert c["directories"] == 2  # pkg, tests
        assert c["test_files"] == 1
        assert c["languages"] == {"python": 3}
        assert c["symbols_total"] >= 3

    def test_import_resolution_rate_is_a_real_ratio(self, db_session, tmp_path):
        repo = _ranked(db_session, tmp_path)
        c = counts(db_session, repo)
        assert c["imports_total"] >= 2
        assert c["imports_resolved"] + c["imports_unresolved"] == c["imports_total"]
        assert 0.0 <= c["import_resolution_rate"] <= 1.0


class TestChurnDegeneracy:
    def test_single_commit_repo_is_degenerate(self, db_session, tmp_path):
        # One commit means every file has the same commit_count, which is
        # exactly the shallow-clone shape hotspots must refuse to rank.
        repo = _ranked(db_session, tmp_path)
        assert churn_is_degenerate(db_session, repo) is True

    def test_hotspots_reports_unavailable_with_a_reason_instead_of_ranking(self, db_session, tmp_path):
        repo = _ranked(db_session, tmp_path)
        result = hotspots(db_session, repo)
        assert result["available"] is False
        assert result["files"] == []
        assert "shallow clone" in result["reason"]

    def test_hotspots_ranks_once_churn_actually_varies(self, db_session, tmp_path):
        repo = _ranked(db_session, tmp_path)
        root = Path(repo.local_path)
        # Touch one file repeatedly so commit_count genuinely differs.
        for i in range(3):
            _write(root / "pkg" / "core.py",
                   f'"""Core module."""\n\n\ndef run():\n    """Run it."""\n    return {i}\n')
            _git(root, "add", "-A")
            _git(root, "-c", "user.name=A", "-c", "user.email=a@t.com", "commit", "-m", f"edit {i}")
        ingest_repo(db_session, repo)
        rank_repo(db_session, repo)

        assert churn_is_degenerate(db_session, repo) is False
        result = hotspots(db_session, repo)
        assert result["available"] is True
        # core.py churns AND is imported by two files -- it is the hotspot.
        assert result["files"][0]["path"] == "pkg/core.py"


class TestHealthFactorExclusion:
    def test_excludes_an_unavailable_factor_from_the_score_rather_than_zeroing_it(self, db_session, tmp_path):
        repo = _ranked(db_session, tmp_path)
        stats = counts(db_session, repo)
        result = health(db_session, repo, stats)

        # Clustering has not been run, so cycle_freedom cannot be known.
        cycle = next(f for f in result["factors"] if f["key"] == "cycle_freedom")
        assert cycle["available"] is False
        assert cycle["value"] is None
        assert result["factors_used"] == result["factors_total"] - 1

        # The score must be the weighted mean of the AVAILABLE factors --
        # if the excluded one had been counted as 0.0 the score would be
        # strictly lower than this.
        usable = [f for f in result["factors"] if f["available"]]
        expected = sum(f["value"] * f["weight"] for f in usable) / sum(f["weight"] for f in usable)
        assert result["score"] == pytest.approx(round(expected, 4))

    def test_documentation_is_excluded_entirely_for_a_repo_with_no_python(self, db_session, tmp_path):
        # The JS/TS extractor never populates docstrings, so scoring a
        # JS-only repo as "undocumented" would report a gap in this tool's
        # parser as a deficiency in the code being analysed.
        root = tmp_path / "jsrepo"
        root.mkdir(parents=True, exist_ok=True)
        _git(root, "init")
        _git(root, "config", "user.email", "t@t.com")
        _git(root, "config", "user.name", "T")
        _write(root / "a.js", "export function a() { return 1; }\n")
        _write(root / "b.js", "import { a } from './a.js';\nexport function b() { return a(); }\n")
        _git(root, "add", "-A")
        _git(root, "-c", "user.name=A", "-c", "user.email=a@t.com", "commit", "-m", "initial")
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)
        rank_repo(db_session, repo)

        result = health(db_session, repo, counts(db_session, repo))
        doc = next(f for f in result["factors"] if f["key"] == "documentation")
        assert doc["available"] is False
        assert doc["value"] is None

    def test_score_carries_the_not_defect_prediction_caveat(self, db_session, tmp_path):
        repo = _ranked(db_session, tmp_path)
        result = health(db_session, repo, counts(db_session, repo))
        assert "not a defect prediction" in result["caveat"]


class TestBuildOverviewAndEndpoint:
    def test_description_is_extracted_at_ingest_and_surfaced(self, db_session, tmp_path):
        repo = _ranked(db_session, tmp_path)
        overview = build_overview(db_session, repo)
        assert overview["repo"]["description"] == "A small demo repository."
        assert overview["repo"]["description_source"] == "README"

    def test_endpoint_returns_the_full_shape(self, db_session, tmp_path):
        repo = _ranked(db_session, tmp_path)
        result = get_overview(repo.id, user=None, db=db_session)
        for key in ("repo", "counts", "health", "hotspots", "cluster_count"):
            assert key in result

    def test_endpoint_404s_for_an_unknown_repo(self, db_session):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            get_overview(999999, user=None, db=db_session)
        assert exc.value.status_code == 404

    def test_overview_does_not_recompute_clustering(self, db_session, tmp_path, monkeypatch):
        """H1.5's rule: a read endpoint reads what a write already stored."""
        import app.services.codebase.subsystems as subsystems_module

        repo = _ranked(db_session, tmp_path)

        def _boom(*a, **kw):
            raise AssertionError("the overview endpoint must not recompute clustering")

        monkeypatch.setattr(subsystems_module, "compute_subsystems", _boom)
        monkeypatch.setattr(subsystems_module, "compute_subsystems_hdbscan", _boom)
        result = build_overview(db_session, repo)
        assert result["cluster_count"] == 0
