"""Phase H1: collapse a file-level graph payload into directory-level
nodes/edges. Pure functions over plain dicts -- no DB session, no
filesystem access -- unit-testable the same way frontend/src/lib/
graphLayout.ts is: layout/aggregation logic belongs in a module nothing
but its own arguments can influence. The caller (repos.py's GET
/{repo_id}/graph) supplies whatever DB- or filesystem-derived facts
(entry detection, the file-level nodes/edges it already built) this needs.
"""
from collections import Counter, defaultdict
from typing import Optional

from app.services.codebase.edge_weights import is_test_file

DEFAULT_MAX_GROUPS = 24

_KIND_PRIORITY = {"migration": 2, "test": 1, "source": 0}


def dirname_of(path: str) -> str:
    """Everything before the last "/", or the sentinel "(root)" for a file
    with none -- a file living directly at the repo root."""
    if "/" not in path:
        return "(root)"
    return path.rsplit("/", 1)[0]


def region_of(path: str) -> str:
    """The top-level path segment (backend, frontend, voice_listener, ...)
    -- used for the architecture map's dashed region groupings. Works
    unmodified on a group's own path too: region_of("(root)") is "(root)",
    same sentinel, no special-casing needed at the call site."""
    return path.split("/", 1)[0]


def _depth(group_path: str) -> int:
    """Slash count, used only to find the currently-deepest groups during
    roll-up. "(root)" is defined as shallower than any real path (-1, not
    0) so it's never a roll-up target and the loop below correctly treats
    it as the terminal case."""
    return -1 if group_path == "(root)" else group_path.count("/")


def _roll_up_to_cap(groups: dict, max_groups: int) -> int:
    """Mutates `groups` (group path -> list of file node dicts) in place,
    merging groups into their parent (dirname_of applied to the group's
    OWN path) until at most `max_groups` remain. Returns how many
    individual child-into-parent merges happened.

    Considers a whole depth level at a time -- when count still exceeds
    the cap after fully processing one level, it moves to the next
    shallower one -- rather than one group at a time, because a single
    deep, narrow chain (a/b/c/d/... with one file each and no siblings)
    merged one group at a time would just rename the deepest link every
    step without ever reducing the total count (popping a lone child and
    creating a brand-new one-child parent is a wash). Considering a whole
    level means max depth is guaranteed to strictly drop at least once per
    level, which bounds how many levels this can ever examine, so it
    always terminates -- in the worst case (more than max_groups distinct
    TOP-LEVEL directories) it correctly bottoms out by merging those into
    "(root)" rather than looping forever. A 5,000-file repo must not
    return 400 directory nodes, even if that means an almost-flat result.

    Within a level, each individual merge still checks the cap and stops
    the instant it's satisfied -- merging renames some children into new,
    still-distinct parents (no reduction yet) before enough of them
    converge on a SHARED parent to actually shrink the count, and once
    that happens there's no reason to keep merging siblings that would
    otherwise survive untouched. Stopping mid-level, rather than mid-level
    then finishing anyway, is what keeps e.g. 30 sibling packages each
    with a lone subdirectory from being needlessly flattened all the way
    down to one node when folding just the excess handful into "(root)"
    would have satisfied the cap."""
    rollups = 0
    while len(groups) > max_groups:
        max_depth = max(_depth(p) for p in groups)
        if max_depth < 0:
            break  # everything already collapsed into "(root)"
        deepest = [p for p in groups if _depth(p) == max_depth]
        for p in deepest:
            if len(groups) <= max_groups:
                break
            parent = dirname_of(p)
            files = groups.pop(p)
            groups.setdefault(parent, []).extend(files)
            rollups += 1
    return rollups


