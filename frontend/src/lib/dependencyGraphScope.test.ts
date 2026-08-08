import { describe, expect, it } from "vitest";
import {
  cycleEdgeKeys,
  edgeKey,
  GraphDirectionT,
  scopeGraph,
  ScopeEdge,
  ScopeNode,
} from "./dependencyGraphScope";

function n(id: number, path: string, cluster: number | null = null): ScopeNode {
  return { id, path, subsystem_modularity_id: cluster };
}

function e(source: number, target: number): ScopeEdge {
  return { source, target };
}

const DEFAULTS = {
  hops: 1,
  direction: "both" as GraphDirectionT,
  sameClusterOnly: false,
  cycleEdgesOnly: false,
  maxNodes: 100,
};

describe("cycleEdgeKeys", () => {
  it("finds no cycle edges in a pure DAG", () => {
    const nodes = [n(1, "a.py"), n(2, "b.py"), n(3, "c.py")];
    const edges = [e(1, 2), e(2, 3), e(1, 3)];
    expect(cycleEdgeKeys(nodes, edges).size).toBe(0);
  });

  it("marks both edges of a 2-cycle", () => {
    const nodes = [n(1, "a.py"), n(2, "b.py")];
    const edges = [e(1, 2), e(2, 1)];
    const keys = cycleEdgeKeys(nodes, edges);
    expect(keys.has(edgeKey(1, 2))).toBe(true);
    expect(keys.has(edgeKey(2, 1))).toBe(true);
  });

  it("marks all three edges of a 3-cycle", () => {
    const nodes = [n(1, "a.py"), n(2, "b.py"), n(3, "c.py")];
    const edges = [e(1, 2), e(2, 3), e(3, 1)];
    expect(cycleEdgeKeys(nodes, edges).size).toBe(3);
  });

  it("does NOT mark an edge that merely touches a cycle without being in it", () => {
    // 1<->2 is a real cycle; 2->3 leaves it and never comes back, so 2->3
    // is not a cycle edge even though node 2 is cyclic. This is the whole
    // reason the check is "same SCC", not "endpoint is in some SCC".
    const nodes = [n(1, "a.py"), n(2, "b.py"), n(3, "c.py")];
    const edges = [e(1, 2), e(2, 1), e(2, 3)];
    const keys = cycleEdgeKeys(nodes, edges);
    expect(keys.has(edgeKey(1, 2))).toBe(true);
    expect(keys.has(edgeKey(2, 1))).toBe(true);
    expect(keys.has(edgeKey(2, 3))).toBe(false);
  });
});

describe("scopeGraph -- hop traversal", () => {
  const nodes = [n(1, "a.py"), n(2, "b.py"), n(3, "c.py"), n(4, "d.py")];
  const edges = [e(1, 2), e(2, 3), e(3, 4)];

  it("one hop reaches only direct neighbours", () => {
    const r = scopeGraph(nodes, edges, { ...DEFAULTS, focusIds: [1], hops: 1 });
    expect(r.nodeIds).toEqual([1, 2]);
    expect(r.hopOf.get(1)).toBe(0);
    expect(r.hopOf.get(2)).toBe(1);
  });

  it("two hops reaches one further", () => {
    const r = scopeGraph(nodes, edges, { ...DEFAULTS, focusIds: [1], hops: 2 });
    expect(r.nodeIds).toEqual([1, 2, 3]);
    expect(r.hopOf.get(3)).toBe(2);
  });

  it("traverses backwards too when direction is both", () => {
    const r = scopeGraph(nodes, edges, { ...DEFAULTS, focusIds: [3], hops: 1 });
    expect(r.nodeIds.sort((a, b) => a - b)).toEqual([2, 3, 4]);
  });

  it("direction=imports follows only outgoing edges", () => {
    const r = scopeGraph(nodes, edges, { ...DEFAULTS, focusIds: [3], hops: 1, direction: "imports" });
    expect(r.nodeIds).toEqual([3, 4]);
  });

  it("direction=importedBy follows only incoming edges", () => {
    const r = scopeGraph(nodes, edges, { ...DEFAULTS, focusIds: [3], hops: 1, direction: "importedBy" });
    expect(r.nodeIds).toEqual([3, 2]);
  });

  it("records the SHORTEST hop when a node is reachable two ways", () => {
    // 1->2->4 and 1->4: node 4 is both 1 and 2 hops away; BFS must record 1.
    const diamond = [e(1, 2), e(2, 4), e(1, 4)];
    const r = scopeGraph(nodes, diamond, { ...DEFAULTS, focusIds: [1], hops: 2 });
    expect(r.hopOf.get(4)).toBe(1);
  });

  it("stops early instead of looping forever on a cycle", () => {
    const cyc = [e(1, 2), e(2, 1)];
    const r = scopeGraph(nodes, cyc, { ...DEFAULTS, focusIds: [1], hops: 5 });
    expect(r.nodeIds.sort((a, b) => a - b)).toEqual([1, 2]);
  });
});

