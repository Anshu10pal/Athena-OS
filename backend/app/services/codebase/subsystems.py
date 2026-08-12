"""Phase I1: subsystem clustering over the resolved import graph.

Motivated by the F7 external-validation finding (docs/external-validation-eslint.md):
import-graph centrality and a maintainer's own architecture doc answer
different questions -- centrality tells you what's load-bearing, not how
the codebase is conceptually organized. Community detection over the same
import graph is a deterministic, zero-LLM way to approximate the second
question.

Two independent algorithms run and persist side by side, deliberately:
- `greedy_modularity_communities` (networkx) -- the primary signal, pure
  Python, no seed needed for determinism, but its API defaults to IGNORING
  edge weights (weight=None) -- verified in I0 that passing weight="weight"
  explicitly produces a materially different (and, given F1's edge kinds
  are load-bearing, more correct) clustering.
- `louvain_communities` (networkx) -- an independent cross-check, seeded
  (seed=42) for determinism since Louvain's algorithm is randomized where
  modularity's greedy merge isn't. On repo 1 the two agree 100% (I0) -- so
  a disagreement-surfacing UI has nothing to render there. Both are kept
  and persisted anyway: the agreement number itself is a finding (reported
  on Repo.subsystem_algorithm_agreement), and it may not hold on every
  repo's graph shape.

Both functions read the SAME edge weights as ranking.py's weighted_pagerank
scorer (config/edge_weights.yaml via edge_weights.resolve_weight, max
weight per file pair -- see _build_undirected_weighted_graph's docstring
for why max, not sum). Deliberately does NOT modify ranking.py's
_build_weighted_graph (directed, used by weighted_pagerank) -- clustering
needs an undirected graph, so this module builds its own from the same
underlying CodeImport rows rather than converting/mutating the existing
directed one.

Phase I6 adds a THIRD, independently-triggered algorithm: HDBSCAN over
FastEmbed embeddings of each file's symbol signatures + docstrings (see
embeddings.py). Motivated directly by I5's own finding (docs/external-
validation-eslint.md, Round 3) that import-graph clustering conflates
coupling with responsibility -- a file can be heavily imported by files
across several conceptually distinct parts of a codebase, which the graph
algorithms have no way to distinguish from "these files are one thing."
Embeddings of what a file's code actually declares are a genuinely
different signal, not a re-derivation of the same one; whether that signal
clusters files into more homogeneous, name-aligned groups than the import
graph does is an empirical question, answered the same way I5 answered it
for modularity -- predict first, then measure per-component recall and
cluster homogeneity against the same ESLint ground truth (see
docs/external-validation-eslint.md's Round 4 once it's run). It is not
assumed to be better just because it uses a different technique.
"""
import time
from collections import Counter
from typing import Optional

import hdbscan as hdbscan_lib
import networkx as nx
import numpy as np
from networkx.algorithms.community import greedy_modularity_communities, louvain_communities
from sqlalchemy.orm import Session

from app.db.models import CodeFile, CodeImport, CodeSubsystem, CodeSymbol, Repo
from app.services.codebase import edge_weights, embeddings, repo_lock
from app.services.codebase.dir_aggregation import dirname_of

