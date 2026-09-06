import { describe, expect, it } from "vitest";

import {
  BOTH_RENDERS_AS,
  buildContextGraph,
  ContextGraphInputT,
  DirectionT,
  layoutSideOf,
} from "./contextGraph";
// REAL captured envelopes, fetched over authenticated HTTP from the live
// backend at snapshot a05a0999877f -- not hand-written. A hand-built fixture
// would only prove the adapter agrees with my idea of the payload.
import ENV_2256 from "./__fixtures__/context-2256.json";
import ENV_2419 from "./__fixtures__/context-2419.json";

const CASES: [string, ContextGraphInputT, {
  connected: number; nodes: number; edges: number; overlap: number;
  unresolved: number; imports: number; importedBy: number; both: number;
}][] = [
  ["2256 superset/models/core.py", ENV_2256 as ContextGraphInputT,
   { connected: 274, nodes: 275, edges: 280, overlap: 6, unresolved: 51,
     imports: 16, importedBy: 252, both: 6 }],
  ["2419 superset/utils/core.py", ENV_2419 as ContextGraphInputT,
   { connected: 355, nodes: 356, edges: 357, overlap: 2, unresolved: 78,
     imports: 9, importedBy: 344, both: 2 }],
];

describe.each(CASES)("buildContextGraph -- %s", (_name, env, exp) => {
  const g = buildContextGraph(env);

  it("nodes = connected + 1 centre, and the centre appears exactly once", () => {
    expect(g.counts.connected).toBe(exp.connected);
    expect(g.nodes.length).toBe(exp.nodes);
    expect(g.nodes.filter((n) => n.id === env.file_id)).toHaveLength(1);
    expect(g.nodes[0]).toEqual({ id: env.file_id, path: env.path });
    // node ids are unique -- a "both" file is ONE node (D16)
    expect(new Set(g.nodes.map((n) => n.id)).size).toBe(exp.nodes);
  });

  it("nodes reconcile to the payload's own connected_files_distinct", () => {
    expect(g.counts.connected).toBe(env.connected_files_distinct);
  });

  it("edges = edge_endpoints_total, NOT the node count", () => {
    // THE D16 GUARD. Emitting one edge per node gives 274, not 280 -- see the
    // dedicated break test below. This assertion is what proves the adapter did
    // not collapse the both-direction files into a single edge each.
    expect(g.counts.edges).toBe(exp.edges);
    expect(g.counts.edges).toBe(env.edge_endpoints_total);
    expect(g.counts.edges).not.toBe(g.counts.connected);
  });

  it("THE THIRD IDENTITY: edges - connected == overlap_count", () => {
    // Three numbers checking each other rather than one being trusted.
    expect(g.counts.overlap).toBe(exp.overlap);
    expect(g.counts.overlap).toBe(env.overlap_count);
  });

  it("direction counts match the payload split", () => {
    const n = (d: DirectionT) =>
      [...g.directionOf.values()].filter((v) => v === d).length;
    expect(n("imports")).toBe(exp.imports);
    expect(n("importedBy")).toBe(exp.importedBy);
    expect(n("both")).toBe(exp.both);
    expect(g.directionOf.size).toBe(exp.connected);
    expect(g.directionOf.has(env.file_id)).toBe(false); // centre not in the lookup
  });

  it("edge orientation follows the real relation, not layout", () => {
    const out = g.edges.filter((e) => e.source === env.file_id).length;
    const inn = g.edges.filter((e) => e.target === env.file_id).length;
    expect(out).toBe(exp.imports + exp.both);      // centre -> what it imports
    expect(inn).toBe(exp.importedBy + exp.both);   // importers -> centre
    expect(out + inn).toBe(exp.edges);
    // every edge touches the centre: this is a 1-hop star, by construction
    expect(g.edges.every((e) => e.source === env.file_id || e.target === env.file_id)).toBe(true);
  });

  it("D17: unresolved travel a separate channel and are absent from nodes", () => {
    expect(g.unresolved.length).toBe(exp.unresolved);
    const specs = new Set(g.unresolved.map((u) => u.raw_specifier));
    expect(g.nodes.some((n) => specs.has(n.path))).toBe(false);
    expect(g.nodes.length).toBe(exp.nodes);        // NOT nodes + unresolved
    expect(g.nodes.length).not.toBe(exp.nodes + exp.unresolved);
  });

  it("D15: subsystem ids come from connected_index, entry for entry", () => {
    const byId = new Map(env.connected_index.map((e) => [e.id, e.subsystem_modularity_id]));
    for (const n of g.nodes.filter((x) => x.id !== env.file_id)) {
      expect(n.subsystem_modularity_id).toBe(byId.get(n.id));
    }
  });

  it("conforms to the ScopeNode contract and does not widen it", () => {
    for (const n of g.nodes) {
      expect(Object.keys(n).sort().join(",")).toMatch(
        /^(id,path|id,path,subsystem_modularity_id)$/);
    }
    for (const e of g.edges) {
      expect(Object.keys(e).sort()).toEqual(["source", "target"]);
    }
  });
});

