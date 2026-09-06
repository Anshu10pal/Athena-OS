import { describe, expect, it } from "vitest";

import { buildContextGraph, ContextGraphInputT } from "./contextGraph";
import {
  buildContextLayout, folderKey, isTestPath, reconcile, SHOWN_GROUPS,
} from "./contextLayout";
import ENV_2256 from "./__fixtures__/context-2256.json";
import ENV_2419 from "./__fixtures__/context-2419.json";

function layoutFor(raw: unknown) {
  const env = raw as ContextGraphInputT;
  const graph = buildContextGraph(env);
  const subsystemOf = new Map(env.connected_index.map((e) => [e.id, e.subsystem_modularity_id]));
  return { env, layout: buildContextLayout(graph, subsystemOf) };
}

describe("2256 -- the numbers D21/D22 were decided on", () => {
  const { env, layout } = layoutFor(ENV_2256);
  const c = layout.counts;

  it("THE BINDING CONSTRAINT: source + tests == 258", () => {
    expect(c.source).toBe(134);
    expect(c.tests).toBe(124);
    expect(c.source + c.tests).toBe(258);
    expect(c.importers).toBe(258);
  });

  it("imports side is 22 minus the 6 both files, drawn as 16", () => {
    // The payload's imports.total is 22 and INCLUDES the both files; they are
    // drawn once on the importer side (D16), so the imports tray holds 16.
    expect(c.imports).toBe(16);
    expect(c.both).toBe(6);
    expect(c.imports + c.both).toBe(22);
  });

  it("LOAD-BEARING: 22 + 258 - 6 == 274 == connected_files_distinct", () => {
    expect(c.imports + c.both + c.importers - c.both).toBe(274);
    expect(c.connected).toBe(274);
    expect(c.connected).toBe(env.connected_files_distinct);
  });

  it("every tray's visible groups account for its whole total", () => {
    const r = reconcile(layout);
    expect(r.perTray).toEqual([
      { id: "imports", total: 16, accounted: 16, ok: true },
      { id: "source", total: 134, accounted: 134, ok: true },
      { id: "tests", total: 124, accounted: 124, ok: true },
    ]);
    expect(r.allOk()).toBe(true);
  });

  it("collapses to at most SHOWN_GROUPS with an explicit aggregate", () => {
    for (const t of layout.trays.filter((x) => x.id !== "imports")) {
      expect(t.shown.length).toBeLessThanOrEqual(SHOWN_GROUPS);
      if (t.aggregate) {
        expect(t.aggregate.groupCount).toBeGreaterThan(0);
        expect(t.aggregate.fileCount).toBeGreaterThan(0);
      }
      // EVERY group carries a visible count -- D1
      expect(t.shown.every((g) => g.fileCount >= 1)).toBe(true);
    }
  });

  it("groups are ordered largest-first and stably", () => {
    const src = layout.trays.find((t) => t.id === "source")!;
    const counts = src.shown.map((g) => g.fileCount);
    expect(counts).toEqual([...counts].sort((a, b) => b - a));
  });

  it("the 6 both files are marked and live on the importer side", () => {
    expect(layout.bothIds.size).toBe(6);
    const importerIds = new Set(
      layout.trays.filter((t) => t.id !== "imports")
        .flatMap((t) => t.shown.flatMap((g) => g.fileIds)));
    // every both file that is individually shown is on the importer side
    for (const id of layout.bothIds) {
      const onImports = layout.trays.find((t) => t.id === "imports")!
        .shown.some((g) => g.fileIds.includes(id));
      expect(onImports).toBe(false);
      void importerIds;
    }
  });

  it("unresolved stay a separate channel, 51 of them, not files", () => {
    expect(layout.counts.unresolved).toBe(51);
    expect(layout.unresolved).toHaveLength(51);
    const specs = new Set(layout.unresolved.map((u) => u.raw_specifier));
    const drawnPaths = layout.trays.flatMap((t) => t.shown.map((g) => g.key));
    expect(drawnPaths.some((p) => specs.has(p))).toBe(false);
  });
});

describe("2419 -- a second real file, different shape", () => {
  const { env, layout } = layoutFor(ENV_2419);
  const c = layout.counts;
  it("reconciles the same way on different numbers", () => {
    expect(c.source + c.tests).toBe(c.importers);
    expect(c.importers).toBe(346);
    expect(c.imports).toBe(9);
    expect(c.both).toBe(2);
    expect(c.imports + c.both).toBe(11);
    expect(c.connected).toBe(355);
    expect(c.connected).toBe(env.connected_files_distinct);
    expect(reconcile(layout).allOk()).toBe(true);
  });
});

