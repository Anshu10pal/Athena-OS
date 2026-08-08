"""Phase F4: reading order. Pure-function tests -- plain networkx graphs, no
DB, no ingest. compute_layers/build_reading_order take a graph and explicit
entry ids, never a scorer or the DB, so ordering is testable independent of
which scorer produced a selection.
"""
import networkx as nx

from app.services.codebase.ordering import build_reading_order, compute_layers


class TestComputeLayers:
    def test_linear_chain(self):
        g = nx.DiGraph()
        g.add_edge("a", "b")
        g.add_edge("b", "c")
        layers = compute_layers(g, {"a"})
        assert layers == {"a": 0, "b": 1, "c": 2}

    def test_cycle_shares_one_layer(self):
        # a<->b is a strongly connected component; neither can be said to
        # come "before" the other, so both share the SCC's layer.
        g = nx.DiGraph()
        g.add_edge("a", "b")
        g.add_edge("b", "a")
        g.add_edge("b", "c")
        layers = compute_layers(g, {"a"})
        assert layers["a"] == 0
        assert layers["b"] == 0
        assert layers["c"] == 1

    def test_multi_source_bfs_takes_shortest_from_either_entry(self):
        # Two independent entry points; c is one hop from the "d" entry and
        # would be two hops from "a" -- it must get the shorter layer (1),
        # not whichever entry happens to be processed first.
        g = nx.DiGraph()
        g.add_edge("a", "b")
        g.add_edge("b", "c")
        g.add_edge("d", "c")
        layers = compute_layers(g, {"a", "d"})
        assert layers["a"] == 0
        assert layers["d"] == 0
        assert layers["b"] == 1
        assert layers["c"] == 1

    def test_unreachable_node_gets_none(self):
        g = nx.DiGraph()
        g.add_edge("a", "b")
        g.add_node("isolated")
        layers = compute_layers(g, {"a"})
        assert layers["isolated"] is None

    def test_no_entry_ids_gives_all_none(self):
        g = nx.DiGraph()
        g.add_edge("a", "b")
        layers = compute_layers(g, set())
        assert layers == {"a": None, "b": None}

    def test_entry_id_not_in_graph_is_ignored_not_an_error(self):
        g = nx.DiGraph()
        g.add_edge("a", "b")
        layers = compute_layers(g, {"nonexistent"})
        assert layers == {"a": None, "b": None}

    def test_empty_graph_returns_empty(self):
        assert compute_layers(nx.DiGraph(), {"a"}) == {}


class TestBuildReadingOrder:
    def _graph_and_scores(self):
        # a (entry) -> b -> c ; d is unreachable from a but scores highest --
        # the exact "selected but not reachable" case this phase exists to flag.
        g = nx.DiGraph()
        g.add_edge("a", "b")
        g.add_edge("b", "c")
        g.add_node("d")
        scored_files = [
            {"file_id": "d", "path": "d.py", "score": 0.9},
            {"file_id": "a", "path": "a.py", "score": 0.8},
            {"file_id": "b", "path": "b.py", "score": 0.5},
            {"file_id": "c", "path": "c.py", "score": 0.3},
        ]
        return g, scored_files

    def test_selection_is_top_n_by_score(self):
        g, scored_files = self._graph_and_scores()
        result = build_reading_order(scored_files, g, entry_ids={"a"}, top_n=2)
        selected_ids = {f["file_id"] for f in result["ordered"]} | {
            f["file_id"] for f in result["unreachable_high_centrality"]
        }
        assert selected_ids == {"d", "a"}  # top 2 by score, not by layer

    def test_ordered_by_layer_ascending_not_score(self):
        g, scored_files = self._graph_and_scores()
        result = build_reading_order(scored_files, g, entry_ids={"a"}, top_n=4)
        # d has the highest score (0.9) but layer None -- must sort LAST,
        # not first. a (layer 0) leads despite a lower score than d.
        ordered_ids = [f["file_id"] for f in result["ordered"]]
        assert ordered_ids == ["a", "b", "c", "d"]

    def test_ties_within_a_layer_broken_by_score_descending(self):
        g = nx.DiGraph()
        g.add_edge("a", "b")
        g.add_edge("a", "c")  # b and c are both layer 1
        scored_files = [
            {"file_id": "a", "path": "a.py", "score": 1.0},
            {"file_id": "c", "path": "c.py", "score": 0.9},
            {"file_id": "b", "path": "b.py", "score": 0.4},
        ]
        result = build_reading_order(scored_files, g, entry_ids={"a"}, top_n=3)
        ordered_ids = [f["file_id"] for f in result["ordered"]]
        assert ordered_ids == ["a", "c", "b"]

    def test_unreachable_high_centrality_reports_selected_but_unreachable(self):
        g, scored_files = self._graph_and_scores()
        result = build_reading_order(scored_files, g, entry_ids={"a"}, top_n=4)
        assert [f["file_id"] for f in result["unreachable_high_centrality"]] == ["d"]
        # and it must NOT also appear in `ordered` at some earlier position --
        # it's reported once, in the unreachable list, and sorted last if it
        # appears in `ordered` at all.
        assert result["ordered"][-1]["file_id"] == "d"

    def test_total_layers_counts_reachable_layers_only(self):
        g, scored_files = self._graph_and_scores()
        result = build_reading_order(scored_files, g, entry_ids={"a"}, top_n=4)
        assert result["total_layers"] == 3  # layers 0, 1, 2 (a, b, c)

    def test_no_reachable_files_gives_zero_total_layers(self):
        g = nx.DiGraph()
        g.add_node("d")
        scored_files = [{"file_id": "d", "path": "d.py", "score": 0.9}]
        result = build_reading_order(scored_files, g, entry_ids=set(), top_n=1)
        assert result["total_layers"] == 0
        assert result["unreachable_high_centrality"][0]["file_id"] == "d"

    def test_scored_files_dict_is_not_mutated(self):
        g, scored_files = self._graph_and_scores()
        original = [dict(f) for f in scored_files]
        build_reading_order(scored_files, g, entry_ids={"a"}, top_n=4)
        assert scored_files == original


