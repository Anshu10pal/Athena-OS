import { describe, expect, it } from "vitest";
import { ScopeEdge, ScopeNode } from "./dependencyGraphScope";
import {
  buildGraphElements,
  BuildElementsInput,
  dirNodeId,
  expandableDirs,
  fileLabel,
  fileNodeId,
  shortDirLabel,
} from "./dependencyGraphElements";

function n(id: number, path: string, cluster: number | null = null): ScopeNode {
  return { id, path, subsystem_modularity_id: cluster };
}

function e(source: number, target: number): ScopeEdge {
  return { source, target };
}

function input(over: Partial<BuildElementsInput> & Pick<BuildElementsInput, "nodes">): BuildElementsInput {
  const scopedNodeIds = over.scopedNodeIds ?? over.nodes.map((x) => x.id);
  return {
    nodes: over.nodes,
    scopedNodeIds,
    scopedEdges: over.scopedEdges ?? [],
    hopOf: over.hopOf ?? new Map(scopedNodeIds.map((id) => [id, 0])),
    cycleEdgeKeys: over.cycleEdgeKeys ?? new Set<string>(),
    focusIds: over.focusIds ?? [],
    expandedDirs: over.expandedDirs ?? new Set<string>(),
  };
}

describe("label helpers", () => {
  it("shortens a nested directory to its last segment", () => {
    expect(shortDirLabel("backend/app/services")).toBe("services");
    expect(shortDirLabel("backend")).toBe("backend");
  });

  it("reduces a file path to its basename", () => {
    expect(fileLabel("backend/app/main.py")).toBe("main.py");
    expect(fileLabel("README.md")).toBe("README.md");
  });
});

describe("buildGraphElements -- collapsing", () => {
  it("collapses a multi-file folder into one node carrying the file count", () => {
    const nodes = [n(1, "lib/a.py"), n(2, "lib/b.py"), n(3, "lib/c.py")];
    const els = buildGraphElements(input({ nodes }));
    expect(els.nodes.length).toBe(1);
    expect(els.nodes[0].data.id).toBe(dirNodeId("lib"));
    expect(els.nodes[0].data.kind).toBe("dir");
    expect(els.nodes[0].data.fileCount).toBe(3);
  });

  it("renders a single-file folder as a bare file node, not a compound of one", () => {
    const nodes = [n(1, "lib/only.py")];
    const els = buildGraphElements(input({ nodes }));
    expect(els.nodes.length).toBe(1);
    expect(els.nodes[0].data.kind).toBe("file");
    expect(els.nodes[0].data.parent).toBeUndefined();
  });

  it("expands a folder into a compound parent plus file children when asked", () => {
    const nodes = [n(1, "lib/a.py"), n(2, "lib/b.py")];
    const els = buildGraphElements(input({ nodes, expandedDirs: new Set(["lib"]) }));
    const parent = els.nodes.find((x) => x.data.id === dirNodeId("lib"));
    const children = els.nodes.filter((x) => x.data.kind === "file");
    expect(parent).toBeDefined();
    expect(children.length).toBe(2);
    for (const c of children) expect(c.data.parent).toBe(dirNodeId("lib"));
  });

  it("always expands the folder containing the focus file, even if not explicitly expanded", () => {
    // Without this, focusing a file in a collapsed folder would hide the
    // one node the entire view is built around.
    const nodes = [n(1, "lib/a.py"), n(2, "lib/b.py")];
    const els = buildGraphElements(input({ nodes, focusIds: [1] }));
    const focusNode = els.nodes.find((x) => x.data.id === fileNodeId(1));
    expect(focusNode).toBeDefined();
    expect(focusNode!.data.isFocus).toBe(true);
  });
});

