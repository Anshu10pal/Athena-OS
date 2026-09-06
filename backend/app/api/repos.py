import json
import math
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.core.security import get_current_user, require_write_access
from app.db.database import SessionLocal, get_db
from app.db.models import (
    CodeFile, CodeFileHealth, CodeFileRank, CodeHealthSnapshot, CodeImport,
    CodeSubsystem, ComprehensionCard, Repo, RepoJob, User,
)
from app.services.codebase import (
    card_generation, card_grading, card_persist, deletion, edge_weights,
    findings_queue, jobs, module_mapping, registry, repo_lock,
)
from app.services.codebase.dir_aggregation import DEFAULT_MAX_GROUPS, aggregate_to_directories
from app.services.codebase.discovery import TooManyFilesError
from app.services.codebase.git_ops import GitBinaryUnavailable
from app.services.codebase.ingest import ingest_repo
from app.services.codebase.node_priors import NOISE_CATEGORIES
from app.services.codebase.ordering import compute_layers
from app.services.codebase.graph_structure import persist_graph_structure
from app.services.codebase.health_rollup import build_rollup
from app.services.codebase.health_snapshots import create_snapshot, snapshot_staleness, trend_delta
from app.services.codebase.overview import build_overview
from app.services.codebase.policy import RepoBlocked
from app.services.codebase.neighborhood import (
    DEFAULT_BUDGET_TOKENS, _estimate_tokens, read_neighborhood,
)
from app.services.codebase.ranking import _build_graph, rank_repo
from app.services.codebase.repo_lock import RepoBusyError
from app.services.codebase import roadmap_persist
from app.services.codebase.roadmap_staging import load_roadmap_staging_config
from app.services.codebase.subsystems import (
    VALID_ALGORITHMS,
    compute_subsystems,
    compute_subsystems_hdbscan,
    subsystem_column_for,
)

router = APIRouter(prefix="/api/repos", tags=["repos"])


class RepoAddIn(BaseModel):
    url: Optional[str] = None
    local_path: Optional[str] = None
    source_root: Optional[str] = None


class RepoSeedExcludeIn(BaseModel):
    seed_exclude_paths: list[str]


class SubsystemRenameIn(BaseModel):
    custom_label: str


def serialize_repo(r: Repo) -> dict:
    return {
        "id": r.id,
        "host": r.host,
        "owner": r.owner,
        "name": r.name,
        "url": r.url,
        "local_path": r.local_path,
        "source_kind": r.source_kind,
        "default_branch": r.default_branch,
        "visibility": r.visibility,
        "source_root": r.source_root,
        "allow_external_llm": r.allow_external_llm,
        "last_ingested_sha": r.last_ingested_sha,
        "last_ingested_at": r.last_ingested_at.isoformat() if r.last_ingested_at else None,
        "file_count": r.file_count,
        "added_at": r.added_at.isoformat(),
        "seed_exclude_paths": r.seed_exclude_paths,
    }


