/** Phase 8 checkpoint 3b-1 -- the /context envelope -> graph adapter.
 *
 *  PURE. No fetch, no React, no side effects, no cytoscape, no ELK. It takes the
 *  envelope and returns the three things ck3b-2 needs to draw, so the drawing
 *  step has no data decisions left to make.
 *
 *  THE WHOLE POINT IS THAT THE DRAWING RECONCILES TO THE NUMBERS. A graph and a
 *  badge can each be internally consistent and disagree, and the viewer has no
 *  way to tell which one is lying. So the counts this returns are pinned to
 *  payload fields rather than derived independently:
 *
 *    nodes  = connected_files_distinct + 1 (the centre)   -> 275 / 356
 *    edges  = edge_endpoints_total                        -> 280 / 357
 *    edges - (nodes - 1) = overlap_count                  ->   6 /   2
 *
 *  Three numbers that check each other. If the adapter ever collapses the
 *  both-direction files, the third identity breaks and the test says so.
 */
import { ScopeEdge, ScopeNode } from "./dependencyGraphScope";

/** D17: unresolved specifiers are NOT ScopeNodes, and this separate type is how
 *  the type system enforces that rather than a convention. They have no
 *  code_files row, no id, and no size -- `builtins` and `_thread` are not files.
 *  Routing them into `nodes` would put 325 objects on screen under a badge
 *  reading 274: consistent on both sides, wrong, and invisible to the viewer. */
export interface UnresolvedT {
  raw_specifier: string;
  line_number: number;
  kind: string;
}

export type DirectionT = "imports" | "importedBy" | "both";

/** Only the fields the adapter reads. Deliberately narrow: the envelope also
 *  carries `neighborhood`, and per D15 nothing here may read its `cluster`
 *  field -- that covers just the 25 enriched entries, so mixing it with
 *  connected_index would be two instruments for one visual property. */
export interface ContextGraphInputT {
  file_id: number;
  path: string;
  connected_files_distinct: number;
  edge_endpoints_total: number;
  overlap_count: number;
  /** D26: produced by the backend, printed verbatim. The frontend does no
   *  arithmetic on any token figure -- D7's tripwire has zero exceptions and
   *  formatting client-side would need one. */
  /** D29: null when there are no connected files -- there is no ratio to
   *  render, and null leaves no string that could be rendered by accident. */
  ratio_display: string | null;
  ratio_absent_reason: string | null;
  envelope_pct: string;
  graph_cost_display: string;
  costs_line: string;
  read_cost_display: string;
  connected_index: {
    id: number;
    path: string;
    direction: DirectionT;
    subsystem_modularity_id: number | null;
  }[];
  unresolved_edges: UnresolvedT[];
}

export interface ContextGraphT {
  nodes: ScopeNode[];
  edges: ScopeEdge[];
  /** Separate channel, per D17. */
  unresolved: UnresolvedT[];
  /** So ck3b-2 positions without recomputing. The centre is not in here. */
  directionOf: Map<number, DirectionT>;
  centreId: number;
  /** Reported so the caller can assert rather than trust, the same discipline as
   *  the backend's total_nodes_before_cap/truncated pair. */
  counts: {
    nodes: number;
    edges: number;
    connected: number;
    overlap: number;
    unresolved: number;
  };
}

/** The side a "both" file is drawn on.
 *
 *  D16: one node, marked, positioned on the DOMINANT relation -- importedBy,
 *  which is the larger side on every real file measured (252 vs 16 on 2256,
 *  344 vs 9 on 2419). Rendering it twice would make the visible node count 280
 *  under a badge saying 274.
 */
export const BOTH_RENDERS_AS: Exclude<DirectionT, "both"> = "importedBy";

export function buildContextGraph(env: ContextGraphInputT): ContextGraphT {
  const centreId = env.file_id;

  // The centre first, so `nodes[0]` is stable for a caller that wants it, and
  // marked via subsystem-independent identity (`centreId`) rather than a flag
  // bolted onto ScopeNode -- the contract in dependencyGraphScope.ts:27-31 is
  // {id, path, subsystem_modularity_id?} and is not widened here.
  const nodes: ScopeNode[] = [{ id: centreId, path: env.path }];
  const edges: ScopeEdge[] = [];
  const directionOf = new Map<number, DirectionT>();

  for (const entry of env.connected_index) {
    // Defensive: the centre must never appear as its own neighbour. The
    // backend's `nb.id != :fid` already excludes it, so this is belt-and-braces
    // and is asserted in the tests rather than assumed here.
    if (entry.id === centreId) continue;

    nodes.push({
      id: entry.id,
      path: entry.path,
      // D15: from connected_index ONLY.
      subsystem_modularity_id: entry.subsystem_modularity_id,
    });
    directionOf.set(entry.id, entry.direction);

    // EDGE DIRECTION IS THE REAL RELATION, not a layout hint. An `imports`
    // neighbour is one the centre imports, so the arrow runs centre -> it.
    if (entry.direction === "imports" || entry.direction === "both") {
      edges.push({ source: centreId, target: entry.id });
    }
    if (entry.direction === "importedBy" || entry.direction === "both") {
      edges.push({ source: entry.id, target: centreId });
    }
    // A "both" file has now contributed TWO edges and ONE node. That asymmetry
    // is the D16 decision, and it is what makes edges total
    // edge_endpoints_total (280) while nodes total connected + 1 (275).
  }

  return {
    nodes,
    edges,
    unresolved: env.unresolved_edges,
    directionOf,
    centreId,
    counts: {
      nodes: nodes.length,
      edges: edges.length,
      connected: nodes.length - 1,
      overlap: edges.length - (nodes.length - 1),
      unresolved: env.unresolved_edges.length,
    },
  };
}

/** Which side to lay a node out on. Separated from the adapter so ck3b-2 has one
 *  place to ask, and so "both goes on the importedBy side" is stated once. */
export function layoutSideOf(direction: DirectionT): Exclude<DirectionT, "both"> {
  return direction === "both" ? BOTH_RENDERS_AS : direction;
}