VALID_ALGORITHMS = ("modularity", "louvain", "hdbscan")
LOUVAIN_SEED = 42
# HDBSCAN's own tuning knob for "how many files make a real cluster,"
# analogous in purpose to modularity/Louvain's implicit tendency to merge
# small groups but not remotely equivalent in mechanism -- these are
# reasoned starting values (a graph-clustering pair of 2 already forms a
# cluster there; embedding space is dense and continuous rather than
# sparse, so a size-2 minimum would over-fragment on noise), not values
# tuned against ground truth yet. Revisit once the Round 4 validation
# (see module docstring) has real recall/homogeneity numbers to tune against.
HDBSCAN_MIN_CLUSTER_SIZE = 3
# Verified empirically (not assumed), two conflicting failure modes at
# this scale: the hdbscan library's default min_samples (= min_cluster_size
# when not given explicitly) sometimes calls a cluster whose real size
# exactly EQUALS min_cluster_size "noise" -- every point's core distance
# reaches all the way to its farthest same-cluster neighbor, starving the
# cluster of the density contrast HDBSCAN's stability calculation needs.
# Lowering min_samples (e.g. to 1) fixes that but introduces the opposite,
# worse failure: a scattered, unrelated point can get pulled into a real
# cluster via density chaining (verified with a synthetic scattered-point
# case). Between "a real 3-file cluster occasionally reports as
# Unclustered" (a false negative -- undersells coverage, never lies) and
# "an unrelated file gets labeled as belonging to a cluster it isn't part
# of" (a false positive -- actively misleading), the library's own
# conservative default is the safer bias, so it is NOT overridden here.
# Revisit only with real validation numbers (see this module's docstring,
# Round 4) showing the conservative default is actually costing real
# clusters on real repos -- not from synthetic toy-example tuning.

_SUBSYSTEM_COLUMN_BY_ALGORITHM = {
    "modularity": CodeFile.subsystem_modularity_id,
    "louvain": CodeFile.subsystem_louvain_id,
    "hdbscan": CodeFile.subsystem_hdbscan_id,
}


def subsystem_column_for(algorithm: str):
    """Single source of truth for the algorithm -> CodeFile column mapping
    -- used to live as an inline ternary in three separate places
    (_persist_algorithm here, plus two spots in api/repos.py); a ternary
    stops working the moment there are three algorithms instead of two, so
    this replaces all three call sites rather than growing into a chained
    ternary."""
    return _SUBSYSTEM_COLUMN_BY_ALGORITHM[algorithm]
# Below this, a directory-pair/group's real import-level cycle (found by
# _directory_scc_groups) is NOT carried by pervasive file-to-file coupling
# -- most of its files scatter into other subsystems. Worth surfacing as
# an actionable finding ("the cycle may be carried by a small number of
# edges, not by both directories' bulk"), not silently treated the same as
# a group that coheres cleanly. A plain display threshold, not a scoring
# weight -- same category as MatrixView.tsx's PRINT_THRESHOLD.
CYCLE_COHERENCE_WEAK_THRESHOLD = 0.75


def _build_undirected_weighted_graph(db: Session, repo: Repo, file_by_id: dict) -> nx.Graph:
    """Undirected, weight="weight" edge attribute -- max weight among all
    CodeImport rows for that file pair, same "max not sum" reasoning as
    ranking.py's _build_weighted_graph (a refactor that splits one import
    statement into several named imports shouldn't change a pair's
    coupling weight; summing would let it). Nodes added in SORTED id order
    -- greedy_modularity_communities' output order depends on Python's
    dict/insertion order, which is deterministic in CPython but not an API
    guarantee networkx documents (confirmed in I0), so the input order is
    pinned here rather than left to whatever order the DB query returns."""
    weights_config = edge_weights.load_edge_weights()
    rows = (
        db.query(CodeImport.from_file_id, CodeImport.to_file_id, CodeImport.kind)
        .filter(CodeImport.repo_id == repo.id, CodeImport.to_file_id.isnot(None))
        .all()
    )
    graph = nx.Graph()
    graph.add_nodes_from(sorted(file_by_id.keys()))
    for from_id, to_id, kind in rows:
        if from_id not in file_by_id or to_id not in file_by_id or from_id == to_id:
            continue
        w = edge_weights.resolve_weight(kind, weights_config)
        if graph.has_edge(from_id, to_id):
            if w > graph[from_id][to_id]["weight"]:
                graph[from_id][to_id]["weight"] = w
        else:
            graph.add_edge(from_id, to_id, weight=w)
    return graph


def _sorted_clusters(raw_clusters) -> list:
    """Sort cluster OUTPUTS too, not just graph inputs -- networkx's own
    community-list order is an implementation detail. Deterministic
    ordering: size descending, then the cluster's own minimum file id."""
    clusters = [sorted(c) for c in raw_clusters]
    clusters.sort(key=lambda c: (-len(c), c[0]))
    return clusters


