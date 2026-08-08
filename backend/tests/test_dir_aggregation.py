"""Phase H1/H1.5: directory aggregation, pure over plain dicts -- no DB,
no filesystem. Mirrors the file-level graph payload's shape closely
enough that these fixtures read like a miniature version of a real
/graph response, but every input here is hand-built.

Phase H1.5: is_entry_point/seed_eligible are now plain fields on each
file dict (mirroring CodeFile's persisted columns), not a separate
entry_info mapping the caller had to build from a live entry_detection
call -- see dir_aggregation.py's _kind_of docstring and repos.py's
get_graph for why that live call was removed from this read path.
"""
import pytest

from app.services.codebase.dir_aggregation import (
    DEFAULT_MAX_GROUPS,
    _cluster_of,
    _kind_of,
    _roll_up_to_cap,
    aggregate_to_directories,
    dirname_of,
    region_of,
)


def _node(id, path, prior_category="source", rank=None, is_entry_point=False, seed_eligible=False,
          subsystem_modularity_id=None):
    return {
        "id": id, "path": path, "prior_category": prior_category, "rank": rank,
        "is_entry_point": is_entry_point, "seed_eligible": seed_eligible,
        "subsystem_modularity_id": subsystem_modularity_id,
    }


def _edge(source, target, weight=1.0):
    return {"source": source, "target": target, "weight": weight}


class TestDirnameAndRegion:
    def test_nested_file(self):
        assert dirname_of("backend/app/api/repos.py") == "backend/app/api"

    def test_distinct_from_parent_directory(self):
        # backend/app/services/codebase must stay distinct from
        # backend/app/services -- this is the exact case named in the brief.
        assert dirname_of("backend/app/services/codebase/registry.py") == "backend/app/services/codebase"
        assert dirname_of("backend/app/services/resolution.py") == "backend/app/services"

    def test_root_level_file(self):
        assert dirname_of("README.md") == "(root)"

    def test_region_is_top_level_segment(self):
        assert region_of("backend/app/api") == "backend"
        assert region_of("voice_listener") == "voice_listener"

    def test_region_of_root_sentinel(self):
        assert region_of("(root)") == "(root)"


class TestRollUpToCap:
    def test_no_rollup_when_under_cap(self):
        groups = {f"dir{i}": [_node(i, f"dir{i}/f.py")] for i in range(5)}
        rollups = _roll_up_to_cap(groups, max_groups=DEFAULT_MAX_GROUPS)
        assert rollups == 0
        assert len(groups) == 5

    def test_collapses_deepest_groups_first(self):
        # a/b/c/d1 and a/b/c/d2 are deepest; they should merge into a/b/c
        # before anything shallower is touched.
        groups = {
            "a/b/c/d1": [_node(1, "a/b/c/d1/f.py")],
            "a/b/c/d2": [_node(2, "a/b/c/d2/f.py")],
            "a/b/c": [_node(3, "a/b/c/f.py")],
        }
        rollups = _roll_up_to_cap(groups, max_groups=1)
        assert rollups == 2
        assert list(groups.keys()) == ["a/b/c"]
        assert len(groups["a/b/c"]) == 3

    def test_caps_a_large_flat_repo_without_overshooting(self):
        # 30 sibling packages, each with one "mod" subdirectory: depth-1
        # merging renames every one of them to a distinct, still-30-strong
        # set of depth-0 package names (no reduction yet -- each pkgN is
        # unique), so the cap isn't satisfied until depth-0 packages start
        # sharing "(root)" as a parent. The regression this guards: an
        # earlier version merged the ENTIRE depth-0 level unconditionally
        # once it started, collapsing all 30 into a single "(root)" node
        # instead of stopping the instant 24 was reached.
        groups = {f"pkg{i}/mod": [_node(i, f"pkg{i}/mod/f.py")] for i in range(30)}
        rollups = _roll_up_to_cap(groups, max_groups=DEFAULT_MAX_GROUPS)
        assert len(groups) == DEFAULT_MAX_GROUPS  # hits the cap exactly, does not overshoot to 1
        assert rollups > 0

    def test_pathological_deep_narrow_chain_terminates(self):
        # Many independent single-file-per-directory chains, each nested
        # several levels deep with no sibling ever sharing an ancestor at
        # the same depth. One-at-a-time merging along a single such chain
        # would never reduce the count (pop a lone child, create a lone
        # parent); the whole-depth-level-per-pass strategy must still
        # terminate because max depth strictly drops every pass, and it
        # must actually reduce the count once distinct chains converge on
        # shared ancestors near the top.
        groups = {}
        for chain in range(30):
            p = "/".join(f"c{chain}_{i}" for i in range(5))
            groups[p] = [_node(chain, f"{p}/f.py")]
        rollups = _roll_up_to_cap(groups, max_groups=DEFAULT_MAX_GROUPS)
        assert len(groups) <= DEFAULT_MAX_GROUPS
        assert rollups > 0

    def test_worst_case_collapses_to_root_rather_than_hanging(self):
        # More than max_groups distinct TOP-LEVEL directories -- nothing
        # left to do but merge into "(root)".
        groups = {f"top{i}": [_node(i, f"top{i}/f.py")] for i in range(30)}
        rollups = _roll_up_to_cap(groups, max_groups=DEFAULT_MAX_GROUPS)
        assert len(groups) <= DEFAULT_MAX_GROUPS
        assert rollups > 0


