import { describe, expect, it } from "vitest";
import { DirEdgeT, DirNodeT } from "./api";
import {
  assignLayers,
  buildRenderNodes,
  computeLayeredLayout,
  condenseSCCs,
  dirnameOfPath,
  groupByRegion,
  layerHistogram,
  nonTrivialSCCs,
  orderWithinLayers,
  placeSatelliteArc,
} from "./layeredLayout";

describe("dirnameOfPath", () => {
  it("matches dir_aggregation.py's dirname_of rule", () => {
    expect(dirnameOfPath("backend/app/api/repos.py")).toBe("backend/app/api");
    expect(dirnameOfPath("backend/app/services/codebase/registry.py")).toBe("backend/app/services/codebase");
    expect(dirnameOfPath("README.md")).toBe("(root)");
  });
});

function makeNode(id: string, overrides: Partial<DirNodeT> = {}): DirNodeT {
  return {
    id, path: id, short_label: id, file_count: 1, kind: "source", region: "backend",
    internal_edge_count: 0, fan_in_dirs: 0, fan_out_dirs: 0, import_count_in: 0, import_count_out: 0,
    ...overrides,
  };
}

function makeEdge(source: string, target: string, weight = 1): DirEdgeT {
  return { source, target, weight, count: 1 };
}

describe("assignLayers", () => {
  it("assigns layer 0 to nodes nothing imports, and 1+max(importer layers) otherwise", () => {
    // a -> b -> c, a -> d -> c: a is the only root; c's two importers (b, d)
    // are both layer 1, so c must be layer 2, not 1.
    const ids = ["a", "b", "c", "d"];
    const edges = [makeEdge("a", "b"), makeEdge("b", "c"), makeEdge("a", "d"), makeEdge("d", "c")];
    const layerOf = assignLayers(ids, edges);
    expect(layerOf.get("a")).toBe(0);
    expect(layerOf.get("b")).toBe(1);
    expect(layerOf.get("d")).toBe(1);
    expect(layerOf.get("c")).toBe(2);
  });

  it("gives every isolated node layer 0, same as a real entry point", () => {
    // Layer 0 means "nothing imports this" -- it catches genuine entry
    // points AND every isolated node. A directory with zero edges at all
    // (e.g. a lone unimported test file) belongs in the same column as
    // main.py, meaning something entirely different -- kind is what
    // distinguishes them, not layer.
    const ids = ["main", "isolated"];
    const edges: DirEdgeT[] = [];
    const layerOf = assignLayers(ids, edges);
    expect(layerOf.get("main")).toBe(0);
    expect(layerOf.get("isolated")).toBe(0);
  });

  it("every member of a cycle shares the same layer", () => {
    // w -> (x -> y -> z -> x) -> v: a 3-cycle with an importer and an
    // exported dependency. x, y, z must all land on the SAME layer --
    // "depth" is undefined inside a cycle, so it must not be arbitrarily
    // split across the members.
    const ids = ["w", "x", "y", "z", "v"];
    const edges = [
      makeEdge("w", "x"), makeEdge("x", "y"), makeEdge("y", "z"), makeEdge("z", "x"), makeEdge("z", "v"),
    ];
    const layerOf = assignLayers(ids, edges);
    expect(layerOf.get("w")).toBe(0);
    const cycleLayer = layerOf.get("x");
    expect(layerOf.get("y")).toBe(cycleLayer);
    expect(layerOf.get("z")).toBe(cycleLayer);
    expect(cycleLayer).toBe(1);
    expect(layerOf.get("v")).toBe((cycleLayer as number) + 1);
  });
});

