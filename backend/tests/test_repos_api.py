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

from app.api.repos import (
    NEIGHBORS_ENDPOINT_CAP,
    VALID_SCORERS,
    SubsystemRenameIn,
    compute_health_endpoint,
    compute_subsystems_endpoint,
    compute_subsystems_hdbscan_endpoint,
    get_file_neighbors,
    get_graph,
    get_ranking,
    get_health,
    get_health_directories,
    get_health_files,
    get_findings,
    get_findings_files,
    get_subsystem_members,
    get_subsystems,
    ingest_repo_endpoint,
    rank_repo_endpoint,
    rename_subsystem,
)
from app.services.codebase.git_ops import run_git
from app.services.codebase.repo_lock import repo_lock
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

    def test_subsystem_ids_present_and_null_before_clustering_has_run(self, db_session, tmp_path):
        # Phase I1: same "read straight off CodeFile" shape as fan_in/
        # fan_out above -- present in every row, null until POST
        # /subsystems has run at least once (rank_repo* alone never sets it).
        repo = self._ranked_repo(db_session, tmp_path)
        result = get_ranking(repo.id, scorer="legacy", user=None, db=db_session)
        for f in result["files"]:
            assert "subsystem_modularity_id" in f
            assert "subsystem_louvain_id" in f
            assert f["subsystem_modularity_id"] is None

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


class TestRepoBusyErrorHandling:
    """Debt item closed: POST /ingest and POST /rank previously let
    RepoBusyError propagate as a raw, unhandled 500 instead of a clean
    409 -- the same class of gap POST /subsystems already closed when it
    was built (see TestSubsystemEndpoints below for its own coverage of
    this). Fixed for both, not just /rank, since /ingest calls a function
    that acquires the exact same lock for the exact same reason."""

    def _make_repo(self, tmp_path) -> Path:
        root = tmp_path / "repo"
        _init_repo(root)
        _write(root / "main.py", "def f(): pass\n")
        _git(root, "add", "-A")
        _git(root, "-c", "user.name=Alice", "-c", "user.email=alice@t.com", "commit", "-m", "initial")
        return root

    def test_ingest_endpoint_returns_409_when_repo_busy(self, db_session, tmp_path):
        root = self._make_repo(tmp_path)
        repo = register_from_path(db_session, str(root))
        with repo_lock(repo.id, "rank"):
            with pytest.raises(HTTPException) as exc_info:
                ingest_repo_endpoint(repo.id, user=None, db=db_session)
        assert exc_info.value.status_code == 409

    def test_rank_endpoint_returns_409_when_repo_busy(self, db_session, tmp_path):
        root = self._make_repo(tmp_path)
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)
        with repo_lock(repo.id, "ingest"):
            with pytest.raises(HTTPException) as exc_info:
                rank_repo_endpoint(repo.id, user=None, db=db_session)
        assert exc_info.value.status_code == 409


