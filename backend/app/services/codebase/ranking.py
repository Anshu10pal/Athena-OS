"""Phase C: rank files by combining always-available graph signals with
optional, degrading git-history signals. Zero LLM calls.

Graph signals (fan_in, fan_out, pagerank, is_entry_point) are always
available -- rebuilt from code_files/code_imports at rank time, not stored
as a separate graph blob. History signals (commit_count, distinct_authors,
days_since_last_change) require git.exe and a real working tree with
history; when either is unavailable, every ranked file is marked
reduced_confidence and the history-weighted portion of the composite score
is redistributed across the graph-only signals rather than silently scored
as zero.

Phase F3 adds a second scorer, weighted_personalized_pagerank /
rank_repo_weighted_pagerank, alongside this one -- selectable by name, never
replacing it. Phase F5 adds a third, rank_repo_rrf (reciprocal_rank_fusion),
fusing the legacy scorer's same six raw signals by rank instead of by tuned
weighted sum. See CodeFileRank.scorer, and app/services/codebase/comparison.py
for the cross-scorer comparison harness that motivates having three.

Phase E4 replaces is_entry_point/prior_category="entry" detection (used by
all three scorers) with real config/code-pattern detection -- see
app/services/codebase/entry_detection.py and _migrate_entry_priors below.
_write_back_entry_priors, the old fan_in==0-or-basename heuristic, is kept
(not deleted) as a dormant safety net: it only ever touches prior_source ==
"graph" rows, and after E4's migration runs once, no row is left
graph-sourced, so it has nothing left to act on.
"""
import logging
import posixpath
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import networkx as nx
import yaml
from sqlalchemy.orm import Session

from app.core.config import BACKEND_DIR, settings
from app.db.models import CodeFile, CodeFileRank, CodeImport, Repo, utcnow
from app.services.codebase import edge_weights, entry_detection, git_ops, node_priors, repo_lock
from app.services.codebase.ingest import _repo_root

logger = logging.getLogger("athena.codebase.ranking")

# Generous on purpose. With --no-renames a 22k-commit repo finishes in ~8s, so
# this is not a budget anyone should be near -- it exists to bound a
# pathological case, and exceeding it now degrades to "no history" rather than
# failing the run.
HISTORY_TIMEOUT_SECONDS = 600

ENTRY_POINT_BASENAMES = {
    "main.py", "__main__.py", "manage.py", "wsgi.py", "asgi.py", "cli.py", "app.py",
    "index.ts", "index.tsx", "index.js", "index.jsx",
    "main.ts", "main.tsx", "server.ts", "server.js",
}

GRAPH_KEYS = ("fan_in", "pagerank", "is_entry_point")
HISTORY_KEYS = ("commit_count", "distinct_authors", "recency")

DEFAULT_WEIGHTS = {
    "fan_in": 0.35, "pagerank": 0.30, "is_entry_point": 0.15,
    "commit_count": 0.10, "distinct_authors": 0.05, "recency": 0.05,
}

DEFAULT_WEIGHTED_PAGERANK_CONFIG = {"damping": 0.65}

DEFAULT_RRF_CONFIG = {
    "k": 60,
    "directions": {
        "fan_in": "desc", "pagerank": "desc", "is_entry_point": "desc",
        "commit_count": "desc", "distinct_authors": "desc", "days_since_last_change": "asc",
    },
}

DEFAULT_RESOLUTION_TRIPWIRE_CONFIG = {"collapse_relative_threshold": 0.5, "minimum_previous_rate_to_check": 0.05}


class ResolutionRateCollapseError(RuntimeError):
    """Phase E2.3 incident: a rank read once observed a Python resolution
    rate that had silently collapsed, and every graph signal downstream
    was wrong as a result -- confident, plausible, and undetected. Raised
    by _check_resolution_rate_tripwire when the current rate has dropped
    too far below this repo's high-water mark (the best rate ever recorded,
    not merely the last one -- see _check_resolution_rate_tripwire for why
    that distinction matters)."""


def _resolution_tripwire_config_path() -> Path:
    p = Path(settings.RESOLUTION_TRIPWIRE_CONFIG_PATH)
    return p if p.is_absolute() else BACKEND_DIR / p


def load_resolution_tripwire_config() -> dict:
    path = _resolution_tripwire_config_path()
    if not path.is_file():
        return dict(DEFAULT_RESOLUTION_TRIPWIRE_CONFIG)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {**DEFAULT_RESOLUTION_TRIPWIRE_CONFIG, **data}


def _python_resolution_rate(db: Session, repo: Repo) -> Optional[float]:
    """None if this repo has no Python CodeImport rows at all -- nothing to
    measure, not a collapse."""
    rows = (
        db.query(CodeImport.resolved)
        .join(CodeFile, CodeImport.from_file_id == CodeFile.id)
        .filter(CodeFile.repo_id == repo.id, CodeFile.language == "python")
        .all()
    )
    if not rows:
        return None
    resolved = sum(1 for (r,) in rows if r)
    return resolved / len(rows)


def _check_resolution_rate_tripwire(db: Session, repo: Repo) -> Optional[float]:
    """The general defense the Phase E2.3 incident argued for: every rank
    run compares the CURRENT Python resolution rate against the HIGH-WATER
    MARK recorded for this repo (Repo.python_resolution_high_water_mark) and
    refuses outright if it has collapsed, rather than silently scoring a
    graph that may be missing most of its edges. Both conditions must hold
    to trip: the high-water mark must itself have been meaningful
    (minimum_previous_rate_to_check -- a repo that's always had near-zero
    resolution shouldn't trip on its own noise), and the current rate must
    have dropped below collapse_relative_threshold of it.

    Phase F7 correction: this compares against the ALL-TIME HIGH, not the
    last observed rate. Comparing against last-observed let a second
    consecutive bad run re-baseline against an already-collapsed value and
    pass -- each step's relative drop looks fine measured against its own
    already-degraded predecessor (e.g. 0.68 -> 0.35 barely clears the 50%
    threshold and re-baselines there; 0.35 -> 0.18 then also barely clears
    it, even though 0.68 -> 0.18 overall is a collapse that should have
    tripped). The high-water mark only ever moves up on a call that doesn't
    trip -- via max(), never overwritten downward -- so a real, gradual
    erosion is measured against the true peak every time, not against
    whatever the previous call happened to leave behind.

    Updates repo.python_resolution_high_water_mark on the ORM object when it
    does NOT trip -- picked up by whichever caller commits next, same
    pattern as _migrate_entry_priors's CodeFile mutations elsewhere in this
    module."""
    config = load_resolution_tripwire_config()
    current = _python_resolution_rate(db, repo)
    high_water_mark = repo.python_resolution_high_water_mark

    if (
        current is not None and high_water_mark is not None
        and high_water_mark >= config["minimum_previous_rate_to_check"]
        and current < high_water_mark * config["collapse_relative_threshold"]
    ):
        raise ResolutionRateCollapseError(
            f"Repo {repo.id} ({repo.host}/{repo.owner}/{repo.name}): Python import resolution rate "
            f"collapsed from a high-water mark of {high_water_mark:.1%} to {current:.1%} -- refusing to "
            "score a graph that may be missing most of its edges. If this repo genuinely lost most of "
            "its Python imports (e.g. a large deletion), clear repo.python_resolution_high_water_mark to "
            "accept the new baseline; otherwise this points at a real bug."
        )

    if current is not None:
        repo.python_resolution_high_water_mark = max(high_water_mark or 0.0, current)
    return current


