"""Phase 6 checkpoint 1b: serialise a repo's graph to a portable artifact.

**This module reads NOTHING directly.** Its only source is
`graph_read.read_repo_graph`. That is the whole point of checkpoint 1a: one
read path, so a schema change breaks in one place instead of in every consumer.
An emitter that reached into tables "just for this one field" would reintroduce
exactly the coupling 1a removed, so there is a test that stubs the boundary and
fails if any output survives the stub (contract §17.28).

**Two modes, and the artifact SAYS WHICH.** Checkpoint 0 measured the compact
whole graph at 31,315 tokens for Athena-OS (280 files), 73,953 for eslint
(1,447) and 962,330 for apache/superset (6,523) -- tokens track EDGES, not
files, and the crossover where a whole graph stops being usable as context sits
around 1,500 files. Above it the export is SCOPED: the top-ranked files and the
subgraph they induce. A consumer that could not tell the two apart would reason
over a partial graph believing it complete, which is the §17.25 failure of a
default standing in for unknown completeness. So `mode` is stated in the
artifact, alongside the counts that make the claim checkable -- `files_total`
against `files_included` -- rather than left to be inferred from size.

**Unresolved edges are carried.** They are a separate list rather than
null-padded pairs, because "a.py imports b.py" and "a.py imports something
called `requests` that is not in this repo" are different facts and a consumer
should not have to test for null to tell them apart. They are also the one
thing grep is good at that a resolved-edges-only graph loses.
"""
import json
from typing import Optional

from sqlalchemy.orm import Session

from app.services.codebase.graph_read import RepoGraphT, read_repo_graph

# Bumped when the artifact's SHAPE changes, so a stored artifact can be
# rejected rather than misread by a consumer written against another version.
ARTIFACT_SCHEMA_VERSION = 1

MODE_WHOLE = "whole_graph"
MODE_SCOPED = "scoped"

# The measurement that sets this, not a round number chosen for looking like
# one: compact whole-graph serialisation ran 31,315 tok at 280 files and 73,953
# at 1,447, then 962,330 at 6,523 -- a 13x jump for 4.5x the files, because
# edges grew 26x. Below ~1,500 files a whole graph is affordable as context;
# above it the artifact must be scoped or it is worse than reading source.
WHOLE_GRAPH_MAX_FILES = 1500

# Scoped mode keeps the same budget: the top `SCOPED_MAX_FILES` by rank and the
# subgraph they induce. Deliberately NOT a query interface -- scoped means "a
# bounded compact graph", and anything needing arbitrary queries is checkpoint 2.
SCOPED_MAX_FILES = WHOLE_GRAPH_MAX_FILES

# Which scorer's rank travels in the artifact. One, not all three: `legacy`,
# `rrf` and `weighted_pagerank` each cover every file, so emitting all three
# triples the rank payload to say nearly the same thing.
ARTIFACT_SCORER = "legacy"

# Which clustering travels. Same reasoning -- three partitions of the same files
# is three times the tokens for one question ("what is this file near").
ARTIFACT_CLUSTERING = "modularity"


def choose_mode(file_count: int) -> str:
    """Whole-graph at or below the threshold, scoped above it."""
    return MODE_WHOLE if file_count <= WHOLE_GRAPH_MAX_FILES else MODE_SCOPED


def _rank_of(node) -> Optional[int]:
    for r in node.ranks:
        if r.scorer == ARTIFACT_SCORER:
            return r.rank
    return None


def _compact_node(node) -> dict:
    """Paths, never database ids -- an id is meaningless outside the database
    that issued it, the same reason 1a emits cluster LABELS. Nulls dropped: a
    key present with a null value costs tokens to say nothing."""
    n = {"p": node.path}
    if node.language:
        n["lang"] = node.language
    if node.fan_in:
        n["fan_in"] = node.fan_in
    if node.fan_out:
        n["fan_out"] = node.fan_out
    if node.seed_eligible:
        n["entry"] = 1
    cluster = node.clusters.get(ARTIFACT_CLUSTERING)
    if cluster:
        n["cluster"] = cluster
    # Only real cycles reach here -- the boundary already normalised
    # one-member SCCs to None, so this never claims a lone file is cyclic.
    if node.scc_id:
        n["scc"] = node.scc_id
    rank = _rank_of(node)
    if rank is not None:
        n["rank"] = rank
    return n