def _cluster_of(files: list) -> tuple:
    """Majority CodeFile.subsystem_modularity_id among this directory's
    files, plus a purity fraction -- same "state the fraction, don't just
    pick a winner" discipline as I5's per-component recall/homogeneity
    metrics (see docs/external-validation-eslint.md's Round 3 correction,
    which is the direct reason this function exists: a directory's files
    can genuinely split across multiple dependency clusters, and coloring
    the whole box one color without saying so would repeat the exact
    overclaim that correction fixed in the Dependency Clusters tab).

    Files with no cluster assignment (None -- clustering never run, or
    genuinely unclustered) are EXCLUDED from the purity denominator, for
    the same reason None was excluded from I5's recall/homogeneity: a
    handful of files independently failing to cluster with anything is
    not evidence they'd agree with each other if they had. Returns
    (cluster_id, purity, unclustered_count) -- cluster_id/purity are both
    None if no member has any cluster assignment at all."""
    clustered = [f["subsystem_modularity_id"] for f in files if f.get("subsystem_modularity_id") is not None]
    unclustered_count = len(files) - len(clustered)
    if not clustered:
        return None, None, unclustered_count
    counts = Counter(clustered)
    majority_id, majority_count = counts.most_common(1)[0]
    return majority_id, majority_count / len(clustered), unclustered_count


def _kind_of(files: list) -> str:
    """Each file dict carries `is_entry_point`/`seed_eligible` straight
    from CodeFile (Phase H1.5: persisted by whichever rank run last ran
    entry detection, not recomputed live here -- see repos.py's get_graph
    docstring for why a live call was removed from this read path). The
    seed-eligible/prior-only split is E4's, introduced for PageRank
    seeding, reused here for a different purpose: a directory containing
    only prior-only entries (backend/scripts: standalone CLI utilities,
    each with its own __main__ guard) is executable but is emphatically
    not where a reader starts -- a materially different fact from
    backend/app containing main.py. Folding both into "entry" would
    visually equate four CLI scripts with the real application entry
    point; leaving prior-only entries generic "source" grey would erase
    the fact that they're executable tooling at all. "tooling" is that
    middle ground.

    Falls through to a migration/test/source majority vote only when the
    directory has no entries of either tier. `is_test_file` is the exact
    path-marker heuristic edge_weights.py already uses for edge-kind
    classification, not a new one -- prior_category has no "test" value.
    A file that is BOTH migration-categorized and test-path-shaped counts
    as migration only, so the three counts never double-count a file."""
    if any(f.get("is_entry_point") and f.get("seed_eligible") for f in files):
        return "entry"
    if any(f.get("is_entry_point") for f in files):
        return "tooling"

    migration_count = sum(1 for f in files if f["prior_category"] == "migration")
    test_count = sum(1 for f in files if f["prior_category"] != "migration" and is_test_file(f["path"]))
    source_count = len(files) - migration_count - test_count
    counts = {"migration": migration_count, "test": test_count, "source": source_count}
    return max(counts, key=lambda k: (counts[k], _KIND_PRIORITY[k]))


