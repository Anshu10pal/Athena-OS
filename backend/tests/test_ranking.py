"""Phase C: ranking. Graph signals are tested against small ingested repos;
history signals against REAL local git repos created on disk (not mocked --
these are local, no-network git operations, same as Phase A's register_from_path
tests already do unmocked). The path-prefix-offset test reproduces the exact
bug found while building this: a registered repo nested inside a larger git
working tree, where `git log`'s reported paths don't match CodeFile.path
without stripping the offset.
"""
import subprocess
from pathlib import Path
from unittest.mock import patch

import networkx as nx
import pytest

from app.db.models import CodeFile, CodeFileRank, CodeImport
from app.services.codebase import git_ops, ranking
from app.services.codebase.git_ops import run_git
from app.services.codebase.ingest import ingest_repo
from app.services.codebase.ranking import (
    ResolutionRateCollapseError,
    _fractional_rank,
    _minmax_normalize,
    composite_score,
    legacy_signal_snapshot,
    load_rrf_config,
    rank_repo,
    rank_repo_rrf,
    rank_repo_weighted_pagerank,
    reciprocal_rank_fusion,
    weighted_personalized_pagerank,
)
from app.services.codebase.registry import register_from_path
from app.services.codebase.repo_lock import RepoBusyError, repo_lock


def _write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _git(cwd: Path, *args):
    result = run_git(list(args), cwd=str(cwd))
    assert result.returncode == 0, f"git {args} failed: {result.stderr}"
    return result


def _init_repo(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init")
    _git(root, "config", "user.email", "t@t.com")
    _git(root, "config", "user.name", "Test User")


class TestMinmaxNormalize:
    def test_empty(self):
        assert _minmax_normalize({}) == {}

    def test_all_equal_values(self):
        assert _minmax_normalize({"a": 5, "b": 5}) == {"a": 0.5, "b": 0.5}

    def test_spread(self):
        result = _minmax_normalize({"a": 0, "b": 5, "c": 10})
        assert result == {"a": 0.0, "b": 0.5, "c": 1.0}


class TestGraphSignals:
    def _make_repo(self, tmp_path) -> Path:
        root = tmp_path / "repo"
        # main.py's __main__ guard is what Phase E4 detects as a real entry
        # point -- fan_in alone (this file has fan_in == 0) is no longer
        # evidence of anything, per the fix in TestEntryDetectionMigration.
        _write(root / "main.py", "from lib import helper\n\nif __name__ == '__main__':\n    helper()\n")
        _write(root / "lib.py", "def helper():\n    return 1\n")
        return root

    def test_fan_in_pagerank_and_entry_point(self, db_session, tmp_path):
        root = self._make_repo(tmp_path)
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)
        result = rank_repo(db_session, repo)

        by_path = {f["path"]: f for f in result["files"]}
        assert by_path["lib.py"]["fan_in"] == 1
        assert by_path["main.py"]["fan_in"] == 0
        assert by_path["main.py"]["is_entry_point"] is True
        assert by_path["lib.py"]["is_entry_point"] is False
        assert by_path["lib.py"]["pagerank"] > 0

    def test_reduced_confidence_without_git_repo(self, db_session, tmp_path):
        root = self._make_repo(tmp_path)  # plain directory, no .git at all
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)
        result = rank_repo(db_session, repo)

        assert result["reduced_confidence"] is True
        for f in result["files"]:
            assert f["commit_count"] is None
            assert f["distinct_authors"] is None
            assert f["days_since_last_change"] is None
            assert f["reduced_confidence"] is True

    def test_rerank_replaces_rows_not_accumulates(self, db_session, tmp_path):
        root = self._make_repo(tmp_path)
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)
        rank_repo(db_session, repo)
        rank_repo(db_session, repo)

        count = db_session.query(CodeFileRank).filter(CodeFileRank.repo_id == repo.id).count()
        assert count == 2  # main.py + lib.py, not 4

    def test_raises_without_prior_ingest(self, db_session, tmp_path):
        root = tmp_path / "empty_repo"
        root.mkdir()
        repo = register_from_path(db_session, str(root))
        with pytest.raises(ValueError):
            rank_repo(db_session, repo)


class TestHistorySignals:
    def test_commit_count_and_authors_from_real_git_repo(self, db_session, tmp_path):
        root = tmp_path / "repo"
        _init_repo(root)
        _write(root / "a.py", "def foo():\n    return 1\n")
        _git(root, "add", "-A")
        _git(root, "-c", "user.name=Alice", "-c", "user.email=alice@t.com", "commit", "-m", "add a")

        _write(root / "a.py", "def foo():\n    return 2\n")
        _git(root, "add", "-A")
        _git(root, "-c", "user.name=Bob", "-c", "user.email=bob@t.com", "commit", "-m", "edit a")

        _write(root / "b.py", "def bar():\n    return 1\n")
        _git(root, "add", "-A")
        _git(root, "-c", "user.name=Alice", "-c", "user.email=alice@t.com", "commit", "-m", "add b")

        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)
        result = rank_repo(db_session, repo)

        assert result["reduced_confidence"] is False
        by_path = {f["path"]: f for f in result["files"]}
        assert by_path["a.py"]["commit_count"] == 2
        assert by_path["a.py"]["distinct_authors"] == 2
        assert by_path["b.py"]["commit_count"] == 1
        assert by_path["b.py"]["distinct_authors"] == 1
        assert by_path["a.py"]["days_since_last_change"] >= 0

    def test_path_prefix_offset_when_repo_is_nested_in_larger_git_tree(self, db_session, tmp_path):
        # Regression test for the exact bug found while building this: git log's
        # reported paths are relative to the git top-level, not to the
        # registered repo's local_path, when local_path is a subdirectory.
        outer = tmp_path / "outer"
        _init_repo(outer)
        _write(outer / "unrelated.txt", "not part of the sub-repo\n")
        _git(outer, "add", "-A")
        _git(outer, "-c", "user.name=Root", "-c", "user.email=root@t.com", "commit", "-m", "outer commit")

        sub = outer / "sub"
        _write(sub / "inner.py", "def inner():\n    return 1\n")
        _git(outer, "add", "-A")
        _git(outer, "-c", "user.name=Sub", "-c", "user.email=sub@t.com", "commit", "-m", "add inner.py")

        repo = register_from_path(db_session, str(sub))
        ingest_repo(db_session, repo)
        result = rank_repo(db_session, repo)

        assert result["reduced_confidence"] is False
        by_path = {f["path"]: f for f in result["files"]}
        assert by_path["inner.py"]["commit_count"] == 1
        assert by_path["inner.py"]["distinct_authors"] == 1

    def test_uncommitted_file_gets_zero_not_unknown(self, db_session, tmp_path):
        # Regression test for a real bug found via a smoke test against this
        # repo's own working tree: a file that exists on disk but was never
        # committed (e.g. work in progress) must get commit_count=0 -- a known
        # fact -- not None, which would wrongly read as "history unavailable"
        # even though git log succeeded for every other file in the repo.
        root = tmp_path / "repo"
        _init_repo(root)
        _write(root / "committed.py", "def foo():\n    return 1\n")
        _git(root, "add", "-A")
        _git(root, "-c", "user.name=Alice", "-c", "user.email=alice@t.com", "commit", "-m", "add committed.py")

        _write(root / "wip.py", "def bar():\n    return 1\n")  # never git-added or committed

        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)
        result = rank_repo(db_session, repo)

        assert result["reduced_confidence"] is False
        by_path = {f["path"]: f for f in result["files"]}
        assert by_path["committed.py"]["commit_count"] == 1
        assert by_path["wip.py"]["commit_count"] == 0
        assert by_path["wip.py"]["distinct_authors"] == 0
        assert by_path["wip.py"]["days_since_last_change"] is None
        assert by_path["wip.py"]["reduced_confidence"] is False


