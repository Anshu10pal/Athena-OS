"""Phase F4: reading order, split out from selection (Phase F3's scoring).

Selection is centrality -- which files make the cut. Either scorer's sorted
`files` list already answers that; the top N of it *is* the selection, no
new logic needed here.

Ordering is dependency depth -- which order to *read* the selected files in.
A file with a high score can still be something you'd want to read after
what it depends on, not before. This module computes that depth (`layer`)
from the import graph alone, independent of score, and combines it with a
selection to produce a final presentation order.

Strongly connected components are condensed first (`networkx.condensation`):
a circular import means "depth" is undefined for the files inside the
cycle, so every file in one SCC shares that SCC's layer rather than being
arbitrarily split across it. `networkx.condensation` returns a DAG keyed by
integer SCC ids; `condensed.graph["mapping"]` maps original node -> SCC id,
`condensed.nodes[scc_id]["members"]` gives the original nodes in that SCC
(verified directly against a real cycle+downstream+isolated-node graph
before writing this).
"""
import networkx as nx


def compute_layers(graph: nx.DiGraph, entry_ids: set) -> dict:
    """file_id -> layer (0 at the entry points, incrementing per hop) or
    None if unreachable from every entry id. Multi-source BFS over the
    condensed DAG: layer 0 is every SCC containing an entry id (there can be
    more than one seed), layer 1 is everything one hop out from any of
    those SCCs, and so on."""
    layers = {node: None for node in graph.nodes()}
    if not entry_ids:
        return layers

    condensed = nx.condensation(graph)
    mapping = condensed.graph["mapping"]

    entry_sccs = {mapping[e] for e in entry_ids if e in mapping}
    if not entry_sccs:
        return layers

    scc_layer = {scc: 0 for scc in entry_sccs}
    frontier = list(entry_sccs)
    layer = 0
    while frontier:
        layer += 1
        next_frontier = []
        for scc in frontier:
            for succ in condensed.successors(scc):
                if succ not in scc_layer:
                    scc_layer[succ] = layer
                    next_frontier.append(succ)
        frontier = next_frontier

    for node in graph.nodes():
        layers[node] = scc_layer.get(mapping[node])
    return layers


def build_reading_order(
    scored_files: list, graph: nx.DiGraph, entry_ids: set, top_n: int, score_exempt_ids: set = frozenset(),
) -> dict:
    """Selection: the first top_n of scored_files (already sorted by score
    descending -- that ordering IS the selection criterion). Ordering: those
    same selected files, re-sorted by (layer ascending, score descending).
    Files with layer None sort last, even if their score is high -- that
    combination (selected for centrality, but not reachable from any entry
    point) means a missing edge or genuinely dead code, and is reported
    separately as unreachable_high_centrality rather than silently pushed to
    the bottom of the list and lost.

    score_exempt_ids: files always included in the selection, without
    competing against the rest of scored_files for the remaining
    top_n - len(score_exempt_ids) slots. Phase F7 finding: under
    weighted_personalized_pagerank, a zero-fan-in seed's score reduces to
    s(f)*[(1-d) + d*D] -- entirely a function of its own seed weight and
    two global constants (the damping factor and the total dangling mass),
    none of it earned from real graph structure (see
    weighted_personalized_pagerank's docstring). Letting that score also win
    a selection slot double-counts a fact ordering already encodes
    structurally: entry points land at layer 0 by construction, below. Pass
    the seed ids here to fix that; the exempted files still get layer 0
    exactly as before, they just never had to out-score anything to get
    there. Leave this empty for legacy/RRF callers -- their entry-point
    signal is one weighted feature among several, not a personalized-
    teleport artifact, so no analogous circularity exists there.

    If more files are exempt than top_n, every exempt file is still
    included -- top_n is a floor on how many non-exempt files compete for
    the remaining slots, not a hard cap that could silently drop a seed."""
    layers = compute_layers(graph, entry_ids)

    exempt = [f for f in scored_files if f["file_id"] in score_exempt_ids]
    competing = [f for f in scored_files if f["file_id"] not in score_exempt_ids]
    remaining_slots = max(top_n - len(exempt), 0)
    selected = [dict(f, layer=layers.get(f["file_id"])) for f in exempt + competing[:remaining_slots]]

    real_layers = [f["layer"] for f in selected if f["layer"] is not None]
    unreachable_sort_layer = (max(real_layers) + 1) if real_layers else 0
    ordered = sorted(
        selected,
        key=lambda f: (f["layer"] if f["layer"] is not None else unreachable_sort_layer, -f["score"]),
    )

    unreachable_high_centrality = [f for f in selected if f["layer"] is None]

    return {
        "ordered": ordered,
        "unreachable_high_centrality": unreachable_high_centrality,
        "total_layers": (max(real_layers) + 1) if real_layers else 0,
    }