def aggregate_to_directories(
    nodes: list, edges: list,
    max_groups: int = DEFAULT_MAX_GROUPS, limit: Optional[int] = None,
) -> dict:
    """nodes: file-level node dicts, each with at least
    {id, path, prior_category, rank, is_entry_point, seed_eligible} (see
    _kind_of for the latter two). edges: file-level edge dicts, each
    {source, target, weight, ...} (source/target are file ids matching a
    node's "id"; extra keys are ignored -- aggregation only sums weight).

    Runs over the FULL node list the caller passes in. `limit` is applied
    HERE, after aggregation, capping directories -- never applied to
    `nodes` before this function ever sees them. Capping files first and
    aggregating second would compute a directory graph from whatever
    fraction of the repo survived the file cap: invisible at 159 files,
    silently wrong at 5,000 (a plausible-looking architecture map built
    from an eighth of the repo, with no indication anything was left out).
    language/path_prefix/min_score are the caller's concern -- user
    intent, applied to `nodes` before this function is ever called;
    `limit` is only a rendering cap and must never distort the aggregate
    itself.

    fan_in_dirs/fan_out_dirs (distinct-directory in/out degree) and
    import_count_in/import_count_out (summed cross-directory weight) are
    derived purely from the returned edge list, on purpose -- a raw sum of
    member files' own fan_in/fan_out would double-count intra-directory
    edges (a heavily self-coupled directory would report a large number
    matching nothing actually drawn); deriving from the edge list instead
    means these numbers can never disagree with what's on screen.

    Returns {"nodes", "edges", "group_rollups", "total_groups_before_limit",
    "truncated"}. Deterministic: nodes are sorted by (best member rank,
    path) before any limit-capping, never by dict iteration order."""
    groups: dict = defaultdict(list)
    for n in nodes:
        groups[dirname_of(n["path"])].append(n)
    groups = dict(groups)

    group_rollups = _roll_up_to_cap(groups, max_groups)

    group_of_file = {n["id"]: gpath for gpath, files in groups.items() for n in files}

    cross_agg: dict = defaultdict(lambda: {"weight": 0.0, "count": 0})
    internal_count: dict = defaultdict(int)
    for e in edges:
        gs, gt = group_of_file.get(e["source"]), group_of_file.get(e["target"])
        if gs is None or gt is None:
            continue  # an endpoint outside this filtered file set
        if gs == gt:
            internal_count[gs] += 1
            continue
        agg = cross_agg[(gs, gt)]
        agg["weight"] += e["weight"]
        agg["count"] += 1

    fan_out_dirs: dict = defaultdict(int)
    fan_in_dirs: dict = defaultdict(int)
    import_out: dict = defaultdict(float)
    import_in: dict = defaultdict(float)
    for (gs, gt), agg in cross_agg.items():
        fan_out_dirs[gs] += 1
        fan_in_dirs[gt] += 1
        import_out[gs] += agg["weight"]
        import_in[gt] += agg["weight"]

    dir_nodes = []
    for gpath, files in groups.items():
        ranks = [f["rank"] for f in files if f.get("rank") is not None]
        cluster_id, cluster_purity, cluster_unclustered_count = _cluster_of(files)
        dir_nodes.append({
            "id": gpath,
            "path": gpath,
            "short_label": gpath.rsplit("/", 1)[-1],
            "file_count": len(files),
            "kind": _kind_of(files),
            "region": region_of(gpath),
            "internal_edge_count": internal_count.get(gpath, 0),
            "fan_in_dirs": fan_in_dirs.get(gpath, 0),
            "fan_out_dirs": fan_out_dirs.get(gpath, 0),
            "import_count_in": import_in.get(gpath, 0.0),
            "import_count_out": import_out.get(gpath, 0.0),
            # Phase I2: dominant dependency-cluster id among this
            # directory's files, plus purity -- see _cluster_of's
            # docstring. cluster_id is None if no member has ANY cluster
            # assignment (clustering never run, or the directory is
            # entirely composed of unclustered files).
            "cluster_id": cluster_id,
            "cluster_purity": cluster_purity,
            "cluster_unclustered_count": cluster_unclustered_count,
            "_rank": min(ranks) if ranks else None,
        })

    dir_nodes.sort(key=lambda d: (d["_rank"] is None, d["_rank"] if d["_rank"] is not None else 0, d["path"]))
    total_groups_before_limit = len(dir_nodes)
    if limit is not None and len(dir_nodes) > limit:
        dir_nodes = dir_nodes[:limit]
    truncated = total_groups_before_limit > len(dir_nodes)
    for d in dir_nodes:
        del d["_rank"]

    kept_group_ids = {d["id"] for d in dir_nodes}
    dir_edges = [
        {"source": gs, "target": gt, "weight": agg["weight"], "count": agg["count"]}
        for (gs, gt), agg in cross_agg.items()
        if gs in kept_group_ids and gt in kept_group_ids
    ]

    return {
        "nodes": dir_nodes,
        "edges": dir_edges,
        "group_rollups": group_rollups,
        "total_groups_before_limit": total_groups_before_limit,
        "truncated": truncated,
    }