class TestSubsystemEndpoints:
    """Two dense triangles (groupA, groupB) with no edges between them --
    same shape as test_subsystems.py's own integration fixture, kept
    minimal here since the clustering math itself is already covered
    there; these tests exercise the HTTP-layer scoping/serialization only."""

    def _make_repo(self, tmp_path) -> Path:
        root = tmp_path / "repo"
        _init_repo(root)
        _write(root / "groupA" / "a1.py", "from groupA.a2 import f2\nfrom groupA.a3 import f3\n")
        _write(root / "groupA" / "a2.py", "from groupA.a3 import f3\ndef f2(): pass\n")
        _write(root / "groupA" / "a3.py", "def f3(): pass\n")
        _write(root / "groupB" / "b1.py", "from groupB.b2 import g2\nfrom groupB.b3 import g3\n")
        _write(root / "groupB" / "b2.py", "from groupB.b3 import g3\ndef g2(): pass\n")
        _write(root / "groupB" / "b3.py", "def g3(): pass\n")
        _git(root, "add", "-A")
        _git(root, "-c", "user.name=Alice", "-c", "user.email=alice@t.com", "commit", "-m", "initial")
        return root

    def _ranked_repo(self, db_session, tmp_path):
        root = self._make_repo(tmp_path)
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)
        rank_repo(db_session, repo)
        return repo

    def test_compute_endpoint_returns_shape(self, db_session, tmp_path):
        repo = self._ranked_repo(db_session, tmp_path)
        result = compute_subsystems_endpoint(repo.id, user=None, db=db_session)
        assert result["algorithms"]["modularity"]["cluster_count"] == 2
        assert "louvain" in result["algorithms"]
        assert "cycle_coherence" in result

    def test_compute_unknown_repo_raises_404(self, db_session):
        with pytest.raises(HTTPException) as exc_info:
            compute_subsystems_endpoint(999999, user=None, db=db_session)
        assert exc_info.value.status_code == 404

    def test_get_subsystems_scoped_by_both_repo_and_algorithm(self, db_session, tmp_path):
        """The exact scoping shape G1 fixed for CodeFileRank/scorer,
        applied here: GET must never mix modularity and louvain rows."""
        repo = self._ranked_repo(db_session, tmp_path)
        compute_subsystems_endpoint(repo.id, user=None, db=db_session)

        modularity = get_subsystems(repo.id, algorithm="modularity", user=None, db=db_session)
        louvain = get_subsystems(repo.id, algorithm="louvain", user=None, db=db_session)
        assert modularity["algorithm"] == "modularity"
        assert louvain["algorithm"] == "louvain"
        assert len(modularity["subsystems"]) == 2
        assert len(louvain["subsystems"]) == 2

        from app.db.models import CodeSubsystem
        modularity_ids = {s["id"] for s in modularity["subsystems"]}
        louvain_ids = {s["id"] for s in louvain["subsystems"]}
        assert modularity_ids.isdisjoint(louvain_ids)  # distinct rows, not the same set filtered twice
        real_algorithms = {
            row.id: row.algorithm
            for row in db_session.query(CodeSubsystem).filter(CodeSubsystem.repo_id == repo.id).all()
        }
        assert all(real_algorithms[i] == "modularity" for i in modularity_ids)
        assert all(real_algorithms[i] == "louvain" for i in louvain_ids)

    def test_get_subsystems_is_read_only_no_recompute(self, db_session, tmp_path, monkeypatch):
        """H1.5's own lesson, applied to a new read endpoint: GET must
        read what POST already persisted, never re-cluster live."""
        import app.api.repos as repos_module

        repo = self._ranked_repo(db_session, tmp_path)
        compute_subsystems_endpoint(repo.id, user=None, db=db_session)

        def _boom(*a, **kw):
            raise AssertionError("get_subsystems must not recompute clustering")

        monkeypatch.setattr(repos_module, "compute_subsystems", _boom)
        result = get_subsystems(repo.id, algorithm="modularity", user=None, db=db_session)
        assert result["agreement"] == 1.0
        assert len(result["cycle_coherence"]) == 0  # no cross-directory cycle in this fixture

    def test_get_subsystems_unknown_algorithm_raises_400(self, db_session, tmp_path):
        repo = self._ranked_repo(db_session, tmp_path)
        compute_subsystems_endpoint(repo.id, user=None, db=db_session)
        with pytest.raises(HTTPException) as exc_info:
            get_subsystems(repo.id, algorithm="nonsense", user=None, db=db_session)
        assert exc_info.value.status_code == 400

    def test_get_subsystem_members_returns_real_files(self, db_session, tmp_path):
        repo = self._ranked_repo(db_session, tmp_path)
        compute_subsystems_endpoint(repo.id, user=None, db=db_session)
        modularity = get_subsystems(repo.id, algorithm="modularity", user=None, db=db_session)
        first = modularity["subsystems"][0]
        result = get_subsystem_members(repo.id, first["id"], user=None, db=db_session)
        assert len(result["files"]) == first["member_count"]

    def test_get_subsystem_members_wrong_repo_raises_404(self, db_session, tmp_path):
        repo = self._ranked_repo(db_session, tmp_path)
        compute_subsystems_endpoint(repo.id, user=None, db=db_session)
        modularity = get_subsystems(repo.id, algorithm="modularity", user=None, db=db_session)
        first_id = modularity["subsystems"][0]["id"]
        with pytest.raises(HTTPException) as exc_info:
            get_subsystem_members(repo.id + 999, first_id, user=None, db=db_session)
        assert exc_info.value.status_code == 404

    def test_rename_persists_custom_label(self, db_session, tmp_path):
        repo = self._ranked_repo(db_session, tmp_path)
        compute_subsystems_endpoint(repo.id, user=None, db=db_session)
        modularity = get_subsystems(repo.id, algorithm="modularity", user=None, db=db_session)
        first_id = modularity["subsystems"][0]["id"]

        result = rename_subsystem(repo.id, first_id, SubsystemRenameIn(custom_label="Auth Subsystem"),
                                   user=None, db=db_session)
        assert result["custom_label"] == "Auth Subsystem"
        assert result["active_label_rule"] == "custom"

        refetched = get_subsystems(repo.id, algorithm="modularity", user=None, db=db_session)
        renamed = next(s for s in refetched["subsystems"] if s["id"] == first_id)
        assert renamed["custom_label"] == "Auth Subsystem"


def _fake_embed_by_group(texts: list):
    """Same stand-in as test_subsystems.py's own fixture -- deterministic,
    no ONNX model, no CPU inference pass. Kept as a free function here
    (rather than importing test_subsystems.py's copy) since test files in
    this suite don't import from one another. This fixture's groupA/groupB
    never fall into the "else" branch (no iso-style file here), but it
    stays angularly distinct from both groups after L2 normalization
    anyway, matching test_subsystems.py's own fix for why a magnitude-only
    outlier like [50, 50] stops being an outlier at all once normalized
    in 2D."""
    import numpy as np
    vecs = []
    for i, t in enumerate(texts):
        jitter = (i % 5) * 0.001
        if "groupA" in t:
            vecs.append([1.0 + jitter, 0.0])
        elif "groupB" in t:
            vecs.append([0.0, 1.0 + jitter])
        else:
            vecs.append([-1.0, -1.0])
    return np.array(vecs)