class TestWriteBackEntryPriorsDormant:
    """_write_back_entry_priors is Phase F2's original fan_in==0-or-basename
    heuristic. Phase E4 supersedes it with real detection (_migrate_entry_priors,
    exercised end-to-end via rank_repo in TestEntryDetectionMigration) --
    no rank_repo* function calls this anymore, but it's kept, not deleted,
    as a dormant safety net (see its own docstring). These call it directly
    to prove it would still work correctly if it were ever wired back in."""

    def test_zero_fan_in_file_flips_source_to_entry_and_is_reported(self, db_session, tmp_path):
        from app.db.models import CodeFile
        from app.services.codebase.ranking import _build_graph, _write_back_entry_priors

        root = tmp_path / "repo"
        _write(root / "main.py", "from lib import helper\nhelper()\n")  # fan_in 0 -- nothing imports it
        _write(root / "lib.py", "def helper():\n    return 1\n")
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)

        main_file = db_session.query(CodeFile).filter(CodeFile.repo_id == repo.id, CodeFile.path == "main.py").one()
        assert main_file.prior_category == "source"  # parse-time default -- entry not decided yet
        assert main_file.prior_source == "graph"

        file_by_id = {f.id: f for f in db_session.query(CodeFile).filter(CodeFile.repo_id == repo.id).all()}
        graph = _build_graph(db_session, repo, file_by_id)
        fan_in = {fid: graph.in_degree(fid) for fid in file_by_id}
        category_flips = _write_back_entry_priors(file_by_id, fan_in)

        assert main_file.prior_category == "entry"
        assert category_flips == [{"path": "main.py", "old_category": "source", "new_category": "entry"}]

    def test_gaining_an_importer_flips_entry_back_to_source(self, db_session, tmp_path):
        from app.db.models import CodeFile
        from app.services.codebase.ranking import _build_graph, _write_back_entry_priors

        # Deliberately NOT named main.py/app.py/etc. -- those match
        # ENTRY_POINT_BASENAMES regardless of fan_in, which would keep this
        # "entry" even after gaining an importer and defeat the point of
        # this test (isolating the fan_in-only path of the heuristic).
        root = tmp_path / "repo"
        _write(root / "standalone.py", "def run():\n    pass\n")  # fan_in 0 initially
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)

        def _write_back():
            file_by_id = {f.id: f for f in db_session.query(CodeFile).filter(CodeFile.repo_id == repo.id).all()}
            graph = _build_graph(db_session, repo, file_by_id)
            fan_in = {fid: graph.in_degree(fid) for fid in file_by_id}
            flips = _write_back_entry_priors(file_by_id, fan_in)
            db_session.commit()
            return flips

        _write_back()
        target_file = db_session.query(CodeFile).filter(CodeFile.repo_id == repo.id, CodeFile.path == "standalone.py").one()
        assert target_file.prior_category == "entry"

        _write(root / "caller.py", "from standalone import run\nrun()\n")  # standalone.py now has an importer
        ingest_repo(db_session, repo)
        category_flips = _write_back()

        db_session.refresh(target_file)
        assert target_file.prior_category == "source"
        flip = next(f for f in category_flips if f["path"] == "standalone.py")
        assert flip == {"path": "standalone.py", "old_category": "entry", "new_category": "source"}


class TestEntryPriorWriteBack:
    def test_pattern_categorized_file_never_touched_even_with_zero_fan_in(self, db_session, tmp_path):
        from app.db.models import CodeFile

        root = tmp_path / "repo"
        _write(root / "app.config.js", "module.exports = {};\n")  # fan_in 0, but matches config pattern
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)

        config_file = db_session.query(CodeFile).filter(CodeFile.repo_id == repo.id, CodeFile.path == "app.config.js").one()
        assert config_file.prior_category == "config"
        assert config_file.prior_source == "pattern"

        result = rank_repo(db_session, repo)

        db_session.refresh(config_file)
        assert config_file.prior_category == "config"  # untouched -- never became "entry"
        assert result["category_flips"] == []

    def test_stale_entry_marking_is_corrected_by_a_real_rank_run(self, db_session, tmp_path):
        # Phase G1 correction: prior_source == "structural" used to mean
        # "frozen forever" for entry/source categories -- a file hand-marked
        # "entry" (however that happened -- a bug, a stale migration, bad
        # test data) would keep that category, and its 1.4 prior, forever,
        # even though nothing about this file (no __main__ guard, no
        # FastAPI/Flask assignment) is actually detectable as an entry.
        # Live re-checking on every rank run means a real rank run corrects
        # this instead of preserving it -- the opposite of what this test
        # asserted before the fix.
        root = tmp_path / "repo"
        _write(root / "main.py", "def run():\n    pass\n")  # no real entry signal at all
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)

        main_file = db_session.query(CodeFile).filter(CodeFile.repo_id == repo.id, CodeFile.path == "main.py").one()
        main_file.prior_category = "entry"
        main_file.prior_source = "structural"  # a stale/incorrect prior classification
        db_session.commit()

        result = rank_repo(db_session, repo)

        db_session.refresh(main_file)
        assert main_file.prior_category == "source"  # corrected, not preserved
        assert result["category_flips"] == [{"path": "main.py", "old_category": "entry", "new_category": "source"}]

    def test_rerank_with_no_graph_change_produces_no_flips(self, db_session, tmp_path):
        root = tmp_path / "repo"
        _write(root / "main.py", "from lib import helper\nhelper()\n")
        _write(root / "lib.py", "def helper():\n    return 1\n")
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)
        rank_repo(db_session, repo)

        result = rank_repo(db_session, repo)
        assert result["category_flips"] == []


class TestWeightedPersonalizedPagerankAlgorithm:
    """Pure-function tests -- plain networkx graphs, no DB, no ingest. The
    legacy _pagerank()'s own dangling/normalization tests are untouched
    elsewhere in this file; Phase F3 adds a second, separate implementation
    rather than modifying that one (see ranking.py's module docstring)."""

    def test_pr_sums_to_one(self):
        g = nx.DiGraph()
        g.add_edge("a", "b")
        g.add_edge("b", "c")
        g.add_edge("c", "a")
        weights = {("a", "b"): 1.0, ("b", "c"): 1.0, ("c", "a"): 1.0}
        seed = {"a": 1.0, "b": 1.0, "c": 1.0}
        pr = weighted_personalized_pagerank(g, weights, seed, damping=0.65)
        assert abs(sum(pr.values()) - 1.0) < 1e-6

    def test_three_node_cycle_uniform_seed_gives_one_third_each(self):
        g = nx.DiGraph()
        g.add_edge("a", "b")
        g.add_edge("b", "c")
        g.add_edge("c", "a")
        weights = {("a", "b"): 1.0, ("b", "c"): 1.0, ("c", "a"): 1.0}
        seed = {"a": 1.0, "b": 1.0, "c": 1.0}
        pr = weighted_personalized_pagerank(g, weights, seed, damping=0.65)
        for node in ("a", "b", "c"):
            assert abs(pr[node] - 1 / 3) < 1e-6

    def test_two_out_edges_different_weights_distribute_in_four_to_one_ratio(self):
        # One source, two targets, edge weights 1.0 and 0.25 -- the direct
        # test of "edges distribute rank proportional to weight." (Not a
        # literal two-node graph: a single edge in a two-node graph would
        # normalize the weight away, w/W = w/w = 1 regardless of magnitude.)
        g = nx.DiGraph()
        g.add_edge("a", "b")
        g.add_edge("a", "c")
        weights = {("a", "b"): 1.0, ("a", "c"): 0.25}
        seed = {"a": 1.0}  # mass originates purely from a, isolating the ratio
        pr = weighted_personalized_pagerank(g, weights, seed, damping=0.65, max_iter=500)
        assert pr["c"] > 0
        assert abs(pr["b"] / pr["c"] - 4.0) < 1e-3

    def test_dangling_and_teleport_both_route_through_seed_not_uniformly(self):
        # The specific property this phase exists to fix: a node unreachable
        # from the seed and with no incoming edges must converge to EXACTLY
        # 0, not a small nonzero share from uniform teleport/dangling
        # redistribution. "d" here has no incoming edges and isn't seeded --
        # if either the (1-d)*s(f) term or the D*s(f) dangling term spread
        # uniformly instead of through s, d would pick up a nonzero value.
        g = nx.DiGraph()
        g.add_edge("a", "b")  # a and b are connected and seeded
        g.add_node("d")       # d is isolated and NOT seeded
        weights = {("a", "b"): 1.0}
        seed = {"a": 1.0}
        pr = weighted_personalized_pagerank(g, weights, seed, damping=0.65, max_iter=200)
        assert pr["d"] == 0.0

    def test_empty_seed_falls_back_to_uniform_documented_behavior(self):
        g = nx.DiGraph()
        g.add_edge("a", "b")
        weights = {("a", "b"): 1.0}
        pr = weighted_personalized_pagerank(g, weights, seed={}, damping=0.65)
        assert abs(sum(pr.values()) - 1.0) < 1e-6

    def test_empty_graph_returns_empty(self):
        assert weighted_personalized_pagerank(nx.DiGraph(), {}, {}) == {}