def cluster_modularity(graph: nx.Graph) -> list:
    return _sorted_clusters(greedy_modularity_communities(graph, weight="weight"))


def cluster_louvain(graph: nx.Graph, seed: int = LOUVAIN_SEED) -> list:
    return _sorted_clusters(louvain_communities(graph, weight="weight", seed=seed))


def cluster_hdbscan(vectors: np.ndarray, ordered_ids: list,
                     min_cluster_size: int = HDBSCAN_MIN_CLUSTER_SIZE) -> list:
    """HDBSCAN over L2-normalized embedding vectors using Euclidean
    distance. Normalizing first makes Euclidean distance a monotonic
    function of cosine distance (||a-b|| == sqrt(2 - 2*cos_sim) for unit
    vectors) -- the standard workaround for the hdbscan package's core
    algorithms not accepting metric="cosine" directly, without needing a
    precomputed distance matrix.

    `ordered_ids` must be the same length and order as `vectors`' rows --
    the caller's responsibility, same contract as
    _build_undirected_weighted_graph's sorted node order, so cluster
    membership is traceable back to real file ids.

    Label -1 ("noise" in HDBSCAN's own terminology -- a point that never
    joined a sufficiently dense region) is not a cluster: each noise point
    becomes its own singleton, given a unique dict key so two different
    noise points never collide into the same "cluster." _sorted_clusters'
    existing size-based filtering (len(members) < 2) is what turns these
    into the same NULL-FK "Unclustered" treatment modularity/Louvain
    singletons already get in _persist_algorithm -- no separate handling
    needed here."""
    if len(ordered_ids) < min_cluster_size:
        return _sorted_clusters([[fid] for fid in ordered_ids])

    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0  # a zero vector (empty text) stays zero, not NaN
    normalized = vectors / norms

    clusterer = hdbscan_lib.HDBSCAN(min_cluster_size=min_cluster_size, metric="euclidean")
    labels = clusterer.fit_predict(normalized)

    grouped: dict = {}
    for fid, label in zip(ordered_ids, labels):
        key = f"noise-{fid}" if label == -1 else int(label)
        grouped.setdefault(key, []).append(fid)
    return _sorted_clusters(grouped.values())


def _dominant_prefix_label(members: list, path_of: dict) -> tuple:
    dirs = Counter(dirname_of(path_of[fid]) for fid in members)
    label, count = dirs.most_common(1)[0]
    return label, count


def _top_fan_in_label(members: list, fan_in_of: dict, path_of: dict) -> tuple:
    top = max(members, key=lambda fid: fan_in_of.get(fid) or 0)
    stem = path_of[top].rsplit("/", 1)[-1]
    if "." in stem:
        stem = stem.rsplit(".", 1)[0]
    return stem, top


def algorithm_agreement(clusters_a: list, clusters_b: list) -> Optional[float]:
    """Fraction of files in clusters_a's MULTI-MEMBER clusters whose
    majority-matching cluster in clusters_b contains them -- i.e. how much
    two independent clusterings agree on this repo's real structure.
    Singleton clusters are excluded from both sides of the ratio: a lone
    file trivially "landing with itself" in both algorithms says nothing
    about whether the algorithms structurally agree (I0's own agreement
    check used this same exclusion). None if clusters_a has no multi-member
    cluster at all (e.g. a graph too sparse for either algorithm to find
    any real community)."""
    cluster_b_of = {fid: i for i, c in enumerate(clusters_b) for fid in c}
    total = 0
    agreeing = 0
    for c in clusters_a:
        if len(c) < 2:
            continue
        counts = Counter(cluster_b_of.get(fid) for fid in c)
        _, best = counts.most_common(1)[0]
        total += len(c)
        agreeing += best
    return (agreeing / total) if total else None


