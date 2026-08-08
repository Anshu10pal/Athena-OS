"""Phase G1: GET /api/repos/{id}/ranking. Calls the route function directly
with a real db_session, same convention this test suite already uses for
service-layer functions -- this app has no existing TestClient-based API
tests to follow instead, and route functions here don't use their `user`
parameter for anything but FastAPI's own dependency injection, so passing
`user=None` directly is safe and avoids introducing a second testing style
for one endpoint.
"""
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.api.repos import NEIGHBORS_ENDPOINT_CAP, VALID_SCORERS, get_file_neighbors, get_graph, get_ranking
from app.services.codebase.git_ops import run_git
from app.services.codebase.ingest import ingest_repo
from app.services.codebase.ranking import rank_repo, rank_repo_rrf, rank_repo_weighted_pagerank
from app.services.codebase.registry import register_from_path


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


class TestGetRankingEndpoint:
    def _make_repo(self, tmp_path) -> Path:
        root = tmp_path / "repo"
        _init_repo(root)
        _write(root / "main.py", "from helper import run\n\nif __name__ == '__main__':\n    run()\n")
        _write(root / "helper.py", "def run():\n    return 1\n")
        _git(root, "add", "-A")
        _git(root, "-c", "user.name=Alice", "-c", "user.email=alice@t.com", "commit", "-m", "initial")
        return root

    def _ranked_repo(self, db_session, tmp_path):
        root = self._make_repo(tmp_path)
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)
        rank_repo(db_session, repo)
        rank_repo_weighted_pagerank(db_session, repo)
        rank_repo_rrf(db_session, repo)
        return repo

    def test_default_scorer_is_legacy(self, db_session, tmp_path):
        repo = self._ranked_repo(db_session, tmp_path)
        result = get_ranking(repo.id, user=None, db=db_session)
        assert result["scorer"] == "legacy"

    def test_each_file_appears_exactly_once(self, db_session, tmp_path):
        repo = self._ranked_repo(db_session, tmp_path)
        for scorer in VALID_SCORERS:
            result = get_ranking(repo.id, scorer=scorer, user=None, db=db_session)
            paths = [f["path"] for f in result["files"]]
            assert len(paths) == len(set(paths)) == 2  # main.py, helper.py -- no duplicate rows per scorer

    def test_ordered_by_stored_rank_not_recomputed(self, db_session, tmp_path):
        repo = self._ranked_repo(db_session, tmp_path)
        result = get_ranking(repo.id, scorer="legacy", user=None, db=db_session)
        ranks = [f["rank"] for f in result["files"]]
        assert ranks == sorted(ranks)
        assert ranks == list(range(1, len(ranks) + 1))

    def test_scorer_name_is_in_the_response_body(self, db_session, tmp_path):
        repo = self._ranked_repo(db_session, tmp_path)
        for scorer in VALID_SCORERS:
            result = get_ranking(repo.id, scorer=scorer, user=None, db=db_session)
            assert result["scorer"] == scorer

    def test_unknown_scorer_raises_400_not_empty_list(self, db_session, tmp_path):
        repo = self._ranked_repo(db_session, tmp_path)
        with pytest.raises(HTTPException) as exc_info:
            get_ranking(repo.id, scorer="nonsense", user=None, db=db_session)
        assert exc_info.value.status_code == 400

    def test_reduced_confidence_is_repo_level_not_per_file(self, db_session, tmp_path):
        repo = self._ranked_repo(db_session, tmp_path)
        result = get_ranking(repo.id, scorer="legacy", user=None, db=db_session)
        assert result["reduced_confidence"] is False
        assert all("reduced_confidence" not in f for f in result["files"])

    def test_switching_scorer_changes_score_scale_consistently(self, db_session, tmp_path):
        # The original bug: reading across scorers mixed incompatible
        # scales into one sort. Each scorer's own response must be
        # internally consistent (sorted by that scorer's own score, desc).
        repo = self._ranked_repo(db_session, tmp_path)
        for scorer in VALID_SCORERS:
            result = get_ranking(repo.id, scorer=scorer, user=None, db=db_session)
            scores = [f["score"] for f in result["files"]]
            assert scores == sorted(scores, reverse=True)