class TestClusterOf:
    """Phase I2. None (unclustered) is deliberately excluded from the
    purity denominator -- see the docstring on _cluster_of, and
    docs/external-validation-eslint.md's Round 3 correction, which is the
    exact reason this exclusion exists: letting None compete as a
    "majority" inflated a recall number there, and would inflate a
    directory's purity here the same way."""

    def test_majority_cluster_and_full_purity(self):
        files = [
            _node(1, "a/x.py", subsystem_modularity_id=5),
            _node(2, "a/y.py", subsystem_modularity_id=5),
        ]
        cluster_id, purity, unclustered = _cluster_of(files)
        assert cluster_id == 5
        assert purity == 1.0
        assert unclustered == 0

    def test_partial_purity_when_members_split_across_clusters(self):
        files = [
            _node(1, "a/x.py", subsystem_modularity_id=5),
            _node(2, "a/y.py", subsystem_modularity_id=5),
            _node(3, "a/z.py", subsystem_modularity_id=9),
        ]
        cluster_id, purity, unclustered = _cluster_of(files)
        assert cluster_id == 5
        assert purity == pytest.approx(2 / 3)
        assert unclustered == 0

    def test_unclustered_files_excluded_from_purity_denominator(self):
        # 1 of 2 REAL cluster members agree; the two unclustered files
        # must not dilute or inflate that ratio in either direction.
        files = [
            _node(1, "a/x.py", subsystem_modularity_id=5),
            _node(2, "a/y.py", subsystem_modularity_id=9),
            _node(3, "a/z.py", subsystem_modularity_id=None),
            _node(4, "a/w.py", subsystem_modularity_id=None),
        ]
        cluster_id, purity, unclustered = _cluster_of(files)
        assert purity == 0.5
        assert unclustered == 2

    def test_all_unclustered_returns_none_not_a_fabricated_purity(self):
        files = [
            _node(1, "a/x.py", subsystem_modularity_id=None),
            _node(2, "a/y.py", subsystem_modularity_id=None),
        ]
        cluster_id, purity, unclustered = _cluster_of(files)
        assert cluster_id is None
        assert purity is None
        assert unclustered == 2