describe("scopeGraph -- cluster filter", () => {
  it("blocks traversal THROUGH an out-of-cluster file, not just its display", () => {
    // A(c1) -> B(c2) -> C(c1). Without pre-filtering, a 2-hop BFS would
    // reach C by passing through B -- producing a view that contains a file
    // two hops away via a node the filter claims to exclude. Filtering the
    // traversable set BEFORE the BFS is what makes "same cluster" honest.
    const nodes = [n(1, "a.py", 1), n(2, "b.py", 2), n(3, "c.py", 1)];
    const edges = [e(1, 2), e(2, 3)];
    const r = scopeGraph(nodes, edges, { ...DEFAULTS, focusIds: [1], hops: 2, sameClusterOnly: true });
    expect(r.nodeIds).toEqual([1]);
    expect(r.nodeIds).not.toContain(3);
  });

  it("keeps same-cluster neighbours", () => {
    const nodes = [n(1, "a.py", 1), n(2, "b.py", 1), n(3, "c.py", 2)];
    const edges = [e(1, 2), e(1, 3)];
    const r = scopeGraph(nodes, edges, { ...DEFAULTS, focusIds: [1], hops: 1, sameClusterOnly: true });
    expect(r.nodeIds).toEqual([1, 2]);
  });

  it("is a no-op when the focus file has no cluster at all", () => {
    // An unclustered focus can't constrain "same cluster" -- collapsing the
    // view to a single node would look like a broken graph rather than a
    // filter result.
    const nodes = [n(1, "a.py", null), n(2, "b.py", 1)];
    const edges = [e(1, 2)];
    const r = scopeGraph(nodes, edges, { ...DEFAULTS, focusIds: [1], hops: 1, sameClusterOnly: true });
    expect(r.nodeIds).toEqual([1, 2]);
  });

  it("never drops the focus file itself even if its cluster differs from the rest", () => {
    const nodes = [n(1, "a.py", 1), n(2, "b.py", 2)];
    const edges = [e(1, 2)];
    const r = scopeGraph(nodes, edges, { ...DEFAULTS, focusIds: [1], hops: 1, sameClusterOnly: true });
    expect(r.nodeIds).toContain(1);
  });
});

describe("scopeGraph -- node cap", () => {
  const nodes = [n(1, "a.py"), n(2, "b.py"), n(3, "c.py"), n(4, "d.py"), n(5, "e.py")];
  const edges = [e(1, 2), e(1, 3), e(2, 4), e(3, 5)];

  it("evicts the farthest nodes first and never the focus", () => {
    const r = scopeGraph(nodes, edges, { ...DEFAULTS, focusIds: [1], hops: 2, maxNodes: 3 });
    expect(r.nodeIds.length).toBe(3);
    expect(r.nodeIds).toContain(1); // hop 0
    expect(r.nodeIds).toContain(2); // hop 1
    expect(r.nodeIds).toContain(3); // hop 1
    expect(r.truncated).toBe(true);
    expect(r.totalNodesBeforeCap).toBe(5);
  });

  it("reports truncated=false and the true total when nothing is cut", () => {
    const r = scopeGraph(nodes, edges, { ...DEFAULTS, focusIds: [1], hops: 2, maxNodes: 100 });
    expect(r.truncated).toBe(false);
    expect(r.totalNodesBeforeCap).toBe(5);
    expect(r.nodeIds.length).toBe(5);
  });

  it("drops edges whose endpoint was evicted, leaving no dangling edge", () => {
    const r = scopeGraph(nodes, edges, { ...DEFAULTS, focusIds: [1], hops: 2, maxNodes: 3 });
    const kept = new Set(r.nodeIds);
    for (const edge of r.edges) {
      expect(kept.has(edge.source)).toBe(true);
      expect(kept.has(edge.target)).toBe(true);
    }
  });

  it("is deterministic across repeated calls", () => {
    const opts = { ...DEFAULTS, focusIds: [1], hops: 2, maxNodes: 3 };
    expect(scopeGraph(nodes, edges, opts).nodeIds).toEqual(scopeGraph(nodes, edges, opts).nodeIds);
  });
});

describe("scopeGraph -- cycle-edges-only is a DISPLAY filter", () => {
  const nodes = [n(1, "a.py"), n(2, "b.py"), n(3, "c.py")];
  const edges = [e(1, 2), e(2, 1), e(2, 3)];

  it("keeps only cyclic edges but leaves the node set untouched", () => {
    const all = scopeGraph(nodes, edges, { ...DEFAULTS, focusIds: [1], hops: 2 });
    const cyclesOnly = scopeGraph(nodes, edges, { ...DEFAULTS, focusIds: [1], hops: 2, cycleEdgesOnly: true });
    // Same files in view either way -- the control filters what is DRAWN
    // between them, not which files are in scope.
    expect(cyclesOnly.nodeIds).toEqual(all.nodeIds);
    expect(all.edges.length).toBe(3);
    expect(cyclesOnly.edges.length).toBe(2);
    for (const edge of cyclesOnly.edges) {
      expect(cyclesOnly.cycleEdgeKeys.has(edgeKey(edge.source, edge.target))).toBe(true);
    }
  });

  it("yields no edges when the scope contains no cycle", () => {
    const dag = [e(1, 2), e(2, 3)];
    const r = scopeGraph(nodes, dag, { ...DEFAULTS, focusIds: [1], hops: 2, cycleEdgesOnly: true });
    expect(r.edges).toEqual([]);
    expect(r.nodeIds.length).toBe(3);
  });

  it("detects cycles within the SCOPED subgraph only", () => {
    // 2->3->4->2 is a real cycle, but with hops=1 from node 1 only nodes
    // 1 and 2 are in scope, so no cycle is visible and none is claimed --
    // highlighting an edge red for a cycle running through off-screen files
    // would be an unexplainable annotation.
    const four = [n(1, "a.py"), n(2, "b.py"), n(3, "c.py"), n(4, "d.py")];
    const cyc = [e(1, 2), e(2, 3), e(3, 4), e(4, 2)];
    const r = scopeGraph(four, cyc, { ...DEFAULTS, focusIds: [1], hops: 1 });
    expect(r.nodeIds).toEqual([1, 2]);
    expect(r.cycleEdgeKeys.size).toBe(0);
  });
});