class TestGetGraphEndpoint:
    """main.py -> a.py, main.py -> b.py, a.py -> c.py; orphan.py stands
    alone (imports nothing, imported by nothing) -- unreachable by
    construction, the case `layer=null`/`reachable=False` exists for.

    Phase H1 flipped the endpoint's default to level=directory, so every
    test in this class that inspects the file-level node/edge SHAPE (layer,
    language, per-file cap semantics) now passes level="file" explicitly --
    these are regression tests for the shape Phase G4 shipped, not for
    whatever the current default happens to be. See
    TestGetGraphEndpointDirectoryLevel below for the new default's own
    tests."""

    def _make_repo(self, tmp_path) -> Path:
        root = tmp_path / "repo"
        _init_repo(root)
        _write(root / "main.py", "from a import x\nfrom b import y\n\nif __name__ == '__main__':\n    x()\n    y()\n")
        _write(root / "a.py", "from c import z\n\ndef x():\n    return z()\n")
        _write(root / "b.py", "def y():\n    return 1\n")
        _write(root / "c.py", "def z():\n    return 1\n")
        _write(root / "orphan.py", "def w():\n    return 1\n")
        _git(root, "add", "-A")
        _git(root, "-c", "user.name=Alice", "-c", "user.email=alice@t.com", "commit", "-m", "initial")
        return root

    def _ranked_repo(self, db_session, tmp_path):
        root = self._make_repo(tmp_path)
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)
        rank_repo(db_session, repo)
        rank_repo_rrf(db_session, repo)
        return repo

    def test_layers_computed_correctly(self, db_session, tmp_path):
        repo = self._ranked_repo(db_session, tmp_path)
        result = get_graph(repo.id, level="file", user=None, db=db_session)
        by_path = {n["path"]: n for n in result["nodes"]}
        assert by_path["main.py"]["layer"] == 0
        assert by_path["a.py"]["layer"] == 1
        assert by_path["b.py"]["layer"] == 1
        assert by_path["c.py"]["layer"] == 2
        assert by_path["orphan.py"]["layer"] is None
        assert by_path["orphan.py"]["reachable"] is False
        assert by_path["main.py"]["reachable"] is True

    def test_layer_is_scorer_independent(self, db_session, tmp_path):
        repo = self._ranked_repo(db_session, tmp_path)
        legacy = get_graph(repo.id, scorer="legacy", level="file", user=None, db=db_session)
        rrf = get_graph(repo.id, scorer="rrf", level="file", user=None, db=db_session)
        legacy_layers = {n["path"]: n["layer"] for n in legacy["nodes"]}
        rrf_layers = {n["path"]: n["layer"] for n in rrf["nodes"]}
        assert legacy_layers == rrf_layers

    def test_edges_present_between_real_importers(self, db_session, tmp_path):
        repo = self._ranked_repo(db_session, tmp_path)
        result = get_graph(repo.id, level="file", user=None, db=db_session)
        by_path = {n["path"]: n["id"] for n in result["nodes"]}
        edge_pairs = {(e["source"], e["target"]) for e in result["edges"]}
        assert (by_path["main.py"], by_path["a.py"]) in edge_pairs
        assert (by_path["main.py"], by_path["b.py"]) in edge_pairs
        assert (by_path["a.py"], by_path["c.py"]) in edge_pairs
        for e in result["edges"]:
            assert set(e.keys()) == {"source", "target", "weight", "kind", "cross_root"}

    def test_cap_prunes_nodes_and_dangling_edges(self, db_session, tmp_path):
        repo = self._ranked_repo(db_session, tmp_path)
        result = get_graph(repo.id, limit=2, level="file", user=None, db=db_session)
        assert len(result["nodes"]) == 2
        assert result["total_nodes_before_cap"] == 5
        assert result["truncated"] is True
        kept_ids = {n["id"] for n in result["nodes"]}
        for e in result["edges"]:
            assert e["source"] in kept_ids
            assert e["target"] in kept_ids

    def test_language_filter(self, db_session, tmp_path):
        repo = self._ranked_repo(db_session, tmp_path)
        result = get_graph(repo.id, language="python", level="file", user=None, db=db_session)
        assert all(n["language"] == "python" for n in result["nodes"])
        assert len(result["nodes"]) == 5

    def test_path_prefix_filter(self, db_session, tmp_path):
        repo = self._ranked_repo(db_session, tmp_path)
        result = get_graph(repo.id, path_prefix="a", level="file", user=None, db=db_session)
        paths = {n["path"] for n in result["nodes"]}
        assert paths == {"a.py"}

    def test_is_entry_point_present_on_file_level_nodes(self, db_session, tmp_path):
        # Overdue -- CodeFile.is_entry_point existed before this endpoint
        # ever surfaced it. main.py has a __main__ guard; the rest don't.
        repo = self._ranked_repo(db_session, tmp_path)
        result = get_graph(repo.id, level="file", user=None, db=db_session)
        by_path = {n["path"]: n for n in result["nodes"]}
        assert by_path["main.py"]["is_entry_point"] is True
        assert by_path["orphan.py"]["is_entry_point"] is False

    def test_unknown_scorer_raises_400(self, db_session, tmp_path):
        repo = self._ranked_repo(db_session, tmp_path)
        with pytest.raises(HTTPException) as exc_info:
            get_graph(repo.id, scorer="nonsense", user=None, db=db_session)
        assert exc_info.value.status_code == 400

    def test_no_ranking_yet_raises_404(self, db_session, tmp_path):
        root = self._make_repo(tmp_path)
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)  # ranked, never
        with pytest.raises(HTTPException) as exc_info:
            get_graph(repo.id, user=None, db=db_session)
        assert exc_info.value.status_code == 404