def _weights_path() -> Path:
    p = Path(settings.RANKING_WEIGHTS_PATH)
    return p if p.is_absolute() else BACKEND_DIR / p


def _load_weights() -> dict:
    path = _weights_path()
    if not path.is_file():
        return dict(DEFAULT_WEIGHTS)  # a missing config file must not crash ranking
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    weights = data.get("weights") or {}
    return {**DEFAULT_WEIGHTS, **weights}


def _weighted_pagerank_config_path() -> Path:
    p = Path(settings.WEIGHTED_PAGERANK_CONFIG_PATH)
    return p if p.is_absolute() else BACKEND_DIR / p


def load_weighted_pagerank_config() -> dict:
    path = _weighted_pagerank_config_path()
    if not path.is_file():
        return dict(DEFAULT_WEIGHTED_PAGERANK_CONFIG)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {**DEFAULT_WEIGHTED_PAGERANK_CONFIG, **data}


def _rrf_config_path() -> Path:
    p = Path(settings.RRF_CONFIG_PATH)
    return p if p.is_absolute() else BACKEND_DIR / p


def load_rrf_config() -> dict:
    path = _rrf_config_path()
    if not path.is_file():
        return dict(DEFAULT_RRF_CONFIG)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    directions = {**DEFAULT_RRF_CONFIG["directions"], **(data.get("directions") or {})}
    return {"k": data.get("k", DEFAULT_RRF_CONFIG["k"]), "directions": directions}


def _minmax_normalize(values: dict) -> dict:
    if not values:
        return {}
    lo, hi = min(values.values()), max(values.values())
    if hi == lo:
        return {k: 0.5 for k in values}
    return {k: (v - lo) / (hi - lo) for k, v in values.items()}


def _pagerank(graph: nx.DiGraph, damping: float = 0.85, max_iter: int = 100, tol: float = 1e-8) -> dict:
    """Plain power-iteration PageRank, not nx.pagerank() -- networkx 3.4's
    pagerank hard-imports scipy with no pure-Python fallback, and this project
    deliberately avoids compiled dependencies (see requirements.txt). Dangling
    nodes (no outgoing edges) redistribute their rank mass uniformly, matching
    networkx's own default behavior.

    This is the LEGACY scorer's PageRank -- unweighted, uniform teleport. Left
    untouched by Phase F3 on purpose: it's provably working for what it does
    (see weighted_personalized_pagerank below for the seeded, edge-weighted
    version added alongside it, not in place of it)."""
    nodes = list(graph.nodes())
    n = len(nodes)
    if n == 0:
        return {}
    rank = {node: 1.0 / n for node in nodes}
    out_degree = {node: graph.out_degree(node) for node in nodes}

    for _ in range(max_iter):
        dangling_mass = sum(rank[node] for node in nodes if out_degree[node] == 0)
        new_rank = {}
        for node in nodes:
            incoming = sum(rank[pred] / out_degree[pred] for pred in graph.predecessors(node))
            new_rank[node] = (1 - damping) / n + damping * (incoming + dangling_mass / n)
        diff = sum(abs(new_rank[node] - rank[node]) for node in nodes)
        rank = new_rank
        if diff < tol:
            break
    return rank


def weighted_personalized_pagerank(
    graph: nx.DiGraph, edge_weight: dict, seed: dict,
    damping: float = 0.65, max_iter: int = 100, tol: float = 1e-8,
) -> dict:
    """Phase F3.

        W(u)  = sum_{u->v} w(u,v)
        PR(f) = (1-d)*s(f) + d*[ sum_{u->f} PR(u)*w(u,f)/W(u) + D*s(f) ]

    where D is the total PageRank mass currently held by dangling nodes
    (no outgoing edges). `edge_weight` maps (from_id, to_id) -> weight; a
    missing entry is treated as weight 0 (no contribution).

    Both the teleport term (1-d)*s(f) AND the dangling redistribution D*s(f)
    route through the SAME seed vector s -- not uniformly. This is the
    specific property that makes a node unreachable from the seed converge
    to exactly 0 rather than picking up a small nonzero share from uniform
    redistribution (which is what produced several unrelated files sharing
    an identical near-zero score before this phase -- see
    test_weighted_pagerank_dangling_and_teleport_both_route_through_seed).

    seed need not already be normalized; it's normalized here. An all-zero
    or empty seed falls back to uniform (documented, not silently wrong --
    callers should treat that as "no valid seed" and decide what to do)."""
    nodes = list(graph.nodes())
    n = len(nodes)
    if n == 0:
        return {}

    seed_total = sum(seed.get(node, 0.0) for node in nodes)
    if seed_total > 0:
        s = {node: seed.get(node, 0.0) / seed_total for node in nodes}
    else:
        s = {node: 1.0 / n for node in nodes}

    out_weight_sum = {u: sum(edge_weight.get((u, v), 0.0) for v in graph.successors(u)) for u in nodes}

    rank = dict(s)
    for _ in range(max_iter):
        dangling_mass = sum(rank[u] for u in nodes if out_weight_sum[u] == 0)
        new_rank = {}
        for f in nodes:
            incoming = 0.0
            for u in graph.predecessors(f):
                w_u = out_weight_sum[u]
                if w_u > 0:
                    incoming += rank[u] * edge_weight.get((u, f), 0.0) / w_u
            new_rank[f] = (1 - damping) * s[f] + damping * (incoming + dangling_mass * s[f])
        diff = sum(abs(new_rank[node] - rank[node]) for node in nodes)
        rank = new_rank
        if diff < tol:
            break
    return rank


