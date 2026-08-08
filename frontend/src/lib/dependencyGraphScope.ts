import { condenseSCCs, DirectedEdgeLike } from "./layeredLayout";

// Phase J1: scoping for the file-level Dependency Graph view.
//
// This module exists because of the H5 postmortem, not in spite of it.
// The old force-directed "Raw" view was deleted for a specific, recorded
// reason: rendering every file at once produced a hairball that answered
// none of the three questions it was tested against (spot a
// heavily-imported utility, find a cycle, trace from an entry point).
// Rebuilding "show every file, force-directed" would recreate exactly
// that failure with a different layout engine.
//
// So the unit of this view is deliberately NOT "the graph" -- it is "one
// focus, N hops out." Every function here narrows before anything is
// rendered. The full graph is reachable only through an explicit opt-in
// (see MAX_NODES_ADVISORY and the caller's own warning), never as the
// default.
//
// Pure functions over the level=file payload the Reading list already
// fetches -- no DOM, no cytoscape import, no new network call. Same
// split that made layeredLayout.ts unit-testable.

// The minimal node/edge shapes this module reads. GraphNodeT/GraphEdgeT
// satisfy both structurally, same "declare the minimum, let the real type
// satisfy it" pattern as filters.ts's Filterable -- so these functions can
// be tested with small literals instead of full 14-field fixtures.
export interface ScopeNode {
  id: number;
  path: string;
  subsystem_modularity_id?: number | null;
}

export interface ScopeEdge {
  source: number;
  target: number;
}

// "both" is the default: a reader asking "what does a change here touch"
// needs downstream (imports) AND upstream (importers) -- restricting to
// one direction answers a narrower question and should be a deliberate
// choice, not the starting state.
export type GraphDirectionT = "both" | "imports" | "importedBy";

export interface ScopeOptions {
  focusIds: number[];
  hops: number;
  direction: GraphDirectionT;
  sameClusterOnly: boolean;
  cycleEdgesOnly: boolean;
  maxNodes: number;
}

export interface ScopeResult {
  nodeIds: number[];
  edges: ScopeEdge[];
  // Hop distance from the focus set, 0 for the focus nodes themselves.
  // Drives both the node cap's eviction order and the component's visual
  // de-emphasis of distant nodes.
  hopOf: Map<number, number>;
  cycleEdgeKeys: Set<string>;
  // Reported, never silent -- same discipline as the backend's
  // total_nodes_before_cap/truncated pair. A view that quietly drops
  // nodes past a cap is indistinguishable from one showing everything.
  totalNodesBeforeCap: number;
  truncated: boolean;
}

// Above this the layout stops being readable and starts being the
// hairball H5 deleted. Not a hard limit -- the caller can raise it via
// ScopeOptions.maxNodes -- but the point past which the UI must warn
// rather than silently render.
export const MAX_NODES_ADVISORY = 150;

export function edgeKey(source: number, target: number): string {
  return `${source}->${target}`;
}

// Edges whose two endpoints sit in the SAME non-trivial strongly-connected
// component -- i.e. edges that actually participate in a dependency cycle,
// not merely edges that touch a file which happens to be in one. Reuses
// layeredLayout.ts's iterative Tarjan rather than carrying a second copy;
// ids are stringified only because that function is keyed on strings (it
// was written for directory ids), and converted straight back.
export function cycleEdgeKeys(nodes: ScopeNode[], edges: ScopeEdge[]): Set<string> {
  const nodeIds = nodes.map((n) => String(n.id));
  const stringEdges: DirectedEdgeLike[] = edges.map((e) => ({
    source: String(e.source),
    target: String(e.target),
  }));
  const { sccOf, sccs } = condenseSCCs(nodeIds, stringEdges);

  // A single node with no self-edge is its own trivial SCC and is not a
  // cycle -- only components with 2+ members count. (A genuine self-import
  // can't occur here: the backend's own graph build drops from_id ==
  // to_id, see subsystems.py's _build_undirected_weighted_graph.)
  const cyclicSccIds = new Set(sccs.filter((s) => s.members.length > 1).map((s) => s.id));

  const keys = new Set<string>();
  for (const e of edges) {
    const s = sccOf.get(String(e.source));
    const t = sccOf.get(String(e.target));
    if (s === undefined || t === undefined) continue;
    if (s === t && cyclicSccIds.has(s)) keys.add(edgeKey(e.source, e.target));
  }
  return keys;
}

function buildAdjacency(edges: ScopeEdge[]): {
  outgoing: Map<number, number[]>;
  incoming: Map<number, number[]>;
} {
  const outgoing = new Map<number, number[]>();
  const incoming = new Map<number, number[]>();
  for (const e of edges) {
    if (!outgoing.has(e.source)) outgoing.set(e.source, []);
    outgoing.get(e.source)!.push(e.target);
    if (!incoming.has(e.target)) incoming.set(e.target, []);
    incoming.get(e.target)!.push(e.source);
  }
  return { outgoing, incoming };
}