def _directory_scc_groups(db: Session, repo: Repo, path_of: dict) -> list:
    """Non-trivial strongly-connected groups of IMMEDIATE directories
    (dir_aggregation.dirname_of) in the resolved import graph -- the same
    kind of cycle H2 finds client-side over the /graph?level=directory
    payload, discovered here server-side over EVERY directory pair/group in
    this repo, not just the three already known from H2's own report."""
    edges = set()
    rows = (
        db.query(CodeImport.from_file_id, CodeImport.to_file_id)
        .filter(CodeImport.repo_id == repo.id, CodeImport.to_file_id.isnot(None))
        .distinct()
        .all()
    )
    for from_id, to_id in rows:
        if from_id not in path_of or to_id not in path_of:
            continue
        a, b = dirname_of(path_of[from_id]), dirname_of(path_of[to_id])
        if a != b:
            edges.add((a, b))
    dg = nx.DiGraph()
    dg.add_edges_from(edges)
    return [sorted(g) for g in nx.strongly_connected_components(dg) if len(g) > 1]


def cycle_cluster_coherence(db: Session, repo: Repo, path_of: dict, cluster_of: dict) -> list:
    """For each real directory-level cycle group, what fraction of its
    pooled member files share ONE dominant subsystem cluster. A group
    scoring below CYCLE_COHERENCE_WEAK_THRESHOLD isn't a clustering defect
    -- it means the cycle is carried by a small number of specific edges
    between specific files, not by pervasive coupling across both
    directories, which is architecturally actionable (the cycle may be
    fixable by inverting one or two edges) rather than requiring a
    restructure of either directory as a whole."""
    groups = _directory_scc_groups(db, repo, path_of)
    results = []
    for group in groups:
        member_files = [fid for fid, p in path_of.items() if dirname_of(p) in group]
        if not member_files:
            continue
        counts = Counter(cluster_of.get(fid) for fid in member_files)
        majority_cluster, majority_count = counts.most_common(1)[0]
        coherence = majority_count / len(member_files)
        results.append({
            "directories": group,
            "total_files": len(member_files),
            "majority_cluster_index": majority_cluster,
            "majority_count": majority_count,
            "coherence": coherence,
            "weak": coherence < CYCLE_COHERENCE_WEAK_THRESHOLD,
        })
    results.sort(key=lambda r: r["coherence"])
    return results


def _persist_algorithm(db: Session, repo: Repo, algorithm: str, clusters: list,
                        path_of: dict, fan_in_of: dict) -> tuple:
    """Replaces this algorithm's CodeSubsystem rows wholesale (decoupled
    from ingest, same shape as CodeFileRank's per-scorer replace), except
    a custom_label survives IF the new cluster overlaps a previously
    custom-labeled cluster by >=50% of that OLD cluster's members -- below
    that, the "same" subsystem can no longer be said to exist and the
    label resets to the default rule. Every carry-over and reset is
    counted and returned, never silent, same discipline as G1's
    category_flips reporting."""
    subsystem_col = subsystem_column_for(algorithm)

    old_rows = db.query(CodeSubsystem).filter(
        CodeSubsystem.repo_id == repo.id, CodeSubsystem.algorithm == algorithm
    ).all()
    old_custom = []
    for row in old_rows:
        if row.custom_label:
            members = {fid for (fid,) in db.query(CodeFile.id).filter(subsystem_col == row.id).all()}
            if members:
                old_custom.append((members, row.custom_label, row.active_label_rule))

    db.query(CodeFile).filter(CodeFile.repo_id == repo.id, subsystem_col.isnot(None)).update(
        {subsystem_col.key: None}, synchronize_session=False
    )
    for row in old_rows:
        db.delete(row)
    db.flush()

    cluster_of = {}
    carried = 0
    reset = 0
    for index, members in enumerate(clusters):
        if len(members) < 2:
            continue  # singleton -- no row, CodeFile stays NULL ("Unclustered")
        dom_label, dom_count = _dominant_prefix_label(members, path_of)
        top_label, top_fid = _top_fan_in_label(members, fan_in_of, path_of)

        member_set = set(members)
        best_overlap, best_old = 0.0, None
        for old_members, old_label, old_rule in old_custom:
            overlap = len(old_members & member_set) / len(old_members)
            if overlap > best_overlap:
                best_overlap, best_old = overlap, (old_label, old_rule)

        custom_label, active_rule = None, "dominant_prefix"
        if best_old is not None and best_overlap >= 0.5:
            custom_label, active_rule = best_old
            carried += 1
        elif best_old is not None:
            reset += 1

        row = CodeSubsystem(
            repo_id=repo.id, algorithm=algorithm, cluster_index=index,
            member_count=len(members), dominant_prefix_label=dom_label,
            dominant_prefix_count=dom_count, top_fan_in_label=top_label,
            top_fan_in_file_id=top_fid, custom_label=custom_label,
            active_label_rule=active_rule,
        )
        db.add(row)
        db.flush()
        db.query(CodeFile).filter(CodeFile.id.in_(members)).update(
            {subsystem_col.key: row.id}, synchronize_session=False
        )
        for fid in members:
            cluster_of[fid] = index

    return cluster_of, carried, reset