def _fractional_rank(values: dict, higher_is_better: bool = True) -> dict:
    """1-indexed rank, best value -> rank 1. Ties share the AVERAGE of the
    ordinal positions they span (e.g. a two-way tie for best -> both get
    rank 1.5) rather than an arbitrary tiebreak: many files on a real repo
    share fan_in=0 or is_entry_point=False, and breaking that tie by e.g.
    path would invent a signal this data doesn't actually carry -- every
    file in a tied group must get the exact same rank, and therefore the
    exact same RRF term."""
    if not values:
        return {}
    sign = -1 if higher_is_better else 1
    ordered = sorted(values.items(), key=lambda kv: sign * kv[1])
    ranks: dict = {}
    n = len(ordered)
    i = 0
    while i < n:
        j = i
        while j + 1 < n and ordered[j + 1][1] == ordered[i][1]:
            j += 1
        avg_rank = (i + 1 + j + 1) / 2  # average of 1-indexed positions i+1..j+1
        for idx in range(i, j + 1):
            ranks[ordered[idx][0]] = avg_rank
        i = j + 1
    return ranks


def reciprocal_rank_fusion(signal_values: dict, directions: dict, k: float) -> dict:
    """Phase F5. score(f) = sum_signal 1/(k + rank_signal(f)). Parameter-free
    in the sense that mixes in no per-signal weight: a file's contribution
    from each signal depends only on where it stands in that signal's own
    order, never on how "important" that signal is judged to be -- unlike
    the legacy scorer's tunable weighted sum.

    signal_values: {signal_name: {file_id: raw_value}}. A signal missing for
    a given file (e.g. commit_count when git history is unavailable, so
    that signal is omitted from signal_values entirely) simply contributes
    no term for that file -- the same graceful degradation the legacy
    scorer has, expressed as "no term" rather than a fabricated worst-case
    rank.

    directions: {signal_name: "desc"|"asc"}, resolved from config
    (load_rrf_config) -- stated explicitly per signal rather than flipped
    implicitly in code, so an inverted signal (days_since_last_change: a
    SMALLER value is better) is visible in config, not buried in a
    transform that would make RRF look like it's simply underperforming."""
    fused: dict = {}
    for name, values in signal_values.items():
        higher_is_better = directions.get(name, "desc") != "asc"
        ranks = _fractional_rank(values, higher_is_better=higher_is_better)
        for fid, rank in ranks.items():
            fused[fid] = fused.get(fid, 0.0) + 1.0 / (k + rank)
    return fused


# ---------------- shared graph building ----------------


def _build_graph(db: Session, repo: Repo, file_by_id: dict) -> nx.DiGraph:
    graph = nx.DiGraph()
    graph.add_nodes_from(file_by_id.keys())
    edges = (
        db.query(CodeImport.from_file_id, CodeImport.to_file_id)
        .filter(CodeImport.repo_id == repo.id, CodeImport.to_file_id.isnot(None))
        .distinct()
        .all()
    )
    for from_id, to_id in edges:
        if from_id in file_by_id and to_id in file_by_id:
            graph.add_edge(from_id, to_id)
    return graph


def _build_weighted_graph(db: Session, repo: Repo, file_by_id: dict) -> tuple:
    """Same edge set as _build_graph, plus edge_weight: (from_id, to_id) ->
    max weight among all CodeImport rows for that file pair. Max, not sum:
    summing would let many trivially-weighted imports between two files
    outweigh a single `inherits` edge, and would make a file pair's edge
    weight shift if one import statement were later split into several
    named imports -- a refactor with no real change in coupling. Max is
    stable under that refactor; sum isn't."""
    weights_config = edge_weights.load_edge_weights()
    rows = (
        db.query(CodeImport.from_file_id, CodeImport.to_file_id, CodeImport.kind)
        .filter(CodeImport.repo_id == repo.id, CodeImport.to_file_id.isnot(None))
        .all()
    )
    graph = nx.DiGraph()
    graph.add_nodes_from(file_by_id.keys())
    edge_weight: dict = {}
    for from_id, to_id, kind in rows:
        if from_id not in file_by_id or to_id not in file_by_id:
            continue
        w = edge_weights.resolve_weight(kind, weights_config)
        key = (from_id, to_id)
        if key not in edge_weight or w > edge_weight[key]:
            edge_weight[key] = w
        graph.add_edge(from_id, to_id)
    return graph, edge_weight


def _write_back_entry_priors(file_by_id: dict, fan_in: dict) -> list:
    """Phase F2's original write-back -- the fan_in==0-or-basename
    heuristic. SUPERSEDED by Phase E4's _migrate_entry_priors below (which
    is what every scorer actually calls now) and kept here UNCALLED, not
    deleted: a dormant safety net that would only ever matter again if some
    future code path started writing prior_source == "graph" rows, since
    that's the only state this function still acts on and E4's migration
    leaves none. Do not wire this back in -- "absence of fan-in" was never
    real evidence of an entry point, which is exactly the bug E4 fixes."""
    category_flips = []
    for fid, f in file_by_id.items():
        if f.prior_source != "graph":
            continue
        is_entry_now = bool(fan_in[fid] == 0 or Path(f.path).name in ENTRY_POINT_BASENAMES)
        new_category = "entry" if is_entry_now else "source"
        if f.prior_category != new_category:
            category_flips.append({"path": f.path, "old_category": f.prior_category, "new_category": new_category})
            f.prior_category = new_category
    return category_flips


def _detect_entries(repo: Repo, file_by_id: dict) -> dict:
    """Thin wrapper around entry_detection.detect_entry_points -- resolves
    repo.local_path/source_root the same way ingest.py does, so entry
    candidates found on disk resolve against the exact same path convention
    CodeFile.path already uses. Passes this repo's own seed_exclude_paths
    override through -- see Repo.seed_exclude_paths.

    config_search_root is always the true repo.local_path, NOT
    _repo_root(repo) -- authoritative config (package.json, Dockerfile,
    pyproject.toml, ...) lives at the real repository root even for a repo
    registered with a source_root that scopes ingestion to a subdirectory.
    A no-op whenever source_root is unset (the two roots coincide), which
    is every repo this project had registered before this was found."""
    return entry_detection.detect_entry_points(
        _repo_root(repo), list(file_by_id.values()), seed_exclude_paths=repo.seed_exclude_paths,
        config_search_root=Path(repo.local_path),
    )