def _graph_body(graph: RepoGraphT, keep: Optional[set] = None) -> dict:
    """The compact graph itself, restricted to `keep` if scoping.

    Edge lists are induced: an edge is emitted only when BOTH ends are in the
    emitted node set. Emitting an edge to a path the artifact does not contain
    would be a dangling reference a consumer cannot follow.
    """
    nodes = [n for n in graph.nodes if keep is None or n.path in keep]
    included = {n.path for n in nodes}

    edges, unresolved = [], []
    for e in graph.edges:
        if e.from_path not in included:
            continue
        if e.is_resolved:
            if e.to_path in included:
                edges.append([e.from_path, e.to_path])
        else:
            # Kept even when scoped: "this file imports something outside the
            # repo" is true regardless of how much of the repo we emitted.
            unresolved.append([e.from_path, e.raw_specifier])

    clusters = [{"label": c["label"], "n": c["member_count"]}
                for c in graph.clusters if c["algorithm"] == ARTIFACT_CLUSTERING]

    return {
        "nodes": [_compact_node(n) for n in nodes],
        "edges": edges,
        "unresolved_edges": unresolved,
        "clusters": clusters,
        "entry_points": [n.path for n in nodes if n.seed_eligible],
    }


def export_atlas(db: Session, repo_id: int, *, mode: Optional[str] = None) -> dict:
    """Build the artifact. `mode` overrides the threshold, for tests and for an
    operator who knows what they are asking for; the artifact records the mode
    actually used either way, so an override cannot produce a mislabelled file.
    """
    # include_symbols=False: symbols are the largest single contributor to a
    # serialised graph (22,872 rows on superset) and the compact shape does not
    # carry them. Paying to read them would be paying for nothing.
    graph = read_repo_graph(db, repo_id, include_symbols=False)

    files_total = len(graph.nodes)
    chosen = mode or choose_mode(files_total)
    if chosen not in (MODE_WHOLE, MODE_SCOPED):
        raise ValueError(f"unknown export mode {chosen!r}")

    keep = None
    if chosen == MODE_SCOPED:
        ranked = sorted(
            graph.nodes,
            # Unranked files sort last rather than first -- an absent rank is
            # not rank 0, and treating it as such would fill a scoped artifact
            # with whatever the ranker had nothing to say about.
            key=lambda n: (_rank_of(n) is None, _rank_of(n) or 0, n.path),
        )
        keep = {n.path for n in ranked[:SCOPED_MAX_FILES]}

    body = _graph_body(graph, keep)
    return {
        "atlas": {
            "schema_version": ARTIFACT_SCHEMA_VERSION,
            "repo": graph.repo_label,
            "repo_id": graph.repo_id,
            # THE COMPLETENESS CLAIM. Stated, not inferable from size: a
            # consumer must be able to read "this is 1,500 of 6,523 files" off
            # the artifact before it concludes anything about the codebase.
            "mode": chosen,
            "complete": chosen == MODE_WHOLE,
            "files_total": files_total,
            "files_included": len(body["nodes"]),
            "edges_total": len(graph.edges),
            "resolved_edges_included": len(body["edges"]),
            "unresolved_edges_included": len(body["unresolved_edges"]),
            "scorer": ARTIFACT_SCORER,
            "clustering": ARTIFACT_CLUSTERING,
            "whole_graph_max_files": WHOLE_GRAPH_MAX_FILES,
        },
        **body,
    }


def serialize(artifact: dict) -> str:
    """One serialisation, so a token count measured anywhere is the same count.

    Separators matter: the default `", "` adds a byte per element, which on
    superset's 60,873 edges is not a rounding error.
    """
    return json.dumps(artifact, separators=(",", ":"))
