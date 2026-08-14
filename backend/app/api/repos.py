import json
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.security import get_current_user, require_write_access
from app.db.database import SessionLocal, get_db
from app.db.models import (
    CodeFile, CodeFileHealth, CodeFileRank, CodeHealthSnapshot, CodeImport,
    CodeSubsystem, Repo, RepoJob, User,
)
from app.services.codebase import (
    deletion, edge_weights, findings_queue, jobs, module_mapping, registry, repo_lock,
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
from app.services.codebase.ranking import _build_graph, rank_repo
from app.services.codebase.repo_lock import RepoBusyError
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
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """One row per file: CodeFileRank filtered by BOTH repo_id and scorer,
    not just repo_id -- the earlier version of this endpoint filtered on
    repo_id alone and sorted by score across all three scorers' rows mixed
    together, which is both duplicate rows per file AND a meaningless sort
    order (three incompatible scales sorted as one). Ordered by the stored
    `rank` (assigned once, at rank-run time, over the whole repo) rather
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
    return {
        "scorer": scorer,
        "reduced_confidence": repo.reduced_confidence,
        "files": [_serialize_rank(r, f) for r, f in rows],
    }


GRAPH_NODE_LIMIT_DEFAULT = 400
NEIGHBORS_ENDPOINT_CAP = 100
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
        "files": [
            {
                "file_id": r.file_id, "path": r.path, "nloc": r.nloc,
                "maintainability": r.maintainability,
                "architecture_health": r.architecture_health,
                "exposure": r.change_hotspot_points,
                "adjusted_exposure": r.adjusted_exposure,
                "explanation": r.explanation,
            }
            for r in rankable[:limit]
        ],
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

    # One pass for every member file, then grouped in memory: a query per
    # subsystem would be 250+ round trips on apache/superset.
    rank_by_file = dict(
        db.query(CodeFileRank.file_id, CodeFileRank.rank)
        .filter(CodeFileRank.repo_id == repo_id, CodeFileRank.scorer == "legacy")
        .all()
    )
    members_by_subsystem: dict[int, list[dict]] = {}
    for file_id, path, category, sid in (
        db.query(CodeFile.id, CodeFile.path, CodeFile.prior_category, column)
        .filter(CodeFile.repo_id == repo_id, column.isnot(None))
        .all()
    ):
        members_by_subsystem.setdefault(sid, []).append(
            {"path": path, "file_id": file_id, "rank": rank_by_file.get(file_id),
             "prior_category": category}
        )

    modules = [
        module_mapping.map_subsystem_to_module(
            repo_id=repo_id,
            subsystem_id=s.id,
            subsystem_label=s.custom_label or s.dominant_prefix_label or s.top_fan_in_label,
            member_count=s.member_count,
            members=members_by_subsystem.get(s.id, []),
            topic_strategy=topic_strategy,
        )
        for s in subsystems
    ]

    return {
        "repo_id": repo_id,
        "algorithm": algorithm,
        "topic_strategy": topic_strategy,
        "available_topic_strategies": sorted(module_mapping.TOPIC_STRATEGIES),
        "writes_nothing": True,
        "summary": module_mapping.summarise(modules, topic_strategy=topic_strategy),
        "modules": [m.to_dict() for m in modules],
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