class TestWeightedPagerankScorer:
    def _make_repo(self, tmp_path) -> Path:
        root = tmp_path / "repo"
        _write(root / "main.tsx", 'import App from "./App";\nApp();\n')
        _write(root / "App.tsx", 'import { helper } from "./lib";\nhelper();\n')
        _write(root / "lib.ts", "export function helper(): number {\n  return 1;\n}\n")
        return root

    def test_basic_run_produces_scores_and_zero_mass_report(self, db_session, tmp_path):
        root = self._make_repo(tmp_path)
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)

        result = rank_repo_weighted_pagerank(db_session, repo, seed_paths=["main.tsx"])

        assert result["scorer"] == "weighted_pagerank"
        by_path = {f["path"]: f for f in result["files"]}
        assert by_path["lib.ts"]["pagerank"] > 0  # reachable from the seed
        assert "zero_mass_count" in result and "zero_mass_percentage" in result

    def test_missing_seed_path_reported_not_silently_dropped(self, db_session, tmp_path):
        root = self._make_repo(tmp_path)
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)

        result = rank_repo_weighted_pagerank(db_session, repo, seed_paths=["main.tsx", "does_not_exist.tsx"])
        assert result["missing_seed_paths"] == ["does_not_exist.tsx"]

    def test_all_seed_paths_missing_raises(self, db_session, tmp_path):
        root = self._make_repo(tmp_path)
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)

        with pytest.raises(ValueError):
            rank_repo_weighted_pagerank(db_session, repo, seed_paths=["nope.tsx"])

    def test_zero_mass_count_reported_for_unreachable_files(self, db_session, tmp_path):
        root = self._make_repo(tmp_path)
        _write(root / "isolated.tsx", "export const x = 1;\n")  # no edges at all, not seeded
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)

        result = rank_repo_weighted_pagerank(db_session, repo, seed_paths=["main.tsx"])
        by_path = {f["path"]: f for f in result["files"]}
        assert by_path["isolated.tsx"]["pagerank"] == 0.0
        assert result["zero_mass_count"] >= 1

    def test_deterministic_secondary_sort_by_path_among_tied_scores(self, db_session, tmp_path):
        root = tmp_path / "repo"
        _write(root / "main.tsx", "export const seed = 1;\n")
        # Three isolated files, all score exactly 0 -- score alone can't order them.
        _write(root / "zeta.ts", "export const z = 1;\n")
        _write(root / "alpha.ts", "export const a = 1;\n")
        _write(root / "mu.ts", "export const m = 1;\n")
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)

        result = rank_repo_weighted_pagerank(db_session, repo, seed_paths=["main.tsx"])
        zero_score_paths = [f["path"] for f in result["files"] if f["score"] == 0.0]
        assert zero_score_paths == sorted(zero_score_paths)

    def test_legacy_and_weighted_pagerank_rows_coexist(self, db_session, tmp_path):
        root = self._make_repo(tmp_path)
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)

        rank_repo(db_session, repo)
        rank_repo_weighted_pagerank(db_session, repo, seed_paths=["main.tsx"])

        legacy_count = db_session.query(CodeFileRank).filter(CodeFileRank.repo_id == repo.id, CodeFileRank.scorer == "legacy").count()
        wpr_count = db_session.query(CodeFileRank).filter(CodeFileRank.repo_id == repo.id, CodeFileRank.scorer == "weighted_pagerank").count()
        assert legacy_count == 3
        assert wpr_count == 3

        # re-running one scorer must not touch the other's rows
        rank_repo_weighted_pagerank(db_session, repo, seed_paths=["main.tsx"])
        legacy_count_after = db_session.query(CodeFileRank).filter(CodeFileRank.repo_id == repo.id, CodeFileRank.scorer == "legacy").count()
        assert legacy_count_after == 3

    def test_max_aggregation_across_multiple_import_rows_for_same_file_pair(self, db_session, tmp_path):
        # Two named imports from the same target file, one heavily used (a
        # strong signal) and one barely used (a weak one) -- the edge weight
        # for this file pair must be the MAX of the two, not their sum or
        # the weight of whichever row happened to be inserted last.
        from app.db.models import CodeFile
        from app.services.codebase import edge_weights as ew

        root = tmp_path / "repo"
        _write(root / "main.tsx", "export const seed = 1;\n")
        _write(root / "lib.ts", "export function heavy(): number { return 1; }\nexport function light(): number { return 1; }\n")
        _write(
            root / "consumer.ts",
            'import { heavy, light } from "./lib";\n'
            "heavy(); heavy(); heavy(); heavy(); heavy();\n"
            "light();\n",
        )
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)

        consumer = db_session.query(CodeFile).filter(CodeFile.repo_id == repo.id, CodeFile.path == "consumer.ts").one()
        lib = db_session.query(CodeFile).filter(CodeFile.repo_id == repo.id, CodeFile.path == "lib.ts").one()

        from app.services.codebase.ranking import _build_weighted_graph

        file_by_id = {f.id: f for f in db_session.query(CodeFile).filter(CodeFile.repo_id == repo.id).all()}
        _, edge_weight = _build_weighted_graph(db_session, repo, file_by_id)

        weights_config = ew.load_edge_weights()
        expected_max = max(ew.resolve_weight("heavy_use", weights_config), ew.resolve_weight("light_use", weights_config))
        assert edge_weight[(consumer.id, lib.id)] == expected_max


class TestLegacySignalSnapshotRefactor:
    """Phase F5's leave-one-out ablation reuses legacy_signal_snapshot +
    composite_score instead of a second copy of rank_repo's scoring math.
    This pins that shared path: calling composite_score with the snapshot's
    OWN active_weights (i.e. no ablation at all) must reproduce exactly what
    rank_repo persisted for real."""

    def _make_repo(self, tmp_path) -> Path:
        root = tmp_path / "repo"
        _write(root / "main.py", "from lib import helper\nhelper()\n")
        _write(root / "lib.py", "def helper():\n    return 1\n")
        return root

    def test_composite_score_with_no_ablation_matches_rank_repo_output(self, db_session, tmp_path):
        root = self._make_repo(tmp_path)
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)
        result = rank_repo(db_session, repo)
        by_path_score = {f["path"]: f["score"] for f in result["files"]}

        snapshot = legacy_signal_snapshot(db_session, repo)
        recomputed = composite_score(snapshot["file_by_id"].keys(), snapshot["norm_by_key"], snapshot["active_weights"])

        for fid, f in snapshot["file_by_id"].items():
            assert abs(recomputed[fid] - by_path_score[f.path]) < 1e-9


class TestFractionalRank:
    def test_no_ties_gives_ordinal_ranks(self):
        ranks = _fractional_rank({"a": 3, "b": 1, "c": 2})
        assert ranks == {"a": 1, "b": 3, "c": 2}

    def test_tied_values_share_average_rank(self):
        # a and b tie for best (ranks 1 and 2 -> average 1.5); c is alone at rank 3
        ranks = _fractional_rank({"a": 5, "b": 5, "c": 1})
        assert ranks["a"] == 1.5
        assert ranks["b"] == 1.5
        assert ranks["c"] == 3

    def test_all_tied_gives_every_item_the_same_middle_rank(self):
        ranks = _fractional_rank({"a": 1, "b": 1, "c": 1})
        assert ranks == {"a": 2.0, "b": 2.0, "c": 2.0}

    def test_higher_is_better_false_reverses_direction(self):
        # smaller value = better (e.g. days_since_last_change)
        ranks = _fractional_rank({"a": 3, "b": 1, "c": 2}, higher_is_better=False)
        assert ranks == {"a": 3, "b": 1, "c": 2}

    def test_empty_returns_empty(self):
        assert _fractional_rank({}) == {}