// ---------------------------------------------------------------------------
describe("the breaks fail, and for the stated reason", () => {
  const { layout } = layoutFor(ENV_2256);

  it("dropping a collapsed group's fileCount breaks its tray sum", () => {
    const broken = structuredClone(layout);
    broken.trays.find((t) => t.id === "source")!.shown[0].fileCount = 0;
    const r = reconcile(broken);
    expect(r.trayTotalsOk).toBe(false);
    expect(r.allOk()).toBe(false);
  });

  it("dropping the aggregate entirely breaks its tray sum", () => {
    // SOURCE, not tests. The tests tray has only TWO two-segment groups
    // (tests/unit_tests 76 + tests/integration_tests 48 = 124), so 12 shown
    // covers it and its aggregate is legitimately null -- targeting it made a
    // break that could not fail. Caught by this test failing on the first run.
    const broken = structuredClone(layout);
    const src = broken.trays.find((t) => t.id === "source")!;
    expect(src.aggregate).not.toBeNull();     // the break must be possible
    src.aggregate = null;
    expect(reconcile(broken).trayTotalsOk).toBe(false);
  });

  it("the tests tray genuinely does not aggregate, and that is a finding", () => {
    // 124 test importers span exactly two second-level folders. Worth pinning:
    // it means the tests tray is complete on screen with no "N more" line, so
    // its 124 is directly countable -- while the source tray's 134 needs its
    // aggregate to reconcile.
    const tests = layout.trays.find((t) => t.id === "tests")!;
    expect(tests.shown).toHaveLength(2);
    expect(tests.aggregate).toBeNull();
    expect(tests.shown.map((g) => g.key).sort())
      .toEqual(["tests/integration_tests", "tests/unit_tests"]);
    expect(tests.shown.reduce((s, g) => s + g.fileCount, 0)).toBe(124);
  });

  it("rendering the tests tray WITHOUT the source tray breaks 258", () => {
    const broken = structuredClone(layout);
    broken.trays = broken.trays.filter((t) => t.id !== "source");
    broken.counts.source = 0;
    const r = reconcile(broken);
    expect(r.importerSplitOk).toBe(false);       // 0 + 124 != 258
    expect(r.allOk()).toBe(false);
  });

  it("classifying on basename instead of prefix misclassifies, measurably", () => {
    // T1's finding, pinned as a test so the heuristic cannot creep back in.
    const basename = (p: string) => {
      const b = p.split("/").pop()!;
      return b.startsWith("test_") || b.endsWith("_test.py") || b === "conftest.py";
    };
    const env = ENV_2256 as ContextGraphInputT;
    const importers = env.connected_index
      .filter((e) => e.direction === "importedBy" || e.direction === "both")
      .map((e) => e.path);
    const byPrefix = importers.filter(isTestPath);
    const byBasename = importers.filter(basename);
    expect(byPrefix).toHaveLength(124);
    // a production file that TESTS A CONNECTION is caught by basename
    const falsePositive = importers.filter((p) => !isTestPath(p) && basename(p));
    expect(falsePositive).toEqual(["superset/commands/database/test_connection.py"]);
    // and 46 real test files are missed
    expect(byPrefix.filter((p) => !basename(p))).toHaveLength(46);
    expect(byBasename.length).toBeLessThan(byPrefix.length);
  });
});

// ---------------------------------------------------------------------------
describe("null subsystem_modularity_id", () => {
  // !! GREEN HERE MEANS "DOES NOT CRASH", NOT "VERIFIED ON DATA" !!
  //
  // Repo 6 is 100% subsystem-covered (274/274 and 355/355, measured at ck3a),
  // so NO real envelope reaches this path. Everything below is synthetic. A
  // repo whose subsystem computation has not run is the case this guards and
  // the case nobody has seen. ck4 inherits the same limitation.
  const graph = buildContextGraph({
    file_id: 1, path: "a.py",
    ratio_display: "~1.00x",
    ratio_absent_reason: null,
    graph_cost_display: "0 tokens",
    costs_line: "this view costs 0 tokens",
    read_cost_display: "0 tokens",
    envelope_pct: "-8% / +9%",
    connected_files_distinct: 3, edge_endpoints_total: 3, overlap_count: 0,
    connected_index: [
      { id: 2, path: "src/b.py", direction: "importedBy", subsystem_modularity_id: null },
      { id: 3, path: "src/c.py", direction: "importedBy", subsystem_modularity_id: null },
      { id: 4, path: "src/d.py", direction: "imports", subsystem_modularity_id: 7 },
    ],
    unresolved_edges: [],
  } as ContextGraphInputT);

  it("an all-null group votes null and is NOT marked mixed", () => {
    const layout = buildContextLayout(graph, new Map([[2, null], [3, null], [4, 7]]));
    const src = layout.trays.find((t) => t.id === "source")!;
    expect(src.shown[0].subsystemId).toBeNull();
    // two files that each failed to cluster have not agreed on anything
    expect(src.shown[0].mixed).toBe(false);
    expect(src.shown[0].fileCount).toBe(2);
  });

  it("null nodes are counted, never dropped", () => {
    const layout = buildContextLayout(graph, new Map([[2, null], [3, null], [4, 7]]));
    expect(layout.counts.connected).toBe(3);
    expect(reconcile(layout).allOk()).toBe(true);
  });

  it("a mixed group with one null votes the non-null and IS mixed only if >1 real", () => {
    const layout = buildContextLayout(graph, new Map([[2, null], [3, 9], [4, 7]]));
    const src = layout.trays.find((t) => t.id === "source")!;
    expect(src.shown[0].subsystemId).toBe(9);
    expect(src.shown[0].mixed).toBe(false);   // one real cluster + a null
  });
});

describe("helpers", () => {
  it("folderKey takes two segments and never eats the filename", () => {
    expect(folderKey("tests/unit_tests/models/x.py")).toBe("tests/unit_tests");
    expect(folderKey("superset/x.py")).toBe("superset");
    expect(folderKey("x.py")).toBe("(root)");
  });
  it("isTestPath is prefix-only", () => {
    expect(isTestPath("tests/a.py")).toBe(true);
    expect(isTestPath("superset/commands/database/test_connection.py")).toBe(false);
    expect(isTestPath("superset/tests/a.py")).toBe(false);
  });
});