def compute_subsystems(db: Session, repo: Repo, on_progress=None) -> dict:
    """Holds the per-repo advisory lock (repo_lock.py) for the whole call --
    same reasoning as ranking.py's rank_repo*: this reads the resolved
    import graph, so it must not run inside an in-flight ingest's
    two-stage resolution window.

    `on_progress(stage, current, total, message)` is optional. It exists
    because this became a pipeline stage (jobs.py) and shipped emitting a bare
    `0, 0` -- a new stage with the exact instrumentation gap that had just been
    fixed on two others. Phase-based rather than per-file: the graph build and
    the two clustering passes are the units, and a reader wants to know which
    is running, not how many nodes are left.
    """
    with repo_lock.repo_lock(repo.id, "subsystems"):
        return _compute_subsystems_locked(db, repo, on_progress=on_progress)


CLUSTERING_PHASES = 3  # graph build, modularity, louvain


def _compute_subsystems_locked(db: Session, repo: Repo, on_progress=None) -> dict:
    files = db.query(CodeFile).filter(CodeFile.repo_id == repo.id).all()
    file_by_id = {f.id: f for f in sorted(files, key=lambda f: f.path)}
    path_of = {fid: f.path for fid, f in file_by_id.items()}
    fan_in_of = {fid: f.fan_in for fid, f in file_by_id.items()}

    def report(step: int, message: str) -> None:
        if on_progress is not None:
            on_progress("clustering", step, CLUSTERING_PHASES, message)

    report(0, "Building the co-import graph")
    graph = _build_undirected_weighted_graph(db, repo, file_by_id)
    report(1, "Grouping files (modularity)")
    modularity_clusters = cluster_modularity(graph)
    report(2, "Grouping files (Louvain)")
    louvain_clusters = cluster_louvain(graph)
    report(3, "Recording subsystems")

    agreement = algorithm_agreement(modularity_clusters, louvain_clusters)
    repo.subsystem_algorithm_agreement = agreement

    report = {"agreement": agreement, "algorithms": {}}
    cluster_of_by_algo = {}
    for algorithm, clusters in (("modularity", modularity_clusters), ("louvain", louvain_clusters)):
        cluster_of, carried, reset = _persist_algorithm(db, repo, algorithm, clusters, path_of, fan_in_of)
        cluster_of_by_algo[algorithm] = cluster_of
        report["algorithms"][algorithm] = {
            "cluster_count": sum(1 for c in clusters if len(c) >= 2),
            "unclustered_count": sum(1 for c in clusters if len(c) < 2),
            "labels_carried_over": carried,
            "labels_reset": reset,
        }

    # Cycle-cluster coherence is reported against the primary algorithm
    # (modularity) -- it's the leading signal per I0's design discussion;
    # Louvain's own coherence is recoverable the same way if a future
    # phase wants it, cluster_of_by_algo["louvain"] is right there.
    coherence = cycle_cluster_coherence(db, repo, path_of, cluster_of_by_algo["modularity"])
    report["cycle_coherence"] = coherence
    repo.subsystem_cycle_coherence = coherence

    db.commit()
    return report