class TestSubsystemHdbscanEndpoint:
    """Phase I6: HTTP-layer scoping/serialization only -- the clustering
    math itself (cluster_hdbscan, compute_subsystems_hdbscan) is already
    covered in test_subsystems.py. Reuses TestSubsystemEndpoints' own
    groupA/groupB fixture shape."""

    def _make_repo(self, tmp_path) -> Path:
        root = tmp_path / "repo"
        _init_repo(root)
        _write(root / "groupA" / "a1.py", "from groupA.a2 import f2\nfrom groupA.a3 import f3\n")
        _write(root / "groupA" / "a2.py", "from groupA.a3 import f3\ndef f2(): pass\n")
        _write(root / "groupA" / "a3.py", "def f3(): pass\n")
        _write(root / "groupB" / "b1.py", "from groupB.b2 import g2\nfrom groupB.b3 import g3\n")
        _write(root / "groupB" / "b2.py", "from groupB.b3 import g3\ndef g2(): pass\n")
        _write(root / "groupB" / "b3.py", "def g3(): pass\n")
        _git(root, "add", "-A")
        _git(root, "-c", "user.name=Alice", "-c", "user.email=alice@t.com", "commit", "-m", "initial")
        return root

    def _ranked_repo(self, db_session, tmp_path):
        root = self._make_repo(tmp_path)
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)
        rank_repo(db_session, repo)
        return repo

    def test_compute_endpoint_returns_shape(self, db_session, tmp_path, monkeypatch):
        import app.services.codebase.subsystems as subsystems_module

        monkeypatch.setattr(subsystems_module.embeddings, "embed_texts", _fake_embed_by_group)
        repo = self._ranked_repo(db_session, tmp_path)
        result = compute_subsystems_hdbscan_endpoint(repo.id, user=None, db=db_session)
        assert result["algorithm"] == "hdbscan"
        assert result["cluster_count"] == 2
        assert result["agreement_with_modularity"] is None  # modularity never ran in this test

    def test_compute_unknown_repo_raises_404(self, db_session):
        with pytest.raises(HTTPException) as exc_info:
            compute_subsystems_hdbscan_endpoint(999999, user=None, db=db_session)
        assert exc_info.value.status_code == 404

    def test_get_subsystems_hdbscan_scoped_separately_from_graph_algorithms(self, db_session, tmp_path, monkeypatch):
        import app.services.codebase.subsystems as subsystems_module

        monkeypatch.setattr(subsystems_module.embeddings, "embed_texts", _fake_embed_by_group)
        repo = self._ranked_repo(db_session, tmp_path)
        compute_subsystems_endpoint(repo.id, user=None, db=db_session)  # modularity + louvain
        compute_subsystems_hdbscan_endpoint(repo.id, user=None, db=db_session)

        hdbscan = get_subsystems(repo.id, algorithm="hdbscan", user=None, db=db_session)
        modularity = get_subsystems(repo.id, algorithm="modularity", user=None, db=db_session)
        assert hdbscan["algorithm"] == "hdbscan"
        assert len(hdbscan["subsystems"]) == 2
        assert hdbscan["agreement"] == 1.0  # hdbscan vs modularity, not modularity vs louvain
        assert modularity["agreement"] == 1.0  # modularity vs louvain -- a different number, same value by coincidence of this fixture's shape
        hdbscan_ids = {s["id"] for s in hdbscan["subsystems"]}
        modularity_ids = {s["id"] for s in modularity["subsystems"]}
        assert hdbscan_ids.isdisjoint(modularity_ids)

    def test_get_subsystem_members_hdbscan_returns_real_files(self, db_session, tmp_path, monkeypatch):
        import app.services.codebase.subsystems as subsystems_module

        monkeypatch.setattr(subsystems_module.embeddings, "embed_texts", _fake_embed_by_group)
        repo = self._ranked_repo(db_session, tmp_path)
        compute_subsystems_hdbscan_endpoint(repo.id, user=None, db=db_session)
        hdbscan = get_subsystems(repo.id, algorithm="hdbscan", user=None, db=db_session)
        first = hdbscan["subsystems"][0]
        result = get_subsystem_members(repo.id, first["id"], user=None, db=db_session)
        assert len(result["files"]) == first["member_count"]

    def test_compute_hdbscan_busy_raises_409(self, db_session, tmp_path, monkeypatch):
        import app.services.codebase.subsystems as subsystems_module

        monkeypatch.setattr(subsystems_module.embeddings, "embed_texts", _fake_embed_by_group)
        repo = self._ranked_repo(db_session, tmp_path)
        with repo_lock(repo.id, "ingest"):
            with pytest.raises(HTTPException) as exc_info:
                compute_subsystems_hdbscan_endpoint(repo.id, user=None, db=db_session)
        assert exc_info.value.status_code == 409


class TestGetGraphClusterFields:
    """Phase I2: dominant-cluster fields on directory nodes at
    level=directory. groupA (3 files, one clique) and groupB (3 files,
    a separate clique with one file also weakly tied to groupA) --
    groupB's split is what proves purity isn't silently reported as 1.0
    for every directory."""

    def _make_repo(self, tmp_path) -> Path:
        root = tmp_path / "repo"
        _init_repo(root)
        _write(root / "groupA" / "a1.py", "from groupA.a2 import f2\nfrom groupA.a3 import f3\n")
        _write(root / "groupA" / "a2.py", "from groupA.a3 import f3\ndef f2(): pass\n")
        _write(root / "groupA" / "a3.py", "def f3(): pass\n")
        _write(root / "groupB" / "b1.py", "from groupB.b2 import g2\nfrom groupB.b3 import g3\n")
        _write(root / "groupB" / "b2.py", "from groupB.b3 import g3\ndef g2(): pass\n")
        _write(root / "groupB" / "b3.py", "def g3(): pass\n")
        _git(root, "add", "-A")
        _git(root, "-c", "user.name=Alice", "-c", "user.email=alice@t.com", "commit", "-m", "initial")
        return root

    def _clustered_repo(self, db_session, tmp_path):
        from app.services.codebase.subsystems import compute_subsystems

        root = self._make_repo(tmp_path)
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)
        rank_repo(db_session, repo)
        compute_subsystems(db_session, repo)
        return repo

    def test_directory_nodes_carry_dominant_cluster_and_full_purity(self, db_session, tmp_path):
        repo = self._clustered_repo(db_session, tmp_path)
        result = get_graph(repo.id, level="directory", user=None, db=db_session)
        by_path = {n["path"]: n for n in result["nodes"]}
        assert by_path["groupA"]["cluster_id"] is not None
        assert by_path["groupA"]["cluster_purity"] == 1.0
        assert by_path["groupB"]["cluster_purity"] == 1.0
        assert by_path["groupA"]["cluster_id"] != by_path["groupB"]["cluster_id"]

    def test_cluster_fields_null_before_clustering_has_run(self, db_session, tmp_path):
        root = self._make_repo(tmp_path)
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)
        rank_repo(db_session, repo)
        result = get_graph(repo.id, level="directory", user=None, db=db_session)
        for n in result["nodes"]:
            assert n["cluster_id"] is None
            assert n["cluster_purity"] is None