class TestReciprocalRankFusion:
    def test_single_signal_matches_the_plain_rrf_formula(self):
        values = {"a": 3, "b": 1, "c": 2}
        fused = reciprocal_rank_fusion({"only": values}, {"only": "desc"}, k=60)
        # a is rank 1, c rank 2, b rank 3
        assert abs(fused["a"] - 1 / 61) < 1e-9
        assert abs(fused["c"] - 1 / 62) < 1e-9
        assert abs(fused["b"] - 1 / 63) < 1e-9

    def test_asc_direction_inverts_ranking(self):
        values = {"a": 3, "b": 1, "c": 2}  # smaller = better under asc
        fused = reciprocal_rank_fusion({"days": values}, {"days": "asc"}, k=60)
        assert fused["b"] > fused["c"] > fused["a"]

    def test_multiple_signals_sum_their_terms(self):
        signal_values = {
            "sig1": {"a": 10, "b": 1},  # a rank 1, b rank 2
            "sig2": {"a": 1, "b": 10},  # a rank 2, b rank 1
        }
        fused = reciprocal_rank_fusion(signal_values, {"sig1": "desc", "sig2": "desc"}, k=60)
        # symmetric setup -- a and b should end up with identical fused scores
        assert abs(fused["a"] - fused["b"]) < 1e-9
        assert abs(fused["a"] - (1 / 61 + 1 / 62)) < 1e-9

    def test_missing_signal_for_a_file_contributes_no_term(self):
        # file "c" has no entry in either signal
        signal_values = {"sig1": {"a": 1, "b": 2}, "sig2": {"a": 1, "b": 2}}
        fused = reciprocal_rank_fusion(signal_values, {"sig1": "desc", "sig2": "desc"}, k=60)
        assert "c" not in fused

    def test_default_direction_is_desc_when_unspecified(self):
        values = {"a": 3, "b": 1}
        fused = reciprocal_rank_fusion({"sig": values}, {}, k=60)
        assert fused["a"] > fused["b"]


class TestRankRepoRRF:
    def _make_repo(self, tmp_path) -> Path:
        root = tmp_path / "repo"
        _write(root / "main.tsx", 'import App from "./App";\nApp();\n')
        _write(root / "App.tsx", 'import { helper } from "./lib";\nhelper();\n')
        _write(root / "lib.ts", "export function helper(): number {\n  return 1;\n}\n")
        return root

    def test_basic_run_produces_scores_and_uses_configured_k(self, db_session, tmp_path):
        root = self._make_repo(tmp_path)
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)

        result = rank_repo_rrf(db_session, repo)
        assert result["scorer"] == "rrf"
        assert result["k"] == load_rrf_config()["k"]
        by_path = {f["path"]: f for f in result["files"]}
        # lib.ts has fan_in=1 (from App.tsx) -- higher than the isolated seed's
        # fan_in=0 case elsewhere, so it must score above main.tsx (fan_in=0).
        assert by_path["lib.ts"]["score"] > by_path["main.tsx"]["score"]

    def test_explicit_k_overrides_config(self, db_session, tmp_path):
        root = self._make_repo(tmp_path)
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)

        result = rank_repo_rrf(db_session, repo, k=5)
        assert result["k"] == 5

    def test_rrf_rows_coexist_with_legacy_and_weighted_pagerank(self, db_session, tmp_path):
        root = self._make_repo(tmp_path)
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)

        rank_repo(db_session, repo)
        rank_repo_weighted_pagerank(db_session, repo, seed_paths=["main.tsx"])
        rank_repo_rrf(db_session, repo)

        for scorer in ("legacy", "weighted_pagerank", "rrf"):
            count = db_session.query(CodeFileRank).filter(CodeFileRank.repo_id == repo.id, CodeFileRank.scorer == scorer).count()
            assert count == 3, f"expected 3 rows for scorer={scorer}, got {count}"

    def test_deterministic_secondary_sort_by_path_among_tied_scores(self, db_session, tmp_path):
        root = tmp_path / "repo"
        _write(root / "alpha.ts", "export const a = 1;\n")
        _write(root / "beta.ts", "export const b = 1;\n")
        _write(root / "gamma.ts", "export const g = 1;\n")
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)

        result = rank_repo_rrf(db_session, repo)
        # three isolated, identical files -- all tied on every signal
        paths_in_order = [f["path"] for f in result["files"]]
        assert paths_in_order == sorted(paths_in_order)

    def test_reduced_confidence_without_git_history_omits_history_signals(self, db_session, tmp_path):
        root = self._make_repo(tmp_path)
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)

        result = rank_repo_rrf(db_session, repo)  # tmp_path has no .git -- history unavailable
        assert result["reduced_confidence"] is True
        for f in result["files"]:
            assert f["commit_count"] is None
            assert f["distinct_authors"] is None


class TestEntryPriorLiveRecheck:
    """Phase G1 correction: prior_category is refreshed against a fresh
    entry_detection call on EVERY rank run for files currently "entry" or
    "source" -- not just once, on a file's first-ever migration. Before
    this fix, prior_source flipping "graph" -> "structural" (a one-time
    event) silently froze prior_category forever after: a file that later
    gains a __main__ guard never earned the entry prior, and a real entry
    point later stripped of its guard kept a 1.4 multiplier forever, with
    nothing surfacing either direction."""

    def test_file_gaining_entry_status_flips_on_next_rank(self, db_session, tmp_path):
        # worker.py's own content never changes across the two rank runs --
        # only an external authoritative signal (a Dockerfile CMD) appears.
        # Deliberate: mutating worker.py's own content instead would make
        # ingest_repo re-parse it, and re-parsing unconditionally resets
        # prior_category/prior_source from classify_file_local_category
        # (which never returns "entry" -- that's graph/rank-time only),
        # which would flip this file back through the ORIGINAL "prior_source
        # == graph" migration branch, not the new live-recheck branch this
        # test exists to isolate. Keeping the file itself untouched is what
        # actually exercises the new code path.
        root = tmp_path / "repo"
        _write(root / "worker.py", "def run():\n    return 1\n")  # no code-pattern signal at all
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)
        first = rank_repo(db_session, repo)

        worker = db_session.query(CodeFile).filter(CodeFile.repo_id == repo.id, CodeFile.path == "worker.py").one()
        assert worker.prior_category == "source"
        assert worker.prior_source == "structural"  # migrated on the first run
        assert {"path": "worker.py", "old_category": "source", "new_category": "entry"} not in first["category_flips"]

        # External authoritative signal appears; worker.py itself is untouched.
        _write(root / "Dockerfile", 'CMD ["python", "-m", "worker"]\n')
        ingest_repo(db_session, repo)  # worker.py's content_sha256 is unchanged -- not re-parsed
        second = rank_repo(db_session, repo)

        db_session.refresh(worker)
        assert worker.prior_category == "entry"
        assert {"path": "worker.py", "old_category": "source", "new_category": "entry"} in second["category_flips"]

    def test_file_losing_entry_status_flips_back_on_next_rank(self, db_session, tmp_path):
        # Same isolation as the test above, mirrored: the Dockerfile is
        # removed, worker.py's own file is never touched.
        root = tmp_path / "repo"
        _write(root / "worker.py", "def run():\n    return 1\n")
        _write(root / "Dockerfile", 'CMD ["python", "-m", "worker"]\n')
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)
        rank_repo(db_session, repo)

        worker = db_session.query(CodeFile).filter(CodeFile.repo_id == repo.id, CodeFile.path == "worker.py").one()
        assert worker.prior_category == "entry"
        assert worker.prior_source == "structural"

        (root / "Dockerfile").unlink()
        ingest_repo(db_session, repo)  # worker.py's content_sha256 is unchanged -- not re-parsed
        result = rank_repo(db_session, repo)

        db_session.refresh(worker)
        assert worker.prior_category == "source"
        assert {"path": "worker.py", "old_category": "entry", "new_category": "source"} in result["category_flips"]

    def test_config_category_never_flipped_by_live_recheck(self, db_session, tmp_path):
        # A config-pattern file's content would never match an entry
        # pattern anyway, but this proves the live recheck doesn't even
        # consider "config"/"migration"/"generated"/"barrel" categories --
        # they're structural/pattern facts, not graph- or
        # detection-dependent, on every single rank run, not just the first.
        root = tmp_path / "repo"
        _write(root / "app.config.js", "module.exports = {};\n")
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)
        rank_repo(db_session, repo)
        result = rank_repo(db_session, repo)  # second run -- live recheck path

        config_file = db_session.query(CodeFile).filter(CodeFile.repo_id == repo.id, CodeFile.path == "app.config.js").one()
        assert config_file.prior_category == "config"
        assert result["category_flips"] == []

    def test_contradiction_detected_on_a_later_run_not_just_the_first(self, db_session, tmp_path):
        # The same staleness bug applied to contradiction reporting: it used
        # to live inside the same early `continue`, so a contradiction that
        # only became true on a LATER run (new importers added after the
        # file was first detected as an entry) was never caught.
        root = tmp_path / "repo"
        _write(root / "main.py", "def run():\n    return 1\n\nif __name__ == '__main__':\n    run()\n")
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)
        first = rank_repo(db_session, repo)
        assert first["contradictions"] == []

        # Add importers of main.py after the fact -- a real entry point
        # should never be imported by other source files.
        _write(root / "a.py", "import main\n")
        ingest_repo(db_session, repo)
        second = rank_repo(db_session, repo)

        contradiction_paths = {c["path"] for c in second["contradictions"]}
        assert "main.py" in contradiction_paths


