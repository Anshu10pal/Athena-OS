import { DirEdgeT, DirKindT, DirNodeT } from "./api";

// Phase H2: deterministic layered layout ("Sugiyama-lite") for the
// architecture map, replacing force simulation at the directory level --
// at ~20 nodes a computed layout is both more readable and stable across
// reloads than d3-force, and layer position encodes real information
// (dependency depth) a force layout destroys. Pure functions over the
// directory graph payload, no DOM/React dependency -- same split that
// made graphLayout.ts unit-testable in G4.

// Mirrors dir_aggregation.py's dirname_of exactly (same rule, same
// "(root)" sentinel) -- needed client-side to group real per-file data
// (already loaded for the Reading list) under each directory box for
// expansion, since the directory-level payload itself carries counts,
// not file lists.
export function dirnameOfPath(path: string): string {
  const idx = path.lastIndexOf("/");
  return idx === -1 ? "(root)" : path.slice(0, idx);
}

export interface SCC {
  id: number;
  members: string[]; // directory node ids
}

export interface CondensedEdge {
  source: number; // SCC id
  target: number; // SCC id
}

export interface CondensationResult {
  sccOf: Map<string, number>;
  sccs: SCC[];
  condensedEdges: CondensedEdge[];
}

// Tarjan's algorithm. Hand-rolled rather than a dependency -- the graph
// this runs on is capped at 24 nodes (dir_aggregation.py's rollup),
// nowhere near where a library's constant-factor optimizations would
// matter, and this repo's own file graph is small enough that directory-
// level cycles (if any) are also small.
export function condenseSCCs(nodeIds: string[], edges: DirEdgeT[]): CondensationResult {
  const adj = new Map<string, string[]>();
  for (const id of nodeIds) adj.set(id, []);
  for (const e of edges) {
    if (!adj.has(e.source) || !adj.has(e.target)) continue;
    adj.get(e.source)!.push(e.target);
  }

  let index = 0;
  const indexOf = new Map<string, number>();
  const lowlink = new Map<string, number>();
  const onStack = new Set<string>();
  const stack: string[] = [];
  const sccOf = new Map<string, number>();
  const sccs: SCC[] = [];

  // Iterative Tarjan (explicit work stack) -- avoids recursion depth
  // limits entirely; irrelevant at 24 nodes, but a recursive version
  // reads identically and this is no harder to follow.
  function strongConnect(start: string) {
    type Frame = { node: string; iter: number };
    const work: Frame[] = [{ node: start, iter: 0 }];

    while (work.length > 0) {
      const frame = work[work.length - 1];
      const { node } = frame;

      if (frame.iter === 0) {
        indexOf.set(node, index);
        lowlink.set(node, index);
        index += 1;
        stack.push(node);
        onStack.add(node);
      }

      const neighbors = adj.get(node) ?? [];
      let recursed = false;
      while (frame.iter < neighbors.length) {
        const next = neighbors[frame.iter];
        frame.iter += 1;
        if (!indexOf.has(next)) {
          work.push({ node: next, iter: 0 });
          recursed = true;
          break;
        } else if (onStack.has(next)) {
          lowlink.set(node, Math.min(lowlink.get(node)!, indexOf.get(next)!));
        }
      }
      if (recursed) continue;

      if (lowlink.get(node) === indexOf.get(node)) {
        const members: string[] = [];
        let member: string;
        do {
          member = stack.pop()!;
          onStack.delete(member);
          sccOf.set(member, sccs.length);
          members.push(member);
        } while (member !== node);
        sccs.push({ id: sccs.length, members });
      }

      work.pop();
      if (work.length > 0) {
        const parent = work[work.length - 1];
        lowlink.set(parent.node, Math.min(lowlink.get(parent.node)!, lowlink.get(node)!));
      }
    }
  }

  for (const id of nodeIds) {
    if (!indexOf.has(id)) strongConnect(id);
  }

  const condensedEdgeSet = new Set<string>();
  const condensedEdges: CondensedEdge[] = [];
  for (const e of edges) {
    const s = sccOf.get(e.source);
    const t = sccOf.get(e.target);
    if (s == null || t == null || s === t) continue; // self-loop after condensation -- inside one SCC
    const key = `${s}->${t}`;
    if (condensedEdgeSet.has(key)) continue;
    condensedEdgeSet.add(key);
    condensedEdges.push({ source: s, target: t });
  }

  return { sccOf, sccs, condensedEdges };
}