class TestKindOf:
    def test_entry_when_any_file_is_seed_eligible(self):
        files = [
            _node(1, "backend/app/main.py", is_entry_point=True, seed_eligible=True),
            _node(2, "backend/app/other.py"),
        ]
        assert _kind_of(files) == "entry"

    def test_tooling_when_entries_are_all_prior_only(self):
        # backend/scripts: every file has a __main__ guard (fallback
        # detection) but sits under a seed-ineligible path marker -- the
        # E4 seed_eligible/prior_only split, reused here.
        files = [
            _node(1, "backend/scripts/validate_ranking.py", is_entry_point=True, seed_eligible=False),
            _node(2, "backend/scripts/compare_scorers.py", is_entry_point=True, seed_eligible=False),
        ]
        assert _kind_of(files) == "tooling"

    def test_entry_beats_tooling_when_both_present(self):
        files = [
            _node(1, "backend/app/main.py", is_entry_point=True, seed_eligible=True),
            _node(2, "backend/scripts/helper.py", is_entry_point=True, seed_eligible=False),
        ]
        assert _kind_of(files) == "entry"

    def test_migration_majority(self):
        files = [
            _node(1, "backend/alembic/versions/a.py", prior_category="migration"),
            _node(2, "backend/alembic/versions/b.py", prior_category="migration"),
            _node(3, "backend/alembic/versions/env.py", prior_category="source"),
        ]
        assert _kind_of(files) == "migration"

    def test_test_majority_via_path_heuristic_not_prior_category(self):
        # prior_category has no "test" value -- this must come from
        # edge_weights.is_test_file's path markers, not prior_category.
        files = [
            _node(1, "backend/tests/test_ranking.py"),
            _node(2, "backend/tests/test_ordering.py"),
            _node(3, "backend/tests/conftest.py"),
        ]
        assert _kind_of(files) == "test"

    def test_source_fallback(self):
        files = [_node(1, "backend/app/core/config.py"), _node(2, "backend/app/core/security.py")]
        assert _kind_of(files) == "source"

    def test_migration_tie_breaks_over_test(self):
        files = [
            _node(1, "backend/alembic/versions/test_data.py", prior_category="migration"),
            _node(2, "backend/tests/test_x.py", prior_category="source"),
        ]
        # migration-categorized file is NOT double-counted as test too.
        assert _kind_of(files) == "migration"

    def test_stale_seed_eligible_none_does_not_count_as_entry(self):
        # Pre-H1.5 data / a file no rank run has touched yet: is_entry_point
        # True but seed_eligible still null. Must read as tooling (an entry
        # of unconfirmed tier), never silently promoted to "entry".
        files = [_node(1, "backend/scripts/old.py", is_entry_point=True, seed_eligible=None)]
        assert _kind_of(files) == "tooling"