class TestEntryDetectionMigration:
    """Phase E4: real config/code-pattern detection replaces the
    fan_in==0-or-basename heuristic as the thing that decides
    prior_category == "entry". orphan.py in this fixture has fan_in == 0
    (nothing imports it) but is not a real entry point -- exactly the case
    the old heuristic got wrong, and the regression this phase exists to fix."""

    def _make_repo(self, tmp_path) -> Path:
        root = tmp_path / "repo"
        _write(root / "main.py", "from lib import helper\n\ndef run():\n    helper()\n\nif __name__ == '__main__':\n    run()\n")
        _write(root / "lib.py", "def helper():\n    return 1\n")
        _write(root / "orphan.py", "def unused():\n    return 2\n")
        return root

    def test_detected_entry_gets_entry_category_and_structural_source(self, db_session, tmp_path):
        from app.db.models import CodeFile

        root = self._make_repo(tmp_path)
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)
        rank_repo(db_session, repo)

        main_file = db_session.query(CodeFile).filter(CodeFile.repo_id == repo.id, CodeFile.path == "main.py").one()
        assert main_file.prior_category == "entry"
        assert main_file.prior_source == "structural"

    def test_zero_fan_in_non_entry_file_stays_source_not_entry(self, db_session, tmp_path):
        from app.db.models import CodeFile

        root = self._make_repo(tmp_path)
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)
        rank_repo(db_session, repo)

        orphan = db_session.query(CodeFile).filter(CodeFile.repo_id == repo.id, CodeFile.path == "orphan.py").one()
        assert orphan.prior_category == "source"
        assert orphan.prior_source == "structural"  # migrated off "graph", but never promoted to entry

    def test_is_entry_point_signal_reflects_detection_not_fan_in(self, db_session, tmp_path):
        root = self._make_repo(tmp_path)
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)
        result = rank_repo(db_session, repo)

        by_path = {f["path"]: f for f in result["files"]}
        assert by_path["main.py"]["is_entry_point"] is True
        assert by_path["orphan.py"]["is_entry_point"] is False  # fan_in == 0 too, but not detected

    def test_migration_reported_once_not_on_every_subsequent_run(self, db_session, tmp_path):
        root = self._make_repo(tmp_path)
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)

        first = rank_repo(db_session, repo)
        assert len(first["prior_source_migrations"]) == 3

        second = rank_repo(db_session, repo)
        assert second["prior_source_migrations"] == []
        assert second["category_flips"] == []

    def test_contradiction_flagged_when_detected_entry_has_nonzero_fan_in(self, db_session, tmp_path):
        root = tmp_path / "repo"
        _write(root / "index.html", '<script type="module" src="/main.tsx"></script>\n')
        _write(root / "main.tsx", 'import App from "./App";\n')
        _write(
            root / "App.tsx",
            "import { createRoot } from 'react-dom/client';\ncreateRoot(document.getElementById('root')).render(null);\n",
        )
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)
        result = rank_repo(db_session, repo)

        contradiction_paths = {c["path"] for c in result["contradictions"]}
        assert "App.tsx" in contradiction_paths
        assert "main.tsx" not in contradiction_paths


class TestEntryDetectionAcrossSourceRoot:
    """Real bug, found by external validation on eslint/eslint (source_root
    scoped to "lib", package.json's "main" at the true root naming a file
    inside "lib"): entry detection used to search for authoritative config
    starting from the source_root-scoped path, so it never looked at the
    true repo root where that config conventionally lives. Fixed by
    ranking._detect_entries passing config_search_root=repo.local_path
    (always the true root) alongside the existing source_root-scoped
    repo_root (which still governs how CodeFile.path is resolved)."""

    def test_package_json_main_above_source_root_is_detected(self, db_session, tmp_path):
        root = tmp_path / "repo"
        _write(root / "package.json", '{"main": "./lib/api.js"}')
        _write(root / "lib" / "api.js", "export function run() { return 1; }\n")
        repo = register_from_path(db_session, str(root), source_root="lib")
        ingest_repo(db_session, repo)
        result = rank_repo(db_session, repo)

        by_path = {f["path"]: f for f in result["files"]}
        assert by_path["api.js"]["is_entry_point"] is True

    def test_package_json_bin_outside_source_root_is_not_a_false_positive(self, db_session, tmp_path):
        root = tmp_path / "repo"
        _write(root / "package.json", '{"bin": "./bin/cli.js"}')
        _write(root / "bin" / "cli.js", "#!/usr/bin/env node\n")
        _write(root / "lib" / "index.js", "export function run() { return 1; }\n")
        repo = register_from_path(db_session, str(root), source_root="lib")
        ingest_repo(db_session, repo)
        result = rank_repo(db_session, repo)

        by_path = {f["path"]: f for f in result["files"]}
        assert by_path["index.js"]["is_entry_point"] is False


class TestFileLevelSignalStorage:
    """Phase G1: fan_in/fan_out/is_entry_point/commit_count/distinct_authors/
    days_since_last_change moved off CodeFileRank (once per (file, scorer),
    no mechanism forcing agreement) onto CodeFile; reduced_confidence
    (repo-wide, not file-level) moved onto Repo. Diagnosed live on
    /repos/:id, which read CodeFileRank without filtering by scorer and
    showed the same file's commit count as a real number under one scorer
    and null under another."""

    def _make_repo(self, tmp_path) -> Path:
        root = tmp_path / "repo"
        _init_repo(root)
        _write(root / "main.py", "from helper import run\n\nif __name__ == '__main__':\n    run()\n")
        _write(root / "helper.py", "def run():\n    return 1\n")
        _git(root, "add", "-A")
        _git(root, "-c", "user.name=Alice", "-c", "user.email=alice@t.com", "commit", "-m", "initial")
        return root

    def test_legacy_writes_file_level_signals_onto_code_file(self, db_session, tmp_path):
        root = self._make_repo(tmp_path)
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)
        rank_repo(db_session, repo)

        helper = db_session.query(CodeFile).filter(CodeFile.repo_id == repo.id, CodeFile.path == "helper.py").one()
        assert helper.fan_in == 1
        assert helper.fan_out == 0
        assert helper.is_entry_point is False
        assert helper.commit_count == 1
        assert helper.distinct_authors == 1

        db_session.refresh(repo)
        assert repo.reduced_confidence is False

    def test_rank_row_no_longer_has_file_level_columns(self, db_session, tmp_path):
        root = self._make_repo(tmp_path)
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)
        rank_repo(db_session, repo)

        row = db_session.query(CodeFileRank).filter(CodeFileRank.repo_id == repo.id).first()
        assert not hasattr(row, "fan_in")
        assert not hasattr(row, "commit_count")
        assert not hasattr(row, "reduced_confidence")
        assert row.rank >= 1  # the field that replaced them

    def test_weighted_pagerank_does_not_clobber_history_written_by_legacy(self, db_session, tmp_path):
        # weighted_pagerank has no history term at all -- running it AFTER
        # legacy must leave legacy's commit_count/distinct_authors on
        # CodeFile untouched, not wipe them to null.
        root = self._make_repo(tmp_path)
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)
        rank_repo(db_session, repo)
        rank_repo_weighted_pagerank(db_session, repo)

        helper = db_session.query(CodeFile).filter(CodeFile.repo_id == repo.id, CodeFile.path == "helper.py").one()
        assert helper.commit_count == 1  # still here, not None
        assert helper.distinct_authors == 1
        assert helper.fan_in == 1  # weighted_pagerank's own (identical) graph value

    def test_rank_stored_matches_score_order(self, db_session, tmp_path):
        root = self._make_repo(tmp_path)
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)
        result = rank_repo(db_session, repo)

        rows = {
            r.file_id: r.rank
            for r in db_session.query(CodeFileRank).filter(CodeFileRank.repo_id == repo.id, CodeFileRank.scorer == "legacy")
        }
        expected_order = [f["file_id"] for f in result["files"]]  # already sorted by score desc
        for i, fid in enumerate(expected_order, start=1):
            assert rows[fid] == i

    def test_rrf_and_legacy_ranks_are_independent(self, db_session, tmp_path):
        root = self._make_repo(tmp_path)
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)
        rank_repo(db_session, repo)
        rank_repo_rrf(db_session, repo)

        legacy_ranks = {
            r.file_id: r.rank
            for r in db_session.query(CodeFileRank).filter(CodeFileRank.repo_id == repo.id, CodeFileRank.scorer == "legacy")
        }
        rrf_ranks = {
            r.file_id: r.rank
            for r in db_session.query(CodeFileRank).filter(CodeFileRank.repo_id == repo.id, CodeFileRank.scorer == "rrf")
        }
        assert sorted(legacy_ranks.values()) == [1, 2]
        assert sorted(rrf_ranks.values()) == [1, 2]  # independent 1..N per scorer, not a shared sequence


