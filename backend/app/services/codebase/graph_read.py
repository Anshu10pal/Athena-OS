"""The single stable read boundary for a repo's WHOLE graph.

Phase 6 checkpoint 1a. Nothing here changes what is stored; it defines the one
function an export -- or any future whole-graph consumer -- reads through, so
that a change to internal table shape breaks THIS FILE loudly instead of
corrupting whatever is downstream.

**Why a new boundary rather than reusing `ranking._build_graph`.** That function
is private by name, returns an `nx.DiGraph` of integer file ids, and carries no
paths, ranks, clusters, symbols or provenance. It also DROPS unresolved imports
(`to_file_id.isnot(None)`), so it cannot express "this import exists in the
source but did not resolve to a file" -- which is real provenance, and exactly
the kind of thing an agent asking about a codebase wants to know. Despite the
underscore it is already imported across module boundaries by `api/repos.py` and
`graph_structure.py` and called from three more places. Adding an EXPORT as a
sixth consumer of a private topology-only helper would put the blast radius
outside the process (contract §17.28).

**The five existing consumers are deliberately NOT migrated here.** That is a
refactor of live code paths and belongs in its own checkpoint; doing it inside
the checkpoint that defines the boundary would mean shipping a new abstraction
and rewiring five callers in one step, with no way to tell which broke what.

**Uncapped by design.** Every graph read the frontend performs is capped (400
nodes) or scoped, because a UI cannot render more. This is the read those
endpoints deliberately do not provide, and it must never be wired behind a UI
route -- on apache/superset it returns 6,523 nodes and 60,873 edges.

**Loud on drift.** The guarantee this boundary exists to provide is that a
renamed or dropped column fails HERE, with a message naming the table and the
missing column, rather than silently yielding a graph with a field quietly
absent. `_require_columns` enforces that before any read runs.
"""
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session


class GraphSchemaDrift(RuntimeError):
    """A table this boundary reads no longer has the shape it expects.

    Its own error class so a caller can tell "the database moved under us" apart
    from "the query failed" -- the first means the export is stale and must not
    be published, the second may be transient.
    """


# What each read depends on. Declared rather than discovered, because the point
# of the boundary is to state its contract with the schema in one place a reader
# can check against a migration.
REQUIRED_COLUMNS: dict = {
    # Read for the repo label AND for ingest provenance. It was previously
    # read without being declared here -- a hole precisely where
    # `_require_columns` promises there is none.
    "repos": ["id", "host", "owner", "name", "last_ingested_sha", "last_ingested_at"],
    "code_files": [
        "id", "repo_id", "path", "language", "size_bytes", "line_count",
        "prior_category", "fan_in", "fan_out", "is_entry_point", "seed_eligible",
        "subsystem_modularity_id", "subsystem_louvain_id", "subsystem_hdbscan_id",
        "scc_id", "scc_size", "reachable_from_entry",
    ],
    "code_imports": [
        "repo_id", "from_file_id", "to_file_id", "raw_specifier",
        "imported_names", "resolved", "line_number", "kind", "cross_root_kind",
    ],
    "code_symbols": ["file_id", "name", "kind", "signature", "line_start", "line_end"],
    "code_file_ranks": ["repo_id", "file_id", "scorer", "score", "rank", "pagerank"],
    "code_subsystems": [
        "id", "repo_id", "algorithm", "cluster_index", "member_count",
        "dominant_prefix_label", "top_fan_in_label", "custom_label",
        "resolution", "internal_weight", "stable_under_perturbation",
    ],
}


@dataclass(frozen=True)
class SymbolT:
    name: str
    kind: str
    signature: Optional[str]
    line_start: Optional[int]
    line_end: Optional[int]


@dataclass(frozen=True)
class RankT:
    scorer: str
    score: Optional[float]
    rank: Optional[int]
    pagerank: Optional[float]


@dataclass
class NodeT:
    """One file, with every signal the pipeline computed for it."""
    path: str
    language: Optional[str]
    size_bytes: Optional[int]
    line_count: Optional[int]
    prior_category: Optional[str]
    fan_in: Optional[int]
    fan_out: Optional[int]
    is_entry_point: bool
    seed_eligible: bool
    reachable_from_entry: Optional[bool]
    # Cluster membership per algorithm, as LABELS rather than row ids: a
    # subsystem id is meaningless outside this database, and the whole point of
    # an export is that it travels.
    clusters: dict = field(default_factory=dict)
    # Cycle membership. `scc_id` groups files that mutually reach each other;
    # size 1 is not a cycle and is normalised to None by the reader.
    scc_id: Optional[int] = None
    scc_size: Optional[int] = None
    ranks: list = field(default_factory=list)
    symbols: list = field(default_factory=list)