def _migrate_entry_priors(file_by_id: dict, entry_info_by_id: dict, fan_in: dict) -> dict:
    """Phase E4: supersedes _write_back_entry_priors as the thing that
    decides prior_category == "entry". For every row still prior_source ==
    "graph" (this file has never been through detection before): a detected
    entry gets prior_category="entry", prior_source="structural";
    everything else keeps its current category but ALSO flips to
    prior_source="structural" -- once every row has been through this once,
    nothing is left graph-sourced anywhere, and _write_back_entry_priors
    (which only touches "graph" rows) goes inert on its own, without
    needing to be deleted or specially guarded against running twice.

    Phase G1 correction: for every OTHER file currently categorized "entry"
    or "source", re-run the same live check on every rank run, not just
    once. prior_source == "graph" was built as a guard against the OLD
    graph-based write-back (_write_back_entry_priors) clobbering E4's real
    detection -- it was never meant to freeze detection's OWN result
    forever after a file's first rank run. But `continue`ing unconditionally
    for every non-"graph" row did exactly that: a file that gains a
    __main__ guard after its first rank never earns the entry prior; a real
    entry point later stripped of its guard keeps a 1.4 multiplier forever;
    neither is surfaced anywhere. Entry detection (config files + code
    patterns, entry_detection.py) is deterministic, so re-running it every
    time is safe. "entry"/"source" are the only two categories this live
    check ever touches -- "config"/"migration"/"generated"/"barrel" are
    structural/pattern facts about a file's own content or path
    (node_priors.classify_file_local_category, decided once at parse time),
    never graph- or detection-dependent, and re-checking them here would be
    a category error, not a staleness fix. Reported through the same
    category_flips list either way -- a flip is a flip regardless of
    whether it happened on a file's first migration or a later live check.

    entry_info_by_id: entry_detection.detect_entry_points's return shape,
    {file_id: {"method": ..., "seed_eligible": ...}}. The prior applies to
    EVERY detected entry regardless of tier -- seed_eligible only affects
    which paths a caller (rank_repo_weighted_pagerank) should seed from, via
    the seed_eligible_entries/prior_only_entries lists below. Being an
    executable entry and being where a newcomer starts reading are
    different properties; only the second should inject PageRank teleport
    mass.

    contradictions: a DETECTED entry whose own fan_in exceeds the
    configured threshold (default 0). Nothing imports a real entry point
    except a build tool, so this almost always means the wrong file was
    flagged -- e.g. a file one hop downstream of the real entry, imported
    once by it. Reported, not auto-corrected: detection came from a real
    authoritative source (or a real code pattern) and must not be silently
    overridden by a graph signal -- that inversion (trusting the graph over
    the detected fact) is exactly the bug this phase replaces. Checked on
    every detected entry on every run now, not just a file's first
    migration -- the same staleness bug applied here too, since this check
    used to live inside the same now-removed early `continue`."""
    threshold = entry_detection.load_entry_detection_config()["fan_in_contradiction_threshold"]
    category_flips = []
    prior_source_migrations = []
    contradictions = []
    for fid, f in file_by_id.items():
        info = entry_info_by_id.get(fid)

        if f.prior_source == "graph":
            new_category = "entry" if info is not None else f.prior_category
            if f.prior_category != new_category:
                category_flips.append({"path": f.path, "old_category": f.prior_category, "new_category": new_category})
                f.prior_category = new_category
            prior_source_migrations.append({"path": f.path, "old_source": "graph", "new_source": "structural"})
            f.prior_source = "structural"
        elif f.prior_category in ("entry", "source"):
            new_category = "entry" if info is not None else "source"
            if f.prior_category != new_category:
                category_flips.append({"path": f.path, "old_category": f.prior_category, "new_category": new_category})
                f.prior_category = new_category
        # else: config/migration/generated/barrel -- never touched here.

        if info is not None and fan_in[fid] > threshold:
            contradictions.append({"path": f.path, "fan_in": fan_in[fid], "detection_method": info["method"]})
    entry_detection_report = {file_by_id[fid].path: info["method"] for fid, info in entry_info_by_id.items()}
    seed_eligible_entries = sorted(file_by_id[fid].path for fid, info in entry_info_by_id.items() if info["seed_eligible"])
    prior_only_entries = sorted(file_by_id[fid].path for fid, info in entry_info_by_id.items() if not info["seed_eligible"])
    return {
        "category_flips": category_flips,
        "prior_source_migrations": prior_source_migrations,
        "contradictions": contradictions,
        "entry_detection": entry_detection_report,
        "seed_eligible_entries": seed_eligible_entries,
        "prior_only_entries": prior_only_entries,
    }


# ---------------- git history ----------------


def _git_root_offset(local_path: str) -> Optional[str]:
    """local_path's path relative to the git top-level dir it lives in, POSIX
    form, "" if local_path IS the top-level. None if not inside a working
    tree at all -- e.g. a `local` repo with no .git."""
    result = git_ops.run_git(["rev-parse", "--show-toplevel"], cwd=local_path)
    if result.returncode != 0:
        return None
    toplevel = Path(result.stdout.strip()).resolve()
    local = Path(local_path).resolve()
    try:
        rel = local.relative_to(toplevel)
    except ValueError:
        return None
    rel_str = rel.as_posix()
    return "" if rel_str == "." else rel_str