describe("condenseSCCs", () => {
  it("puts acyclic nodes each in their own singleton SCC", () => {
    const ids = ["a", "b", "c"];
    const edges = [makeEdge("a", "b"), makeEdge("b", "c")];
    const { sccs, sccOf } = condenseSCCs(ids, edges);
    expect(sccs).toHaveLength(3);
    expect(sccOf.get("a")).not.toBe(sccOf.get("b"));
    expect(sccOf.get("b")).not.toBe(sccOf.get("c"));
  });

  it("collapses a deliberate cycle into one SCC with all its members", () => {
    // x -> y -> z -> x is a real cycle; w and v sit outside it.
    const ids = ["w", "x", "y", "z", "v"];
    const edges = [
      makeEdge("w", "x"), makeEdge("x", "y"), makeEdge("y", "z"), makeEdge("z", "x"), makeEdge("z", "v"),
    ];
    const { sccs, sccOf } = condenseSCCs(ids, edges);
    const nonTrivial = nonTrivialSCCs(sccs);
    expect(nonTrivial).toHaveLength(1);
    expect(new Set(nonTrivial[0].members)).toEqual(new Set(["x", "y", "z"]));
    expect(sccOf.get("x")).toBe(sccOf.get("y"));
    expect(sccOf.get("y")).toBe(sccOf.get("z"));
    expect(sccOf.get("w")).not.toBe(sccOf.get("x"));
    expect(sccOf.get("v")).not.toBe(sccOf.get("x"));
  });

  it("reports zero non-trivial SCCs for a real acyclic directory graph", () => {
    const ids = ["app", "api", "db"];
    const edges = [makeEdge("app", "api"), makeEdge("api", "db")];
    const { sccs } = condenseSCCs(ids, edges);
    expect(nonTrivialSCCs(sccs)).toHaveLength(0);
  });

  it("condensed edges drop self-loops and duplicate parallel edges", () => {
    // Two file-level edges both crossing api -> db must collapse to one
    // condensed edge, and a cycle member's edge to another member of the
    // SAME cycle must not appear as a self-loop in the condensed graph.
    const ids = ["api", "db", "x", "y"];
    const edges = [makeEdge("api", "db"), makeEdge("api", "db"), makeEdge("x", "y"), makeEdge("y", "x")];
    const { condensedEdges, sccOf } = condenseSCCs(ids, edges);
    const apiDbEdges = condensedEdges.filter((e) => e.source === sccOf.get("api") && e.target === sccOf.get("db"));
    expect(apiDbEdges).toHaveLength(1);
    expect(condensedEdges.every((e) => e.source !== e.target)).toBe(true);
  });
});

describe("orderWithinLayers", () => {
  function countCrossings(topOrder: string[], bottomOrder: string[], edges: DirEdgeT[]): number {
    const topPos = new Map(topOrder.map((id, i) => [id, i]));
    const bottomPos = new Map(bottomOrder.map((id, i) => [id, i]));
    const pairs = edges.map((e) => [topPos.get(e.source)!, bottomPos.get(e.target)!]);
    let crossings = 0;
    for (let i = 0; i < pairs.length; i++) {
      for (let j = i + 1; j < pairs.length; j++) {
        const [a1, b1] = pairs[i];
        const [a2, b2] = pairs[j];
        if ((a1 < a2 && b1 > b2) || (a1 > a2 && b1 < b2)) crossings++;
      }
    }
    return crossings;
  }

  it("reduces a known crossing to zero", () => {
    // layer0 = [a, b], layer1 = [c, d]; edges a->d, b->c cross when c
    // precedes d (the input order). One down-sweep's median heuristic
    // must reorder layer1 to [d, c], removing the crossing entirely.
    const ids = ["a", "b", "c", "d"];
    const nodes = ids.map((id) => makeNode(id));
    const edges = [makeEdge("a", "d"), makeEdge("b", "c")];
    const layerOf = new Map([["a", 0], ["b", 0], ["c", 1], ["d", 1]]);

    const before = countCrossings(["a", "b"], ["c", "d"], edges);
    expect(before).toBe(1);

    const orderOf = orderWithinLayers(ids, layerOf, edges, 1);
    const layer1Order = ["c", "d"].sort((x, y) => orderOf.get(x)! - orderOf.get(y)!);
    const after = countCrossings(["a", "b"], layer1Order, edges);
    expect(after).toBe(0);
    expect(layer1Order).toEqual(["d", "c"]);
    void nodes; // nodes unused directly -- orderWithinLayers takes ids, kept for readability
  });

  it("leaves a neighborless node's relative position alone rather than forcing it to an edge", () => {
    const ids = ["a", "b", "isolated"];
    const layerOf = new Map([["a", 0], ["b", 1], ["isolated", 1]]);
    const edges = [makeEdge("a", "b")];
    const orderOf = orderWithinLayers(ids, layerOf, edges, 4);
    // Both "b" and "isolated" get valid, distinct positions -- isolated
    // isn't dropped or collapsed onto b's position.
    expect(orderOf.get("b")).not.toBe(orderOf.get("isolated"));
  });
});