class TestBuildReadingOrderScoreExemption:
    """Phase F7: a zero-fan-in seed's weighted_pagerank score is entirely a
    function of its own seed weight and global constants (see
    weighted_personalized_pagerank's docstring) -- letting it also win a
    selection slot on that score double-counts what layer 0 already
    guarantees. score_exempt_ids lets a caller (e.g. weighted_pagerank's
    seed set) keep those files in the selection without letting their
    score consume one of the competitive slots."""

    def _graph_and_scores(self):
        # Same shape as TestBuildReadingOrder, but "a" (the entry) now scores
        # LOWEST -- exactly the case a real zero-fan-in seed with a small
        # teleport share could produce, and the case plain top_n truncation
        # would drop it on.
        g = nx.DiGraph()
        g.add_edge("a", "b")
        g.add_edge("b", "c")
        g.add_node("d")
        scored_files = [
            {"file_id": "d", "path": "d.py", "score": 0.9},
            {"file_id": "b", "path": "b.py", "score": 0.5},
            {"file_id": "c", "path": "c.py", "score": 0.3},
            {"file_id": "a", "path": "a.py", "score": 0.1},
        ]
        return g, scored_files

    def test_exempt_file_included_despite_losing_on_score(self):
        g, scored_files = self._graph_and_scores()
        result = build_reading_order(scored_files, g, entry_ids={"a"}, top_n=1, score_exempt_ids={"a"})
        selected_ids = {f["file_id"] for f in result["ordered"]}
        assert "a" in selected_ids  # would NOT have made top_n=1 by score alone

    def test_exempt_file_does_not_consume_a_competitive_slot(self):
        g, scored_files = self._graph_and_scores()
        result = build_reading_order(scored_files, g, entry_ids={"a"}, top_n=2, score_exempt_ids={"a"})
        selected_ids = {f["file_id"] for f in result["ordered"]} | {
            f["file_id"] for f in result["unreachable_high_centrality"]
        }
        # "a" is exempt (always in); the ONE remaining slot goes to the
        # best-scoring non-exempt file (d), not to b despite b being reachable.
        assert selected_ids == {"a", "d"}

    def test_more_exempt_than_top_n_all_still_included(self):
        g, scored_files = self._graph_and_scores()
        result = build_reading_order(
            scored_files, g, entry_ids={"a", "b"}, top_n=1, score_exempt_ids={"a", "b"}
        )
        selected_ids = {f["file_id"] for f in result["ordered"]}
        assert selected_ids == {"a", "b"}  # top_n is a floor here, not a hard cap

    def test_exempt_file_still_gets_its_real_layer(self):
        g, scored_files = self._graph_and_scores()
        result = build_reading_order(scored_files, g, entry_ids={"a"}, top_n=1, score_exempt_ids={"a"})
        a_row = next(f for f in result["ordered"] if f["file_id"] == "a")
        assert a_row["layer"] == 0

    def test_empty_score_exempt_ids_matches_old_behavior(self):
        g, scored_files = self._graph_and_scores()
        with_default = build_reading_order(scored_files, g, entry_ids={"a"}, top_n=2)
        with_explicit_empty = build_reading_order(scored_files, g, entry_ids={"a"}, top_n=2, score_exempt_ids=set())
        assert with_default == with_explicit_empty