@dataclass(frozen=True)
class EdgeT:
    """One import, resolved or not.

    `to_path` is None for an import the resolver could not map to a file in this
    repo -- a third-party package, a dynamic import, a broken reference. Those
    rows are KEPT: "X imports something called Y that is not in this repo" is a
    fact about the codebase, and dropping it (as `_build_graph` does) silently
    turns an incomplete answer into a confident one.
    """
    from_path: str
    to_path: Optional[str]
    raw_specifier: Optional[str]
    imported_names: Optional[str]
    resolved: Optional[bool]
    line_number: Optional[int]
    kind: Optional[str]
    cross_root_kind: Optional[str]

    @property
    def is_resolved(self) -> bool:
        return self.to_path is not None


@dataclass(frozen=True)
class CycleT:
    scc_id: int
    members: tuple


@dataclass
class RepoGraphT:
    repo_id: int
    repo_label: str
    nodes: list
    edges: list
    cycles: list
    clusters: list
    # WHICH SNAPSHOT THIS IS. A graph read says nothing about its own currency
    # unless it carries the commit it was built from; without this a consumer
    # cannot tell a current answer from one computed against a tree that has
    # since moved, which is the same undetectable-completeness failure the rest
    # of this module exists to prevent. Optional because a `local` repo may
    # never have had a sha.
    last_ingested_sha: Optional[str] = None
    # Always ISO 8601, never the driver's native type -- see `_iso`.
    last_ingested_at: Optional[str] = None

    @property
    def resolved_edges(self) -> int:
        return sum(1 for e in self.edges if e.is_resolved)

    @property
    def entry_points(self) -> list:
        return [n.path for n in self.nodes if n.seed_eligible]


def _iso(value) -> Optional[str]:
    """One timestamp format for every consumer, whatever the driver returned.

    Raw `text()` SQL does not go through the ORM's type coercion, so SQLite
    hands back a string like `2026-08-13 16:26:07.000000` while PostgreSQL
    hands back a `datetime`. Left alone, the same field would have two shapes
    depending on the backend -- one source of truth rendered two ways, which is
    the §17.28 trap. Normalised here, once, at the boundary that owns the read.
    """
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    # SQLite's stored form differs from ISO only in the date/time separator.
    return str(value).replace(" ", "T", 1)


def _require_columns(db: Session) -> None:
    """Fail LOUDLY, before reading, if the schema moved.

    Without this the boundary would still 'work' after a column was renamed --
    SQLAlchemy would raise deep inside one query with a driver-level message, or
    worse, a SELECT of the remaining columns would succeed and the export would
    ship missing a field nobody noticed. The whole reason this boundary exists
    is to make that failure loud and locatable, so the check is part of the
    contract rather than a nicety.
    """
    insp = inspect(db.get_bind())
    problems = []
    for table, needed in REQUIRED_COLUMNS.items():
        if not insp.has_table(table):
            problems.append(f"table {table!r} is missing entirely")
            continue
        have = {c["name"] for c in insp.get_columns(table)}
        missing = [c for c in needed if c not in have]
        if missing:
            problems.append(f"table {table!r} is missing column(s): {', '.join(missing)}")
    if problems:
        raise GraphSchemaDrift(
            "The graph read boundary cannot run against this schema — "
            + "; ".join(problems)
            + ". Update app/services/codebase/graph_read.py's REQUIRED_COLUMNS "
              "and the readers below together, then re-export; do NOT publish an "
              "artifact produced against a schema this boundary does not "
              "recognise."
        )