def _clusters_from_persisted(db: Session, repo: Repo, algorithm: str) -> list:
    """Reconstructs a clusters-list (list of member-file-id lists) from
    whatever this algorithm last persisted to CodeFile/CodeSubsystem,
    grouped by cluster id -- lets a fresh HDBSCAN run compare itself
    against modularity's CURRENT persisted state without recomputing
    modularity's own graph clustering (a genuinely separate, more
    expensive computation this function has no reason to redo)."""
    col = subsystem_column_for(algorithm)
    rows = db.query(CodeFile.id, col).filter(CodeFile.repo_id == repo.id, col.isnot(None)).all()
    grouped: dict = {}
    for fid, cluster_id in rows:
        grouped.setdefault(cluster_id, []).append(fid)
    return [sorted(members) for members in grouped.values()]


def compute_subsystems_hdbscan(db: Session, repo: Repo) -> dict:
    """On-demand third algorithm -- separate lock acquisition (still keyed
    by repo.id, so it still can't run concurrently with ingest/rank/the
    modularity+Louvain pair, all of which share the same per-repo lock)
    from compute_subsystems above, since this is a materially heavier,
    separately-triggered operation (embedding every file's symbol text is
    real CPU work, unlike the near-instant graph math the other two
    algorithms do) -- see api/repos.py's POST /subsystems/hdbscan for why
    it's its own endpoint rather than folded into POST /subsystems."""
    with repo_lock.repo_lock(repo.id, "subsystems_hdbscan"):
        return _compute_subsystems_hdbscan_locked(db, repo)


def _compute_subsystems_hdbscan_locked(db: Session, repo: Repo) -> dict:
    files = db.query(CodeFile).filter(CodeFile.repo_id == repo.id).all()
    file_by_id = {f.id: f for f in sorted(files, key=lambda f: f.path)}
    path_of = {fid: f.path for fid, f in file_by_id.items()}
    fan_in_of = {fid: f.fan_in for fid, f in file_by_id.items()}
    ordered_ids = sorted(file_by_id.keys())

    symbol_rows = (
        db.query(CodeSymbol)
        .filter(CodeSymbol.file_id.in_(ordered_ids))
        .order_by(CodeSymbol.file_id.asc(), CodeSymbol.line_start.asc())
        .all()
    )
    symbols_by_file: dict = {}
    for sym in symbol_rows:
        symbols_by_file.setdefault(sym.file_id, []).append(sym)

    texts = [
        embeddings.build_file_embedding_text(path_of[fid], symbols_by_file.get(fid, []))
        for fid in ordered_ids
    ]

    t0 = time.monotonic()
    vectors = embeddings.embed_texts(texts) if texts else np.zeros((0, 0))
    embedding_seconds = round(time.monotonic() - t0, 2)

    clusters = cluster_hdbscan(vectors, ordered_ids)
    cluster_of, carried, reset = _persist_algorithm(db, repo, "hdbscan", clusters, path_of, fan_in_of)

    # Compared against modularity's CURRENT persisted clustering, not
    # Louvain's -- modularity is this project's primary graph-based signal
    # (see this module's docstring); a repo where modularity hasn't been
    # run yet has nothing to compare against, hence the None guard rather
    # than treating "no modularity clusters" as 0% agreement.
    modularity_clusters = _clusters_from_persisted(db, repo, "modularity")
    agreement = algorithm_agreement(clusters, modularity_clusters) if modularity_clusters else None
    repo.subsystem_hdbscan_agreement = agreement

    coherence = cycle_cluster_coherence(db, repo, path_of, cluster_of)
    repo.subsystem_hdbscan_cycle_coherence = coherence

    db.commit()
    return {
        "algorithm": "hdbscan",
        "cluster_count": sum(1 for c in clusters if len(c) >= 2),
        "unclustered_count": sum(1 for c in clusters if len(c) < 2),
        "labels_carried_over": carried,
        "labels_reset": reset,
        "agreement_with_modularity": agreement,
        "cycle_coherence": coherence,
        "embedded_file_count": len(ordered_ids),
        "embedding_seconds": embedding_seconds,
    }