class TestArchitectureDisclosureContract:
    """The disclosure must travel WITH the score, as structured data.

    A documented rendering rule is not enough: a future UI could receive a
    non-null Architecture Health score and simply omit the scope it applies
    to, leaving 10.00 reading as "the architecture is healthy" while the same
    product shows the user directory-level cycles elsewhere. These tests make
    that combination impossible to serve.
    """

    def _make_repo(self, tmp_path) -> Path:
        root = tmp_path / "repo"
        _init_repo(root)
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
        _git(root, "add", "-A")
        _git(root, "-c", "user.name=A", "-c", "user.email=a@t.com", "commit", "-m", "initial")
        return root

    def _analysed(self, db_session, tmp_path):
        repo = register_from_path(db_session, str(self._make_repo(tmp_path)))
        ingest_repo(db_session, repo)
        rank_repo(db_session, repo)
        return repo

    REQUIRED_FIELDS = (
        "inputs_complete", "file_level_cycle_count",
        "directory_cycle_count", "active_markers", "limitations",
    )

    def test_a_non_null_architecture_score_always_ships_its_disclosure(self, db_session, tmp_path):
        repo = self._analysed(db_session, tmp_path)
        payload = compute_health_endpoint(repo.id, user=None, db=db_session)
        arch = payload["axes"]["architecture_health"]

        assert arch.get("mean") is not None, "expected a presentable score for this fixture"
        coverage = arch["coverage"]
        for field in self.REQUIRED_FIELDS:
            assert field in coverage, f"score served without disclosure field {field!r}"

    def test_the_same_holds_on_the_read_endpoint_not_just_the_compute_one(self, db_session, tmp_path):
        repo = self._analysed(db_session, tmp_path)
        compute_health_endpoint(repo.id, user=None, db=db_session)
        payload = get_health(repo.id, user=None, db=db_session)
        coverage = payload["axes"]["architecture_health"]["coverage"]
        for field in self.REQUIRED_FIELDS:
            assert field in coverage

    def test_disclosure_reports_both_cycle_kinds_separately(self, db_session, tmp_path):
        # The two facts are not in conflict -- a directory cycle needs only
        # a1->b1 and b2->a2, with no file in a cycle -- and reporting them
        # apart is what makes that legible rather than contradictory.
        repo = self._analysed(db_session, tmp_path)
        payload = compute_health_endpoint(repo.id, user=None, db=db_session)
        coverage = payload["axes"]["architecture_health"]["coverage"]
        assert coverage["file_level_cycle_count"] == 0
        assert "directory_cycle_count" in coverage

    def test_inactive_markers_distinguish_never_computed_from_found_nothing(
            self, db_session, tmp_path):
        from app.db.models import CodeFile

        repo = self._analysed(db_session, tmp_path)
        # Force the "never computed" state by clearing SCC data AFTER the
        # endpoint's own graph pass would have run -- use the service directly.
        from app.services.codebase.health_snapshots import (
            architecture_coverage, build_repo_context, collect_inputs,
        )
        from app.services.codebase.health_scoring import score_file

        for f in db_session.query(CodeFile).filter(CodeFile.repo_id == repo.id).all():
            f.scc_size = None
        db_session.commit()

        inputs = collect_inputs(db_session, repo)
        ctx = build_repo_context(inputs)
        results = [score_file(f, ctx).architecture_health for f in inputs]
        coverage = architecture_coverage(inputs, results, repo)

        inactive = {m["key"]: m["state"] for m in coverage["inactive_markers"]}
        assert inactive["cycle_participation"] == "no_input"
        assert coverage["inputs_complete"] is False
        joined = " ".join(coverage["limitations"]).lower()
        assert "never computed" in joined

    def test_limitations_name_the_static_analysis_blind_spot(self, db_session, tmp_path):
        repo = self._analysed(db_session, tmp_path)
        payload = compute_health_endpoint(repo.id, user=None, db=db_session)
        text = " ".join(payload["axes"]["architecture_health"]["coverage"]["limitations"]).lower()
        assert "dynamic import" in text or "static import" in text

    def test_active_markers_names_what_actually_carried_the_score(self, db_session, tmp_path):
        # "Active" means FIRED, not merely "had data". cycle_participation has
        # complete data on this fixture and finds nothing, so listing it as
        # active would imply the score reflects a check that never engaged.
        repo = self._analysed(db_session, tmp_path)
        payload = compute_health_endpoint(repo.id, user=None, db=db_session)
        coverage = payload["axes"]["architecture_health"]["coverage"]
        assert coverage["file_level_cycle_count"] == 0
        assert "cycle_participation" not in coverage["active_markers"]
        inactive = {m["key"]: m for m in coverage["inactive_markers"]}
        assert "cycle_participation" in inactive
        # And the REASON is preserved: measured-and-found-nothing is a
        # different fact from never-computed, and collapsing them would let a
        # coverage gap masquerade as a clean result.
        assert inactive["cycle_participation"]["state"] == "input_available_zero_severity"

    def test_a_marker_that_fires_is_listed_as_active(self, db_session, tmp_path):
        # A REAL mutual import, not a patched scc_size: compute_health_endpoint
        # recomputes graph structure first, so any hand-set value is
        # overwritten before scoring -- which an earlier version of this test
        # discovered the hard way.
        root = tmp_path / "cyclerepo"
        _init_repo(root)
        _write(root / "pkg" / "alpha.py",
               "from pkg.beta import beta_helper\n\n\n"
               "def alpha_run(x):\n"
               "    if x > 1:\n        return beta_helper(x)\n"
               "    return 0\n\n\n"
               "def alpha_extra(y):\n    return y + 1\n")
        _write(root / "pkg" / "beta.py",
               "from pkg.alpha import alpha_extra\n\n\n"
               "def beta_helper(x):\n"
               "    if x > 2:\n        return alpha_extra(x)\n"
               "    return 1\n\n\n"
               "def beta_extra(y):\n    return y * 2\n")
        _git(root, "add", "-A")
        _git(root, "-c", "user.name=A", "-c", "user.email=a@t.com", "commit", "-m", "initial")

        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)
        rank_repo(db_session, repo)

        payload = compute_health_endpoint(repo.id, user=None, db=db_session)
        coverage = payload["axes"]["architecture_health"]["coverage"]
        assert coverage["file_level_cycle_count"] == 1
        assert "cycle_participation" in coverage["active_markers"]

    def test_snapshot_carries_provenance_including_dirty_working_tree(self, db_session, tmp_path):
        repo = self._analysed(db_session, tmp_path)
        snap = compute_health_endpoint(repo.id, user=None, db=db_session)["snapshot"]
        for field in ("head_sha", "branch", "working_tree_dirty",
                      "analyzer_version", "thresholds_version", "weights_version"):
            assert field in snap

    def test_first_snapshot_reports_no_baseline_rather_than_a_zero_delta(self, db_session, tmp_path):
        repo = self._analysed(db_session, tmp_path)
        trend = compute_health_endpoint(repo.id, user=None, db=db_session)["trend"]
        assert trend["comparable"] is False
        assert trend["deltas"] == {}

    def test_health_endpoints_404_before_any_snapshot_exists(self, db_session, tmp_path):
        # Deliberately not an empty scorecard, which would read as
        # "measured, and fine".
        repo = self._analysed(db_session, tmp_path)
        for fn in (get_health, get_health_files):
            with pytest.raises(HTTPException) as exc:
                fn(repo.id, user=None, db=db_session)
            assert exc.value.status_code == 404

    def test_file_ranking_excludes_na_files_instead_of_sorting_them_as_zero(self, db_session, tmp_path):
        # This fixture is a single-commit repo, so Change Hotspot is N/A for
        # every file; they must be excluded and counted, not ranked as 0.
        repo = self._analysed(db_session, tmp_path)
        compute_health_endpoint(repo.id, user=None, db=db_session)
        result = get_health_files(repo.id, sort="adjusted_exposure", user=None, db=db_session)
        assert result["files"] == []
        assert result["excluded_na"] > 0

    def test_file_ranking_serves_both_exposure_columns(self, db_session, tmp_path):
        repo = self._analysed(db_session, tmp_path)
        compute_health_endpoint(repo.id, user=None, db=db_session)
        result = get_health_files(repo.id, sort="maintainability", user=None, db=db_session)
        assert result["files"], "expected maintainability-ranked files"
        for row in result["files"]:
            assert "exposure" in row and "adjusted_exposure" in row
            assert "explanation" in row


