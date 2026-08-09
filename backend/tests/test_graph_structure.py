"""Phase 1 code health: file-level SCCs and reachability.

The pure graph functions are tested with synthetic graphs -- these fed a
finding (zero file-level cycles across 599 real files) that would be
indistinguishable from a broken detector without them.
"""
import networkx as nx

from app.services.codebase.graph_structure import (
    compute_file_sccs,
    compute_reachability,
)


class TestFileSccs:
    def test_detects_a_real_cycle_and_reports_its_size(self):
        g = nx.DiGraph()
        g.add_edges_from([(1, 2), (2, 3), (3, 1)])
        sccs = compute_file_sccs(g)
        assert {sccs[i][1] for i in (1, 2, 3)} == {3}
        assert len({sccs[i][0] for i in (1, 2, 3)}) == 1  # one shared component

    def test_a_dag_yields_only_trivial_components(self):
        g = nx.DiGraph()
        g.add_edges_from([(1, 2), (2, 3), (1, 3)])
        assert all(size == 1 for _, size in compute_file_sccs(g).values())

    def test_every_node_gets_an_entry_including_isolated_ones(self):
        # size==1 is a MEASURED "not in a cycle"; only persisting it lets the
        # scorer tell a clean file from an unanalysed one (None).
        g = nx.DiGraph()
        g.add_nodes_from([1, 2, 3])
        g.add_edge(1, 2)
        assert set(compute_file_sccs(g)) == {1, 2, 3}

    def test_two_separate_cycles_get_distinct_component_ids(self):
        g = nx.DiGraph()
        g.add_edges_from([(1, 2), (2, 1), (3, 4), (4, 3)])
        sccs = compute_file_sccs(g)
        assert sccs[1][0] == sccs[2][0]
        assert sccs[3][0] == sccs[4][0]
        assert sccs[1][0] != sccs[3][0]

    def test_component_ids_are_deterministic_across_runs(self):
        # An unstable labelling would look like a structural change in a
        # trend line on every re-analysis.
        g = nx.DiGraph()
        g.add_edges_from([(5, 6), (6, 5), (1, 2), (2, 1), (9, 1)])
        assert compute_file_sccs(g) == compute_file_sccs(g)

    def test_two_node_mutual_import_is_a_cycle(self):
        g = nx.DiGraph()
        g.add_edges_from([(1, 2), (2, 1)])
        assert compute_file_sccs(g)[1][1] == 2


class TestReachability:
    def test_reachable_and_unreachable_are_distinguished(self):
        g = nx.DiGraph()
        g.add_edges_from([(1, 2), (2, 3)])
        g.add_node(9)
        r = compute_reachability(g, {1})
        assert r[1] is True and r[2] is True and r[3] is True
        assert r[9] is False

    def test_no_entry_points_means_unknown_not_all_unreachable(self):
        # Returning False everywhere would assert every file is possibly-dead,
        # which is an artifact of having nothing to search from rather than a
        # fact about the code.
        g = nx.DiGraph()
        g.add_edges_from([(1, 2)])
        assert set(compute_reachability(g, set()).values()) == {None}

    def test_multiple_entry_points_are_all_used_as_sources(self):
        g = nx.DiGraph()
        g.add_edges_from([(1, 2), (8, 9)])
        r = compute_reachability(g, {1, 8})
        assert all(r[n] is True for n in (1, 2, 8, 9))

    def test_direction_matters_importers_are_not_reachable_from_the_imported(self):
        # a -> b means a imports b, so from entry b you cannot reach a.
        g = nx.DiGraph()
        g.add_edge(1, 2)
        r = compute_reachability(g, {2})
        assert r[2] is True
        assert r[1] is False