// layer(scc) = 0 if nothing imports it; otherwise 1 + max(layer(u)) over
// every u with an edge u -> scc. Computed via topological order over the
// (now acyclic, post-condensation) SCC graph: by the time a node is
// visited in topo order every predecessor already has a layer assigned.
// Every member of an SCC shares its SCC's layer -- "depth" is undefined
// for files inside a cycle, so they must not be arbitrarily split across
// layers (same rule ordering.py's compute_layers documents).
export function assignLayers(nodeIds: string[], edges: DirEdgeT[]): Map<string, number> {
  const { sccOf, sccs, condensedEdges } = condenseSCCs(nodeIds, edges);

  const predecessors = new Map<number, number[]>();
  const successors = new Map<number, number[]>();
  for (const scc of sccs) {
    predecessors.set(scc.id, []);
    successors.set(scc.id, []);
  }
  for (const e of condensedEdges) {
    predecessors.get(e.target)!.push(e.source);
    successors.get(e.source)!.push(e.target);
  }

  // Kahn's algorithm for a topological order, seeded with every SCC that
  // has no predecessor (layer 0 by definition).
  const inDegree = new Map<number, number>();
  for (const scc of sccs) inDegree.set(scc.id, predecessors.get(scc.id)!.length);

  const sccLayer = new Map<number, number>();
  const queue: number[] = sccs.filter((s) => inDegree.get(s.id) === 0).map((s) => s.id);
  for (const id of queue) sccLayer.set(id, 0);

  let head = 0;
  while (head < queue.length) {
    const current = queue[head];
    head += 1;
    for (const next of successors.get(current)!) {
      const remaining = inDegree.get(next)! - 1;
      inDegree.set(next, remaining);
      const candidateLayer = sccLayer.get(current)! + 1;
      sccLayer.set(next, Math.max(sccLayer.get(next) ?? 0, candidateLayer));
      if (remaining === 0) {
        queue.push(next);
      }
    }
  }

  const layerOf = new Map<string, number>();
  for (const id of nodeIds) {
    const scc = sccOf.get(id);
    layerOf.set(id, scc != null ? sccLayer.get(scc) ?? 0 : 0);
  }
  return layerOf;
}

// Barycenter crossing-minimization: 4 sweeps alternating direction. A
// down-sweep positions each layer by the median position of its
// PREDECESSOR-layer neighbors (already fixed from the previous sweep); an
// up-sweep uses successor-layer neighbors instead. Nodes with no neighbor
// in the reference layer keep their previous relative position rather
// than collapsing to some arbitrary default, so an isolated node doesn't
// get yanked to one edge of its layer every sweep.
export function orderWithinLayers(
  nodeIds: string[], layerOf: Map<string, number>, edges: DirEdgeT[], sweeps = 4,
): Map<string, number> {
  const byLayer = new Map<number, string[]>();
  for (const id of nodeIds) {
    const l = layerOf.get(id) ?? 0;
    if (!byLayer.has(l)) byLayer.set(l, []);
    byLayer.get(l)!.push(id);
  }
  const layers = [...byLayer.keys()].sort((a, b) => a - b);

  // Initial order: input order, for determinism (never Map/Set iteration
  // order alone -- those already reflect input order here, but pinning it
  // explicitly documents the intent and survives future refactors).
  const position = new Map<string, number>();
  for (const l of layers) {
    byLayer.get(l)!.forEach((id, i) => position.set(id, i));
  }

  const predecessorsOf = new Map<string, string[]>();
  const successorsOf = new Map<string, string[]>();
  for (const id of nodeIds) {
    predecessorsOf.set(id, []);
    successorsOf.set(id, []);
  }
  for (const e of edges) {
    if (!predecessorsOf.has(e.source) || !predecessorsOf.has(e.target)) continue;
    successorsOf.get(e.source)!.push(e.target);
    predecessorsOf.get(e.target)!.push(e.source);
  }

  function median(values: number[]): number | null {
    if (values.length === 0) return null;
    const sorted = [...values].sort((a, b) => a - b);
    const mid = Math.floor(sorted.length / 2);
    return sorted.length % 2 === 1 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
  }

  function sweepOnce(order: number[], neighborsOf: Map<string, string[]>) {
    for (const l of order) {
      const ids = byLayer.get(l)!;
      const keyed = ids.map((id) => {
        const neighborPositions = neighborsOf.get(id)!.map((n) => position.get(n)).filter((p): p is number => p != null);
        const med = median(neighborPositions);
        return { id, key: med ?? position.get(id)! };
      });
      keyed.sort((a, b) => a.key - b.key);
      keyed.forEach((k, i) => position.set(k.id, i));
    }
  }

  for (let sweep = 0; sweep < sweeps; sweep++) {
    const downward = sweep % 2 === 0;
    // Down-sweep: skip the first layer (no predecessor layer to react to).
    // Up-sweep: skip the last layer (no successor layer to react to).
    const order = downward ? layers.slice(1) : [...layers].reverse().slice(1);
    sweepOnce(order, downward ? predecessorsOf : successorsOf);
  }

  return position;
}