class TestGetGraphEndpointDirectoryLevel:
    """main.py (root, real __main__ entry) -> pkg/a.py -> pkg/sub/b.py.
    scripts/tool.py is a standalone CLI utility (its own __main__ guard,
    under the seed-ineligible "scripts/" marker) with no edges at all --
    the entry-vs-tooling split's exact motivating shape. frontend/app.ts
    is an unrelated TypeScript file, present only for the language-filter
    test. Four real directories: "(root)", "pkg", "pkg/sub", "scripts" --
    "frontend" is a fifth, excluded by the language filter test itself."""

    def _make_repo(self, tmp_path) -> Path:
        root = tmp_path / "repo"
        _init_repo(root)
        _write(root / "main.py", "from pkg.a import x\n\nif __name__ == '__main__':\n    x()\n")
        _write(root / "pkg" / "a.py", "from pkg.sub.b import y\n\ndef x():\n    return y()\n")
        _write(root / "pkg" / "sub" / "b.py", "def y():\n    return 1\n")
        _write(root / "scripts" / "tool.py", "if __name__ == '__main__':\n    pass\n")
        _write(root / "frontend" / "app.ts", "export const z = 1;\n")
        _git(root, "add", "-A")
        _git(root, "-c", "user.name=Alice", "-c", "user.email=alice@t.com", "commit", "-m", "initial")
        return root

    def _ranked_repo(self, db_session, tmp_path):
        root = self._make_repo(tmp_path)
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)
        rank_repo(db_session, repo)
        return repo

    def test_default_level_is_directory(self, db_session, tmp_path):
        repo = self._ranked_repo(db_session, tmp_path)
        result = get_graph(repo.id, user=None, db=db_session)
        assert result["level"] == "directory"
        paths = {n["path"] for n in result["nodes"]}
        assert paths == {"(root)", "pkg", "pkg/sub", "scripts", "frontend"}
        # directory shape, not file shape
        sample = result["nodes"][0]
        assert "short_label" in sample and "file_count" in sample
        assert "layer" not in sample and "language" not in sample

    def test_pkg_and_pkg_sub_stay_distinct_directories(self, db_session, tmp_path):
        # The exact case named in the brief: backend/app/services/codebase
        # must not collapse into backend/app/services. Here: pkg/sub must
        # not collapse into pkg.
        repo = self._ranked_repo(db_session, tmp_path)
        result = get_graph(repo.id, user=None, db=db_session)
        paths = {n["path"] for n in result["nodes"]}
        assert "pkg" in paths and "pkg/sub" in paths

    def test_kind_entry_vs_tooling_split(self, db_session, tmp_path):
        repo = self._ranked_repo(db_session, tmp_path)
        result = get_graph(repo.id, user=None, db=db_session)
        by_path = {n["path"]: n for n in result["nodes"]}
        assert by_path["(root)"]["kind"] == "entry"  # main.py: seed-eligible
        assert by_path["scripts"]["kind"] == "tooling"  # tool.py: prior-only (under scripts/)
        assert by_path["pkg"]["kind"] == "source"
        assert by_path["pkg/sub"]["kind"] == "source"

    def test_cross_directory_edges_aggregated_with_counts(self, db_session, tmp_path):
        repo = self._ranked_repo(db_session, tmp_path)
        result = get_graph(repo.id, user=None, db=db_session)
        by_pair = {(e["source"], e["target"]): e for e in result["edges"]}
        assert ("(root)", "pkg") in by_pair
        assert by_pair[("(root)", "pkg")]["count"] == 1
        assert by_pair[("(root)", "pkg")]["weight"] > 0
        assert ("pkg", "pkg/sub") in by_pair
        # scripts has no edges to or from anything.
        assert not any("scripts" in pair for pair in by_pair)

    def test_fan_and_import_fields_replace_raw_fan_in_out(self, db_session, tmp_path):
        repo = self._ranked_repo(db_session, tmp_path)
        result = get_graph(repo.id, user=None, db=db_session)
        pkg = next(n for n in result["nodes"] if n["path"] == "pkg")
        assert pkg["fan_in_dirs"] == 1  # imported by (root) only
        assert pkg["fan_out_dirs"] == 1  # imports pkg/sub only
        assert pkg["import_count_in"] > 0
        assert pkg["import_count_out"] > 0
        assert "fan_in" not in pkg and "fan_out" not in pkg

    def test_group_rollups_field_present_and_zero_for_a_small_repo(self, db_session, tmp_path):
        repo = self._ranked_repo(db_session, tmp_path)
        result = get_graph(repo.id, user=None, db=db_session)
        assert result["group_rollups"] == 0

    def test_language_filter_applies_before_aggregation(self, db_session, tmp_path):
        repo = self._ranked_repo(db_session, tmp_path)
        result = get_graph(repo.id, language="python", user=None, db=db_session)
        paths = {n["path"] for n in result["nodes"]}
        assert "frontend" not in paths  # app.ts filtered out before grouping ever ran
        assert paths == {"(root)", "pkg", "pkg/sub", "scripts"}

    def test_limit_caps_directories_after_aggregation_not_files_before_it(self, db_session, tmp_path):
        # The regression this guards: capping FILES to `limit` before
        # aggregating would only ever see `limit` files and could miss
        # entire directories' worth of edges -- invisible at small scale,
        # silently wrong at large scale. With 5 real files across 5
        # directories, a file-level limit of 2 would leave aggregation
        # unable to see pkg/sub or scripts at all. Asserting
        # total_groups_before_limit == 5 (not <= 2) proves aggregation ran
        # over every filtered file, and only the returned NODE list was
        # trimmed afterward.
        repo = self._ranked_repo(db_session, tmp_path)
        result = get_graph(repo.id, limit=2, user=None, db=db_session)
        assert result["total_groups_before_limit"] == 5
        assert result["truncated"] is True
        assert len(result["nodes"]) == 2
        kept = {n["path"] for n in result["nodes"]}
        for e in result["edges"]:
            assert e["source"] in kept and e["target"] in kept

    def test_level_file_unchanged_shape_still_available(self, db_session, tmp_path):
        repo = self._ranked_repo(db_session, tmp_path)
        result = get_graph(repo.id, level="file", user=None, db=db_session)
        assert result["level"] == "file"
        paths = {n["path"] for n in result["nodes"]}
        assert paths == {"main.py", "pkg/a.py", "pkg/sub/b.py", "scripts/tool.py", "frontend/app.ts"}

    def test_unknown_level_raises_400(self, db_session, tmp_path):
        repo = self._ranked_repo(db_session, tmp_path)
        with pytest.raises(HTTPException) as exc_info:
            get_graph(repo.id, level="nonsense", user=None, db=db_session)
        assert exc_info.value.status_code == 400

    def test_never_calls_entry_detection_live(self, db_session, tmp_path, monkeypatch):
        # Phase H1.5: this endpoint used to call entry_detection.
        # detect_entry_points live, on every request, to get the
        # seed-eligible/prior-only split for directory `kind` -- 15-20s on
        # a real repo, because entry detection walks the filesystem, and a
        # staleness risk even when fast (a directory could be coloured
        # from a fresher scan than the ranking it's supposedly describing).
        # It now reads CodeFile.seed_eligible, persisted by rank_repo.
        # Making the live call raise proves this read path never touches
        # it at all, not just that it happens to be fast today.
        import app.services.codebase.entry_detection as entry_detection

        # Rank FIRST, with the real detection call (that's the legitimate,
        # explicit-user-action write path this phase doesn't touch) --
        # only then make it raise, isolating "get_graph itself must never
        # call this" from "nothing anywhere may ever call this".
        repo = self._ranked_repo(db_session, tmp_path)

        def _boom(*args, **kwargs):
            raise AssertionError("get_graph must not call entry_detection live")

        monkeypatch.setattr(entry_detection, "detect_entry_points", _boom)
        result = get_graph(repo.id, user=None, db=db_session)
        assert result["level"] == "directory"
        by_path = {n["path"]: n for n in result["nodes"]}
        assert by_path["(root)"]["kind"] == "entry"  # still correctly derived, from persisted data


