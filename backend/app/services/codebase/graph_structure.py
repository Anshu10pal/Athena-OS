"""Phase 1 code health: file-level import structure (SCCs + reachability).

Two facts about a file's position in the resolved import graph, computed once
and persisted, rather than recomputed on every read (the H1.5 rule).

**These two are deliberately NOT peers**, and the asymmetry is the point:

- **SCC membership is evidence of a cycle**, and a cycle is a structural fact
  about the code. `cycle_participation` scores it.
- **Reachability is NOT evidence of dead code**, and must never be scored.
  Static import reachability has predictable false positives -- framework
  discovery, plugin registries, reflection, generated code, and dynamic
  `import()` with a computed path. This project has already measured one:
  `docs/external-validation-eslint.md` records the four
  `cli-engine/formatters/*.js` files as `layer=None` purely because ESLint
  loads them by runtime-computed path. They are not dead; they are the plugin
  pattern our own BLIND_SPOTS list predicted. Reachability is persisted here
  ONLY as evidence for the neutral "possibly unreachable by static imports"
  advisory, and turning it into a deduction requires a separate validation
  study, not a decision in this module.

Reuses ranking._build_graph and ordering.compute_layers rather than building
a third notion of "the import graph" that could drift from the two that
already exist.
"""
from typing import Optional

import networkx as nx
from sqlalchemy.orm import Session

from app.db.models import CodeFile, Repo
from app.services.codebase.ordering import compute_layers
from app.services.codebase.ranking import _build_graph


def compute_file_sccs(graph: nx.DiGraph) -> dict:
    """file_id -> (scc_id, scc_size).

    Every node gets an entry, including the overwhelming majority that sit in
    a trivial component of one. That is deliberate: `scc_size == 1` is a
    measured "not in a cycle", which is different from NULL meaning "never
    analysed", and only the persisted difference lets the scorer tell an
    absent measurement from a clean one.

    SCC ids are assigned in a deterministic order (by each component's
    smallest member id) so the same graph always produces the same labels --
    otherwise a re-run would look like a structural change in a trend line.
    """
    components = [sorted(c) for c in nx.strongly_connected_components(graph)]
    components.sort(key=lambda c: c[0])
    out = {}
    for scc_id, members in enumerate(components):
        size = len(members)
        for file_id in members:
            out[file_id] = (scc_id, size)
    return out


def compute_reachability(graph: nx.DiGraph, entry_ids: set) -> dict:
    """file_id -> bool. Evidence only (see module docstring).

    With no entry points at all, reachability is unknowable rather than
    False -- returning False everywhere would assert that every file is
    possibly-dead, which is an artifact of having nothing to search from.
    """
    if not entry_ids:
        return {node: None for node in graph.nodes()}
    layers = compute_layers(graph, entry_ids)
    return {node: (layers.get(node) is not None) for node in graph.nodes()}


def persist_graph_structure(db: Session, repo: Repo) -> dict:
    """Recomputes and writes scc_id/scc_size/reachable_from_entry for every
    file in the repo. Returns a report describing what was computed, so a
    caller can record evidence completeness rather than assume it."""
    files = db.query(CodeFile).filter(CodeFile.repo_id == repo.id).all()
    if not files:
        return {
            "files": 0, "sccs": 0, "files_in_cycles": 0, "largest_cycle": 0,
            "entry_points": 0, "reachability_computed": False, "unreachable": 0,
        }

    file_by_id = {f.id: f for f in files}
    graph = _build_graph(db, repo, file_by_id)

    sccs = compute_file_sccs(graph)
    entry_ids = {fid for fid, f in file_by_id.items() if f.seed_eligible}
    reachable = compute_reachability(graph, entry_ids)

    non_trivial = {sid for sid, size in sccs.values() if size > 1}
    files_in_cycles = sum(1 for _, size in sccs.values() if size > 1)
    largest = max((size for _, size in sccs.values()), default=0)

    for f in files:
        scc = sccs.get(f.id)
        f.scc_id, f.scc_size = scc if scc else (None, None)
        f.reachable_from_entry = reachable.get(f.id)
    db.commit()

    return {
        "files": len(files),
        "sccs": len({sid for sid, _ in sccs.values()}),
        "cycles": len(non_trivial),
        "files_in_cycles": files_in_cycles,
        "largest_cycle": largest,
        "entry_points": len(entry_ids),
        # False when there were no entry points to search from -- the
        # advisory must say "could not be determined", not "unreachable".
        "reachability_computed": bool(entry_ids),
        "unreachable": sum(1 for v in reachable.values() if v is False),
    }


def cycle_size_for(file: CodeFile) -> Optional[int]:
    """The value `cycle_participation` consumes. None when no analysis has
    run (N/A); a trivial component reports as "not in a cycle" via the
    marker's own warn threshold rather than by being hidden here."""
    if file.scc_size is None:
        return None
    return file.scc_size