@router.get("")
def list_repos(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [serialize_repo(r) for r in db.query(Repo).order_by(Repo.added_at.desc()).all()]


@router.get("/{repo_id}")
def get_repo(repo_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    repo = db.get(Repo, repo_id)
    if not repo:
        raise HTTPException(404, "Repo not found")
    return serialize_repo(repo)


@router.post("")
def add_repo(payload: RepoAddIn, user: User = Depends(require_write_access), db: Session = Depends(get_db)):
    if not payload.url and not payload.local_path:
        raise HTTPException(400, "Provide either a url or a local_path")
    if payload.url and payload.local_path:
        raise HTTPException(400, "Provide only one of url or local_path, not both")
    try:
        if payload.url:
            repo = registry.register_from_url(db, payload.url, source_root=payload.source_root)
        else:
            repo = registry.register_from_path(db, payload.local_path, source_root=payload.source_root)
    except RepoBlocked as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except GitBinaryUnavailable as e:
        raise HTTPException(503, str(e))
    except RuntimeError as e:
        raise HTTPException(502, f"Could not acquire the repository: {e}")
    return serialize_repo(repo)


@router.put("/{repo_id}/seed-exclude-paths")
def set_seed_exclude_paths(
    repo_id: int, payload: RepoSeedExcludeIn,
    user: User = Depends(require_write_access), db: Session = Depends(get_db),
):
    """Phase E4 refinement: per-repo override for which detected entry
    points are eligible to seed weighted PageRank (prefix-matched against
    CodeFile.path) -- see entry_detection.py. Every repo has some auxiliary
    surface (a worker, a cron script, a dev harness) that no ecosystem-wide
    marker catches; this is that escape hatch. Takes effect on the next
    rank run, not retroactively."""
    repo = db.get(Repo, repo_id)
    if not repo:
        raise HTTPException(404, "Repo not found")
    repo.seed_exclude_paths = payload.seed_exclude_paths
    db.commit()
    return serialize_repo(repo)


class RepoDeleteIn(BaseModel):
    # Typed confirmation, matching the shape used for other irreversible or
    # externally-visible actions. Named `confirm` rather than `name` so a caller
    # cannot pass it by accident while meaning something else.
    confirm: str


@router.delete("/{repo_id}")
def delete_repo_endpoint(
    repo_id: int, body: RepoDeleteIn,
    user: User = Depends(require_write_access), db: Session = Depends(get_db),
):
    """Remove a repo: its rows always, its clone directory only when Athena
    created it. Irreversible, no undo.

    Held under the per-repo advisory lock for the whole operation. Without it an
    in-flight ingest would keep writing rows into a repo being deleted, and the
    two would interleave into a half-present repo -- exactly the contention the
    lock already exists for. A busy repo is a 409 naming the job, not a failure
    partway through.

    See deletion.py for why the directory guard has two independent conditions
    and why the delete order is written out."""
    repo = db.get(Repo, repo_id)
    if not repo:
        raise HTTPException(404, "Repo not found")

    try:
        with repo_lock.repo_lock(repo_id, "delete"):
            try:
                report = deletion.delete_repo(db, repo, body.confirm)
            except deletion.RepoDeletionRefused as e:
                raise HTTPException(400, str(e))
            except OSError as e:
                # Rows are already committed at this point; only the directory
                # removal can fail here. Reported as a partial success with the
                # path, because "the repo is gone but this directory is still on
                # disk" is actionable and "500" is not.
                raise HTTPException(
                    500,
                    f"Repo rows were deleted, but its directory could not be removed: {e}. "
                    f"Remove {repo.local_path!r} by hand.",
                )
    except RepoBusyError as e:
        raise HTTPException(409, str(e))

    return report.to_dict()


@router.post("/{repo_id}/resync")
def resync_repo(repo_id: int, user: User = Depends(require_write_access), db: Session = Depends(get_db)):
    repo = db.get(Repo, repo_id)
    if not repo:
        raise HTTPException(404, "Repo not found")
    try:
        registry.resync(db, repo)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(502, f"Resync failed: {e}")
    return serialize_repo(repo)


@router.post("/{repo_id}/ingest")
def ingest_repo_endpoint(repo_id: int, user: User = Depends(require_write_access), db: Session = Depends(get_db)):
    repo = db.get(Repo, repo_id)
    if not repo:
        raise HTTPException(404, "Repo not found")
    try:
        report = ingest_repo(db, repo)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except TooManyFilesError as e:
        raise HTTPException(413, str(e))
    except RepoBusyError as e:
        raise HTTPException(409, str(e))
    return {
        "repo_id": report.repo_id,
        "files_total": report.files_total,
        "files_parsed": report.files_parsed,
        "files_skipped_unchanged": report.files_skipped_unchanged,
        "files_deleted": report.files_deleted,
        "symbols_total": report.symbols_total,
        "imports_total": report.imports_total,
        "imports_resolved": report.imports_resolved,
        "promoted_python_roots": report.promoted_python_roots,
        "python_cross_root_edges": report.python_cross_root_edges,
        "js_configs_found": report.js_configs_found,
        "js_cross_root_edges": report.js_cross_root_edges,
        "blind_spots": report.blind_spots,
    }


VALID_SCORERS = ("legacy", "weighted_pagerank", "rrf")


def _serialize_rank(r: CodeFileRank, f: CodeFile) -> dict:
    """Phase G1: file-level signals (fan_in/fan_out/is_entry_point/history)
    read from the CodeFile row, not the CodeFileRank row -- they're
    properties of the file, identical regardless of which scorer produced
    this rank row. Only score/rank/pagerank are genuinely scorer-dependent."""
    return {
        "file_id": r.file_id,
        "path": f.path,
        "language": f.language,
        "prior_category": f.prior_category,
        "rank": r.rank,
        "score": r.score,
        "fan_in": f.fan_in,
        "fan_out": f.fan_out,
        "pagerank": r.pagerank,
        "is_entry_point": f.is_entry_point,
        "commit_count": f.commit_count,
        "distinct_authors": f.distinct_authors,
        "days_since_last_change": f.days_since_last_change,
        "computed_at": r.computed_at.isoformat(),
        # Phase I1: same reasoning as the fan_in/fan_out block above --
        # subsystem membership is a property of the FILE (from the last
        # POST /subsystems run), identical regardless of which scorer
        # produced this rank row, so it's read straight off CodeFile with
        # no extra query. Null until subsystem clustering has run, or if
        # this file landed in a singleton (never given a CodeSubsystem row).
        "subsystem_modularity_id": f.subsystem_modularity_id,
        "subsystem_louvain_id": f.subsystem_louvain_id,
        "subsystem_hdbscan_id": f.subsystem_hdbscan_id,
    }


@router.post("/{repo_id}/rank")
def rank_repo_endpoint(repo_id: int, user: User = Depends(require_write_access), db: Session = Depends(get_db)):
    repo = db.get(Repo, repo_id)
    if not repo:
        raise HTTPException(404, "Repo not found")
    try:
        result = rank_repo(db, repo)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RepoBusyError as e:
        raise HTTPException(409, str(e))
    return result


@router.get("/{repo_id}/ranking")
def get_ranking(
    repo_id: int, scorer: str = "legacy",
    # D13, additive. Uncapped this endpoint returns every file: 6,584 rows and
    # 2.85 MB on Superset, which is a real cost for a caller that wants a top-N
    # starting list. A PLAIN default, not `Query(None)` -- that marker object
    # reaches a direct call as itself and this suite calls route functions
    # directly (see `_as_list`, and the ck1b bug it cost).
    #
    # None means UNCAPPED, so every existing caller is byte-for-byte unchanged.
    # Applied AFTER the rank ordering, never before: a "top 10 by rank" that
    # sliced before ordering would return ten arbitrary files under a name that
    # promises the ten that matter.
    limit: Optional[int] = None,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """One row per file: CodeFileRank filtered by BOTH repo_id and scorer,
    not just repo_id -- the earlier version of this endpoint filtered on
    repo_id alone and sorted by score across all three scorers' rows mixed
    together, which is both duplicate rows per file AND a meaningless sort
    order (three incompatible scales sorted as one). Ordered by the stored
    `rank` (assigned once, at rank-run time over the whole repo) rather
    than re-sorting by score here -- a file's rank must never be
    recomputed from whatever subset a caller happens to be looking at."""
    repo = db.get(Repo, repo_id)
    if not repo:
        raise HTTPException(404, "Repo not found")
    if scorer not in VALID_SCORERS:
        raise HTTPException(400, f"Unknown scorer {scorer!r} -- must be one of {VALID_SCORERS}")

    rows = (
        db.query(CodeFileRank, CodeFile)
        .join(CodeFile, CodeFileRank.file_id == CodeFile.id)
        .filter(CodeFileRank.repo_id == repo_id, CodeFile.repo_id == repo_id, CodeFileRank.scorer == scorer)
        .order_by(CodeFileRank.rank.asc())
        .all()
    )
    total = len(rows)
    if limit is not None and limit >= 0:
        rows = rows[:limit]
    return {
        "scorer": scorer,
        "reduced_confidence": repo.reduced_confidence,
        # Reported so a truncated response is DETECTABLE by its consumer rather
        # than looking like a repo with fewer files -- the same
        # total-before-cap discipline as /graph and /files/{id}/neighbors.
        "total_before_limit": total,
        "limit": limit,
        "truncated": limit is not None and limit >= 0 and total > limit,
        "files": [_serialize_rank(r, f) for r, f in rows],
    }


GRAPH_NODE_LIMIT_DEFAULT = 400
NEIGHBORS_ENDPOINT_CAP = 100

# THE SOURCE-BYTE DIVISOR, DELIBERATELY SEPARATE FROM neighborhood._CHARS_PER_TOKEN.
#
# That constant is 3.6 and is calibrated against tiktoken cl100k on this repo's
# PATH CORPUS. This one divides SOURCE-CODE BYTES. They are no longer even the
# same number, which is the clearest possible argument for having kept them apart.
#
# 4.7 IS A CONSERVATIVE ROUND-UP OF A DERIVED 4.6737, AND HERE IS WHERE IT CAME
# FROM. Phase 6's checkpoint-3 benchmark stored no per-file character counts and
# no artifact survives -- tiktoken is not installed and nothing was ever
# committed. But the char side is recoverable: pairing the naive tiktoken totals
# recorded in docs/phase6-graph-as-context.md 4.2 with summed code_files.size_bytes
# over each file's DISTINCT connected set gives 16,059,975 bytes / 3,436,264
# tokens = 4.6737 pooled, with a per-file range of 4.511-4.907. Two independent
# checks that the pairing is sound: the DISTINCT connected counts reproduce 4.2's
# recorded counts exactly for all five files (0, 6, 10, 524, 355), and the summed
# naive total reproduces 4.2's pooled 3,436,264 exactly.
#
# ROUNDED UP, NOT TO NEAREST. A higher divisor means a smaller denominator, a
# smaller claimed saving, and an estimate that errs against our own pitch. The
# previous 3.6 was ~30% low, which inflated the denominator in the flattering
# direction -- on superset/models/core.py it claimed 349.5x where 4.7 claims
# 267.7x.
#
# WHAT THE CALIBRATION LABEL ASSERTS, AND WHAT IT DOES NOT. It is AGGREGATE-level
# -- derived from per-file totals over connected sets, never from a per-file
# char/token pair, so it cannot be quoted as "this file tokenises at 4.7". It
# covers SUPERSET PYTHON SOURCE ONLY. It makes NO claim for other languages or
# other repositories, and applying it to a JS or Go repo would be reusing a
# constant outside the corpus it was measured on -- the exact mistake that
# reusing _CHARS_PER_TOKEN here would have been.
_CHARS_PER_TOKEN_SOURCE = 4.7
_CALIBRATION_STATUS = (
    "derived_from_phase6_4.2_aggregate_tiktoken_cl100k_at_a05a0999_rounded_conservative")

# THE ONE FILE BOTH INSTRUMENTS MEASURED. superset/utils/core.py is a checkpoint-3
# benchmark hub, so it has a tiktoken-measured naive cost AND a graph cost, and it
# is the only file where this endpoint's estimate can be checked against measured
# ground truth rather than against itself.
#
# Deliberately NOT extended to other files. There is no benchmark figure for them,
# so `estimator_vs_measured` would either be absent or silently mean something
# different per file -- a number whose meaning the consumer cannot assess, which
# is the 17.25 shape exactly. It is null everywhere else, on purpose.
#
# NOTE ON POPULATIONS, because the comparison is not perfectly apples-to-apples:
# 4.2's naive cost includes the file's OWN text (76,119 B) and this endpoint's
# connected_bytes does not. The direction holds either way -- 1,710,425 excluding
# self and 1,726,621 including it, both under the measured 1,746,672 -- so the
# assertion is not an artifact of the population difference, but the gap is
# smaller than it looks.
#
# ALL FIVE checkpoint-3 files, transcribed from docs/phase6-graph-as-context.md
# 4.2. Extended from one to five at 3a-quater so the estimator's error can be
# measured across the connectivity range rather than asserted from its top end
# -- which is how the "< 1.0" invariant survived four checkpoints while being
# false at the floor.
_PHASE6_BENCHMARK = {
    (6, "scripts/__init__.py"): {"naive_tokens": 174, "graph_tokens": 188},
    (6, "superset/commands/annotation_layer/annotation/create.py"):
        {"naive_tokens": 7_754, "graph_tokens": 489},
    (6, "superset/commands/chart/delete.py"):
        {"naive_tokens": 30_206, "graph_tokens": 561},
    (6, "superset/utils/core.py"): {"naive_tokens": 1_746_672, "graph_tokens": 5_954},
    (6, "superset/__init__.py"): {"naive_tokens": 1_651_458, "graph_tokens": 8_452},
}
for _k, _v in _PHASE6_BENCHMARK.items():
    _v["ratio"] = _v["naive_tokens"] / _v["graph_tokens"]

# ONE query, both directions, deduped, self-edge excluded. Resolved edges only:
# an unresolved specifier has to_file_id IS NULL and so cannot survive the join --
# structurally excluded from the priced population rather than counted as a
# zero-cost file.
_CONNECTED_FILES_SQL = """
SELECT nb.id                          AS file_id,
       nb.path                        AS path,
       nb.size_bytes                  AS size_bytes,
       nb.subsystem_modularity_id     AS subsystem_modularity_id,
       -- DIRECTION, aggregated per NEIGHBOUR rather than per edge. A file can
       -- appear on both sides (6 of 2256's 274 do), and GROUP BY is what makes
       -- that one row with direction "both" instead of two contradictory rows.
       -- MAX over the two flags because a neighbour is an importer if ANY edge
       -- makes it one.
       MAX(CASE WHEN ci.from_file_id = :fid THEN 1 ELSE 0 END) AS is_import,
       MAX(CASE WHEN ci.to_file_id   = :fid THEN 1 ELSE 0 END) AS is_importer
FROM code_imports ci
JOIN code_files nb
  ON nb.id = CASE WHEN ci.from_file_id = :fid THEN ci.to_file_id ELSE ci.from_file_id END
WHERE ci.repo_id = :rid
  AND ci.resolved = 1
  AND ci.to_file_id IS NOT NULL
  AND (ci.from_file_id = :fid OR ci.to_file_id = :fid)
  AND nb.id != :fid
GROUP BY nb.id, nb.path, nb.size_bytes, nb.subsystem_modularity_id
"""

# DISPLAY DATA ONLY, and this is load-bearing rather than a note.
#
# Unresolved specifiers have to_file_id IS NULL -- they are not files, they have
# no size_bytes, and they MUST NOT enter the priced population. Folding them in
# would inflate `connected_files_distinct` while `connected_bytes` stayed put,
# so the count and the cost would silently describe different populations -- the
# exact failure C4's discriminating break demonstrates (274 -> 325, bytes
# unchanged). They are surfaced for display because an agent editing this file
# needs to know a dependency could not be pinned, which is precisely the case it
# cannot discover by looking.
_UNRESOLVED_EDGES_SQL = """
SELECT raw_specifier, line_number, kind
FROM code_imports
WHERE repo_id = :rid AND from_file_id = :fid
  AND resolved = 0 AND to_file_id IS NULL
ORDER BY line_number, raw_specifier
"""
VALID_GRAPH_LEVELS = ("directory", "file")


def _resolve_edges_by_neighbor(rows: list) -> dict:
    """rows: [(neighbor_file_id, kind, cross_root_kind), ...] -- the caller
    queries only the varying endpoint (from_file_id for importers,
    to_file_id for imports), already reduced to just the neighbor id, so
    this function never has to guess which side of an edge is "the other
    file." Returns {neighbor_file_id: {weight, kind, cross_root}} -- max
    weight wins per neighbor (same rule as ranking.py's
    _build_weighted_graph, for the same reason: a refactor splitting one
    import into several shouldn't change how coupled two files look),
    first non-null cross_root_kind wins if any row has one."""
    config = edge_weights.load_edge_weights()
    agg: dict = {}
    for neighbor_id, kind, cross_root_kind in rows:
        w = edge_weights.resolve_weight(kind, config)
        existing = agg.get(neighbor_id)
        if existing is None or w > existing["weight"]:
            agg[neighbor_id] = {"weight": w, "kind": kind, "cross_root": cross_root_kind}
        elif cross_root_kind and not existing["cross_root"]:
            existing["cross_root"] = cross_root_kind
    return agg


def _as_list(value) -> Optional[list[str]]:
    """Normalise a repeated query param to a list or None.

    `Query(None)` is a MARKER object, not the value None. FastAPI replaces it
    when it invokes the route, but this test suite calls route functions
    directly (see this module's docstring in tests/test_repos_api.py), and a
    direct call receives the marker -- which is truthy, so every "no filter"
    call would take the filtering branch and then fail on `in` against a
    non-iterable. Normalised here so the function behaves identically whether
    FastAPI supplies the argument or a caller omits it.
    """
    return value if isinstance(value, list) else None


def _top_level_segment(path: str) -> str:
    """Mirrors lib/filters.ts::topLevelSegment, including "(root)" for a file
    with no "/" at all -- a repo's own top-level files need a segment too, or
    they are silently unmatchable by a segment filter that lists "(root)"."""
    idx = path.find("/")
    return "(root)" if idx == -1 else path[:idx]


@router.get("/{repo_id}/graph")
def get_graph(
    repo_id: int, scorer: str = "legacy", level: str = "directory", limit: int = GRAPH_NODE_LIMIT_DEFAULT,
    language: Optional[str] = None, path_prefix: Optional[str] = None, min_score: Optional[float] = None,
    # --- the UI's own filter vocabulary (Phase L2) -------------------------
    # Repeated values: ?languages=python&languages=tsx. Deliberately NOT a
    # single value the client collapses a multi-select into -- sending the
    # first of three selected languages would silently under-filter, and the
    # user would read a plausible result computed from a third of what they
    # asked for. Confidently wrong, which is worse than visibly broken.
    segments: Optional[list[str]] = Query(None),
    languages: Optional[list[str]] = Query(None),
    query: Optional[str] = None,
    hide_noise: bool = False,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Nodes + edges for the graph, layer, and architecture-map views.
    Read-only -- reads whatever the last actual rank run persisted, never
    recomputes or re-persists entry detection itself. Phase H1.5: this
    used to call entry_detection live, on every request, to get the
    seed-eligible/prior-only split -- 15-20s on this project's own repo,
    because entry detection walks the filesystem. Reads
    CodeFile.seed_eligible now (set by rank_repo/_rank_repo_weighted_
    pagerank/_rank_repo_rrf's own entry_info_by_id, the same call, just
    made once at rank time instead of on every read) -- also closes a
    staleness gap the live call had: a directory's `kind` could otherwise
    reflect a fresher filesystem scan than the ranking itself.

    `layer`/`reachable` are computed from the persisted seed-ELIGIBLE set
    (not the narrower set weighted_pagerank actually seeds from after
    excluding fan_out==0 entries). Deliberate: a structurally-inert entry
    (e.g. run.py, fan_out==0) is still a real place a reader starts, even
    though seeding PageRank from it would waste teleport mass on a dead
    end -- "is this a legitimate starting point for reading order" and
    "should this seed carry PageRank mass" are different questions, and
    layers only need to answer the first one. This makes layer
    scorer-independent, like fan_in/is_entry_point.

    `level=file` (Phase G4's original shape) or `level=directory` (Phase
    H1's default, see dir_aggregation.py). Directory aggregation runs as a
    post-processing step over the file-level nodes/edges below, not a
    parallel query path -- one pipeline, so the two levels can't silently
    drift apart.

    language/path_prefix/min_score filter the FILE set before either level
    sees it -- user intent. `limit` means something different per level:
    at file level it caps FILES (default 400) by stored rank, exactly as
    before Phase H1. At directory level it is never applied to files --
    aggregate_to_directories sees every filtered file, uncapped, and
    `limit` only caps the resulting DIRECTORIES afterward. Capping files
    first and aggregating second would compute a directory graph from
    whatever fraction of the repo survived the file cap: invisible at 159
    files, silently wrong at 5,000 (a plausible-looking architecture map
    built from an eighth of the repo). `truncated`/`total_nodes_before_cap`
    (file level) or `truncated`/`total_groups_before_limit` (directory
    level) report what was cut either way.

    Phase L2 -- the UI's filter vocabulary, so Architecture, Matrix and the
    Dependency Graph can honour the file filter bar they had been rendering
    and ignoring. `segments`, `languages`, `query` and `hide_noise` mirror
    lib/filters.ts::filterFiles exactly. Two of the bar's controls are
    deliberately NOT accepted here, and the reasons are recorded at the
    endpoint so they are not "added for completeness" later:

      hideZeroFanIn -- fan-in is a property of a FILE. Aggregating it to a
        directory has three defensible answers (sum, max, distinct external
        importers) and no obviously correct one. Picking one silently is worse
        than not offering the filter, because the number would look
        authoritative.

      subsystemId -- DirNodeT carries a dominant cluster and a purity, not
        membership, so it cannot answer "is this directory in cluster N".
        Already recorded in lib/filters.ts's Filterable comment.

    Filtering happens BEFORE aggregation for the same reason capping does not:
    a directory graph computed from a filtered file set is a different, correct
    graph, whereas one that filtered the aggregate afterwards would report
    file counts and edge weights over files the user excluded. That is not
    available client-side at all -- DirNodeT has no member list -- which is why
    this lives here rather than in the browser."""
    repo = db.get(Repo, repo_id)
    if not repo:
        raise HTTPException(404, "Repo not found")
    if scorer not in VALID_SCORERS:
        raise HTTPException(400, f"Unknown scorer {scorer!r} -- must be one of {VALID_SCORERS}")
    if level not in VALID_GRAPH_LEVELS:
        raise HTTPException(400, f"Unknown level {level!r} -- must be one of {VALID_GRAPH_LEVELS}")

    rows = (
        db.query(CodeFileRank, CodeFile)
        .join(CodeFile, CodeFileRank.file_id == CodeFile.id)
        .filter(CodeFileRank.repo_id == repo_id, CodeFile.repo_id == repo_id, CodeFileRank.scorer == scorer)
        .order_by(CodeFileRank.rank.asc())
        .all()
    )
    if not rows:
        raise HTTPException(404, f"No {scorer!r} ranking for this repo yet -- run rank first.")

    segments = _as_list(segments)
    languages = _as_list(languages)
    # Trimmed and lower-cased once, not per file. Matches filterFiles, which
    # trims before testing -- a whitespace-only query narrows nothing there and
    # must narrow nothing here, or the two views disagree over a filter the
    # user cannot see.
    query_needle = (query or "").strip().lower()

    def matches(f: CodeFile, r: CodeFileRank) -> bool:
        # Legacy single-value params, kept because they are a real lower-level
        # API with their own tests. The UI uses the plural forms below.
        if language and f.language != language:
            return False
        if path_prefix and not f.path.startswith(path_prefix):
            return False
        if min_score is not None and r.score < min_score:
            return False
        # --- the UI's vocabulary, mirroring filterFiles ---
        if segments and _top_level_segment(f.path) not in segments:
            return False
        if languages and f.language not in languages:
            return False
        if hide_noise and f.prior_category in NOISE_CATEGORIES:
            return False
        if query_needle and query_needle not in f.path.lower():
            return False
        return True

    filtered = [(r, f) for r, f in rows if matches(f, r)]
    # Already the POST-filter denominator, which is what the truncation notice
    # has to report: "400 of 6,523" unfiltered and "400 of N matching" once a
    # filter is on are the same number computed the same way, and a notice built
    # against the unfiltered total would be right in one case and wrong in the
    # other with nothing to distinguish them.
    total_before_cap = len(filtered)
    # File-level cap only applies at level=file -- see the docstring above
    # for why directory level must see every filtered file uncapped.
    capped = filtered if level == "directory" else filtered[:limit]
    truncated = total_before_cap > len(capped)
    kept_ids = {f.id for _, f in capped}

    file_by_id = {f.id: f for _, f in rows}  # full set -- layers need the WHOLE graph, not just the capped view
    graph = _build_graph(db, repo, file_by_id)
    entry_ids = {fid for fid, f in file_by_id.items() if f.seed_eligible}
    layers = compute_layers(graph, entry_ids)

    nodes = [
        {
            "id": f.id, "path": f.path, "language": f.language, "score": r.score, "rank": r.rank,
            "layer": layers.get(f.id), "prior_category": f.prior_category,
            "fan_in": f.fan_in, "fan_out": f.fan_out, "pagerank": r.pagerank,
            "is_entry_point": f.is_entry_point, "seed_eligible": f.seed_eligible,
            "reachable": layers.get(f.id) is not None,
            # Phase I2: read straight off CodeFile, same "property of the
            # file" shape as everything else here -- lets
            # aggregate_to_directories compute a directory's dominant
            # dependency cluster without a second query.
            "subsystem_modularity_id": f.subsystem_modularity_id,
        }
        for r, f in capped
    ]

    edge_rows = (
        db.query(CodeImport.from_file_id, CodeImport.to_file_id, CodeImport.kind, CodeImport.cross_root_kind)
        .filter(CodeImport.repo_id == repo_id, CodeImport.to_file_id.isnot(None))
        .all()
    )
    edge_config = edge_weights.load_edge_weights()
    edge_agg: dict = {}
    for from_id, to_id, kind, cross_root_kind in edge_rows:
        if from_id not in kept_ids or to_id not in kept_ids:
            continue
        w = edge_weights.resolve_weight(kind, edge_config)
        key = (from_id, to_id)
        existing = edge_agg.get(key)
        if existing is None or w > existing["weight"]:
            edge_agg[key] = {"weight": w, "kind": kind, "cross_root": cross_root_kind}
        elif cross_root_kind and not existing["cross_root"]:
            existing["cross_root"] = cross_root_kind

    edges = [
        {"source": from_id, "target": to_id, **info}
        for (from_id, to_id), info in edge_agg.items()
    ]

    # Echoed so a client can tell WHICH population a total describes. Without
    # it "400 of 6,523" and "400 of 6,523 matching" are indistinguishable in the
    # payload, and a UI has to infer the answer from filter state it might not
    # have sent -- the same reason the findings endpoint echoes its floor.
    applied = {
        "segments": segments or [],
        "languages": languages or [],
        "query": query_needle,
        "hide_noise": hide_noise,
        # Included so the legacy params cannot silently narrow a response that
        # claims to be unfiltered.
        "language": language,
        "path_prefix": path_prefix,
        "min_score": min_score,
    }
    filters_active = bool(
        segments or languages or query_needle or hide_noise
        or language or path_prefix or min_score is not None
    )

    if level == "directory":
        agg = aggregate_to_directories(nodes, edges, max_groups=DEFAULT_MAX_GROUPS, limit=limit)
        return {
            "scorer": scorer, "level": "directory",
            # Files behind the aggregate, post-filter -- the directory counts
            # are rolled up from these, so a client showing "N directories from
            # M files" needs both and can derive neither from the other.
            "files_matched": total_before_cap,
            "filters": applied,
            "filters_active": filters_active,
            **agg,
        }

    return {
        "scorer": scorer,
        "level": "file",
        "total_nodes_before_cap": total_before_cap,
        "truncated": truncated,
        "files_matched": total_before_cap,
        "filters": applied,
        "filters_active": filters_active,
        "nodes": nodes,
        "edges": edges,
    }


def _serialize_neighbor_list(db: Session, agg: dict, rank_by_file_id: dict) -> list:
    if not agg:
        return []
    neighbor_files = {f.id: f for f in db.query(CodeFile).filter(CodeFile.id.in_(agg.keys())).all()}
    items = []
    for nid, info in agg.items():
        nf = neighbor_files.get(nid)
        if nf is None:
            continue
        r = rank_by_file_id.get(nid)
        items.append({
            "file_id": nid, "path": nf.path,
            "rank": r.rank if r else None, "score": r.score if r else None,
            "weight": info["weight"], "kind": info["kind"], "cross_root": info["cross_root"],
        })
    items.sort(key=lambda it: (it["rank"] is None, it["rank"]))
    return items


# D25/D26 -- the DISPLAY strings for the saving, produced here and not in the
# browser.
#
# WHY THE BACKEND OWNS THEM. D7's tripwire asserts the frontend does no
# arithmetic on any token field, and it currently has ZERO exceptions. Formatting
# a ratio client-side would need one, and the `or 0` incident is the argument
# against that: a tripwire whose first catch is a false positive teaches people
# to delete tripwires. One producer for the number, and a grep-level guard with
# nothing carved out of it.
#
# ROUNDING IS ONE-DIRECTIONAL AND NEVER FAVOURS US (D25). Seven digits on a
# figure with a measured +/-9% envelope is false precision on the most attackable
# number in the feature, so it is cut to two significant figures -- and every cut
# goes DOWN on a savings claim:
#
#   270.6303  ->  "~270x"     (not 271)
#     0.9940  ->  "~0.99x"    (never "~1x", which would erase a real LOSS)
#
# `math.floor` on the scaled value rather than `round`, because `round` is
# half-to-even and would take 0.9940 to 1.0 at one decimal -- turning "the graph
# costs MORE here" into "break-even", which is exactly the claim Phase 6 reports
# this file to avoid making.
_ENVELOPE_LO, _ENVELOPE_HI = 0.9225, 1.0910


def _format_saved_ratio(ratio: Optional[float]) -> Optional[str]:
    if ratio is None:
        return None
    if ratio >= 100:
        return f"~{math.floor(ratio):,.0f}x"
    if ratio >= 10:
        return f"~{math.floor(ratio * 10) / 10:.1f}x"
    # Below 10x, two decimals -- and this is the band the floor file lives in,
    # where the difference between 0.99 and 1.0 is the difference between an
    # honest loss and a false break-even.
    return f"~{math.floor(ratio * 100) / 100:.2f}x"


def _envelope_pct() -> str:
    """The measured two-sided error band, as a string the UI states rather than
    derives. From ck3a-quater: our/measured ran 0.9225 to 1.0910 across the five
    checkpoint-3 files, so the estimate can sit ~8% under or ~9% over the
    tiktoken-measured ratio. Stated as the wider side, and as a RANGE rather than
    a symmetric +/- because it is not symmetric."""
    lo = round((1 - _ENVELOPE_LO) * 100)
    hi = round((_ENVELOPE_HI - 1) * 100)
    return f"-{lo}% / +{hi}%"


@router.get("/{repo_id}/files/{file_id}/context")
def get_file_context(
    repo_id: int, file_id: int,
    second_hop: bool = False,
    # PLAIN defaults, not `Query(...)`. FastAPI treats both as query params, but
    # `Query(x)` is a MARKER object that FastAPI substitutes only when IT invokes
    # the route -- and this suite calls route functions directly (see `_as_list`
    # below, which exists because of that same trap). A marker would reach
    # `read_neighborhood` as the budget and blow up in `json.dumps`. It did,
    # on the first direct call, before this was changed.
    budget: int = DEFAULT_BUDGET_TOKENS,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """One file's dependency neighbourhood, plus what reading it would have cost.

    THE SAME QUESTION THE MCP TOOL ANSWERS, OVER HTTP -- a browser cannot speak
    MCP stdio, and `read_neighborhood` was reachable only through the stdio
    server. This calls that same function; it does not reimplement any of it,
    and `neighborhood` is returned EXACTLY as the function produced it.

    THIS IS NOT `/files/{file_id}/neighbors` AND WILL NOT AGREE WITH IT. That
    endpoint is one hop capped at NEIGHBORS_ENDPOINT_CAP (100) for the Mermaid
    export; this one is budget-ranked through `read_neighborhood`, enriching
    MAX_ENRICHED (25) entries while keeping every remaining path. Same file, two
    numbers, and neither is wrong -- one answers "what should this diagram
    draw", the other "what must I read to change this safely". Documented in
    decisions.md so the divergence is not reconciled away as a defect.

    THE TWO TOKEN FIGURES ARE MEASURED BY DIFFERENT INSTRUMENTS AND SAY SO.
    `view_tokens` is `_estimate_tokens` over the neighbourhood sub-object -- the
    same call, on the same object, that the budget accounting uses, so the number
    the UI shows is the number the tool priced. `connected_files_tokens` CANNOT
    use that function: `_estimate_tokens` JSON-serialises its argument, so
    `_estimate_tokens(76119)` prices five digits. It divides raw bytes by
    `_CHARS_PER_TOKEN_SOURCE` instead. Both instruments are named in the payload
    rather than left for the reader to infer, and the calibration status of the
    second travels with it.

    THE DENOMINATOR IS THIS ENDPOINT'S OWN WORK, BY DESIGN. Widening
    `read_neighborhood` to carry sizes would have re-priced Phase 6's 219.7x
    figure, which was measured against the current payload shape -- invisibly,
    and in the direction of looking worse. The MCP tool's need did not change, so
    its payload does not either.

    No headline framing here: components only. What to call a ratio is the
    presentation layer's decision, not this endpoint's.
    """
    repo = db.get(Repo, repo_id)
    if not repo:
        raise HTTPException(404, "Repo not found")
    file = db.get(CodeFile, file_id)
    if not file or file.repo_id != repo_id:
        raise HTTPException(404, "File not found in this repo")

    # file_id -> path: `read_neighborhood` addresses files by repo-relative path.
    # Route option (a) was chosen precisely so this lookup is the whole cost and
    # no file path ever has to survive URL encoding.
    try:
        neighborhood = read_neighborhood(
            db, repo_id, file.path, second_hop=second_hop, budget_tokens=budget)
    except ValueError as exc:
        # The file exists in code_files but not in the graph snapshot -- a real
        # and reportable state (an ingest behind HEAD), not a 500.
        raise HTTPException(409, str(exc))

    # AFTER read_neighborhood returns, so this prices the payload actually being
    # sent, post-budget, including the `budget` block itself -- which is what the
    # internal accounting counted.
    view_tokens = _estimate_tokens(neighborhood)

    rows = db.execute(
        text(_CONNECTED_FILES_SQL), {"fid": file_id, "rid": repo_id}).mappings().all()
    connected_files_distinct = len(rows)

    # The un-deduped edge-endpoint count, kept ONLY so the gap between it and the
    # deduped population is visible in the payload instead of looking like a bug.
    # A file that both imports and is imported by the target is ONE file to read.
    edge_endpoints_total = (
        neighborhood["imports"]["total"] + neighborhood["importers"]["total"])

    priced = [r for r in rows if r["size_bytes"]]

    # D18: THE CENTRE FILE'S OWN BYTES ARE IN THE DENOMINATOR.
    #
    # NOTE THE DELIBERATE ASYMMETRY, and it is stated here so nobody has to
    # guess: `connected_files_distinct` EXCLUDES self (274/355) while
    # `connected_bytes` INCLUDES it.
    #
    # The bytes include it because the counterfactual being priced is "read this
    # file AND its connected files" -- which is also exactly what Phase 6's
    # checkpoint-3 benchmark measured (docs/phase6-graph-as-context.md 4.2:
    # "the full text of the file PLUS every file directly connected to it"). One
    # instrument for one number; excluding self made this endpoint measure a
    # slightly different quantity than the 219.7x figure it is compared against.
    #
    # The COUNT excludes it because ck3b-1's reconciliation is pinned to that
    # number: nodes == connected_files_distinct + 1, edges == edge_endpoints_total,
    # and edges - connected == overlap_count. Folding the centre into the count
    # would break three identities to tidy one field name.
    #
    # WHY THIS WAS CORRECTED (17.16): the exclude-self version was accepted on a
    # 1.1% margin measured on a 355-connection hub. That margin is
    # SCALE-DEPENDENT and total at the floor -- for a zero-connection file the
    # benchmark's denominator is the file itself and ours was 0, a 100%
    # divergence at exactly the point the 0.93x-293x spread bottoms out.
    connected_bytes = (file.size_bytes or 0) + sum(r["size_bytes"] for r in priced)
    connected_files_tokens = int(connected_bytes / _CHARS_PER_TOKEN_SOURCE)
    saved_ratio = connected_files_tokens / view_tokens if view_tokens else None
    bench = _PHASE6_BENCHMARK.get((repo_id, file.path))
    unresolved_rows = db.execute(
        text(_UNRESOLVED_EDGES_SQL), {"fid": file_id, "rid": repo_id}).mappings().all()

    return {
        "repo_id": repo_id,
        "file_id": file_id,
        "path": file.path,
        "neighborhood": neighborhood,
        # THE ID<->PATH MAP FOR THE CONNECTED SET, and an envelope field rather
        # than a neighbourhood one: `neighborhood` is returned exactly as
        # `read_neighborhood` produced it, and adding to it would re-price the
        # MCP payload -- the thing Option B exists to avoid.
        #
        # WHY IT IS HERE AT ALL: the panel is self-navigating by node click, but
        # the graph's nodes carry PATHS while this endpoint and the URL take an
        # integer id. Without this map every click costs a resolve roundtrip. The
        # ids are already selected by the denominator query and were being thrown
        # away; this is the same query, one column wider.
        "connected_index": [
            {
                "id": r["file_id"],
                "path": r["path"],
                # "both" is not a tie-break, it is the truth for a file that
                # imports the target AND is imported by it. 6 of 2256's 274 are
                # in that position, which is also why the direction counts
                # reconcile as 22 + 258 - 6 = 274 rather than summing to 280.
                "direction": (
                    "both" if r["is_import"] and r["is_importer"]
                    else "imports" if r["is_import"]
                    else "importedBy"
                ),
                # D15: the ONLY source of cluster colour for this view. The
                # neighbourhood's own `cluster` field covers just the 25 enriched
                # entries, and mixing the two would be two instruments for one
                # visual property.
                "subsystem_modularity_id": r["subsystem_modularity_id"],
            }
            for r in rows
        ],
        # Display only -- see _UNRESOLVED_EDGES_SQL. Never priced.
        "unresolved_edges": [
            {"raw_specifier": u["raw_specifier"], "line_number": u["line_number"],
             "kind": u["kind"]}
            for u in unresolved_rows
        ],
        "view_tokens": view_tokens,
        "view_tokens_instrument": "_estimate_tokens(neighborhood)",
        # EXCLUDES the centre file -- see D18. `connected_bytes` includes it.
        "connected_files_distinct": connected_files_distinct,
        "edge_endpoints_total": edge_endpoints_total,
        "overlap_count": edge_endpoints_total - connected_files_distinct,
        "unresolved_excluded": len(neighborhood["imports"]["unresolved"]),
        # A TRIPWIRE, not a formality. size_bytes is NOT NULL and 0 rows are
        # currently 0-or-null on every ingested repo, so this equals
        # connected_files_distinct today. It is returned separately so that the
        # first repo where it does NOT is visible in the payload rather than
        # silently under-pricing the denominator.
        "priced_files": len(priced),
        # INCLUDES the centre file's own size_bytes -- see D18. Scope differs
        # from connected_files_distinct on purpose.
        "connected_bytes": connected_bytes,
        "connected_files_tokens": connected_files_tokens,
        "connected_tokens_instrument": "size_bytes/_CHARS_PER_TOKEN_SOURCE",
        "calibration_status": _CALIBRATION_STATUS,
        "snapshot_sha": neighborhood["snapshot"]["last_ingested_sha"],
        "saved_tokens": connected_files_tokens - view_tokens,
        "saved_ratio": saved_ratio,
        # HOW THIS ENDPOINT'S ESTIMATE COMPARES TO MEASURED GROUND TRUTH -- and
        # null unless there IS ground truth. Populated only for files carrying a
        # checkpoint-3 tiktoken benchmark (today: superset/utils/core.py alone,
        # 0.914). Below 1.0 means the estimate lands UNDER the measured ratio,
        # which is the direction the divisor was rounded to guarantee. A value at
        # or above 1.0 means the UI would overstate against tiktoken and no ratio
        # should be shown. Never computed by analogy for files without a
        # benchmark: a field that means something different per file is worse
        # than a field that is absent.
        # 4dp, not 3. This field's ONLY job is to be checked against the
        # benchmark, and 3dp made 0.9225 unrepresentable -- a field that cannot
        # express the value it exists to report.
        #
        # NOTE: this is NOT bounded below 1.0. That invariant was pinned at ck1c
        # and is FALSE -- it held only because every file checked was a hub. At
        # the floor (scripts/__init__.py, 0 connections) it is 1.0740: the
        # estimator OVERSTATES the ratio there. The measured two-sided envelope
        # is in decisions.md; do not reintroduce a one-sided assertion.
        # D25/D26: display strings, conservative. The UI prints these verbatim.
        # NAMED `ratio_display`, NOT `saved_ratio_display` (D26 said the latter).
        # D7's tripwire bans the substring "saved_ratio" from frontend source,
        # and a component printing `envelope.saved_ratio_display` trips it --
        # a FALSE POSITIVE, since printing a string is display, not arithmetic.
        # The choice was: narrow the tripwire, or rename the field. D26's own
        # stated reason for putting these strings in the backend was to keep the
        # tripwire at ZERO exceptions, citing the `or 0` incident -- so the
        # reason outranks the name. Renamed; tripwire untouched.
        # D29: ABSENT, not clamped, when there are no connected files.
        #
        # `None` rather than a sentinel string, deliberately: the frontend must
        # not be able to render a ratio for these files EVEN BY ACCIDENT, and
        # `null` leaves no string to print. A sentinel like "n/a" would still be
        # a value someone could style as if it were a number.
        #
        # WHY IT IS VOID RATHER THAN JUST SMALL. With zero connections the
        # denominator collapses to the file's OWN bytes (D18 includes the
        # centre), so the ratio becomes (own_bytes / 4.7) over the cost of a
        # neighbourhood that says "no neighbours". Arithmetically fine; it
        # measures nothing. The 219.7x claim rests on SUBSTITUTION -- read the
        # neighbourhood instead of the connected files -- and here there is
        # nothing to substitute, so numerator and denominator answer different
        # questions. Measured: an 18KB unconnected file showed ~10.9x captioned
        # "cheaper than reading every connected file", about an empty set.
        #
        # Clamping to 1.0x was rejected: it would replace a meaningless number
        # with a plausible one, which is the §17.25 failure rather than a fix.
        "ratio_display": (
            _format_saved_ratio(saved_ratio) if connected_files_distinct else None),
        # The caption comes from here too (D26): the frontend prints, it does
        # not compose sentences about numbers it is not allowed to reason about.
        "ratio_absent_reason": (
            None if connected_files_distinct else
            "This file has no connected files, so there is nothing for the graph "
            "to substitute for. A ratio here would compare the cost of reading "
            "the file against the cost of being told it has no neighbours -- two "
            "different questions. The costs below are still real."),
        # The two component counts, as strings, for the same reason and with the
        # same naming constraint: `view_tokens_display` would contain
        # "view_tokens" and trip D7's substring ban. Named for what they MEAN to
        # a reader rather than for the field they come from -- which is better UI
        # language anyway: "what the graph costs" vs "what reading would cost".
        "graph_cost_display": f"{view_tokens:,} tokens",
        "read_cost_display": f"{connected_files_tokens:,} tokens",
        # THE WHOLE SENTENCE, not the parts, because the LABEL is conditional
        # too and the frontend must not choose between phrasings.
        #
        # Found by looking at the rendered page: with zero connected files the
        # caption still read "reading every connected file would cost 3,844
        # tokens" -- about a set with nothing in it, and the 3,844 is the cost of
        # reading THIS file. The same false-caption defect the ratio had, one
        # layer down, and it survived the ratio fix because only the number was
        # suppressed and not the sentence around it.
        "costs_line": (
            f"this view costs {view_tokens:,} tokens · "
            f"reading every connected file would cost {connected_files_tokens:,} tokens"
            if connected_files_distinct else
            f"this view costs {view_tokens:,} tokens · "
            f"reading this file would cost {connected_files_tokens:,} tokens"),
        "envelope_pct": _envelope_pct(),
        # D27: NOT for the UI. A validation artifact that exists only where a
        # benchmark does, so it means something different per file -- §17.25 by
        # construction. Kept in the payload for the test suite and for anyone
        # auditing the estimator; a ?raw tripwire asserts no src/ file prints it.
        "estimator_vs_measured": (
            round(saved_ratio / bench["ratio"], 4)
            if bench and saved_ratio else None),
    }


@router.get("/{repo_id}/files/{file_id}/neighbors")
def get_file_neighbors(
    repo_id: int, file_id: int, scorer: str = "legacy",
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """One file's direct importers and imports, for the per-file Mermaid
    export -- deliberately a SEPARATE query from GET /graph's capped
    payload, not a lookup into it. If Mermaid read from the 400-node-capped
    graph, a real importer excluded by that cap would silently vanish from
    the diagram with no indication why -- the same failure shape as
    letting one mechanism's limit corrupt a different mechanism's
    correctness (see weighted_pagerank's seed-exclusion docstring for the
    earlier instance of this argument).

    Capped here at NEIGHBORS_ENDPOINT_CAP (100) -- generous, and only to
    bound a pathological hub's response size, not to BE Mermaid's real
    cap. Mermaid's own cap (top 15 per direction, applied client-side) is
    a separate concern; `*_total_before_cap` always reports the TRUE
    count (an unbounded COUNT, not `min(true_count, 100)`) so a caller can
    honestly report e.g. "15 of 44" even when 44 is under 100 and the
    endpoint cap never engaged, or "15 of 200" when it did."""
    repo = db.get(Repo, repo_id)
    if not repo:
        raise HTTPException(404, "Repo not found")
    file = db.get(CodeFile, file_id)
    if not file or file.repo_id != repo_id:
        raise HTTPException(404, "File not found in this repo")
    if scorer not in VALID_SCORERS:
        raise HTTPException(400, f"Unknown scorer {scorer!r} -- must be one of {VALID_SCORERS}")

    rank_by_file_id = {
        r.file_id: r
        for r in db.query(CodeFileRank).filter(CodeFileRank.repo_id == repo_id, CodeFileRank.scorer == scorer)
    }

    importer_rows = (
        db.query(CodeImport.from_file_id, CodeImport.kind, CodeImport.cross_root_kind)
        .filter(CodeImport.repo_id == repo_id, CodeImport.to_file_id == file_id)
        .all()
    )  # from_file_id here IS the neighbor -- the file doing the importing
    import_rows = (
        db.query(CodeImport.to_file_id, CodeImport.kind, CodeImport.cross_root_kind)
        .filter(CodeImport.repo_id == repo_id, CodeImport.from_file_id == file_id, CodeImport.to_file_id.isnot(None))
        .all()
    )  # to_file_id here IS the neighbor -- the file being imported
    importers_agg = _resolve_edges_by_neighbor(importer_rows)
    imports_agg = _resolve_edges_by_neighbor(import_rows)

    importers = _serialize_neighbor_list(db, importers_agg, rank_by_file_id)
    imports = _serialize_neighbor_list(db, imports_agg, rank_by_file_id)

    return {
        "file_id": file_id,
        "path": file.path,
        "importers": importers[:NEIGHBORS_ENDPOINT_CAP],
        "importers_total_before_cap": len(importers),
        "imports": imports[:NEIGHBORS_ENDPOINT_CAP],
        "imports_total_before_cap": len(imports),
    }


def _serialize_job(job: RepoJob) -> dict:
    return {
        "id": job.id,
        "repo_id": job.repo_id,
        "status": job.status,
        "stage": job.stage,
        "progress_current": job.progress_current,
        "progress_total": job.progress_total,
        "message": job.message,
        "result": job.result,
        "error": job.error,
        "created_at": job.created_at.isoformat(),
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


@router.post("/{repo_id}/jobs")
def start_job_endpoint(repo_id: int, user: User = Depends(require_write_access), db: Session = Depends(get_db)):
    repo = db.get(Repo, repo_id)
    if not repo:
        raise HTTPException(404, "Repo not found")
    try:
        job_id = jobs.start_job(repo_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"job_id": job_id}


@router.get("/{repo_id}/jobs/latest")
def latest_job(repo_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    job = (
        db.query(RepoJob)
        .filter(RepoJob.repo_id == repo_id)
        .order_by(RepoJob.created_at.desc())
        .first()
    )
    if not job:
        raise HTTPException(404, "No jobs for this repo yet")
    return _serialize_job(job)


@router.get("/{repo_id}/jobs/{job_id}/stream")
def stream_job(repo_id: int, job_id: int, user: User = Depends(get_current_user)):
    """Polls the repo_jobs row (a fresh session per poll, not the request's --
    a long-lived session would risk reading a stale snapshot instead of the
    background thread's latest commit) and yields a `type`-discriminated SSE
    frame on every change, same wire format as /api/chat/stream. Reconnect-safe:
    a client that drops and reopens this just resumes reading current state."""

    def event_stream():
        last_signature = None
        while True:
            poll_db = SessionLocal()
            try:
                job = poll_db.get(RepoJob, job_id)
            finally:
                poll_db.close()

            if job is None or job.repo_id != repo_id:
                yield f"data: {json.dumps({'type': 'error', 'message': 'Job not found'})}\n\n"
                return

            signature = (job.status, job.stage, job.progress_current, job.progress_total, job.message)
            if signature != last_signature:
                yield f"data: {json.dumps({'type': 'progress', 'status': job.status, 'stage': job.stage, 'current': job.progress_current, 'total': job.progress_total, 'message': job.message})}\n\n"
                last_signature = signature

            if job.status == "done":
                yield f"data: {json.dumps({'type': 'done', 'result': job.result})}\n\n"
                return
            if job.status == "failed":
                yield f"data: {json.dumps({'type': 'error', 'message': job.error or 'Job failed'})}\n\n"
                return
            time.sleep(0.5)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def _serialize_subsystem(s: CodeSubsystem) -> dict:
    return {
        "id": s.id,
        "algorithm": s.algorithm,
        "cluster_index": s.cluster_index,
        "member_count": s.member_count,
        "dominant_prefix_label": s.dominant_prefix_label,
        "dominant_prefix_count": s.dominant_prefix_count,
        "top_fan_in_label": s.top_fan_in_label,
        "top_fan_in_file_id": s.top_fan_in_file_id,
        "custom_label": s.custom_label,
        "active_label_rule": s.active_label_rule,
        "computed_at": s.computed_at.isoformat(),
    }


@router.post("/{repo_id}/subsystems")
def compute_subsystems_endpoint(
    repo_id: int, user: User = Depends(require_write_access), db: Session = Depends(get_db),
):
    """Phase I1: community-detection clustering over the resolved import
    graph (see subsystems.py's module docstring for why two algorithms run
    and what each answers). Synchronous, same convention as POST /rank --
    this repo's scale (hundreds of files) makes it fast enough not to need
    a background job."""
    repo = db.get(Repo, repo_id)
    if not repo:
        raise HTTPException(404, "Repo not found")
    try:
        return compute_subsystems(db, repo)
    except RepoBusyError as e:
        raise HTTPException(409, str(e))


def _serialize_snapshot(db: Session, snapshot: CodeHealthSnapshot, repo: Repo) -> dict:
    """Snapshot + trend, with the coverage disclosure carried as structured
    data on the Architecture axis.

    The disclosure is part of the payload, not a rendering convention: a UI
    that receives a score must also receive the scope that score applies to,
    so it cannot show 10.00 as "healthy architecture" while the same product
    shows the user directory-level cycles elsewhere. Enforced by
    TestArchitectureDisclosureContract in test_repos_api.py."""
    return {
        "snapshot": {
            "id": snapshot.id,
            "branch": snapshot.branch,
            "head_sha": snapshot.head_sha,
            # Load-bearing provenance: for a local repo we analyse the live
            # working directory, so HEAD may not describe the analysed bytes.
            "working_tree_dirty": snapshot.working_tree_dirty,
            "analyzer_version": snapshot.analyzer_version,
            "thresholds_version": snapshot.thresholds_version,
            "weights_version": snapshot.weights_version,
            "computed_at": snapshot.computed_at.isoformat(),
            "files_scored": snapshot.files_scored,
            "files_na": snapshot.files_na,
            # Served WITH files_na, always. files_na alone reads as "everything
            # else was scored"; on apache/superset it is 0 while 782 files are
            # scored on architecture only. See the column comment on the model.
            "files_partially_na": snapshot.files_partially_na,
            "inputs_complete": snapshot.inputs_complete,
        },
        "axes": snapshot.axis_summary,
        "trend": trend_delta(db, snapshot),
        # Whether this stored snapshot still describes the repo as it is now.
        # Served with the scores rather than left for the caller to work out,
        # for the same reason the architecture disclosure is: a client that
        # receives a number must receive the conditions under which it holds.
        "staleness": snapshot_staleness(db, repo, snapshot),
    }


@router.post("/{repo_id}/health")
def compute_health_endpoint(
    repo_id: int, user: User = Depends(require_write_access), db: Session = Depends(get_db),
):
    """Runs the analyzer and writes ONE immutable snapshot, atomically -- see
    health_snapshots.create_snapshot. Nothing is written unless the whole run
    succeeds, so a trend line can never mistake a partial run for a real
    change."""
    repo = db.get(Repo, repo_id)
    if not repo:
        raise HTTPException(404, "Repo not found")
    persist_graph_structure(db, repo)
    snapshot = create_snapshot(db, repo)
    return _serialize_snapshot(db, snapshot, repo)


@router.get("/{repo_id}/health")
def get_health(repo_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Latest snapshot, read-only. 404 when none exists -- deliberately not an
    empty scorecard, which would read as "measured and fine"."""
    repo = db.get(Repo, repo_id)
    if not repo:
        raise HTTPException(404, "Repo not found")
    snapshot = (
        db.query(CodeHealthSnapshot)
        .filter(CodeHealthSnapshot.repo_id == repo_id)
        .order_by(CodeHealthSnapshot.computed_at.desc(), CodeHealthSnapshot.id.desc())
        .first()
    )
    if not snapshot:
        raise HTTPException(404, "No code-health snapshot for this repo yet.")
    return _serialize_snapshot(db, snapshot, repo)


@router.get("/{repo_id}/health/directories")
def get_health_directories(
    repo_id: int, max_depth: Optional[int] = None, weak_limit: int = 5,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Per-directory aggregates plus the change-cohort comparison, both derived
    from the latest snapshot's stored per-file rows.

    Read-only and additive: no threshold, weight or marker is involved, so
    these numbers cannot disagree with the scores they summarise. Works on
    snapshots taken before this endpoint existed, since it re-reads rows rather
    than requiring anything new to have been written.

    404 with no snapshot, matching GET /health -- an empty directory table
    would read as "measured and nothing to report"."""
    repo = db.get(Repo, repo_id)
    if not repo:
        raise HTTPException(404, "Repo not found")
    if max_depth is not None and max_depth < 0:
        raise HTTPException(400, "max_depth must be >= 0")
    snapshot = (
        db.query(CodeHealthSnapshot)
        .filter(CodeHealthSnapshot.repo_id == repo_id)
        .order_by(CodeHealthSnapshot.computed_at.desc(), CodeHealthSnapshot.id.desc())
        .first()
    )
    if not snapshot:
        raise HTTPException(404, "No code-health snapshot for this repo yet.")
    payload = build_rollup(db, repo, snapshot, max_depth=max_depth, weak_limit=weak_limit)
    # The staleness verdict travels with any surface that shows these numbers,
    # for the same reason it travels with the scores themselves: a directory
    # table built from a snapshot describing files that no longer exist is
    # exactly as misleading as the headline was.
    payload["staleness"] = snapshot_staleness(db, repo, snapshot)
    return payload


@router.get("/{repo_id}/health/files")
def get_health_files(
    repo_id: int, sort: str = "adjusted_exposure", limit: int = 50,
    # Optional lookup for ONE file. Additive: absent, the response is exactly
    # what it was. The Focus view needs this file's health, and a ranked slice
    # cannot answer that -- the file being looked at is usually not in the top
    # 50 by exposure, so filtering the list client-side would silently show
    # nothing for most files.
    file_id: Optional[int] = None,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Per-file results from the latest snapshot, with stored explanations.

    Effort-aware ranking shows BOTH columns (contract Â§11): `exposure` and
    `adjusted_exposure`. Files whose axis was N/A are excluded from ranking
    and counted separately rather than sorted as if they scored zero."""
    repo = db.get(Repo, repo_id)
    if not repo:
        raise HTTPException(404, "Repo not found")
    snapshot = (
        db.query(CodeHealthSnapshot)
        .filter(CodeHealthSnapshot.repo_id == repo_id)
        .order_by(CodeHealthSnapshot.computed_at.desc(), CodeHealthSnapshot.id.desc())
        .first()
    )
    if not snapshot:
        raise HTTPException(404, "No code-health snapshot for this repo yet.")
    if sort not in ("adjusted_exposure", "exposure", "maintainability", "architecture_health"):
        raise HTTPException(400, f"Unknown sort {sort!r}")

    rows = db.query(CodeFileHealth).filter(CodeFileHealth.snapshot_id == snapshot.id).all()

    if file_id is not None:
        # One file, and it is returned whether or not it is RANKABLE by `sort`.
        # A file whose hotspot axis is N/A still has maintainability, an
        # architecture score and its stored explanations, and dropping it here
        # because it cannot be sorted would hide health data that exists --
        # exclude-don't-zero applies to the ranking, not to a direct lookup.
        row = next((r for r in rows if r.file_id == file_id), None)
        if row is None:
            raise HTTPException(
                404,
                f"No health record for file {file_id} in snapshot {snapshot.id} -- the file "
                "may post-date the snapshot, or have been excluded from analysis.",
            )
        return {
            "snapshot_id": snapshot.id,
            "sort": sort,
            "excluded_na": 0,
            "files": [_serialize_file_health(row)],
        }

    column = {
        "adjusted_exposure": lambda r: r.adjusted_exposure,
        "exposure": lambda r: r.change_hotspot_points,
        "maintainability": lambda r: r.maintainability,
        "architecture_health": lambda r: r.architecture_health,
    }[sort]

    rankable = [r for r in rows if column(r) is not None]
    excluded = len(rows) - len(rankable)
    descending = sort in ("adjusted_exposure", "exposure")
    rankable.sort(key=lambda r: column(r), reverse=descending)

    return {
        "snapshot_id": snapshot.id,
        "sort": sort,
        "excluded_na": excluded,
        "files": [_serialize_file_health(r) for r in rankable[:limit]],
    }


def _serialize_file_health(r: CodeFileHealth) -> dict:
    """One shape, used by both the ranked list and the single-file lookup --
    the two must not drift, or a client would need to know which path produced
    the row it is holding."""
    return {
        "file_id": r.file_id, "path": r.path, "nloc": r.nloc,
        "maintainability": r.maintainability,
        "architecture_health": r.architecture_health,
        "exposure": r.change_hotspot_points,
        "adjusted_exposure": r.adjusted_exposure,
        "explanation": r.explanation,
    }


def _latest_snapshot_or_404(db: Session, repo_id: int) -> CodeHealthSnapshot:
    snapshot = (
        db.query(CodeHealthSnapshot)
        .filter(CodeHealthSnapshot.repo_id == repo_id)
        .order_by(CodeHealthSnapshot.computed_at.desc(), CodeHealthSnapshot.id.desc())
        .first()
    )
    if not snapshot:
        raise HTTPException(404, "No code-health snapshot for this repo yet.")
    return snapshot


def _findings_rows(db: Session, snapshot: CodeHealthSnapshot, floor: float, cap: int):
    rows = db.query(CodeFileHealth).filter(CodeFileHealth.snapshot_id == snapshot.id).all()
    findings, hidden, churn_files = findings_queue.extract_findings(
        [(r.path, r.file_id, r.adjusted_exposure, r.explanation) for r in rows], floor=floor)
    return findings_queue.build_rows(findings, max_files=cap), findings, hidden, churn_files


@router.get("/{repo_id}/findings")
def get_findings(
    repo_id: int,
    floor: float = findings_queue.SEVERITY_FLOOR,
    max_files: int = findings_queue.MAX_FILES_PER_ROW,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Phase L: health markers grouped into pickable work -- see
    findings_queue.py for why rows are (marker x directory) and why the
    directory granularity is adaptive rather than a fixed depth.

    Row SUMMARIES only; members come from /findings/files. Inline they cost
    296 KB on apache/superset's 109 rows.

    `hidden_below_floor` is served with the list, not left for the caller to
    work out, because a floor a user cannot see is indistinguishable from a
    tool that missed something. Same reasoning as the architecture coverage
    disclosure travelling with the architecture score.

    404 with no snapshot, matching every other health surface -- an empty queue
    would read as "measured and nothing to fix"."""
    repo = db.get(Repo, repo_id)
    if not repo:
        raise HTTPException(404, "Repo not found")
    if not 0.0 <= floor <= 1.0:
        raise HTTPException(400, "floor must be between 0.0 and 1.0")
    if max_files < 1:
        raise HTTPException(400, "max_files must be at least 1")
    snapshot = _latest_snapshot_or_404(db, repo_id)
    rows, findings, hidden, churn_files = _findings_rows(db, snapshot, floor, max_files)
    return {
        "snapshot_id": snapshot.id,
        "floor": floor,
        "max_files_per_row": max_files,
        "shown": len(findings),
        "hidden_below_floor": hidden,
        # Not a findings count: churn is the ordering weight, never a row.
        "churn_weighted_files": churn_files,
        "rows": [r.to_dict() for r in rows],
        "staleness": snapshot_staleness(db, repo, snapshot),
    }


@router.get("/{repo_id}/findings/files")
def get_findings_files(
    repo_id: int, marker: str, directory: str,
    floor: float = findings_queue.SEVERITY_FLOOR,
    max_files: int = findings_queue.MAX_FILES_PER_ROW,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Members of one queue row, worst first.

    Re-derives the same split rather than storing row ids: the aggregation is
    a pure function of (snapshot, floor, max_files), all three of which the
    caller passes back, so the same row is reproduced exactly. Costs ~280 ms,
    nearly all of it reading the snapshot's rows.

    Purity cuts both ways, which is why the parameters are ECHOED in the
    response. A caller that passes a floor or cap other than the one that
    produced the list it is looking at gets a different, internally consistent
    split -- and would receive members for a row that was never displayed, with
    nothing in the payload to say so. Serving the triple back makes the
    mismatch detectable rather than silent. The same reasoning as the snapshot
    id: a client that receives a result must receive the conditions that
    produced it."""
    repo = db.get(Repo, repo_id)
    if not repo:
        raise HTTPException(404, "Repo not found")
    if not 0.0 <= floor <= 1.0:
        raise HTTPException(400, "floor must be between 0.0 and 1.0")
    if max_files < 1:
        raise HTTPException(400, "max_files must be at least 1")
    snapshot = _latest_snapshot_or_404(db, repo_id)
    rows, _, _, _ = _findings_rows(db, snapshot, floor, max_files)
    for row in rows:
        if row.marker == marker and row.directory == directory:
            return {
                "snapshot_id": snapshot.id,
                "floor": floor,
                "max_files_per_row": max_files,
                "marker": row.marker,
                "directory": row.directory,
                "file_count": row.file_count,
                "files": row.files_payload(),
            }
    # A row that does not exist under THESE parameters. Most likely the caller
    # is holding a list built under different ones -- said explicitly, because
    # "not found" alone would send someone looking for a missing file.
    raise HTTPException(
        404,
        f"No queue row for marker {marker!r} in {directory!r} at "
        f"floor={floor} max_files={max_files}. If these differ from the "
        f"parameters that produced the list, the split differs too.",
    )


@router.get("/{repo_id}/module-preview")
def get_module_preview(
    repo_id: int, algorithm: str = "modularity",
    topic_strategy: str = module_mapping.DEFAULT_TOPIC_STRATEGY,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Phase 4 groundwork: what modules this repo's subsystems WOULD produce.

    READ-ONLY. Computes and returns; writes nothing, inserts nothing, and no
    other code path consumes it. It exists so the mapping can be seen and
    argued with BEFORE a row is written into tables that hold hand-curated
    content -- `modules`/`topics`/`resources` mix curated and derived rows
    already, and getting that mixing wrong is the hard-to-unwind case.

    Everything here is derived from rows that already exist: `code_subsystems`
    for the groups, `code_files` for membership, `code_file_ranks` for the
    ordering. Nothing is invented and no prose is generated -- see
    module_mapping.py for why the summary is deliberately empty.

    Subsystems too small to be a module are RETURNED with a `skipped_reason`
    rather than filtered out, so the preview's counts can be checked against
    the Dependency Clusters tab instead of silently disagreeing with it.

    `topic_strategy` is exposed because the topic level is the part of this
    mapping the data does NOT supply -- see module_mapping.py for the three
    candidates and what each measured against a 3-8 target (none is close).
    Selectable so the shape can be compared from real output rather than
    argued from a docstring."""
    repo = db.get(Repo, repo_id)
    if not repo:
        raise HTTPException(404, "Repo not found")
    if algorithm not in VALID_ALGORITHMS:
        raise HTTPException(400, f"Unknown algorithm {algorithm!r} -- must be one of {VALID_ALGORITHMS}")
    if topic_strategy not in module_mapping.TOPIC_STRATEGIES:
        raise HTTPException(
            400,
            f"Unknown topic_strategy {topic_strategy!r} -- must be one of "
            f"{sorted(module_mapping.TOPIC_STRATEGIES)}",
        )

    column = subsystem_column_for(algorithm)
    subsystems = (
        db.query(CodeSubsystem)
        .filter(CodeSubsystem.repo_id == repo_id, CodeSubsystem.algorithm == algorithm)
        .order_by(CodeSubsystem.member_count.desc(), CodeSubsystem.id.asc())
        .all()
    )
    if not subsystems:
        raise HTTPException(
            404,
            f"No {algorithm} clustering for this repo yet -- run clustering first. "
            "An empty preview would read as 'this repo produces no modules'.",
        )

    modules = _build_repo_candidate_modules(db, repo_id, algorithm, topic_strategy, subsystems)

    return {
        "repo_id": repo_id,
        "algorithm": algorithm,
        "topic_strategy": topic_strategy,
        "available_topic_strategies": sorted(module_mapping.TOPIC_STRATEGIES),
        "writes_nothing": True,
        "summary": module_mapping.summarise(modules, topic_strategy=topic_strategy),
        "modules": [m.to_dict() for m in modules],
    }


def _build_repo_candidate_modules(
    db: Session, repo_id: int, algorithm: str, topic_strategy: str, subsystems: list,
) -> list:
    """Thin alias for roadmap_persist.build_candidate_modules.

    The build moved into the service layer when persistence became a THIRD
    consumer alongside /module-preview and /roadmap-preview. Keeping a
    preview's modules and a written module in step is the same requirement
    that made the two previews share a build in the first place, one step
    further: the rows written must be provably the rows previewed.
    """
    return roadmap_persist.build_candidate_modules(
        db, repo_id, algorithm, topic_strategy, subsystems)


@router.get("/{repo_id}/roadmap-preview")
def get_roadmap_preview(
    repo_id: int, algorithm: str = "modularity",
    topic_strategy: str = module_mapping.DEFAULT_TOPIC_STRATEGY,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """What ONE ContentRoadmap for this repo would look like: the same
    modules /module-preview computes (see _build_repo_candidate_modules --
    shared, so the two previews cannot silently disagree on what a module
    IS), grouped into stages by dependency layer instead of listed flat.

    READ-ONLY, same contract as /module-preview: computes and returns,
    writes nothing, inserts nothing. ContentRoadmap/RoadmapStage/RoadmapNode
    already have the exact shape needed (an ordered composition of module
    references) -- nothing here is a schema gap, only unwritten code, and
    this endpoint stays on the read side of that gap deliberately.

    Layers come from the same BFS-from-entry-points computation the file
    graph and the Layers view already use (compute_layers over the resolved
    import graph, entry_ids = seed-eligible files) -- not recomputed
    differently here, so a module's stage means the same "how many hops
    from an entry point" thing a file's "Layer N" column already means.
    """
    repo = db.get(Repo, repo_id)
    if not repo:
        raise HTTPException(404, "Repo not found")
    if algorithm not in VALID_ALGORITHMS:
        raise HTTPException(400, f"Unknown algorithm {algorithm!r} -- must be one of {VALID_ALGORITHMS}")
    if topic_strategy not in module_mapping.TOPIC_STRATEGIES:
        raise HTTPException(
            400,
            f"Unknown topic_strategy {topic_strategy!r} -- must be one of "
            f"{sorted(module_mapping.TOPIC_STRATEGIES)}",
        )

    subsystems = (
        db.query(CodeSubsystem)
        .filter(CodeSubsystem.repo_id == repo_id, CodeSubsystem.algorithm == algorithm)
        .order_by(CodeSubsystem.member_count.desc(), CodeSubsystem.id.asc())
        .all()
    )
    if not subsystems:
        raise HTTPException(
            404,
            f"No {algorithm} clustering for this repo yet -- run clustering first. "
            "An empty preview would read as 'this repo produces no modules'.",
        )

    # The identical read-only half persistence runs, so a preview and a
    # written roadmap cannot disagree about what this repo's roadmap IS.
    modules, staging = roadmap_persist.stage_repo_modules(
        db, repo, algorithm, topic_strategy, subsystems)
    stages = staging["stages"]
    unreachable_count = next((len(s["modules"]) for s in stages if s["title"] == "Unreachable"), 0)

    return {
        "repo_id": repo_id,
        "algorithm": algorithm,
        "topic_strategy": topic_strategy,
        "writes_nothing": True,
        "staging_basis": staging["basis"],
        "layer_coverage": staging["layer_coverage"],
        "layer_coverage_threshold": staging["layer_coverage_threshold"],
        "basis_reason": staging["basis_reason"],
        "stage_count": len(stages),
        "modules_produced": sum(1 for m in modules if m.skipped_reason is None),
        "unreachable_module_count": unreachable_count,
        "stages": [
            {"title": s["title"], "module_count": len(s["modules"]),
             "modules": [m.to_dict() for m in s["modules"]]}
            for s in stages
        ],
    }


@router.post("/{repo_id}/roadmap")
def create_repo_roadmap(
    repo_id: int, algorithm: str = "modularity",
    topic_strategy: str = module_mapping.DEFAULT_TOPIC_STRATEGY,
    user: User = Depends(require_write_access), db: Session = Depends(get_db),
):
    """Write this repo's derived roadmap into the curated tables.

    The write counterpart to /roadmap-preview, and the first code in this
    project that puts derived rows in `modules`/`topics`/`resources`/
    `content_roadmaps` alongside hand-written seed content. Both endpoints run
    the SAME read-only half (roadmap_persist.stage_repo_modules), so what gets
    written is what the preview showed.

    Idempotent: re-running upserts by slug and REUSES topic ids, so
    `topic_progress` survives. The response reports every row created, reused
    and deleted, including `topic_progress_rows_deleted` -- stated even when
    zero, because "no progress was lost" is a result rather than the absence
    of one.

    Held under the per-repo advisory lock: this reads the clustering and the
    resolved import graph, so it must not run inside an in-flight ingest.
    """
    repo = db.get(Repo, repo_id)
    if not repo:
        raise HTTPException(404, "Repo not found")
    if algorithm not in VALID_ALGORITHMS:
        raise HTTPException(400, f"Unknown algorithm {algorithm!r} -- must be one of {VALID_ALGORITHMS}")
    if topic_strategy not in module_mapping.TOPIC_STRATEGIES:
        raise HTTPException(
            400,
            f"Unknown topic_strategy {topic_strategy!r} -- must be one of "
            f"{sorted(module_mapping.TOPIC_STRATEGIES)}",
        )
    try:
        with repo_lock.repo_lock(repo_id, "roadmap"):
            try:
                return roadmap_persist.persist_repo_roadmap(
                    db, repo, algorithm=algorithm, topic_strategy=topic_strategy,
                    # last_ingested_sha, not a freshly-read HEAD: the resources
                    # describe the files INGEST saw, and stamping them with a
                    # newer HEAD would claim provenance the rows do not have.
                    commit_sha=repo.last_ingested_sha,
                )
            except ValueError as e:
                raise HTTPException(400, str(e))
    except RepoBusyError as e:
        raise HTTPException(409, str(e))


@router.post("/{repo_id}/cards")
def generate_repo_cards_endpoint(
    repo_id: int, card_source: str = card_generation.SOURCE_DETERMINISTIC,
    cap: int = card_generation.MAX_CARDS_PER_MODULE,
    user: User = Depends(require_write_access), db: Session = Depends(get_db),
):
    """Regenerate this repo's comprehension cards (Phase 5).

    Requires the roadmap to exist -- cards attach to persisted modules, and
    generating them for nothing would report success over an empty set.

    `card_source` selects the generator through the same dispatch table the
    `card_source` COLUMN stores, so a row and the function that produced it
    cannot drift apart. Passing "llm" today raises NotImplementedError by
    design: the seam is declared, not built.

    The response carries the conservation equation (rows before, after,
    expected) alongside the counts, and reports zero-valued counters rather
    than omitting them.
    """
    repo = db.get(Repo, repo_id)
    if not repo:
        raise HTTPException(404, "Repo not found")
    try:
        with repo_lock.repo_lock(repo_id, "cards"):
            try:
                return card_persist.generate_repo_cards(
                    db, repo, card_source=card_source, cap=cap,
                    commit_sha=repo.last_ingested_sha,
                )
            except ValueError as e:
                raise HTTPException(400, str(e))
            except NotImplementedError as e:
                # 501, not 400: the request is well formed and the capability
                # is declared but unbuilt. A 400 would blame the caller.
                raise HTTPException(501, str(e))
    except RepoBusyError as e:
        raise HTTPException(409, str(e))


@router.get("/{repo_id}/cards")
def get_repo_cards(
    repo_id: int, module_id: Optional[int] = None,
    card_source: Optional[str] = None, limit: int = 50, offset: int = 0,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """This repo's cards, newest generation only (they are replaced wholesale).

    `answer` and `rationale` are deliberately INCLUDED. These are a question
    bank for review, not a live exam -- an attempt table that would need to
    withhold answers does not exist yet, and pretending otherwise by hiding
    them here would be security theatre over a GET that any reader can run.
    When attempts exist, the withholding belongs on that endpoint.
    """
    repo = db.get(Repo, repo_id)
    if not repo:
        raise HTTPException(404, "Repo not found")

    q = db.query(ComprehensionCard).filter(ComprehensionCard.code_repo_id == repo_id)
    if module_id is not None:
        q = q.filter(ComprehensionCard.module_id == module_id)
    if card_source is not None:
        q = q.filter(ComprehensionCard.card_source == card_source)
    total = q.count()
    rows = (q.order_by(ComprehensionCard.module_id, ComprehensionCard.order_index)
            .offset(offset).limit(limit).all())

    by_source = dict(
        db.query(ComprehensionCard.card_source, func.count(ComprehensionCard.id))
        .filter(ComprehensionCard.code_repo_id == repo_id)
        .group_by(ComprehensionCard.card_source).all()
    )
    return {
        "repo_id": repo_id,
        "total": total,
        "returned": len(rows),
        # The truncation is stated rather than implied -- same rule as the
        # module preview's resource cap.
        "truncated": offset + len(rows) < total,
        "offset": offset,
        "limit": limit,
        # The seam, visible: a reader can see which sources this repo has
        # cards from without inferring it from the rows returned.
        "cards_by_source": by_source,
        "cards": [
            {
                "id": c.id, "module_id": c.module_id, "template": c.template,
                "card_source": c.card_source, "question": c.question,
                "options": c.options, "answer": c.answer,
                "rationale": c.rationale, "subject_path": c.subject_path,
                "code_commit_sha": c.code_commit_sha, "order_index": c.order_index,
            }
            for c in rows
        ],
    }


class CardAnswerIn(BaseModel):
    response: str


@router.post("/{repo_id}/cards/{card_id}/grade")
def grade_repo_card(
    repo_id: int, card_id: int, payload: CardAnswerIn,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Grade one answer against the stored card.

    **The grading rule lives here and only here.** `card_grading.grade_card`
    normalises with `" ".join(text.split()).casefold()` before comparing, so a
    client that did its own string match would agree with this endpoint until
    the day someone changed that normalisation -- at which point a card the
    backend calls correct would be marked wrong in the browser, or the reverse,
    with nothing failing. That is §17.28 exactly: a mirrored implementation is a
    consumer nobody remembers is there. A round trip per answer is invisible to
    someone reading a question and choosing an option, and it buys one rule with
    one home.

    Deliberately NOT persisting the result. Attempt history is a separate
    checkpoint, and writing rows from a viewer that has not been verified yet
    would mean debugging persistence and presentation together.
    """
    card = db.get(ComprehensionCard, card_id)
    if card is None or card.code_repo_id != repo_id:
        # Scoped by repo as well as id: a card id from another repo must not be
        # gradeable through this repo's URL, or the route lies about what it
        # addresses.
        raise HTTPException(404, "Card not found for this repo")
    try:
        grade = card_grading.grade_card(card, payload.response)
    except NotImplementedError as e:
        # The llm source is a declared seam. 501, not 500: the request is well
        # formed and the capability is declared but unbuilt.
        raise HTTPException(501, str(e))
    except ValueError as e:
        # A card with no stored answer cannot grade anything -- that is a defect
        # in the card, not in the learner's answer.
        raise HTTPException(500, str(e))
    return {
        "card_id": card.id,
        "correct": grade.correct,
        "score": grade.score,
        "rationale": grade.rationale,
        "answer": card.answer,
        "card_source": card.card_source,
    }


@router.get("/{repo_id}/overview")
def get_overview(repo_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Phase K1: aggregate stats, structural health, and change hotspots
    for the repo landing page. Purely a read over what ingest/rank/
    clustering already persisted -- no filesystem walk, no re-parse, no
    re-clustering (H1.5's rule).

    The `health` block is STRUCTURAL health, not defect prediction: this
    system holds no defect data at all, and `hotspots` is a churn x fan-in
    risk proxy that reports itself unavailable rather than ranking files
    by a constant when churn has no variance (the shallow-clone case).
    See overview.py's module docstring."""
    repo = db.get(Repo, repo_id)
    if not repo:
        raise HTTPException(404, "Repo not found")
    return build_overview(db, repo)


@router.post("/{repo_id}/subsystems/hdbscan")
def compute_subsystems_hdbscan_endpoint(
    repo_id: int, user: User = Depends(require_write_access), db: Session = Depends(get_db),
):
    """Phase I6: a third, separately-triggered clustering algorithm --
    HDBSCAN over FastEmbed embeddings of each file's symbol signatures and
    docstrings (subsystems.py/embeddings.py), rather than the import graph
    modularity/Louvain use. Deliberately its own endpoint, not folded into
    POST /subsystems above: embedding every file is real CPU work (seconds,
    not the near-instant graph math the other two do), and it answers a
    different question (what a file's code says it does, not who imports
    it) worth keeping optional and explicit rather than automatic.

    FastEmbed runs entirely local -- ONNX runtime, CPU-only, no network
    call, no data leaving this machine. An earlier design for this feature
    considered a hosted embeddings API gated behind an explicit
    confirm-before-sending step; with FastEmbed there is nothing to
    confirm, since nothing is sent anywhere -- this endpoint needs no such
    gate."""
    repo = db.get(Repo, repo_id)
    if not repo:
        raise HTTPException(404, "Repo not found")
    try:
        return compute_subsystems_hdbscan(db, repo)
    except RepoBusyError as e:
        raise HTTPException(409, str(e))


@router.get("/{repo_id}/subsystems")
def get_subsystems(
    repo_id: int, algorithm: str = "modularity",
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Reads ONLY what a POST /subsystems or /subsystems/hdbscan run
    already persisted -- no live graph rebuild, no live clustering re-run,
    no live embedding. Filtered by BOTH repo_id and algorithm, not just
    repo_id -- the exact scoping bug G1 fixed for CodeFileRank/scorer,
    applied here to a second dimension that has the same "N incompatible
    values sharing one table" shape."""
    repo = db.get(Repo, repo_id)
    if not repo:
        raise HTTPException(404, "Repo not found")
    if algorithm not in VALID_ALGORITHMS:
        raise HTTPException(400, f"Unknown algorithm {algorithm!r} -- must be one of {VALID_ALGORITHMS}")

    subsystem_col = subsystem_column_for(algorithm)
    rows = (
        db.query(CodeSubsystem)
        .filter(CodeSubsystem.repo_id == repo_id, CodeSubsystem.algorithm == algorithm)
        .order_by(CodeSubsystem.cluster_index.asc())
        .all()
    )
    unclustered_count = (
        db.query(CodeFile)
        .filter(CodeFile.repo_id == repo_id, subsystem_col.is_(None))
        .count()
    )
    # hdbscan's agreement/cycle_coherence are its own fields on Repo (see
    # models.py) -- modularity vs Louvain's agreement number specifically
    # means "modularity vs Louvain" everywhere else it's read, so hdbscan
    # (compared against modularity instead) can't reuse those same fields
    # without silently changing what an existing caller's number means.
    if algorithm == "hdbscan":
        agreement = repo.subsystem_hdbscan_agreement
        cycle_coherence = repo.subsystem_hdbscan_cycle_coherence
    else:
        agreement = repo.subsystem_algorithm_agreement
        cycle_coherence = repo.subsystem_cycle_coherence
    return {
        "algorithm": algorithm,
        "agreement": agreement,
        "cycle_coherence": cycle_coherence,
        "unclustered_count": unclustered_count,
        "subsystems": [_serialize_subsystem(s) for s in rows],
    }


@router.get("/{repo_id}/subsystems/{subsystem_id}/members")
def get_subsystem_members(
    repo_id: int, subsystem_id: int,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    subsystem = db.get(CodeSubsystem, subsystem_id)
    if not subsystem or subsystem.repo_id != repo_id:
        raise HTTPException(404, "Subsystem not found")
    subsystem_col = subsystem_column_for(subsystem.algorithm)
    files = (
        db.query(CodeFile)
        .filter(CodeFile.repo_id == repo_id, subsystem_col == subsystem_id)
        .order_by(CodeFile.path.asc())
        .all()
    )
    return {"files": [{"id": f.id, "path": f.path, "language": f.language, "fan_in": f.fan_in} for f in files]}


@router.patch("/{repo_id}/subsystems/{subsystem_id}")
def rename_subsystem(
    repo_id: int, subsystem_id: int, payload: SubsystemRenameIn,
    user: User = Depends(require_write_access), db: Session = Depends(get_db),
):
    subsystem = db.get(CodeSubsystem, subsystem_id)
    if not subsystem or subsystem.repo_id != repo_id:
        raise HTTPException(404, "Subsystem not found")
    subsystem.custom_label = payload.custom_label
    subsystem.active_label_rule = "custom"
    db.commit()
    return _serialize_subsystem(subsystem)