class TestGetFileNeighborsEndpoint:
    def _make_repo(self, tmp_path) -> Path:
        root = tmp_path / "repo"
        _init_repo(root)
        # hub.py is imported by three files and imports nothing itself --
        # direction-asymmetric on purpose (importers=3, imports=0), the
        # exact shape models.py has in the real repo (high fan-in, low
        # fan-out) that motivated capping each direction separately.
        _write(root / "hub.py", "def shared():\n    return 1\n")
        _write(root / "a.py", "from hub import shared\n")
        _write(root / "b.py", "from hub import shared\n")
        _write(root / "c.py", "from hub import shared\n")
        _git(root, "add", "-A")
        _git(root, "-c", "user.name=Alice", "-c", "user.email=alice@t.com", "commit", "-m", "initial")
        return root

    def _ranked_repo(self, db_session, tmp_path):
        root = self._make_repo(tmp_path)
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)
        rank_repo(db_session, repo)
        return repo

    def _file_id(self, db_session, repo, path):
        from app.db.models import CodeFile
        return db_session.query(CodeFile).filter(CodeFile.repo_id == repo.id, CodeFile.path == path).one().id

    def test_importers_and_imports_are_independent_directions(self, db_session, tmp_path):
        repo = self._ranked_repo(db_session, tmp_path)
        hub_id = self._file_id(db_session, repo, "hub.py")
        result = get_file_neighbors(repo.id, hub_id, user=None, db=db_session)
        importer_paths = {n["path"] for n in result["importers"]}
        assert importer_paths == {"a.py", "b.py", "c.py"}
        assert result["importers_total_before_cap"] == 3
        assert result["imports"] == []
        assert result["imports_total_before_cap"] == 0

    def test_reverse_direction_for_the_importing_file(self, db_session, tmp_path):
        repo = self._ranked_repo(db_session, tmp_path)
        a_id = self._file_id(db_session, repo, "a.py")
        result = get_file_neighbors(repo.id, a_id, user=None, db=db_session)
        assert result["importers"] == []
        assert [n["path"] for n in result["imports"]] == ["hub.py"]

    def test_endpoint_cap_is_generous_but_real(self, db_session, tmp_path, monkeypatch):
        import app.api.repos as repos_module
        monkeypatch.setattr(repos_module, "NEIGHBORS_ENDPOINT_CAP", 2)
        repo = self._ranked_repo(db_session, tmp_path)
        hub_id = self._file_id(db_session, repo, "hub.py")
        result = get_file_neighbors(repo.id, hub_id, user=None, db=db_session)
        assert len(result["importers"]) == 2  # capped
        assert result["importers_total_before_cap"] == 3  # true count, not the capped count

    def test_unknown_scorer_raises_400(self, db_session, tmp_path):
        repo = self._ranked_repo(db_session, tmp_path)
        hub_id = self._file_id(db_session, repo, "hub.py")
        with pytest.raises(HTTPException) as exc_info:
            get_file_neighbors(repo.id, hub_id, scorer="nonsense", user=None, db=db_session)
        assert exc_info.value.status_code == 400

    def test_unknown_file_raises_404(self, db_session, tmp_path):
        repo = self._ranked_repo(db_session, tmp_path)
        with pytest.raises(HTTPException) as exc_info:
            get_file_neighbors(repo.id, 999999, user=None, db=db_session)
        assert exc_info.value.status_code == 404