class TestWeightedPagerankSeedAutoDerivation:
    def _make_repo(self, tmp_path) -> Path:
        root = tmp_path / "repo"
        _write(root / "index.html", '<script type="module" src="/main.tsx"></script>\n')
        _write(root / "main.tsx", 'import App from "./App";\nApp();\n')
        _write(root / "App.tsx", 'import { helper } from "./lib";\nhelper();\n')
        _write(root / "lib.ts", "export function helper(): number {\n  return 1;\n}\n")
        return root

    def test_auto_derives_seed_from_detected_entries_when_seed_paths_omitted(self, db_session, tmp_path):
        root = self._make_repo(tmp_path)
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)

        result = rank_repo_weighted_pagerank(db_session, repo)
        assert result["seed_auto_derived"] is True
        assert result["seed_paths"] == ["main.tsx"]

    def test_explicit_seed_overrides_detection(self, db_session, tmp_path):
        root = self._make_repo(tmp_path)
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)

        result = rank_repo_weighted_pagerank(db_session, repo, seed_paths=["App.tsx"])
        assert result["seed_auto_derived"] is False
        assert result["seed_paths"] == ["App.tsx"]

    def test_structurally_inert_entry_excluded_from_seed_but_reported(self, db_session, tmp_path):
        # Phase F7 incident: backend/run.py and voice_listener/wake_word.py
        # on repo 1 are both real, seed-eligible detected entries with
        # fan_out == 0 -- their entire share of teleport mass has nowhere
        # to propagate, ever, regardless of how many other seeds exist.
        # This is a structural fact about the entry, not a path-marker
        # judgment call the way seed_exclude_paths is.
        root = tmp_path / "repo"
        _write(root / "index.html", '<script type="module" src="/main.tsx"></script>\n')
        _write(root / "main.tsx", 'import App from "./App";\nApp();\n')
        _write(root / "App.tsx", "export default function App() { return null }\n")
        _write(root / "standalone_launcher.py", "if __name__ == '__main__':\n    pass\n")
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)

        result = rank_repo_weighted_pagerank(db_session, repo)
        assert result["seed_auto_derived"] is True
        assert result["seed_paths"] == ["main.tsx"]
        assert result["seed_excluded_structurally_inert"] == ["standalone_launcher.py"]

    def test_raises_when_every_seed_eligible_entry_is_structurally_inert(self, db_session, tmp_path):
        root = tmp_path / "repo"
        _write(root / "standalone_launcher.py", "if __name__ == '__main__':\n    pass\n")
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)

        with pytest.raises(ValueError, match="No seed-eligible entry points with real outgoing edges"):
            rank_repo_weighted_pagerank(db_session, repo)

    def test_fan_out_zero_entry_still_gets_the_entry_prior(self, db_session, tmp_path):
        root = tmp_path / "repo"
        _write(root / "index.html", '<script type="module" src="/main.tsx"></script>\n')
        _write(root / "main.tsx", 'import App from "./App";\nApp();\n')
        _write(root / "App.tsx", "export default function App() { return null }\n")
        _write(root / "standalone_launcher.py", "if __name__ == '__main__':\n    pass\n")
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)

        rank_repo_weighted_pagerank(db_session, repo)
        launcher = db_session.query(CodeFile).filter(
            CodeFile.repo_id == repo.id, CodeFile.path == "standalone_launcher.py"
        ).one()
        assert launcher.prior_category == "entry"  # structurally inert for SEEDING, still a real entry

    def test_raises_loudly_when_no_entries_detected_and_no_explicit_seed(self, db_session, tmp_path):
        root = tmp_path / "repo"
        _write(root / "a.ts", "export const a = 1;\n")
        _write(root / "b.ts", "export const b = 1;\n")
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)

        with pytest.raises(ValueError, match="No seed-eligible entry points with real outgoing edges detected"):
            rank_repo_weighted_pagerank(db_session, repo)

    def test_prior_only_entry_excluded_from_auto_derived_seed_but_still_gets_the_prior(self, db_session, tmp_path):
        # E4 refinement: a script under scripts/ with its own __main__ guard
        # is a genuine entry (earns prior_category="entry") but must not
        # inject PageRank teleport mass -- that's what seed_eligible gates.
        from app.db.models import CodeFile

        root = tmp_path / "repo"
        _write(root / "index.html", '<script type="module" src="/main.tsx"></script>\n')
        _write(root / "main.tsx", 'import App from "./App";\n')
        _write(root / "App.tsx", "export default function App() { return null }\n")
        _write(root / "scripts" / "validate.py", "import argparse\n\nif __name__ == '__main__':\n    pass\n")
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)

        result = rank_repo_weighted_pagerank(db_session, repo)
        assert result["seed_auto_derived"] is True
        assert result["seed_paths"] == ["main.tsx"]
        assert result["seed_eligible_entries"] == ["main.tsx"]
        assert result["prior_only_entries"] == ["scripts/validate.py"]

        validate_file = db_session.query(CodeFile).filter(
            CodeFile.repo_id == repo.id, CodeFile.path == "scripts/validate.py"
        ).one()
        assert validate_file.prior_category == "entry"

    def test_repo_seed_exclude_paths_overrides_an_otherwise_seed_eligible_entry(self, db_session, tmp_path):
        # A standalone auxiliary component that no generic marker catches
        # (voice_listener/ isn't scripts/tools/tests) -- the per-repo
        # override is the only way to exclude it from seeding.
        root = tmp_path / "repo"
        _write(root / "index.html", '<script type="module" src="/main.tsx"></script>\n')
        _write(root / "main.tsx", 'import App from "./App";\n')
        _write(root / "App.tsx", "export default function App() { return null }\n")
        _write(root / "voice_listener" / "wake_word.py", "if __name__ == '__main__':\n    pass\n")
        repo = register_from_path(db_session, str(root))
        repo.seed_exclude_paths = ["voice_listener/"]
        db_session.commit()
        ingest_repo(db_session, repo)

        result = rank_repo_weighted_pagerank(db_session, repo)
        assert result["seed_paths"] == ["main.tsx"]
        assert result["prior_only_entries"] == ["voice_listener/wake_word.py"]