def _collect_git_history(repo: Repo) -> Optional[dict]:
    """None means the caller must mark reduced_confidence -- either git.exe
    isn't available or `git log` produced nothing usable. One `git log`
    call for the whole repo (not one per file), scoped to repo.local_path's
    subtree when it's nested inside a larger working tree, with the git
    top-level offset stripped from every reported path so they match
    CodeFile.path (verified against this exact scenario: backend/ here is a
    subdirectory of the actual git root, not the root itself).

    ## Why `--name-only --no-renames` and not `--numstat`

    Measured on apache/superset (22,119 commits, 6,516 files), cloned the way
    this project clones -- `--filter=blob:none`:

        git log                                    2.3 s
        git log --numstat                       ~427 s  (extrapolated; timed out)
        git log --name-only  (renames on)       >600 s  (killed)
        git log --name-only --no-renames         8.45 s

    The decisive flag is `--no-renames`, and the mechanism is not "a heuristic
    we skipped". Git detects a rename by comparing file CONTENTS -- that is how
    it distinguishes a rename from a delete plus an add. On a blob-filtered
    clone the blobs are not local, so every rename check becomes a lazy fetch
    from the remote. The command was not computing slowly; it was
    re-downloading the repository one object at a time over the network.
    Thousands of unintended round trips, disguised as CPU cost.

    This is our own clone optimisation colliding with our own history pass:
    `--filter=blob:none` (git_ops._clone_git_exe) makes cloning fast and makes
    any diff-bearing `git log` pathological. The two decisions were made in
    different modules and never met.

    `--numstat` was also asking for more than we use -- the added/deleted
    columns were parsed and discarded on the very next line. `--name-only`
    returns exactly what is consumed.

    ## Known limitation, accepted deliberately

    With rename detection off, A renamed to B appears as A deleted at time T
    and B created at time T. Churn on A stops at the rename; churn on B starts
    fresh, and B's commit_count no longer includes the work done under its old
    name. Negligible on most repos; it will underweight files in a repo that
    has just been through a large rename-heavy refactor. Accepted because the
    alternative is that large repos cannot be ranked at all -- but it is a real
    cost, not a free win, and belongs in any reading of churn numbers.

    (The previous docstring claimed rename detection meant commits before a
    rename stayed on the old path. That was already the behaviour and still is;
    what changes is that the OLD path now also collects the deletion commit.
    Old paths have no CodeFile row, so they are dropped when history is joined
    back to files.)
    """
    if not git_ops.GIT_AVAILABLE:
        return None
    offset = _git_root_offset(repo.local_path)
    if offset is None:
        return None
    prefix = posixpath.normpath(posixpath.join(offset, repo.source_root or "")) if (offset or repo.source_root) else ""
    if prefix == ".":
        prefix = ""

    # "." here means "everything under cwd" -- cwd is already repo.local_path,
    # so this is root-relative-offset-agnostic. `prefix` is only used below to
    # strip git's still-root-relative *output* paths back down to
    # local_path-relative ones; it must never be reused as the pathspec
    # argument itself (that would double the offset when local_path is a
    # subdirectory of the git root -- caught by a real nested-repo test).
    # A timeout here must degrade to "no history", not kill the ranking run.
    # This function's whole contract is that None means reduced confidence --
    # the graceful path already existed and an uncaught TimeoutExpired walked
    # straight past it, so one slow git call cost the repo its entire ranking:
    # no fan-in, no fan-out, no reading list, and an Architecture axis that had
    # to be marked N/A for want of inputs a different pass had already
    # computed. Cascade suppression (see the module docstring): a coarse
    # upstream failure discarding fine-grained downstream signal.
    #
    # --no-renames makes the known-large case fast; this makes every OTHER
    # large case survivable. Both are needed and this is the general one.
    #
    # `-c core.quotepath=false` (K8): git's default escapes every byte outside
    # ASCII as octal inside double quotes, so `git log --name-only` reports
    #
    #     "superset/\346\226\207\346\233\270.py"
    #
    # while CodeFile.path holds the real UTF-8 string. Those lines match
    # nothing, and the file is not reported as missing -- it simply gets no
    # churn, no author count and no last-changed date, and scores as though it
    # had never been touched. Silent, and worse than an error.
    #
    # Measured on a fixture with CJK, accented-Latin and Cyrillic filenames:
    # 1 of 4 paths matched with the default, 4 of 4 with the flag. `-c` is used
    # rather than a repo config write because this must not modify a user's
    # repository to read from it.
    try:
        result = git_ops.run_git(
            ["-c", "core.quotepath=false",
             "log", "--format=@@%an|%aI", "--name-only", "--no-renames", "--", "."],
            cwd=repo.local_path, timeout=HISTORY_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        logger.warning(
            "git history collection exceeded %ss for repo %s -- ranking continues "
            "without history signals (reduced confidence).",
            HISTORY_TIMEOUT_SECONDS, repo.id,
        )
        return None
    except OSError as e:
        logger.warning("git history collection failed for repo %s: %s", repo.id, e)
        return None
    if result.returncode != 0 or not (result.stdout or "").strip():
        return None

    history: dict[str, dict] = {}
    strip_prefix = f"{prefix}/" if prefix else ""
    current_author, current_date = None, None
    for raw_line in result.stdout.splitlines():
        line = raw_line.rstrip("\r")
        if line.startswith("@@"):
            current_author, _, current_date = line[2:].partition("|")
            continue
        if not line.strip():
            continue
        # `--name-only` emits one bare path per line -- no leading add/delete
        # columns to strip. A tab can legally appear inside a path, so the line
        # is taken whole rather than split.
        path = line
        if strip_prefix:
            if not path.startswith(strip_prefix):
                continue
            path = path[len(strip_prefix):]
        entry = history.setdefault(path, {"commit_count": 0, "authors": set(), "last_date": current_date})
        entry["commit_count"] += 1
        if current_author:
            entry["authors"].add(current_author)
    return history


# ---------------- ranking: legacy scorer ----------------


def legacy_signal_snapshot(
    db: Session, repo: Repo, on_progress: Optional[Callable[[str, int, int, str], None]] = None
) -> dict:
    """Everything the legacy scorer needs, before its six signals are
    combined into one number. Shared by rank_repo (real scoring, writes to
    the DB) and Phase F5's comparison harness (pure, read-only leave-one-out
    ablation) so ablating a signal's weight can never drift from what
    rank_repo actually computes -- both call composite_score() below with
    the same norm_by_key this function returns, just different weights."""
    if on_progress is None:
        on_progress = lambda *a: None  # noqa: E731

    _check_resolution_rate_tripwire(db, repo)

    files = db.query(CodeFile).filter(CodeFile.repo_id == repo.id).all()
    if not files:
        raise ValueError("Repo has no ingested files to rank -- run ingest first.")
    file_by_id = {f.id: f for f in files}

    on_progress("ranking_graph", 0, 0, "Building import graph")
    graph = _build_graph(db, repo, file_by_id)

    fan_in = {fid: graph.in_degree(fid) for fid in file_by_id}
    fan_out = {fid: graph.out_degree(fid) for fid in file_by_id}
    pagerank = _pagerank(graph) if graph.number_of_edges() > 0 else {fid: 0.0 for fid in file_by_id}

    entry_info_by_id = _detect_entries(repo, file_by_id)
    is_entry = {fid: (fid in entry_info_by_id) for fid in file_by_id}
    seed_eligible = {fid: entry_info_by_id[fid]["seed_eligible"] if fid in entry_info_by_id else False for fid in file_by_id}
    migration = _migrate_entry_priors(file_by_id, entry_info_by_id, fan_in)
    category_flips = migration["category_flips"]

    on_progress("ranking_history", 0, 0, "Collecting git history")
    history = _collect_git_history(repo)
    now = datetime.now(timezone.utc)
    commit_count, distinct_authors, days_since_change = {}, {}, {}
    for fid, f in file_by_id.items():
        if history is None:
            # git log itself failed/unavailable -- genuinely unknown, not zero.
            commit_count[fid] = None
            distinct_authors[fid] = None
            days_since_change[fid] = None
            continue
        h = history.get(f.path)
        if h and h["last_date"]:
            commit_count[fid] = h["commit_count"]
            distinct_authors[fid] = len(h["authors"])
            try:
                last_dt = datetime.fromisoformat(h["last_date"])
                days_since_change[fid] = (now - last_dt.astimezone(timezone.utc)).days
            except ValueError:
                days_since_change[fid] = None
        else:
            # git log succeeded for this repo, but this specific file has no
            # commit touching it yet (e.g. created and not yet committed) --
            # a known fact (zero), not missing data.
            commit_count[fid] = 0
            distinct_authors[fid] = 0
            days_since_change[fid] = None

    have_history = history is not None

    weights = _load_weights()
    norm_fan_in = _minmax_normalize(fan_in)
    norm_pagerank = _minmax_normalize(pagerank)

    if have_history:
        active_weights = dict(weights)
        norm_commits = _minmax_normalize({k: v for k, v in commit_count.items() if v is not None})
        norm_authors = _minmax_normalize({k: v for k, v in distinct_authors.items() if v is not None})
        norm_days = _minmax_normalize({k: v for k, v in days_since_change.items() if v is not None})
        norm_recency = {k: 1 - v for k, v in norm_days.items()}
    else:
        history_weight = sum(weights.get(k, 0) for k in HISTORY_KEYS)
        graph_weight = sum(weights.get(k, 0) for k in GRAPH_KEYS) or 1.0
        active_weights = {k: weights.get(k, 0) * (1 + history_weight / graph_weight) for k in GRAPH_KEYS}
        norm_commits, norm_authors, norm_recency = {}, {}, {}

    norm_by_key = {
        "fan_in": norm_fan_in,
        "pagerank": norm_pagerank,
        "is_entry_point": {fid: (1.0 if is_entry[fid] else 0.0) for fid in file_by_id},
        "commit_count": norm_commits,
        "distinct_authors": norm_authors,
        "recency": norm_recency,
    }

    return {
        "file_by_id": file_by_id,
        "fan_in": fan_in, "fan_out": fan_out, "pagerank": pagerank, "is_entry": is_entry,
        "seed_eligible": seed_eligible,
        "commit_count": commit_count, "distinct_authors": distinct_authors, "days_since_change": days_since_change,
        "have_history": have_history,
        "active_weights": active_weights, "norm_by_key": norm_by_key,
        "category_flips": category_flips,
        "entry_info_by_id": entry_info_by_id,
        "prior_source_migrations": migration["prior_source_migrations"],
        "contradictions": migration["contradictions"],
        "seed_eligible_entries": migration["seed_eligible_entries"],
        "prior_only_entries": migration["prior_only_entries"],
        "entry_detection": migration["entry_detection"],
    }


def _write_file_level_signals(
    file_by_id: dict, fan_in: dict, fan_out: dict, is_entry: dict, seed_eligible: dict,
    commit_count: Optional[dict] = None, distinct_authors: Optional[dict] = None,
    days_since_change: Optional[dict] = None,
) -> None:
    """Phase G1: fan_in/fan_out/is_entry_point are identical regardless of
    which scorer computed them -- same resolved import graph (legacy/rrf's
    _build_graph and weighted_pagerank's _build_weighted_graph share the
    same underlying edge set), same entry_detection call -- so it's safe
    for whichever scorer runs to write them onto CodeFile. History signals
    are passed only by callers that compute them (legacy, rrf); left
    omitted (None) by weighted_pagerank, which has no history term at all
    -- passing None here must never overwrite what a previous legacy/rrf
    run already established, so each history arg is applied only when not
    None, never unconditionally.

    seed_eligible: Phase H1.5, same "identical regardless of scorer"
    reasoning as is_entry_point -- required (not Optional), unlike the
    history args, because every caller already has it in hand from the
    same entry_info_by_id that produced is_entry."""
    for fid, f in file_by_id.items():
        f.fan_in = fan_in[fid]
        f.fan_out = fan_out[fid]
        f.is_entry_point = is_entry[fid]
        f.seed_eligible = seed_eligible[fid]
        if commit_count is not None:
            f.commit_count = commit_count[fid]
        if distinct_authors is not None:
            f.distinct_authors = distinct_authors[fid]
        if days_since_change is not None:
            f.days_since_last_change = days_since_change[fid]


def composite_score(file_ids, norm_by_key: dict, weights: dict) -> dict:
    """score(f) = sum_k weights[k] * norm_by_key[k][f]. The one place the
    legacy scorer's weighted-sum combination happens -- rank_repo calls this
    to score for real; Phase F5's leave-one-out ablation calls it again with
    one key's weight zeroed (no renormalization -- see comparison.py for
    why that's correct, not an oversight), so both are provably the same
    formula, just different weights."""
    return {
        fid: sum(weights.get(k, 0) * norm_by_key[k].get(fid, 0) for k in norm_by_key)
        for fid in file_ids
    }


def rank_repo(
    db: Session, repo: Repo, on_progress: Optional[Callable[[str, int, int, str], None]] = None
) -> dict:
    """Holds this repo's advisory lock (repo_lock.py) for the whole call --
    a rank read must never land inside an in-flight ingest's two-stage
    resolution window for the same repo."""
    with repo_lock.repo_lock(repo.id, "rank"):
        return _rank_repo_locked(db, repo, on_progress)


def _rank_repo_locked(
    db: Session, repo: Repo, on_progress: Optional[Callable[[str, int, int, str], None]]
) -> dict:
    if on_progress is None:
        on_progress = lambda *a: None  # noqa: E731

    snapshot = legacy_signal_snapshot(db, repo, on_progress=on_progress)
    file_by_id = snapshot["file_by_id"]
    fan_in, fan_out, pagerank, is_entry = snapshot["fan_in"], snapshot["fan_out"], snapshot["pagerank"], snapshot["is_entry"]
    seed_eligible = snapshot["seed_eligible"]
    commit_count, distinct_authors, days_since_change = (
        snapshot["commit_count"], snapshot["distinct_authors"], snapshot["days_since_change"]
    )
    reduced_confidence = not snapshot["have_history"]
    category_flips = snapshot["category_flips"]

    on_progress("ranking_scoring", 0, len(file_by_id), "Scoring files")
    scores = composite_score(file_by_id.keys(), snapshot["norm_by_key"], snapshot["active_weights"])
    results = []
    for fid, f in file_by_id.items():
        results.append({
            "file_id": fid, "path": f.path, "score": scores[fid],
            "fan_in": fan_in[fid], "fan_out": fan_out[fid], "pagerank": pagerank[fid],
            "is_entry_point": is_entry[fid],
            "commit_count": commit_count[fid], "distinct_authors": distinct_authors[fid],
            "days_since_last_change": days_since_change[fid],
            "reduced_confidence": reduced_confidence,
        })
    results.sort(key=lambda r: r["score"], reverse=True)

    _write_file_level_signals(
        file_by_id, fan_in, fan_out, is_entry, seed_eligible, commit_count, distinct_authors, days_since_change,
    )
    repo.reduced_confidence = reduced_confidence

    db.query(CodeFileRank).filter(CodeFileRank.repo_id == repo.id, CodeFileRank.scorer == "legacy").delete()
    for i, r in enumerate(results, start=1):
        db.add(CodeFileRank(
            repo_id=repo.id, file_id=r["file_id"], scorer="legacy", score=r["score"],
            rank=i, pagerank=r["pagerank"], computed_at=utcnow(),
        ))
    db.commit()

    on_progress("ranking_done", len(file_by_id), len(file_by_id), "Ranking complete")
    return {
        "reduced_confidence": reduced_confidence, "files": results, "category_flips": category_flips,
        "entry_detection": snapshot["entry_detection"],
        "prior_source_migrations": snapshot["prior_source_migrations"],
        "contradictions": snapshot["contradictions"],
        "seed_eligible_entries": snapshot["seed_eligible_entries"],
        "prior_only_entries": snapshot["prior_only_entries"],
    }


# ---------------- ranking: Phase F3 weighted-pagerank scorer ----------------


def rank_repo_weighted_pagerank(
    db: Session, repo: Repo, seed_paths: Optional[list] = None,
    damping: Optional[float] = None, on_progress: Optional[Callable[[str, int, int, str], None]] = None,
) -> dict:
    """score(f) = PR(f) * prior(f). No history signals -- the formula has no
    term for them (unlike the legacy scorer, which folds them into its
    weighted sum); commit_count/distinct_authors/days_since_last_change stay
    null on this scorer's CodeFileRank rows, not a gap.

    Phase E4: seed_paths is now optional. When omitted, the seed is
    auto-derived from entry_detection's detected entry points (real
    config/code-pattern detection, no longer the untrustworthy graph-based
    heuristic Phase F3 deliberately avoided auto-seeding from). An explicit
    seed_paths still overrides detection entirely, for testing or
    comparison. If detection returns nothing AND no explicit seed_paths was
    given, this raises rather than silently falling back to anything --
    an empty seed vector makes every node converge to exactly 0 (see
    weighted_personalized_pagerank's docstring), producing a ranking of
    pure ties that looks like a valid result but means nothing. The
    resolved seed_paths (whichever source) is always returned in the
    result, alongside seed_auto_derived, so "which files was this seeded
    from" never requires re-running anything to answer.

    Holds this repo's advisory lock (repo_lock.py) for the whole call --
    see rank_repo's docstring for why."""
    with repo_lock.repo_lock(repo.id, "rank"):
        return _rank_repo_weighted_pagerank_locked(db, repo, seed_paths, damping, on_progress)


def _rank_repo_weighted_pagerank_locked(
    db: Session, repo: Repo, seed_paths: Optional[list],
    damping: Optional[float], on_progress: Optional[Callable[[str, int, int, str], None]],
) -> dict:
    if on_progress is None:
        on_progress = lambda *a: None  # noqa: E731

    _check_resolution_rate_tripwire(db, repo)

    files = db.query(CodeFile).filter(CodeFile.repo_id == repo.id).all()
    if not files:
        raise ValueError("Repo has no ingested files to rank -- run ingest first.")
    file_by_id = {f.id: f for f in files}
    path_to_id = {f.path: f.id for f in files}

    on_progress("ranking_graph", 0, 0, "Building weighted import graph")
    graph, edge_weight = _build_weighted_graph(db, repo, file_by_id)
    fan_in = {fid: graph.in_degree(fid) for fid in file_by_id}
    fan_out = {fid: graph.out_degree(fid) for fid in file_by_id}

    entry_info_by_id = _detect_entries(repo, file_by_id)
    migration = _migrate_entry_priors(file_by_id, entry_info_by_id, fan_in)
    category_flips = migration["category_flips"]

    seed_auto_derived = seed_paths is None
    seed_excluded_structurally_inert: list = []
    if seed_auto_derived:
        # Only seed_eligible_entries -- an entry detected under scripts/
        # tools/tests (e.g. a validation script with its own __main__ guard)
        # still earns the prior via _migrate_entry_priors above, but must
        # not inject PageRank teleport mass at the wrong origin. See
        # entry_detection._is_seed_eligible.
        #
        # A further, structural exclusion, independent of path-marker
        # heuristics: an entry with fan_out == 0 has NO resolved outgoing
        # edges at all, in the graph we've already built -- its entire
        # share of teleport mass can never propagate anywhere, no matter
        # how many other seeds exist. That's not "a small subgraph," it's
        # zero graph -- verified on repo 1's own backend/run.py and
        # voice_listener/wake_word.py, both real detected entries whose
        # only imports are external (never resolve internally). Seeding
        # them is pure waste, always, for any repo -- a general property
        # of the seed, not a per-repo judgment call the way
        # seed_exclude_paths is.
        candidate_paths = migration["seed_eligible_entries"]
        seed_excluded_structurally_inert = sorted(
            p for p in candidate_paths if fan_out.get(path_to_id.get(p), 0) == 0
        )
        detected_paths = [p for p in candidate_paths if p not in seed_excluded_structurally_inert]
        if not detected_paths:
            raise ValueError(
                f"No seed-eligible entry points with real outgoing edges detected for repo "
                f"{repo.host}/{repo.owner}/{repo.name} (id={repo.id}) -- refusing to auto-derive an "
                "empty PageRank seed (every file would converge to score 0, a ranking of pure ties). "
                "Pass seed_paths explicitly to override."
            )
        seed_paths = detected_paths

    seed_ids = [path_to_id[p] for p in seed_paths if p in path_to_id]
    missing_seed_paths = [p for p in seed_paths if p not in path_to_id]
    if not seed_ids:
        raise ValueError(f"None of the seed paths were found in this repo: {seed_paths}")
    seed = {fid: 1.0 / len(seed_ids) for fid in seed_ids}

    if damping is None:
        damping = load_weighted_pagerank_config()["damping"]

    on_progress("ranking_pagerank", 0, 0, "Computing weighted personalised PageRank")
    pr = weighted_personalized_pagerank(graph, edge_weight, seed, damping=damping)

    priors_config = node_priors.load_node_priors()
    is_entry = {fid: (fid in entry_info_by_id) for fid in file_by_id}
    seed_eligible = {fid: entry_info_by_id[fid]["seed_eligible"] if fid in entry_info_by_id else False for fid in file_by_id}

    on_progress("ranking_scoring", 0, len(file_by_id), "Scoring files")
    results = []
    zero_mass_count = 0
    for fid, f in file_by_id.items():
        pr_f = pr.get(fid, 0.0)
        if pr_f == 0.0:
            zero_mass_count += 1
        prior = node_priors.resolve_prior(f.prior_category, priors_config)
        results.append({
            "file_id": fid, "path": f.path, "score": pr_f * prior,
            "pagerank": pr_f, "prior_category": f.prior_category, "prior": prior,
            "fan_in": fan_in[fid], "fan_out": fan_out[fid], "is_entry_point": is_entry[fid],
        })

    total = len(results)
    zero_mass_percentage = 100.0 * zero_mass_count / total if total else 0.0
    # Deterministic secondary sort (path, ascending) -- a large block of
    # files unreachable from the seed all score exactly 0 and can't be
    # ordered by score at all; without a defined tie-break, sort order
    # across that block would depend on whatever order the DB happens to
    # return, which isn't guaranteed stable across runs. That would make
    # Phase F5's Kendall tau comparison non-reproducible on identical data.
    results.sort(key=lambda r: (-r["score"], r["path"]))

    # No history args -- this scorer's formula has no history term, and
    # passing None for each leaves whatever a previous legacy/rrf run
    # already wrote on CodeFile untouched (see _write_file_level_signals).
    _write_file_level_signals(file_by_id, fan_in, fan_out, is_entry, seed_eligible)

    db.query(CodeFileRank).filter(CodeFileRank.repo_id == repo.id, CodeFileRank.scorer == "weighted_pagerank").delete()
    for i, r in enumerate(results, start=1):
        db.add(CodeFileRank(
            repo_id=repo.id, file_id=r["file_id"], scorer="weighted_pagerank", score=r["score"],
            rank=i, pagerank=r["pagerank"], computed_at=utcnow(),
        ))
    db.commit()

    on_progress("ranking_done", total, total, "Weighted PageRank ranking complete")
    return {
        "scorer": "weighted_pagerank",
        "damping": damping,
        "seed_paths": seed_paths,
        "seed_auto_derived": seed_auto_derived,
        "seed_excluded_structurally_inert": seed_excluded_structurally_inert,
        "missing_seed_paths": missing_seed_paths,
        "zero_mass_count": zero_mass_count,
        "zero_mass_percentage": zero_mass_percentage,
        "files": results,
        "category_flips": category_flips,
        "entry_detection": migration["entry_detection"],
        "prior_source_migrations": migration["prior_source_migrations"],
        "contradictions": migration["contradictions"],
        "seed_eligible_entries": migration["seed_eligible_entries"],
        "prior_only_entries": migration["prior_only_entries"],
    }


# ---------------- ranking: Phase F5 RRF scorer ----------------


def rank_repo_rrf(
    db: Session, repo: Repo, on_progress: Optional[Callable[[str, int, int, str], None]] = None,
    k: Optional[float] = None,
) -> dict:
    """Fuses the SAME six raw signals the legacy scorer uses (fan_in,
    pagerank, is_entry_point, commit_count, distinct_authors,
    days_since_last_change) via reciprocal_rank_fusion() instead of a tuned
    weighted sum -- reuses legacy_signal_snapshot so this can never observe
    a different graph/history/entry-prior state than the legacy scorer did.
    No history-unavailable weight-redistribution the way legacy has (there
    are no weights to redistribute); when git history is unavailable, those
    three signals are simply omitted from signal_values, same as they're
    excluded from active_weights when history isn't available.

    Holds this repo's advisory lock (repo_lock.py) for the whole call --
    see rank_repo's docstring for why."""
    with repo_lock.repo_lock(repo.id, "rank"):
        return _rank_repo_rrf_locked(db, repo, on_progress, k)


def _rank_repo_rrf_locked(
    db: Session, repo: Repo, on_progress: Optional[Callable[[str, int, int, str], None]], k: Optional[float],
) -> dict:
    if on_progress is None:
        on_progress = lambda *a: None  # noqa: E731

    snapshot = legacy_signal_snapshot(db, repo, on_progress=on_progress)
    file_by_id = snapshot["file_by_id"]
    fan_in, fan_out, pagerank, is_entry = snapshot["fan_in"], snapshot["fan_out"], snapshot["pagerank"], snapshot["is_entry"]
    seed_eligible = snapshot["seed_eligible"]
    commit_count, distinct_authors, days_since_change = (
        snapshot["commit_count"], snapshot["distinct_authors"], snapshot["days_since_change"]
    )
    reduced_confidence = not snapshot["have_history"]
    category_flips = snapshot["category_flips"]

    rrf_config = load_rrf_config()
    if k is None:
        k = rrf_config["k"]
    directions = rrf_config["directions"]

    signal_values = {
        "fan_in": fan_in,
        "pagerank": pagerank,
        "is_entry_point": {fid: (1.0 if is_entry[fid] else 0.0) for fid in file_by_id},
    }
    if snapshot["have_history"]:
        signal_values["commit_count"] = {fid: v for fid, v in commit_count.items() if v is not None}
        signal_values["distinct_authors"] = {fid: v for fid, v in distinct_authors.items() if v is not None}
        signal_values["days_since_last_change"] = {fid: v for fid, v in days_since_change.items() if v is not None}

    on_progress("ranking_scoring", 0, len(file_by_id), "Fusing signal ranks")
    fused = reciprocal_rank_fusion(signal_values, directions, k)

    results = []
    for fid, f in file_by_id.items():
        results.append({
            "file_id": fid, "path": f.path, "score": fused.get(fid, 0.0),
            "fan_in": fan_in[fid], "fan_out": fan_out[fid], "pagerank": pagerank[fid],
            "is_entry_point": is_entry[fid],
            "commit_count": commit_count[fid], "distinct_authors": distinct_authors[fid],
            "days_since_last_change": days_since_change[fid],
            "reduced_confidence": reduced_confidence,
        })
    # Same deterministic secondary sort as the weighted-pagerank scorer, for
    # the same reason: reproducible Kendall tau across runs on identical data.
    results.sort(key=lambda r: (-r["score"], r["path"]))

    _write_file_level_signals(
        file_by_id, fan_in, fan_out, is_entry, seed_eligible, commit_count, distinct_authors, days_since_change,
    )
    repo.reduced_confidence = reduced_confidence

    db.query(CodeFileRank).filter(CodeFileRank.repo_id == repo.id, CodeFileRank.scorer == "rrf").delete()
    for i, r in enumerate(results, start=1):
        db.add(CodeFileRank(
            repo_id=repo.id, file_id=r["file_id"], scorer="rrf", score=r["score"],
            rank=i, pagerank=r["pagerank"], computed_at=utcnow(),
        ))
    db.commit()

    on_progress("ranking_done", len(results), len(results), "RRF ranking complete")
    return {
        "scorer": "rrf",
        "k": k,
        "reduced_confidence": reduced_confidence,
        "files": results,
        "category_flips": category_flips,
        "entry_detection": snapshot["entry_detection"],
        "prior_source_migrations": snapshot["prior_source_migrations"],
        "contradictions": snapshot["contradictions"],
        "seed_eligible_entries": snapshot["seed_eligible_entries"],
        "prior_only_entries": snapshot["prior_only_entries"],
    }