class TestStalenessTravelsWithTheScore:
    """A score is a claim about a repo at a moment. The read endpoint returned
    the newest snapshot and checked nothing, so a repo whose files had gone
    still rendered a green 97 beside a Contents panel reading 0 files. The
    staleness verdict now ships in the same payload as the number, for the
    same reason the architecture disclosure does.
    """

    def _analysed(self, db_session, tmp_path):
        root = tmp_path / "repo"
        _init_repo(root)
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
        _git(root, "add", "-A")
        _git(root, "-c", "user.name=A", "-c", "user.email=a@t.com", "commit", "-m", "initial")
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)
        rank_repo(db_session, repo)
        return repo

    def test_a_fresh_snapshot_reports_not_stale(self, db_session, tmp_path):
        repo = self._analysed(db_session, tmp_path)
        compute_health_endpoint(repo.id, user=None, db=db_session)
        payload = get_health(repo.id, user=None, db=db_session)
        assert payload["staleness"]["stale"] is False

    def test_an_emptied_repo_never_serves_a_score_without_the_warning(self, db_session, tmp_path):
        from app.db.models import CodeFile

        repo = self._analysed(db_session, tmp_path)
        compute_health_endpoint(repo.id, user=None, db=db_session)
        db_session.query(CodeFile).filter(CodeFile.repo_id == repo.id).delete()
        db_session.commit()

        payload = get_health(repo.id, user=None, db=db_session)
        assert payload["axes"]["maintainability"]["mean"] is not None, \
            "the stored score is still served -- it is the framing that must change"
        assert payload["staleness"]["stale"] is True
        assert payload["staleness"]["reason"] == "no_files_ingested"
        assert payload["staleness"]["detail"]

    def test_the_compute_endpoint_carries_it_too(self, db_session, tmp_path):
        repo = self._analysed(db_session, tmp_path)
        payload = compute_health_endpoint(repo.id, user=None, db=db_session)
        assert "staleness" in payload