class TestRankRepoHoldsRepoLock:
    """Phase E2.3 incident follow-up: rank must refuse to run concurrently
    with another ingest/rank for the SAME repo -- see repo_lock.py."""

    def _make_repo(self, tmp_path) -> Path:
        root = tmp_path / "repo"
        _write(root / "main.py", "def run():\n    pass\n")
        return root

    def test_rank_repo_refuses_while_repo_lock_already_held(self, db_session, tmp_path):
        root = self._make_repo(tmp_path)
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)

        with repo_lock(repo.id, "test"):
            with pytest.raises(RepoBusyError):
                rank_repo(db_session, repo)

    def test_rank_repo_rrf_refuses_while_repo_lock_already_held(self, db_session, tmp_path):
        root = self._make_repo(tmp_path)
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)

        with repo_lock(repo.id, "test"):
            with pytest.raises(RepoBusyError):
                rank_repo_rrf(db_session, repo)

    def test_weighted_pagerank_refuses_while_repo_lock_already_held(self, db_session, tmp_path):
        root = tmp_path / "repo"
        _write(root / "index.html", '<script type="module" src="/main.tsx"></script>\n')
        _write(root / "main.tsx", "export {}\n")
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)

        with repo_lock(repo.id, "test"):
            with pytest.raises(RepoBusyError):
                rank_repo_weighted_pagerank(db_session, repo)

    def test_rank_releases_lock_after_completing(self, db_session, tmp_path):
        root = self._make_repo(tmp_path)
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)

        rank_repo(db_session, repo)
        with repo_lock(repo.id, "test"):  # must succeed -- rank released its own lock
            pass


class TestResolutionRateTripwire:
    """Phase E2.3 incident: a rank read once observed a Python resolution
    rate that had silently collapsed, and nothing caught it automatically.
    This is the general defense -- every rank run compares against the
    repo's high-water mark and refuses if it collapsed. Phase F7 renamed
    the underlying column from last_python_resolution_rate to
    python_resolution_high_water_mark and changed its update rule from
    "last observed" to max() -- see _check_resolution_rate_tripwire."""

    def _make_repo(self, tmp_path) -> Path:
        # 4 absolute imports resolving via a promoted root -- enough for a
        # real, non-trivial resolution rate to establish a baseline.
        root = tmp_path / "repo"
        _write(root / "backend" / "requirements.txt", "fastapi\n")
        _write(root / "backend" / "app" / "__init__.py", "")
        _write(
            root / "backend" / "app" / "main.py",
            "from app.a import x\nfrom app.b import y\nfrom app.c import z\nfrom app.d import w\n",
        )
        _write(root / "backend" / "app" / "a.py", "x = 1\n")
        _write(root / "backend" / "app" / "b.py", "y = 1\n")
        _write(root / "backend" / "app" / "c.py", "z = 1\n")
        _write(root / "backend" / "app" / "d.py", "w = 1\n")
        return root

    def test_first_rank_run_records_a_baseline_without_raising(self, db_session, tmp_path):
        root = self._make_repo(tmp_path)
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)

        rank_repo(db_session, repo)  # must not raise -- no previous rate to compare against
        db_session.refresh(repo)
        assert repo.python_resolution_high_water_mark == 1.0

    def test_stable_resolution_across_reranks_does_not_raise(self, db_session, tmp_path):
        root = self._make_repo(tmp_path)
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)

        rank_repo(db_session, repo)
        rank_repo(db_session, repo)  # must not raise -- rate unchanged

    def test_collapsed_resolution_raises_and_names_both_rates(self, db_session, tmp_path):
        root = self._make_repo(tmp_path)
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)
        rank_repo(db_session, repo)  # establishes baseline: rate == 1.0

        # simulate the Phase E2.3 incident directly: something resets
        # resolution for this repo's Python rows without re-ingesting.
        python_file_ids = {f.id for f in db_session.query(CodeFile).filter(CodeFile.repo_id == repo.id).all()}
        for row in db_session.query(CodeImport).filter(CodeImport.repo_id == repo.id).all():
            if row.from_file_id in python_file_ids:
                row.resolved = False
                row.to_file_id = None
        db_session.commit()

        with pytest.raises(ResolutionRateCollapseError, match=r"100\.0%.*0\.0%"):
            rank_repo(db_session, repo)

    def test_no_collapse_check_when_previous_rate_was_below_the_floor(self, db_session, tmp_path):
        # a repo whose baseline resolution was already near-zero shouldn't
        # trip on further noise near that same floor.
        root = tmp_path / "repo"
        _write(root / "main.py", "import fastapi\nimport sqlalchemy\n")  # nothing resolves internally
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)

        rank_repo(db_session, repo)  # baseline: rate == 0.0 (below minimum_previous_rate_to_check)
        rank_repo(db_session, repo)  # must not raise

    def test_no_python_files_gives_no_rate_and_never_raises(self, db_session, tmp_path):
        root = tmp_path / "repo"
        _write(root / "src" / "main.ts", "export {}\n")
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)

        rank_repo(db_session, repo)  # must not raise -- no Python rows to measure
        db_session.refresh(repo)
        assert repo.python_resolution_high_water_mark is None

    def test_high_water_mark_never_moves_down_on_a_non_tripping_call(self, db_session, tmp_path):
        # A rate DROP that's still above the collapse threshold must not
        # lower the stored baseline -- only a higher rate (or the same one)
        # should ever be recorded, so a later, smaller drop is still judged
        # against the true peak, not against this intermediate dip.
        root = self._make_repo(tmp_path)
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)
        rank_repo(db_session, repo)  # baseline: rate == 1.0
        db_session.refresh(repo)
        assert repo.python_resolution_high_water_mark == 1.0

        # Drop one of four imports to unresolved: rate 1.0 -> 0.75, which is
        # NOT below collapse_relative_threshold (0.5) of 1.0, so this must
        # not raise -- but it also must not lower the recorded high-water mark.
        python_file_ids = {f.id for f in db_session.query(CodeFile).filter(CodeFile.repo_id == repo.id).all()}
        one_row = next(
            row for row in db_session.query(CodeImport).filter(CodeImport.repo_id == repo.id).all()
            if row.from_file_id in python_file_ids and row.resolved
        )
        one_row.resolved = False
        one_row.to_file_id = None
        db_session.commit()

        rank_repo(db_session, repo)  # must not raise: 0.75 >= 1.0 * 0.5
        db_session.refresh(repo)
        assert repo.python_resolution_high_water_mark == 1.0  # unchanged, NOT dropped to 0.75

    def test_high_water_mark_catches_a_collapse_a_last_observed_baseline_would_miss(self, db_session, tmp_path):
        # The exact "boiling frog" case the rename fixes: two individually
        # small drops, each staying just above 50% of its own immediate
        # predecessor, but the cumulative drop from the TRUE peak (1.0) is
        # a real collapse that a last-observed baseline would never catch.
        root = self._make_repo(tmp_path)
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)
        rank_repo(db_session, repo)  # baseline/high-water mark: 1.0

        python_file_ids = {f.id for f in db_session.query(CodeFile).filter(CodeFile.repo_id == repo.id).all()}
        python_rows = [
            row for row in db_session.query(CodeImport).filter(CodeImport.repo_id == repo.id).all()
            if row.from_file_id in python_file_ids
        ]

        # Step 1: 4/4 -> 3/4 resolved (0.75). Not a collapse relative to the
        # 1.0 high-water mark (0.75 >= 0.5), so this must not raise, and the
        # high-water mark must stay at 1.0 (per the test above).
        python_rows[0].resolved = False
        python_rows[0].to_file_id = None
        db_session.commit()
        rank_repo(db_session, repo)

        # Step 2: 3/4 -> 1/4 resolved (0.25). A last-observed baseline would
        # compare 0.25 against 0.75 (0.25 < 0.75*0.5 == 0.375) -- that WOULD
        # trip either way here, so make step 2 land just above half of the
        # LAST-OBSERVED 0.75 (i.e. > 0.375) while still being a real,
        # severe collapse relative to the true 1.0 peak (0.25 < 1.0*0.5).
        python_rows[1].resolved = False
        python_rows[1].to_file_id = None
        db_session.commit()  # now 2/4 == 0.5 -- above 0.75*0.5 (0.375), a last-observed check would pass this
        rank_repo(db_session, repo)  # must not raise: 0.5 >= 0.75*0.5, and 0.5 >= 1.0*0.5 too -- not yet a collapse

        # Step 3: one more drop, 2/4 -> 1/4 (0.25). Relative to the last
        # OBSERVED rate (0.5), this is exactly the boundary; relative to the
        # TRUE high-water mark (1.0, unchanged throughout since it never
        # moved down), 0.25 is a genuine collapse that must raise.
        python_rows[2].resolved = False
        python_rows[2].to_file_id = None
        db_session.commit()
        with pytest.raises(ResolutionRateCollapseError, match=r"100\.0%.*25\.0%"):
            rank_repo(db_session, repo)