def read_repo_graph(db: Session, repo_id: int, *, include_symbols: bool = True) -> RepoGraphT:
    """The whole graph for one repo. Read-only, uncapped, unpaginated.

    `include_symbols` exists because symbols are the largest single contributor
    to a serialised graph (22,872 rows on apache/superset) and a consumer asking
    only structural questions does not need them. It is a size lever, not a
    filter on correctness: nodes and edges are unaffected by it.
    """
    _require_columns(db)

    repo = db.execute(text(
        "SELECT id, host, owner, name, last_ingested_sha, last_ingested_at "
        "FROM repos WHERE id = :r"), {"r": repo_id}).first()
    if repo is None:
        raise ValueError(f"repo {repo_id} does not exist")
    label = "/".join(p for p in (repo[1], repo[2], repo[3]) if p)

    cluster_label_by_id: dict = {}
    clusters = []
    for row in db.execute(text("""
        SELECT id, algorithm, cluster_index, member_count, dominant_prefix_label,
               top_fan_in_label, custom_label, resolution, internal_weight,
               stable_under_perturbation
        FROM code_subsystems WHERE repo_id = :r
    """), {"r": repo_id}).all():
        lbl = row[6] or row[4] or row[5] or f"cluster {row[2]}"
        cluster_label_by_id[row[0]] = lbl
        clusters.append({
            "algorithm": row[1], "label": lbl, "member_count": row[3],
            "resolution": row[7], "internal_weight": row[8],
            # NULL means NOT MEASURED, never "unstable" -- the column's own
            # contract, preserved rather than coerced to a boolean here.
            "stable_under_perturbation": row[9],
        })

    ranks_by_file: dict = {}
    for fid, scorer, score, rank, pr in db.execute(text("""
        SELECT file_id, scorer, score, rank, pagerank
        FROM code_file_ranks WHERE repo_id = :r
    """), {"r": repo_id}).all():
        ranks_by_file.setdefault(fid, []).append(RankT(scorer, score, rank, pr))

    symbols_by_file: dict = {}
    if include_symbols:
        for fid, name, kind, sig, ls, le in db.execute(text("""
            SELECT s.file_id, s.name, s.kind, s.signature, s.line_start, s.line_end
            FROM code_symbols s JOIN code_files f ON f.id = s.file_id
            WHERE f.repo_id = :r
        """), {"r": repo_id}).all():
            symbols_by_file.setdefault(fid, []).append(SymbolT(name, kind, sig, ls, le))

    nodes, path_by_id = [], {}
    scc_members: dict = {}
    for row in db.execute(text("""
        SELECT id, path, language, size_bytes, line_count, prior_category,
               fan_in, fan_out, is_entry_point, seed_eligible, reachable_from_entry,
               subsystem_modularity_id, subsystem_louvain_id, subsystem_hdbscan_id,
               scc_id, scc_size
        FROM code_files WHERE repo_id = :r
    """), {"r": repo_id}).all():
        (fid, path, lang, size, lines, cat, fan_in, fan_out, is_entry,
         seed, reach, mod_id, lou_id, hdb_id, scc_id, scc_size) = row
        path_by_id[fid] = path
        cl = {}
        for algo, sid in (("modularity", mod_id), ("louvain", lou_id), ("hdbscan", hdb_id)):
            if sid is not None and sid in cluster_label_by_id:
                cl[algo] = cluster_label_by_id[sid]
        # A one-member SCC is not a cycle. Reporting it as one would make every
        # file in the repo "in a cycle", which is true of the datatype and false
        # of the codebase.
        in_cycle = scc_id is not None and (scc_size or 0) > 1
        if in_cycle:
            scc_members.setdefault(scc_id, []).append(path)
        nodes.append(NodeT(
            path=path, language=lang, size_bytes=size, line_count=lines,
            prior_category=cat, fan_in=fan_in, fan_out=fan_out,
            is_entry_point=bool(is_entry), seed_eligible=bool(seed),
            reachable_from_entry=reach, clusters=cl,
            scc_id=scc_id if in_cycle else None,
            scc_size=scc_size if in_cycle else None,
            ranks=ranks_by_file.get(fid, []),
            symbols=symbols_by_file.get(fid, []),
        ))

    edges = []
    for row in db.execute(text("""
        SELECT from_file_id, to_file_id, raw_specifier, imported_names,
               resolved, line_number, kind, cross_root_kind
        FROM code_imports WHERE repo_id = :r
    """), {"r": repo_id}).all():
        frm, to, spec, names, resolved, line, kind, cross = row
        src = path_by_id.get(frm)
        if src is None:
            # An edge whose SOURCE is not in this repo's file set would be a
            # referential inconsistency, not an unresolved import. Skipped
            # rather than emitted with a null source, which would be a
            # different and misleading claim.
            continue
        edges.append(EdgeT(
            from_path=src, to_path=path_by_id.get(to) if to is not None else None,
            raw_specifier=spec, imported_names=names,
            resolved=bool(resolved) if resolved is not None else None,
            line_number=line, kind=kind, cross_root_kind=cross,
        ))

    cycles = [CycleT(scc_id=k, members=tuple(sorted(v)))
              for k, v in sorted(scc_members.items()) if len(v) > 1]

    return RepoGraphT(repo_id=repo_id, repo_label=label, nodes=nodes,
                      edges=edges, cycles=cycles, clusters=clusters,
                      last_ingested_sha=repo[4],
                      last_ingested_at=_iso(repo[5]))