class TestDirectoryRollupEndpoint:
    """The rollup is a view of stored rows, so the endpoint's job is to refuse
    to serve one when there is nothing to view, and to carry the same staleness
    verdict the scores themselves carry."""

    def _analysed(self, db_session, tmp_path):
        root = tmp_path / "repo"
        _init_repo(root)
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
        _git(root, "add", "-A")
        _git(root, "-c", "user.name=A", "-c", "user.email=a@t.com", "commit", "-m", "initial")
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)
        rank_repo(db_session, repo)
        return repo

    def test_404_before_any_snapshot_rather_than_an_empty_table(self, db_session, tmp_path):
        repo = self._analysed(db_session, tmp_path)
        with pytest.raises(HTTPException) as e:
            get_health_directories(repo.id, user=None, db=db_session)
        assert e.value.status_code == 404

    def test_directories_are_derived_from_the_stored_snapshot(self, db_session, tmp_path):
        repo = self._analysed(db_session, tmp_path)
        compute_health_endpoint(repo.id, user=None, db=db_session)

        payload = get_health_directories(repo.id, user=None, db=db_session)
        paths = {d["path"] for d in payload["directories"]}
        assert "pkg" in paths
        assert payload["files_in_snapshot"] > 0

    def test_every_directory_reports_its_scored_and_na_counts(self, db_session, tmp_path):
        """A number without its denominator is the failure this whole surface
        exists to prevent."""
        repo = self._analysed(db_session, tmp_path)
        compute_health_endpoint(repo.id, user=None, db=db_session)

        payload = get_health_directories(repo.id, user=None, db=db_session)
        for d in payload["directories"]:
            for axis in ("maintainability", "architecture_health", "change_hotspot"):
                a = d["axes"][axis]
                assert "files_scored" in a and "files_na" in a
                if a["weighted_mean"] is not None:
                    assert a["files_scored"] > 0

    def test_the_ranking_floor_is_declared_in_the_payload(self, db_session, tmp_path):
        """A reader must be able to tell that small directories were held back
        from the ranking rather than found healthy."""
        repo = self._analysed(db_session, tmp_path)
        compute_health_endpoint(repo.id, user=None, db=db_session)
        payload = get_health_directories(repo.id, user=None, db=db_session)
        assert payload["min_files_to_rank"] >= 1

    def test_staleness_travels_with_the_rollup_too(self, db_session, tmp_path):
        from app.db.models import CodeFile

        repo = self._analysed(db_session, tmp_path)
        compute_health_endpoint(repo.id, user=None, db=db_session)
        db_session.query(CodeFile).filter(CodeFile.repo_id == repo.id).delete()
        db_session.commit()

        payload = get_health_directories(repo.id, user=None, db=db_session)
        assert payload["staleness"]["stale"] is True
        assert payload["staleness"]["reason"] == "no_files_ingested"

    def test_hot_cohort_is_na_on_a_single_commit_repo(self, db_session, tmp_path):
        """One commit means one distinct commit count, so there is no cohort to
        compare -- the endpoint must say so rather than slice arbitrarily."""
        repo = self._analysed(db_session, tmp_path)
        compute_health_endpoint(repo.id, user=None, db=db_session)
        payload = get_health_directories(repo.id, user=None, db=db_session)
        assert payload["hot_cohort"]["available"] is False
        assert payload["hot_cohort"]["na_reason"]

    def test_max_depth_is_validated(self, db_session, tmp_path):
        repo = self._analysed(db_session, tmp_path)
        with pytest.raises(HTTPException) as e:
            get_health_directories(repo.id, max_depth=-1, user=None, db=db_session)
        assert e.value.status_code == 400