class TestHistoryCollectionSurvivesSlowRepos:
    """Cascade suppression, instance 3: an uncaught TimeoutExpired walked past
    this function's own "None means no history" contract, so one slow git log
    cost apache/superset its entire ranking -- no fan-in, no fan-out, no
    reading list, and an Architecture axis marked N/A for want of inputs a
    different pass had already computed."""

    def _repo(self, db_session, tmp_path):
        root = tmp_path / "repo"
        _init_repo(root)
        _write(root / "a.py", "def a():\n    return 1\n")
        _write(root / "b.py", "from a import a\n\n\ndef b():\n    return a() + 1\n")
        _git(root, "add", "-A")
        _git(root, "-c", "user.name=A", "-c", "user.email=a@t.com", "commit", "-m", "initial")
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)
        return repo

    @staticmethod
    def _failing_log(exc):
        """Fail only the `git log` call. Patching run_git wholesale would break
        the earlier `rev-parse --show-toplevel` instead, and pass for the wrong
        reason -- the guard under test is on the log call specifically."""
        real = git_ops.run_git

        def side_effect(args, **kw):
            if args and args[0] == "log":
                raise exc
            return real(args, **kw)

        return side_effect

    def test_a_timeout_degrades_to_no_history_instead_of_failing(self, db_session, tmp_path):
        import subprocess
        repo = self._repo(db_session, tmp_path)

        exc = subprocess.TimeoutExpired(cmd="git log", timeout=600)
        with patch("app.services.codebase.git_ops.run_git", side_effect=self._failing_log(exc)):
            assert ranking._collect_git_history(repo) is None

    def test_a_timeout_does_not_stop_the_ranking_run(self, db_session, tmp_path):
        """The load-bearing property: --no-renames makes the known-large case
        fast, this makes every other large case survivable."""
        import subprocess
        repo = self._repo(db_session, tmp_path)

        with patch("app.services.codebase.ranking._collect_git_history",
                   side_effect=lambda r: None):
            rank_repo(db_session, repo)

        rows = db_session.query(CodeFileRank).filter(CodeFileRank.repo_id == repo.id).all()
        assert rows, "ranking must still produce rows when history is unavailable"
        files = db_session.query(CodeFile).filter(CodeFile.repo_id == repo.id).all()
        assert all(f.fan_in is not None for f in files), (
            "fan-in/fan-out come from the import graph, not from git history, and must "
            "survive a history failure"
        )

    def test_an_os_error_degrades_the_same_way(self, db_session, tmp_path):
        repo = self._repo(db_session, tmp_path)
        with patch("app.services.codebase.git_ops.run_git",
                   side_effect=self._failing_log(OSError("boom"))):
            assert ranking._collect_git_history(repo) is None


class TestHistoryCommandShape:
    """--numstat asked for line counts the parser discarded on the next line,
    and rename detection needs blob CONTENT -- which a --filter=blob:none clone
    does not have locally, turning every rename check into a network round
    trip. Measured on superset: 427s extrapolated vs 8.45s."""

    def _repo(self, db_session, tmp_path):
        root = tmp_path / "repo"
        _init_repo(root)
        _write(root / "a.py", "def a():\n    return 1\n")
        _git(root, "add", "-A")
        _git(root, "-c", "user.name=A", "-c", "user.email=a@t.com", "commit", "-m", "initial")
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)
        return repo

    def test_rename_detection_is_disabled(self, db_session, tmp_path):
        repo = self._repo(db_session, tmp_path)
        seen = {}

        real = git_ops.run_git

        def capture(args, **kw):
            if args and args[0] == "log":
                seen["args"] = args
            return real(args, **kw)

        with patch("app.services.codebase.git_ops.run_git", side_effect=capture):
            ranking._collect_git_history(repo)

        assert "--no-renames" in seen["args"], (
            "without this, a blob-filtered clone lazily fetches blobs to compare "
            "file contents for rename detection"
        )
        assert "--name-only" in seen["args"]
        assert "--numstat" not in seen["args"], "the add/delete columns were never used"

    def test_history_is_still_collected_correctly(self, db_session, tmp_path):
        """The command changed; the output it produces must not."""
        repo = self._repo(db_session, tmp_path)
        history = ranking._collect_git_history(repo)
        assert history is not None
        assert "a.py" in history
        assert history["a.py"]["commit_count"] == 1
        assert history["a.py"]["authors"] == {"A"}

    def test_a_second_commit_increments_the_count(self, db_session, tmp_path):
        repo = self._repo(db_session, tmp_path)
        root = Path(repo.local_path)
        _write(root / "a.py", "def a():\n    return 2\n")
        _git(root, "add", "-A")
        _git(root, "-c", "user.name=B", "-c", "user.email=b@t.com", "commit", "-m", "second")

        history = ranking._collect_git_history(repo)
        assert history["a.py"]["commit_count"] == 2
        assert history["a.py"]["authors"] == {"A", "B"}


class TestGitOutputDecoding:
    """Pins the fix for the four-layer failure on apache/superset:

        180s timeout -> UnicodeDecodeError -> stdout=None -> AttributeError

    `text=True` decodes with the platform default. On Windows that is the ANSI
    codepage (cp1252 here); git emits UTF-8 author names.

    ## Why the first test looks structural rather than behavioural

    The bug is platform-specific: on Linux the default IS UTF-8, so a purely
    behavioural test passes there whether or not the fix is present -- the
    classic pass-for-the-wrong-reason. Forcing a locale in CI is worse, because
    locale handling is itself environment-dependent in exactly the way that
    produces false confidence.

    So the configuration is asserted directly. It fails on every platform if
    the fix is reverted. The behavioural test below then proves the
    configuration actually achieves the round trip.
    """

    def test_LOADBEARING_run_git_pins_utf8_and_never_inherits_the_platform_default(self):
        """This is the one that pins the bug. Platform-independent by
        construction: it fails on Linux and Windows alike if reverted."""
        seen = {}

        def fake_run(cmd, **kw):
            seen.update(kw)
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with patch("app.services.codebase.git_ops.subprocess.run", side_effect=fake_run):
            git_ops.run_git(["status"], cwd=".")

        assert seen.get("encoding") == "utf-8", (
            "text=True would decode with the platform codepage -- cp1252 on Windows, "
            "UTF-8 on Linux. That difference is why this assertion is structural: a "
            "behavioural test alone passes on Linux with the bug still present."
        )
        assert seen.get("errors") == "replace", (
            "one unmappable byte must not cost a repository its entire history"
        )
        assert seen.get("text") is not True, "text=True re-introduces platform-default decoding"

    def test_DOCUMENTS_INTENT_a_non_latin1_author_name_survives_the_round_trip(
            self, db_session, tmp_path):
        """Companion, deliberately NOT the primary. U+4E2D is outside cp1252,
        so on Windows this raised UnicodeDecodeError inside subprocess's reader
        thread and surfaced as stdout=None.

        But on Linux the platform default IS UTF-8, so this passes there with
        the defect fully present. It documents the intent and proves the round
        trip works; it does not pin the bug. The structural test above does
        that."""
        root = tmp_path / "repo"
        _init_repo(root)
        _write(root / "a.py", "def a():\n    return 1\n")
        _git(root, "add", "-A")
        _git(root, "-c", "user.name=\u4e2d\u6751", "-c", "user.email=n@t.com",
             "commit", "-m", "initial")

        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)
        history = ranking._collect_git_history(repo)

        assert history is not None, "a non-ASCII author name must not kill history collection"
        assert history["a.py"]["authors"] == {"\u4e2d\u6751"}

    def test_history_survives_a_none_stdout(self, db_session, tmp_path):
        """The layer beneath: even with decoding fixed, a None stdout from any
        future cause must return None rather than raising AttributeError."""
        root = tmp_path / "repo"
        _init_repo(root)
        _write(root / "a.py", "x = 1\n")
        _git(root, "add", "-A")
        _git(root, "-c", "user.name=A", "-c", "user.email=a@t.com", "commit", "-m", "i")
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)

        real = git_ops.run_git

        def none_stdout(args, **kw):
            if args and args[0] == "log":
                return subprocess.CompletedProcess(args, 0, stdout=None, stderr="")
            return real(args, **kw)

        with patch("app.services.codebase.git_ops.run_git", side_effect=none_stdout):
            assert ranking._collect_git_history(repo) is None