describe("groupByRegion", () => {
  it("groups nodes by their region field", () => {
    const nodes = [
      makeNode("backend/app", { region: "backend" }),
      makeNode("backend/api", { region: "backend" }),
      makeNode("frontend/src", { region: "frontend" }),
    ];
    const edges = [makeEdge("backend/app", "backend/api")];
    const groups = groupByRegion(nodes, edges);
    const backend = groups.find((g) => g.region === "backend")!;
    expect(new Set(backend.ids)).toEqual(new Set(["backend/app", "backend/api"]));
  });

  it("flags a region with zero touching edges as isolated -- the voice_listener case", () => {
    const nodes = [
      makeNode("backend/app", { region: "backend" }),
      makeNode("backend/api", { region: "backend" }),
      makeNode("voice_listener", { region: "voice_listener" }),
    ];
    const edges = [makeEdge("backend/app", "backend/api")];
    const groups = groupByRegion(nodes, edges);
    expect(groups.find((g) => g.region === "voice_listener")!.isolated).toBe(true);
    expect(groups.find((g) => g.region === "backend")!.isolated).toBe(false);
  });
});

describe("layerHistogram", () => {
  it("counts how many directories land in each layer", () => {
    const layerOf = new Map([["a", 0], ["b", 0], ["c", 1], ["d", 2], ["e", 2]]);
    expect(layerHistogram(layerOf)).toEqual({ 0: 2, 1: 1, 2: 2 });
  });
});

describe("buildRenderNodes", () => {
  it("merges a real cycle's members into one render node with a joined label", () => {
    // core <-> db, the exact real finding from repo 1.
    const nodes = [
      makeNode("backend/app/core", { short_label: "core", region: "backend", file_count: 3 }),
      makeNode("backend/app/db", { short_label: "db", region: "backend", file_count: 3 }),
      makeNode("backend/app/api", { short_label: "api", region: "backend", file_count: 2 }),
    ];
    const edges = [
      makeEdge("backend/app/core", "backend/app/db", 0.65),
      makeEdge("backend/app/db", "backend/app/core", 0.4),
      makeEdge("backend/app/api", "backend/app/core", 1.0),
    ];
    const layout = computeLayeredLayout(nodes, edges);
    const { renderNodes, renderEdges } = buildRenderNodes(nodes, edges, layout);

    const cycleNode = renderNodes.find((n) => n.isCycle)!;
    expect(cycleNode).toBeDefined();
    expect(cycleNode.label).toBe("core ⇄ db");
    expect(new Set(cycleNode.memberIds)).toEqual(new Set(["backend/app/core", "backend/app/db"]));
    expect(cycleNode.fileCount).toBe(6);

    // the internal core<->db edges must not appear in renderEdges at all.
    expect(renderEdges.some((e) => e.source === cycleNode.id && e.target === cycleNode.id)).toBe(false);
    // api -> core must now point at the merged render node.
    const apiEdge = renderEdges.find((e) => e.source === "backend/app/api" && e.target === cycleNode.id);
    expect(apiEdge).toBeDefined();
    expect(apiEdge!.weight).toBe(1.0);
  });

  it("leaves acyclic nodes as singleton render nodes, unmerged", () => {
    const nodes = [makeNode("app", { short_label: "app" }), makeNode("api", { short_label: "api" })];
    const edges = [makeEdge("app", "api")];
    const layout = computeLayeredLayout(nodes, edges);
    const { renderNodes } = buildRenderNodes(nodes, edges, layout);
    expect(renderNodes).toHaveLength(2);
    expect(renderNodes.every((n) => !n.isCycle)).toBe(true);
    expect(renderNodes.map((n) => n.id).sort()).toEqual(["api", "app"]);
  });

  it("sums parallel cross-node edges after several distinct file-directory edges land on the same pair", () => {
    // Two SEPARATE cycle members both importing the SAME outside directory
    // -- both edges must fold into one summed render edge, not two.
    const nodes = [
      makeNode("x", { short_label: "x", region: "r" }),
      makeNode("y", { short_label: "y", region: "r" }),
      makeNode("out", { short_label: "out", region: "r" }),
    ];
    const edges = [
      makeEdge("x", "y", 0.5), makeEdge("y", "x", 0.5), // x <-> y cycle
      makeEdge("x", "out", 1.0), makeEdge("y", "out", 2.0),
    ];
    const layout = computeLayeredLayout(nodes, edges);
    const { renderNodes, renderEdges } = buildRenderNodes(nodes, edges, layout);
    const cycleNode = renderNodes.find((n) => n.isCycle)!;
    const toOut = renderEdges.filter((e) => e.source === cycleNode.id && e.target === "out");
    expect(toOut).toHaveLength(1);
    expect(toOut[0].weight).toBe(3.0);
  });
});