class TestFindingsEndpoint:
    """Phase L. The aggregation itself is covered by test_findings_queue.py --
    these cover the endpoint contract: what it refuses, what it discloses, and
    that members reproduce the row they came from."""

    def _make_repo(self, tmp_path) -> Path:
        root = tmp_path / "findings_repo"
        _init_repo(root)
        _write(root / "pkg" / "__init__.py", "")
        # Deliberately over the large-function threshold so at least one marker
        # fires -- a fixture that produces an empty queue would let every
        # assertion below pass vacuously.
        body = "\n".join(f"    x{i} = {i}" for i in range(120))
        _write(root / "pkg" / "big.py", f"def enormous():\n{body}\n    return x0\n")
        _write(root / "pkg" / "small.py", "def tiny():\n    return 1\n")
        _git(root, "add", "-A")
        _git(root, "-c", "user.name=A", "-c", "user.email=a@t.com", "commit", "-m", "initial")
        return root

    def _analysed(self, db_session, tmp_path):
        repo = register_from_path(db_session, str(self._make_repo(tmp_path)))
        ingest_repo(db_session, repo)
        rank_repo(db_session, repo)
        compute_health_endpoint(repo.id, user=None, db=db_session)
        return repo

    def test_404_before_any_snapshot_rather_than_an_empty_queue(self, db_session, tmp_path):
        """An empty queue reads as "measured and nothing to fix". Same choice
        as GET /health and /health/directories."""
        repo = register_from_path(db_session, str(self._make_repo(tmp_path)))
        ingest_repo(db_session, repo)
        with pytest.raises(HTTPException) as e:
            get_findings(repo.id, user=None, db=db_session)
        assert e.value.status_code == 404

    def test_LOADBEARING_hidden_below_floor_is_disclosed_with_the_list(self, db_session, tmp_path):
        """A floor a user cannot see is indistinguishable from a tool that
        missed something."""
        repo = self._analysed(db_session, tmp_path)
        payload = get_findings(repo.id, user=None, db=db_session)

        assert "hidden_below_floor" in payload
        assert "floor" in payload and "max_files_per_row" in payload
        assert payload["shown"] == sum(r["file_count"] for r in payload["rows"])

    def test_LOADBEARING_churn_is_never_a_row(self, db_session, tmp_path):
        """It fires on 47.8% of evaluable files on apache/superset. As rows it
        would be 41% of the queue while telling nobody which file to open."""
        repo = self._analysed(db_session, tmp_path)
        payload = get_findings(repo.id, user=None, db=db_session)

        assert all(r["marker"] != "churn_volume" for r in payload["rows"])
        assert "churn_weighted_files" in payload

    def test_LOADBEARING_rows_carry_no_inline_file_list(self, db_session, tmp_path):
        """296 KB on apache/superset if they did. Members are a second call."""
        repo = self._analysed(db_session, tmp_path)
        payload = get_findings(repo.id, user=None, db=db_session)

        assert payload["rows"], "fixture produced no findings -- assertions would be vacuous"
        assert all("files" not in r for r in payload["rows"])

    def test_LOADBEARING_members_reproduce_the_row_they_came_from(self, db_session, tmp_path):
        """The split is re-derived, not stored, so it must be a pure function of
        (snapshot, floor, max_files). If it were not, expanding a row would show
        the members of a row that was never displayed."""
        repo = self._analysed(db_session, tmp_path)
        payload = get_findings(repo.id, user=None, db=db_session)
        row = payload["rows"][0]

        members = get_findings_files(
            repo.id, marker=row["marker"], directory=row["directory"],
            floor=payload["floor"], max_files=payload["max_files_per_row"],
            user=None, db=db_session)

        assert members["file_count"] == row["file_count"]
        assert len(members["files"]) == row["file_count"]
        severities = [f["severity"] for f in members["files"]]
        assert severities == sorted(severities, reverse=True), "worst first"

    def test_unknown_row_is_404_not_an_empty_member_list(self, db_session, tmp_path):
        repo = self._analysed(db_session, tmp_path)
        with pytest.raises(HTTPException) as e:
            get_findings_files(repo.id, marker="no_such_marker", directory="nowhere",
                               user=None, db=db_session)
        assert e.value.status_code == 404

    def test_parameters_are_validated(self, db_session, tmp_path):
        repo = self._analysed(db_session, tmp_path)
        for kwargs in ({"floor": -0.1}, {"floor": 1.5}, {"max_files": 0}):
            with pytest.raises(HTTPException) as e:
                get_findings(repo.id, user=None, db=db_session, **kwargs)
            assert e.value.status_code == 400, kwargs

    def test_LOADBEARING_files_partially_na_is_served_beside_files_na(self, db_session, tmp_path):
        """files_na alone reads as "everything else was scored". On
        apache/superset it is 0 while 782 files are scored on architecture
        only."""
        repo = self._analysed(db_session, tmp_path)
        payload = get_health(repo.id, user=None, db=db_session)

        assert "files_partially_na" in payload["snapshot"]
        assert "files_na" in payload["snapshot"]

    def test_LOADBEARING_a_fresh_snapshot_measures_partially_na_rather_than_leaving_it_null(
            self, db_session, tmp_path):
        """NULL is reserved for snapshots that never measured it. A snapshot
        written by today's code must report a number, or the "not measured"
        signal stops distinguishing anything."""
        repo = self._analysed(db_session, tmp_path)
        payload = get_health(repo.id, user=None, db=db_session)

        assert payload["snapshot"]["files_partially_na"] is not None

    def test_LOADBEARING_member_lookup_echoes_the_parameters_that_built_it(
            self, db_session, tmp_path):
        """The split is pure, so a caller passing a different floor or cap gets
        a different, internally consistent split. Echoing the triple is what
        makes that detectable instead of silent."""
        repo = self._analysed(db_session, tmp_path)
        payload = get_findings(repo.id, user=None, db=db_session)
        row = payload["rows"][0]

        members = get_findings_files(
            repo.id, marker=row["marker"], directory=row["directory"],
            floor=payload["floor"], max_files=payload["max_files_per_row"],
            user=None, db=db_session)

        assert members["floor"] == payload["floor"]
        assert members["max_files_per_row"] == payload["max_files_per_row"]
        assert members["snapshot_id"] == payload["snapshot_id"]