// Breadth-first from the focus set, honouring `direction`, stopping at
// `hops`. BFS (not DFS) because the hop number is the whole point: it is
// what the cap evicts by and what the view dims by, so it has to be the
// true shortest distance, which only a breadth-first frontier guarantees.
function bfsHops(
  focusIds: number[], hops: number, direction: GraphDirectionT,
  outgoing: Map<number, number[]>, incoming: Map<number, number[]>,
  present: Set<number>,
): Map<number, number> {
  const hopOf = new Map<number, number>();
  let frontier: number[] = [];
  for (const id of focusIds) {
    if (!present.has(id) || hopOf.has(id)) continue;
    hopOf.set(id, 0);
    frontier.push(id);
  }

  for (let depth = 1; depth <= hops; depth++) {
    const next: number[] = [];
    for (const id of frontier) {
      const neighbors: number[] = [];
      if (direction === "both" || direction === "imports") {
        neighbors.push(...(outgoing.get(id) ?? []));
      }
      if (direction === "both" || direction === "importedBy") {
        neighbors.push(...(incoming.get(id) ?? []));
      }
      for (const n of neighbors) {
        if (!present.has(n) || hopOf.has(n)) continue;
        hopOf.set(n, depth);
        next.push(n);
      }
    }
    if (next.length === 0) break; // exhausted the reachable set early
    frontier = next;
  }
  return hopOf;
}

/**
 * Narrow a full file-level graph to a readable neighbourhood around a
 * focus set.
 *
 * Order of operations is load-bearing and deliberately NOT rearrangeable:
 *
 *   1. cluster filter (restricts which nodes may be traversed AT ALL)
 *   2. BFS to `hops` over the surviving nodes
 *   3. node cap by hop distance
 *   4. edge selection, then optional cycle-edges-only filter
 *
 * The cluster filter has to come before BFS, not after: applying it
 * afterwards would let a path escape the cluster and come back, so the
 * result would contain nodes two hops from the focus via a file the
 * filter claims to have excluded. Filtering the traversable set up front
 * makes "same cluster" mean what it says.
 *
 * Conversely the cycle-edges-only filter comes LAST, applied to edges
 * only, never to the node set -- it is a display filter ("show me just
 * the cycle edges among these files"), not a scoping one. Applying it
 * before BFS would silently change which files are in view, which is a
 * different question than the one the control asks.
 */
export function scopeGraph(
  nodes: ScopeNode[], edges: ScopeEdge[], options: ScopeOptions,
): ScopeResult {
  const { focusIds, hops, direction, sameClusterOnly, cycleEdgesOnly, maxNodes } = options;

  const nodeById = new Map(nodes.map((n) => [n.id, n]));

  // Step 1 -- traversable set. Note a deliberate asymmetry: a focus file
  // with NO cluster (null) can't meaningfully constrain "same cluster",
  // so the filter is a no-op rather than collapsing the view to the focus
  // alone. Silently showing one node would look like a broken graph; the
  // caller surfaces cluster state separately.
  const focusClusters = new Set<number>();
  for (const id of focusIds) {
    const cid = nodeById.get(id)?.subsystem_modularity_id;
    if (cid != null) focusClusters.add(cid);
  }
  const clusterFilterActive = sameClusterOnly && focusClusters.size > 0;

  const present = new Set<number>();
  for (const n of nodes) {
    if (clusterFilterActive) {
      const cid = n.subsystem_modularity_id;
      // Focus nodes are always traversable even if the filter would
      // exclude them -- dropping the thing the user selected is never the
      // right answer to "filter around it."
      if (!(cid != null && focusClusters.has(cid)) && !focusIds.includes(n.id)) continue;
    }
    present.add(n.id);
  }

  const { outgoing, incoming } = buildAdjacency(edges);

  // Step 2 -- BFS.
  const hopOf = bfsHops(focusIds, hops, direction, outgoing, incoming, present);

  // Step 3 -- cap. Evict the FARTHEST nodes first, tie-broken by id for
  // determinism (an unstable cap would reshuffle the view on every
  // re-render). Focus nodes are hop 0 and therefore never evicted.
  const totalNodesBeforeCap = hopOf.size;
  let keptIds = [...hopOf.keys()];
  const truncated = totalNodesBeforeCap > maxNodes;
  if (truncated) {
    keptIds.sort((a, b) => (hopOf.get(a)! - hopOf.get(b)!) || (a - b));
    keptIds = keptIds.slice(0, maxNodes);
  }
  const kept = new Set(keptIds);
  for (const id of hopOf.keys()) if (!kept.has(id)) hopOf.delete(id);

  // Step 4 -- edges wholly inside the kept set, then the display filter.
  let scopedEdges = edges.filter((e) => kept.has(e.source) && kept.has(e.target));

  // Cycle detection runs on the SCOPED subgraph, not the whole repo graph,
  // and that is the honest choice for this view: an edge is highlighted
  // when it closes a cycle among the files currently ON SCREEN. Marking an
  // edge red because of a cycle running through files the user can't see
  // would be an unexplainable annotation.
  const scopedNodes = keptIds.map((id) => nodeById.get(id)).filter((n): n is ScopeNode => n !== undefined);
  const cycleKeys = cycleEdgeKeys(scopedNodes, scopedEdges);

  if (cycleEdgesOnly) {
    scopedEdges = scopedEdges.filter((e) => cycleKeys.has(edgeKey(e.source, e.target)));
  }

  return {
    nodeIds: [...kept].sort((a, b) => (hopOf.get(a)! - hopOf.get(b)!) || (a - b)),
    edges: scopedEdges,
    hopOf,
    cycleEdgeKeys: cycleKeys,
    totalNodesBeforeCap,
    truncated,
  };
}