export interface RegionGroup {
  region: string;
  ids: string[];
  isolated: boolean; // zero edges touch any node in this region
}

export function groupByRegion(nodes: DirNodeT[], edges: DirEdgeT[]): RegionGroup[] {
  const byRegion = new Map<string, string[]>();
  for (const n of nodes) {
    if (!byRegion.has(n.region)) byRegion.set(n.region, []);
    byRegion.get(n.region)!.push(n.id);
  }
  const touched = new Set<string>();
  for (const e of edges) {
    touched.add(e.source);
    touched.add(e.target);
  }
  return [...byRegion.entries()].map(([region, ids]) => ({
    region,
    ids,
    isolated: !ids.some((id) => touched.has(id)),
  }));
}

export interface LayeredLayoutResult {
  layerOf: Map<string, number>;
  orderOf: Map<string, number>;
  sccOf: Map<string, number>;
  sccs: SCC[];
  regions: RegionGroup[];
}

export function computeLayeredLayout(nodes: DirNodeT[], edges: DirEdgeT[]): LayeredLayoutResult {
  const nodeIds = nodes.map((n) => n.id);
  const layerOf = assignLayers(nodeIds, edges);
  const orderOf = orderWithinLayers(nodeIds, layerOf, edges);
  const { sccOf, sccs } = condenseSCCs(nodeIds, edges);
  const regions = groupByRegion(nodes, edges);
  return { layerOf, orderOf, sccOf, sccs, regions };
}

// A non-trivial SCC (a real directory-level cycle, e.g. core <-> db) must
// render as ONE box holding both directories' files, per the design
// mockup -- two boxes with a bidirectional edge would visually claim they
// have independent positions in the dependency order, which is exactly
// the fact a cycle contradicts. Merging is itself a pure, testable
// transform, same as dir_aggregation.py's file-to-directory rollup one
// level down: internal (within-cycle) edges are dropped, cross-cycle
// edges are redirected to the merged node and summed if more than one
// original edge lands on the same (source, target) render pair.
export interface RenderNode {
  id: string; // a real directory id for singletons, "scc:<sccId>" for a merged cycle group
  label: string; // short_label, or "a ⇄ b" (basenames only) for a cycle group
  path: string; // full path, or "a + b" for a cycle group
  memberIds: string[]; // original directory node ids folded into this render node
  isCycle: boolean;
  kind: DirKindT;
  region: string;
  fileCount: number;
  layer: number;
  order: number; // for stable tie-breaking only -- actual vertical position is recomputed by the renderer
  isolated: boolean;
}

export interface RenderEdge {
  source: string;
  target: string;
  weight: number;
  count: number;
}

// Priority order for picking a cycle group's displayed kind when its
// members disagree -- same "rarer/more structurally distinctive fact
// wins ties" reasoning as dir_aggregation.py's own kind-priority order,
// one level up. In practice a real cycle's members are almost always
// both "source" (backend/app/core <-> backend/app/db), so this rarely
// has to break an actual tie.
const KIND_MERGE_PRIORITY: DirKindT[] = ["entry", "tooling", "migration", "test", "source"];