describe("buildGraphElements -- edge rewriting", () => {
  it("aggregates many file edges between two collapsed folders into one counted edge", () => {
    const nodes = [n(1, "a/x.py"), n(2, "a/y.py"), n(3, "b/p.py"), n(4, "b/q.py")];
    const edges = [e(1, 3), e(1, 4), e(2, 3)];
    const els = buildGraphElements(input({ nodes, scopedEdges: edges }));
    expect(els.edges.length).toBe(1);
    expect(els.edges[0].data.count).toBe(3);
    expect(els.edges[0].data.source).toBe(dirNodeId("a"));
    expect(els.edges[0].data.target).toBe(dirNodeId("b"));
  });

  it("counts folder-internal edges on the node instead of drawing self-loops", () => {
    const nodes = [n(1, "a/x.py"), n(2, "a/y.py")];
    const edges = [e(1, 2)];
    const els = buildGraphElements(input({ nodes, scopedEdges: edges }));
    expect(els.edges.length).toBe(0);
    expect(els.nodes[0].data.internalEdgeCount).toBe(1);
  });

  it("reveals the previously-internal edge once the folder is expanded", () => {
    // The same underlying edge, drawn or not depending only on granularity --
    // collapse/expand is a relabelling, never a different graph.
    const nodes = [n(1, "a/x.py"), n(2, "a/y.py")];
    const edges = [e(1, 2)];
    const els = buildGraphElements(input({ nodes, scopedEdges: edges, expandedDirs: new Set(["a"]) }));
    expect(els.edges.length).toBe(1);
    expect(els.edges[0].data.source).toBe(fileNodeId(1));
    expect(els.edges[0].data.target).toBe(fileNodeId(2));
  });

  it("marks an aggregated edge cyclic if ANY underlying edge is cyclic", () => {
    const nodes = [n(1, "a/x.py"), n(2, "a/y.py"), n(3, "b/p.py"), n(4, "b/q.py")];
    const edges = [e(1, 3), e(2, 4)];
    const els = buildGraphElements(input({
      nodes, scopedEdges: edges, cycleEdgeKeys: new Set(["2->4"]),
    }));
    expect(els.edges.length).toBe(1);
    expect(els.edges[0].data.cyclic).toBe(true);
  });

  it("leaves an aggregated edge non-cyclic when no underlying edge is", () => {
    const nodes = [n(1, "a/x.py"), n(2, "b/p.py")];
    const els = buildGraphElements(input({ nodes, scopedEdges: [e(1, 2)] }));
    expect(els.edges[0].data.cyclic).toBe(false);
  });
});

describe("buildGraphElements -- cluster summarisation", () => {
  it("reports the dominant cluster and flags a mixed folder", () => {
    const nodes = [n(1, "a/x.py", 5), n(2, "a/y.py", 5), n(3, "a/z.py", 9)];
    const els = buildGraphElements(input({ nodes }));
    expect(els.nodes[0].data.clusterId).toBe(5);
    expect(els.nodes[0].data.clusterMixed).toBe(true);
  });

  it("does not flag a folder whose files all share one cluster", () => {
    const nodes = [n(1, "a/x.py", 5), n(2, "a/y.py", 5)];
    const els = buildGraphElements(input({ nodes }));
    expect(els.nodes[0].data.clusterMixed).toBe(false);
  });

  it("excludes unclustered files from the vote rather than counting them as a cluster", () => {
    // Two files that each failed to cluster have not agreed on anything --
    // same exclusion rule as the backend's _cluster_of and the ESLint
    // validation's recall computation.
    const nodes = [n(1, "a/x.py", null), n(2, "a/y.py", null), n(3, "a/z.py", 7)];
    const els = buildGraphElements(input({ nodes }));
    expect(els.nodes[0].data.clusterId).toBe(7);
    expect(els.nodes[0].data.clusterMixed).toBe(false);
  });

  it("reports null when no file in the folder has a cluster", () => {
    const nodes = [n(1, "a/x.py", null), n(2, "a/y.py", null)];
    const els = buildGraphElements(input({ nodes }));
    expect(els.nodes[0].data.clusterId).toBeNull();
  });
});

describe("expandableDirs", () => {
  it("lists only folders where expanding would actually change anything", () => {
    const nodes = [n(1, "a/x.py"), n(2, "a/y.py"), n(3, "b/solo.py")];
    const dirs = expandableDirs(nodes, [1, 2, 3]);
    expect(dirs).toEqual([{ dir: "a", fileCount: 2 }]);
  });

  it("orders by file count descending so the densest folder is offered first", () => {
    const nodes = [
      n(1, "a/1.py"), n(2, "a/2.py"),
      n(3, "b/1.py"), n(4, "b/2.py"), n(5, "b/3.py"),
    ];
    const dirs = expandableDirs(nodes, [1, 2, 3, 4, 5]);
    expect(dirs.map((d) => d.dir)).toEqual(["b", "a"]);
  });
});