class TestAggregateToDirectories:
    def _sample(self):
        nodes = [
            _node(1, "backend/app/main.py", rank=1, is_entry_point=True, seed_eligible=True),
            _node(2, "backend/app/api/repos.py", rank=2),
            _node(3, "backend/app/api/roadmaps.py", rank=3),
            _node(4, "backend/app/db/models.py", rank=4),
        ]
        edges = [
            _edge(1, 2, weight=1.0),
            _edge(2, 4, weight=0.8),
            _edge(3, 4, weight=0.4),
            _edge(2, 3, weight=0.15),  # internal to backend/app/api
        ]
        return nodes, edges

    def test_groups_by_dirname(self):
        nodes, edges = self._sample()
        result = aggregate_to_directories(nodes, edges)
        paths = {n["path"] for n in result["nodes"]}
        assert paths == {"backend/app", "backend/app/api", "backend/app/db"}

    def test_cross_group_edges_summed_with_counts(self):
        nodes, edges = self._sample()
        result = aggregate_to_directories(nodes, edges)
        by_pair = {(e["source"], e["target"]): e for e in result["edges"]}
        assert by_pair[("backend/app", "backend/app/api")]["weight"] == 1.0
        assert by_pair[("backend/app", "backend/app/api")]["count"] == 1
        api_to_db = by_pair[("backend/app/api", "backend/app/db")]
        assert api_to_db["weight"] == pytest.approx(1.2)
        assert api_to_db["count"] == 2

    def test_internal_edges_excluded_from_list_but_counted(self):
        nodes, edges = self._sample()
        result = aggregate_to_directories(nodes, edges)
        for e in result["edges"]:
            assert e["source"] != e["target"]
        api_node = next(n for n in result["nodes"] if n["path"] == "backend/app/api")
        assert api_node["internal_edge_count"] == 1

    def test_fan_and_import_counts_derived_from_edges_not_files(self):
        nodes, edges = self._sample()
        result = aggregate_to_directories(nodes, edges)
        api_node = next(n for n in result["nodes"] if n["path"] == "backend/app/api")
        # api has 1 distinct importer (backend/app) and 1 distinct import
        # target (backend/app/db) -- NOT 2 (repos.py+roadmaps.py's raw
        # fan_out summed), since that would double-count the internal edge.
        assert api_node["fan_in_dirs"] == 1
        assert api_node["fan_out_dirs"] == 1
        assert api_node["import_count_in"] == 1.0
        assert api_node["import_count_out"] == pytest.approx(1.2)
        assert "fan_in" not in api_node
        assert "fan_out" not in api_node

    def test_kind_and_region_and_short_label(self):
        nodes, edges = self._sample()
        result = aggregate_to_directories(nodes, edges)
        by_path = {n["path"]: n for n in result["nodes"]}
        assert by_path["backend/app"]["kind"] == "entry"
        assert by_path["backend/app"]["region"] == "backend"
        assert by_path["backend/app/api"]["short_label"] == "api"
        assert by_path["backend/app/api"]["file_count"] == 2

    def test_limit_applied_after_aggregation_not_to_files(self):
        # The regression case from the brief: if `limit` capped FILES
        # before aggregation, a low limit could silently drop an entire
        # directory's files before their edges were ever counted. Here a
        # limit of 2 (fewer than the 3 real directories) must still
        # aggregate from all 4 files and only trim the DIRECTORY list
        # afterward, keeping edge weights computed from the full set.
        nodes, edges = self._sample()
        result = aggregate_to_directories(nodes, edges, limit=2)
        assert len(result["nodes"]) == 2
        assert result["total_groups_before_limit"] == 3
        assert result["truncated"] is True
        # best-ranked directories survive: backend/app (rank 1) and
        # backend/app/api (rank 2) beat backend/app/db (rank 4).
        kept = {n["path"] for n in result["nodes"]}
        assert kept == {"backend/app", "backend/app/api"}
        # edges dangling to the dropped directory must not appear.
        for e in result["edges"]:
            assert e["source"] in kept and e["target"] in kept

    def test_group_rollups_reported_when_cap_engages(self):
        nodes = [_node(i, f"pkg{i}/mod/f.py", rank=i) for i in range(30)]
        result = aggregate_to_directories(nodes, [], max_groups=DEFAULT_MAX_GROUPS)
        assert len(result["nodes"]) <= DEFAULT_MAX_GROUPS
        assert result["group_rollups"] > 0

    def test_deterministic_across_repeated_calls(self):
        nodes, edges = self._sample()
        first = aggregate_to_directories(nodes, edges)
        second = aggregate_to_directories(nodes, edges)
        assert first == second
        assert [n["path"] for n in first["nodes"]] == [n["path"] for n in second["nodes"]]

    def test_empty_input(self):
        result = aggregate_to_directories([], [])
        assert result["nodes"] == []
        assert result["edges"] == []
        assert result["group_rollups"] == 0
        assert result["truncated"] is False

    def test_cluster_fields_surfaced_on_directory_nodes(self):
        # Phase I2: a/two files share cluster 1 (pure); b/two files split
        # across clusters 1 and 2 (impure, purity 0.5).
        nodes = [
            _node(1, "a/x.py", rank=1, subsystem_modularity_id=1),
            _node(2, "a/y.py", rank=2, subsystem_modularity_id=1),
            _node(3, "b/x.py", rank=3, subsystem_modularity_id=1),
            _node(4, "b/y.py", rank=4, subsystem_modularity_id=2),
        ]
        result = aggregate_to_directories(nodes, [])
        by_path = {n["path"]: n for n in result["nodes"]}
        assert by_path["a"]["cluster_id"] == 1
        assert by_path["a"]["cluster_purity"] == 1.0
        assert by_path["a"]["cluster_unclustered_count"] == 0
        assert by_path["b"]["cluster_purity"] == 0.5