// ---------------------------------------------------------------------------
// THE BREAKS. Each assertion above was observed failing on deliberately broken
// behaviour before being trusted (§15.1). These reproduce the breaks in-suite
// so they cannot rot into assertions nobody has seen fail.
// ---------------------------------------------------------------------------

describe("the breaks fail, and fail for the stated reason", () => {
  it("D16 break: one edge per node gives 274, not 280", () => {
    const env = ENV_2256 as ContextGraphInputT;
    const collapsed = env.connected_index.length;      // one edge per node
    expect(collapsed).toBe(274);
    expect(collapsed).not.toBe(env.edge_endpoints_total);
    expect(env.edge_endpoints_total - collapsed).toBe(env.overlap_count);
  });

  it("D16 break: rendering both twice gives 280 nodes under a 274 badge", () => {
    const env = ENV_2256 as ContextGraphInputT;
    const doubled = env.connected_index.reduce(
      (acc, e) => acc + (e.direction === "both" ? 2 : 1), 0);
    expect(doubled).toBe(280);
    expect(doubled).not.toBe(env.connected_files_distinct);
  });

  it("D17 break: routing unresolved into nodes gives 325 objects", () => {
    const env = ENV_2256 as ContextGraphInputT;
    const g = buildContextGraph(env);
    const leaked = [
      ...g.nodes,
      ...env.unresolved_edges.map((u, i) => ({ id: -1 - i, path: u.raw_specifier })),
    ];
    // 275 real + 51 leaked = 326 objects while every payload number says 274.
    expect(leaked.length).toBe(326);
    expect(leaked.length).not.toBe(g.nodes.length);
    const specs = new Set(env.unresolved_edges.map((u) => u.raw_specifier));
    expect(leaked.some((n) => specs.has(n.path))).toBe(true);   // the guard would catch it
    expect(g.nodes.some((n) => specs.has(n.path))).toBe(false); // and does not fire on the real output
  });
});

// ---------------------------------------------------------------------------
describe("null subsystem_modularity_id", () => {
  // !! READ THIS BEFORE TRUSTING THIS TEST !!
  //
  // THIS BRANCH IS LIB-TESTED ONLY AND HAS NEVER BEEN EXERCISED AGAINST REAL
  // DATA. Repo 6 measured 274/274 and 355/355 non-null at ck3a -- 100% coverage
  // on both files -- so no real envelope reaches this path. The fixture below is
  // SYNTHETIC, hand-edited from the real 2256 payload.
  //
  // Green here therefore means "the adapter passes null through without
  // crashing", NOT "null subsystems are verified on data". A repo whose
  // subsystem computation has not run, or which has unclustered files, is the
  // case this is written against and the case nobody has actually seen. ck3b-2
  // must still handle null when colouring, and its handling will be equally
  // unverified until such a repo is ingested.
  const synthetic: ContextGraphInputT = {
    file_id: 1,
    path: "a.py",
    ratio_display: "~1.00x",
    ratio_absent_reason: null,
    graph_cost_display: "0 tokens",
    costs_line: "this view costs 0 tokens",
    read_cost_display: "0 tokens",
    envelope_pct: "-8% / +9%",
    connected_files_distinct: 2,
    edge_endpoints_total: 2,
    overlap_count: 0,
    connected_index: [
      { id: 2, path: "b.py", direction: "imports", subsystem_modularity_id: null },
      { id: 3, path: "c.py", direction: "importedBy", subsystem_modularity_id: 42 },
    ],
    unresolved_edges: [],
  };

  it("passes null through rather than substituting or dropping the node", () => {
    const g = buildContextGraph(synthetic);
    expect(g.nodes).toHaveLength(3);
    expect(g.nodes.find((n) => n.id === 2)!.subsystem_modularity_id).toBeNull();
    expect(g.nodes.find((n) => n.id === 3)!.subsystem_modularity_id).toBe(42);
    // A dropped node would be the dangerous outcome: the count would disagree
    // with connected_files_distinct and the graph would be quietly incomplete.
    expect(g.counts.connected).toBe(synthetic.connected_files_distinct);
  });

  it("null does not become 0, which would collide with a real subsystem id", () => {
    const g = buildContextGraph(synthetic);
    expect(g.nodes.find((n) => n.id === 2)!.subsystem_modularity_id).not.toBe(0);
  });
});

describe("layoutSideOf", () => {
  it("D16: both is drawn on the importedBy side", () => {
    expect(BOTH_RENDERS_AS).toBe("importedBy");
    expect(layoutSideOf("both")).toBe("importedBy");
    expect(layoutSideOf("imports")).toBe("imports");
    expect(layoutSideOf("importedBy")).toBe("importedBy");
  });
});

describe("purity", () => {
  it("does not mutate the envelope it is given", () => {
    const env = ENV_2256 as ContextGraphInputT;
    const before = JSON.stringify(env);
    buildContextGraph(env);
    expect(JSON.stringify(env)).toBe(before);
  });

  it("is deterministic across calls", () => {
    const env = ENV_2419 as ContextGraphInputT;
    const a = buildContextGraph(env);
    const b = buildContextGraph(env);
    expect(a.nodes).toEqual(b.nodes);
    expect(a.edges).toEqual(b.edges);
    expect(a.counts).toEqual(b.counts);
  });
});