describe("placeSatelliteArc", () => {
  it("places each isolated node at a distinct point on the arc, none at the exact center", () => {
    const positions = placeSatelliteArc(["voice_listener"], { x: 380, y: 300 }, 330);
    const p = positions.get("voice_listener")!;
    expect(p).toBeDefined();
    expect(Math.hypot(p.x - 380, p.y - 300)).toBeGreaterThan(0);
  });

  it("gives multiple isolated nodes distinct positions", () => {
    const positions = placeSatelliteArc(["a", "b", "c"], { x: 0, y: 0 }, 100);
    const pts = [...positions.values()];
    const unique = new Set(pts.map((p) => `${p.x.toFixed(2)},${p.y.toFixed(2)}`));
    expect(unique.size).toBe(3);
  });
});

describe("computeLayeredLayout determinism", () => {
  it("produces identical layer/order/SCC assignments across repeated calls", () => {
    const nodes = [
      makeNode("app", { region: "backend" }),
      makeNode("api", { region: "backend" }),
      makeNode("db", { region: "backend" }),
      makeNode("core", { region: "backend" }),
    ];
    const edges = [makeEdge("app", "api"), makeEdge("api", "db"), makeEdge("api", "core"), makeEdge("db", "core")];

    const first = computeLayeredLayout(nodes, edges);
    const second = computeLayeredLayout(nodes, edges);

    expect([...first.layerOf.entries()]).toEqual([...second.layerOf.entries()]);
    expect([...first.orderOf.entries()]).toEqual([...second.orderOf.entries()]);
    expect([...first.sccOf.entries()]).toEqual([...second.sccOf.entries()]);
    expect(first.regions).toEqual(second.regions);
  });

  it("core and db land at a strictly higher layer than app -- the H2 prediction", () => {
    const nodes = [
      makeNode("app", { region: "backend" }),
      makeNode("api", { region: "backend" }),
      makeNode("db", { region: "backend" }),
      makeNode("core", { region: "backend" }),
    ];
    const edges = [makeEdge("app", "api"), makeEdge("api", "db"), makeEdge("api", "core"), makeEdge("db", "core")];
    const { layerOf } = computeLayeredLayout(nodes, edges);
    expect(layerOf.get("app")).toBe(0);
    expect(layerOf.get("core")).toBeGreaterThan(layerOf.get("app")!);
    expect(layerOf.get("db")).toBeGreaterThan(layerOf.get("app")!);
    expect(layerOf.get("core")).toBeGreaterThanOrEqual(layerOf.get("db")!);
  });
});