class TestGraphFilterVocabulary:
    """Phase L2. Architecture, Matrix and the Dependency Graph rendered the file
    filter bar and ignored it; these cover the endpoint half of the fix."""

    def _make_repo(self, tmp_path) -> Path:
        root = tmp_path / "vocab_repo"
        _init_repo(root)
        # Three languages and three top-level segments, so multi-value tests
        # have something to distinguish.
        _write(root / "backend" / "app.py", "from backend.util import helper\n\n\ndef run():\n    return helper()\n")
        _write(root / "backend" / "util.py", "def helper():\n    return 1\n")
        _write(root / "frontend" / "main.ts", "export const a = 1;\n")
        _write(root / "frontend" / "view.tsx", "export const V = () => null;\n")
        _write(root / "scripts" / "build.py", "def build():\n    return 2\n")
        # A file the noise filter must remove: setup.py is categorised config.
        _write(root / "setup.py", "from setuptools import setup\n\nsetup(name='x')\n")
        _git(root, "add", "-A")
        _git(root, "-c", "user.name=A", "-c", "user.email=a@t.com", "commit", "-m", "initial")
        return root

    def _ranked(self, db_session, tmp_path):
        repo = register_from_path(db_session, str(self._make_repo(tmp_path)))
        ingest_repo(db_session, repo)
        rank_repo(db_session, repo)
        return repo

    def _paths(self, payload):
        return sorted(n["path"] for n in payload["nodes"])

    def test_LOADBEARING_languages_accepts_REPEATED_values(self, db_session, tmp_path):
        """Three values, and the result must differ from EVERY single one of
        them. A two-value test passes on an implementation that reads only the
        last value, which is exactly the silent under-filtering this exists to
        prevent."""
        repo = self._ranked(db_session, tmp_path)
        langs = ["python", "typescript", "tsx"]

        multi = get_graph(repo.id, level="file", languages=langs, user=None, db=db_session)
        multi_paths = set(self._paths(multi))

        singles = {}
        for lang in langs:
            single = get_graph(repo.id, level="file", languages=[lang], user=None, db=db_session)
            singles[lang] = set(self._paths(single))
            assert single["nodes"], f"fixture produced no {lang} files"
            assert multi_paths != singles[lang], (
                f"three-language result equals the {lang}-only result -- "
                "the endpoint is reading one value, not all three"
            )

        # And it is the union, not an arbitrary subset.
        assert multi_paths == set().union(*singles.values())

    def test_LOADBEARING_segments_accepts_repeated_values(self, db_session, tmp_path):
        repo = self._ranked(db_session, tmp_path)
        both = get_graph(repo.id, level="file", segments=["backend", "frontend"],
                         user=None, db=db_session)
        back = get_graph(repo.id, level="file", segments=["backend"], user=None, db=db_session)
        front = get_graph(repo.id, level="file", segments=["frontend"], user=None, db=db_session)

        assert set(self._paths(both)) == set(self._paths(back)) | set(self._paths(front))
        assert set(self._paths(both)) != set(self._paths(back))

    def test_root_level_files_are_reachable_through_the_root_segment(self, db_session, tmp_path):
        """topLevelSegment maps a file with no "/" to "(root)". If the server
        spelled that differently, root files would be unmatchable by a chip the
        UI offers."""
        repo = self._ranked(db_session, tmp_path)
        payload = get_graph(repo.id, level="file", segments=["(root)"], user=None, db=db_session)
        assert "setup.py" in self._paths(payload)

    def test_query_is_a_case_insensitive_substring_of_the_path(self, db_session, tmp_path):
        repo = self._ranked(db_session, tmp_path)
        payload = get_graph(repo.id, level="file", query="UTIL", user=None, db=db_session)
        assert self._paths(payload) == ["backend/util.py"]

    def test_LOADBEARING_a_whitespace_query_narrows_nothing(self, db_session, tmp_path):
        """filterFiles trims before matching, so a whitespace query removes no
        files there. If it removed files here the two views would disagree over
        a filter the user cannot see."""
        repo = self._ranked(db_session, tmp_path)
        blank = get_graph(repo.id, level="file", query="   ", user=None, db=db_session)
        none = get_graph(repo.id, level="file", user=None, db=db_session)

        assert self._paths(blank) == self._paths(none)
        assert blank["filters_active"] is False

    def test_hide_noise_removes_config_migration_generated(self, db_session, tmp_path):
        repo = self._ranked(db_session, tmp_path)
        unfiltered = get_graph(repo.id, level="file", user=None, db=db_session)
        assert "setup.py" in self._paths(unfiltered), "fixture's config file was not ingested"

        hidden = get_graph(repo.id, level="file", hide_noise=True, user=None, db=db_session)
        assert "setup.py" not in self._paths(hidden)

    def test_LOADBEARING_filters_apply_BEFORE_directory_aggregation(self, db_session, tmp_path):
        """The whole reason this is server-side. A directory graph filtered
        after aggregation would report file counts over files the user
        excluded -- "50 files" beside a filter matching 3."""
        repo = self._ranked(db_session, tmp_path)
        payload = get_graph(repo.id, level="directory", segments=["backend"],
                            user=None, db=db_session)

        assert payload["nodes"], "no directories survived the filter"
        for node in payload["nodes"]:
            assert node["path"].startswith("backend"), f"unfiltered directory {node['path']}"
        # Counts describe the filtered set, not the whole repo.
        assert sum(n["file_count"] for n in payload["nodes"]) == payload["files_matched"]

    def test_LOADBEARING_no_edge_survives_whose_endpoint_was_filtered_out(self, db_session, tmp_path):
        """The dangling-edge condition, checked at the source. The client pins
        this invariant too, but the server should not be emitting one."""
        repo = self._ranked(db_session, tmp_path)
        for kwargs in ({"segments": ["backend"]}, {"languages": ["python"]}, {"query": "util"}):
            payload = get_graph(repo.id, level="file", user=None, db=db_session, **kwargs)
            ids = {n["id"] for n in payload["nodes"]}
            for e in payload["edges"]:
                assert e["source"] in ids and e["target"] in ids, f"dangling edge under {kwargs}"

    def test_totals_describe_the_POST_filter_population(self, db_session, tmp_path):
        """The truncation notice reads "400 of N". N must be the matching
        count once a filter is on, or the notice is right unfiltered and wrong
        filtered with nothing to distinguish them."""
        repo = self._ranked(db_session, tmp_path)
        unfiltered = get_graph(repo.id, level="file", user=None, db=db_session)
        filtered = get_graph(repo.id, level="file", segments=["backend"], user=None, db=db_session)

        assert unfiltered["total_nodes_before_cap"] == len(unfiltered["nodes"])
        assert filtered["total_nodes_before_cap"] == len(filtered["nodes"])
        assert filtered["total_nodes_before_cap"] < unfiltered["total_nodes_before_cap"]

    def test_the_applied_filters_are_echoed(self, db_session, tmp_path):
        repo = self._ranked(db_session, tmp_path)
        payload = get_graph(repo.id, level="file", languages=["python"], hide_noise=True,
                            user=None, db=db_session)

        assert payload["filters"]["languages"] == ["python"]
        assert payload["filters"]["hide_noise"] is True
        assert payload["filters_active"] is True

    def test_directory_level_also_echoes_and_counts(self, db_session, tmp_path):
        repo = self._ranked(db_session, tmp_path)
        payload = get_graph(repo.id, level="directory", languages=["python"],
                            user=None, db=db_session)
        assert payload["filters_active"] is True
        assert payload["files_matched"] > 0