export function buildRenderNodes(
  nodes: DirNodeT[], edges: DirEdgeT[], layout: LayeredLayoutResult,
): { renderNodes: RenderNode[]; renderEdges: RenderEdge[] } {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const isolatedIds = new Set(layout.regions.filter((r) => r.isolated).flatMap((r) => r.ids));

  const membersBySCC = new Map<number, string[]>();
  for (const n of nodes) {
    const scc = layout.sccOf.get(n.id);
    if (scc == null) continue;
    if (!membersBySCC.has(scc)) membersBySCC.set(scc, []);
    membersBySCC.get(scc)!.push(n.id);
  }

  const renderIdOf = new Map<string, string>();
  const renderNodes: RenderNode[] = [];

  for (const [sccId, memberIds] of membersBySCC) {
    const members = memberIds.map((id) => byId.get(id)!);
    const isCycle = members.length > 1;
    const renderId = isCycle ? `scc:${sccId}` : memberIds[0];
    for (const id of memberIds) renderIdOf.set(id, renderId);

    const kind = isCycle
      ? KIND_MERGE_PRIORITY.find((k) => members.some((m) => m.kind === k)) ?? "source"
      : members[0].kind;

    renderNodes.push({
      id: renderId,
      label: isCycle ? members.map((m) => m.short_label).join(" ⇄ ") : members[0].short_label,
      path: isCycle ? members.map((m) => m.path).join(" + ") : members[0].path,
      memberIds,
      isCycle,
      kind,
      region: members[0].region,
      fileCount: members.reduce((sum, m) => sum + m.file_count, 0),
      layer: layout.layerOf.get(memberIds[0]) ?? 0,
      order: Math.min(...memberIds.map((id) => layout.orderOf.get(id) ?? 0)),
      isolated: memberIds.every((id) => isolatedIds.has(id)),
    });
  }

  const crossAgg = new Map<string, { weight: number; count: number }>();
  for (const e of edges) {
    const rs = renderIdOf.get(e.source);
    const rt = renderIdOf.get(e.target);
    if (rs == null || rt == null || rs === rt) continue; // internal to a cycle group
    const key = `${rs}=>${rt}`;
    const agg = crossAgg.get(key) ?? { weight: 0, count: 0 };
    agg.weight += e.weight;
    agg.count += e.count;
    crossAgg.set(key, agg);
  }
  const renderEdges: RenderEdge[] = [...crossAgg.entries()].map(([key, agg]) => {
    const [source, target] = key.split("=>");
    return { source, target, ...agg };
  });

  renderNodes.sort((a, b) => a.layer - b.layer || a.order - b.order);
  return { renderNodes, renderEdges };
}

// Deliberate placement for isolated directories (voice_listener): an arc
// around the main layout rather than clamping them against whichever
// container edge a force layout would have pushed them to. Pure geometry
// -- the component supplies the actual stage-relative center/radius.
export function placeSatelliteArc(
  ids: string[], center: { x: number; y: number }, radius: number, startDeg = -38, stepDeg = 22,
): Map<string, { x: number; y: number }> {
  const positions = new Map<string, { x: number; y: number }>();
  ids.forEach((id, i) => {
    const angle = ((startDeg + i * stepDeg) * Math.PI) / 180;
    positions.set(id, { x: center.x + radius * Math.cos(angle), y: center.y + radius * Math.sin(angle) * 1.35 });
  });
  return positions;
}

// How many directories land in each layer -- the report the H2 checkpoint
// explicitly asked for. 8/4/3/2 reads as a healthy layered architecture;
// 15/3/1/2 means layer 0 is a dumping ground for everything unimported
// and the x-axis carries less information than the design assumes.
export function layerHistogram(layerOf: Map<string, number>): Record<number, number> {
  const hist: Record<number, number> = {};
  for (const layer of layerOf.values()) {
    hist[layer] = (hist[layer] ?? 0) + 1;
  }
  return hist;
}

// SCCs with more than one member are real merge groups -- a directory
// cycle collapsed into one box, which H3 must visibly label as a cycle
// group rather than silently present as an ordinary directory.
export function nonTrivialSCCs(sccs: SCC[]): SCC[] {
  return sccs.filter((s) => s.members.length > 1);
}
