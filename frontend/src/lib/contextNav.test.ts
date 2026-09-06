import { describe, expect, it } from "vitest";

import { buildContextGraph, ContextGraphInputT } from "./contextGraph";
import { buildContextLayout, reconcile } from "./contextLayout";
import {
  actionForNode, contextParams, fingerprintPath, verifyFingerprint,
} from "./contextNav";
import ENV_2256 from "./__fixtures__/context-2256.json";
import ENV_2419 from "./__fixtures__/context-2419.json";

describe("fingerprintPath", () => {
  it("is stable and deterministic", () => {
    const a = fingerprintPath("superset/models/core.py");
    expect(a).toBe(fingerprintPath("superset/models/core.py"));
    expect(a).toHaveLength(6);
    expect(a).toMatch(/^[0-9a-z]{6}$/);
  });

  it("differs for different paths -- including near-identical ones", () => {
    const pairs: [string, string][] = [
      ["superset/models/core.py", "superset/utils/core.py"],
      ["superset/models/core.py", "superset/models/core.pyc"],
      ["a/b.py", "a/c.py"],
      ["scripts/__init__.py", "superset/__init__.py"],
    ];
    for (const [x, y] of pairs) {
      expect(fingerprintPath(x)).not.toBe(fingerprintPath(y));
    }
  });

  it("no collisions across every path in both real fixtures", () => {
    const paths = new Set<string>();
    for (const raw of [ENV_2256, ENV_2419]) {
      const env = raw as ContextGraphInputT;
      paths.add(env.path);
      env.connected_index.forEach((e) => paths.add(e.path));
    }
    const fps = new Set([...paths].map(fingerprintPath));
    // 518, not 631: the two fixtures overlap heavily (both are Superset files,
    // and 2419 is itself one of 2256's neighbours). My first assertion said
    // >600 by adding 275 + 356 without deduping -- caught by this test failing.
    expect(paths.size).toBe(518);
    // THE PROPERTY THAT MATTERS: every distinct path gets a distinct
    // fingerprint. Zero collisions across all 518.
    expect(fps.size).toBe(paths.size);
  });
});

describe("verifyFingerprint -- D14", () => {
  const path = "superset/models/core.py";

  it("absent fp is `unverified`, NOT a mismatch", () => {
    // Links made before this checkpoint must keep working; absence is not
    // evidence of substitution.
    expect(verifyFingerprint(null, path).status).toBe("unverified");
    expect(verifyFingerprint("", path).status).toBe("unverified");
  });

  it("correct fp matches", () => {
    expect(verifyFingerprint(fingerprintPath(path), path).status).toBe("match");
  });

  it("LOADBEARING: a WRONG fp is a mismatch, never a silent render", () => {
    // The whole point. A reassigned id renders a different file's
    // neighbourhood -- correctly computed and plausible -- and the ONLY signal
    // is that the fingerprint no longer matches the path that came back.
    const v = verifyFingerprint(fingerprintPath("superset/utils/core.py"), path);
    expect(v.status).toBe("mismatch");
    if (v.status !== "mismatch") throw new Error("unreachable");
    expect(v.actualPath).toBe(path);
    expect(v.actual).not.toBe(v.expected);
  });

  it("the mismatch carries what is needed to explain it to a person", () => {
    const v = verifyFingerprint("zzzzzz", path);
    if (v.status !== "mismatch") throw new Error("unreachable");
    expect(v.expected).toBe("zzzzzz");
    expect(v.actualPath).toBe(path);
  });
});

describe("contextParams -- one builder, so links cannot disagree", () => {
  it("carries view, fileId and a matching fp", () => {
    const p = contextParams(2256, "superset/models/core.py");
    expect(p.get("view")).toBe("context");
    expect(p.get("fileId")).toBe("2256");
    expect(verifyFingerprint(p.get("fp"), "superset/models/core.py").status).toBe("match");
  });
});

describe("actionForNode -- the click decision", () => {
  it("a single-file node navigates", () => {
    const a = actionForNode({ kind: "file", fileIds: [7], groupKey: "x/y.py", paths: ["x/y.py"] });
    expect(a).toEqual({ kind: "navigate", fileId: 7, path: "x/y.py" });
  });

  it("a collapsed group DRILLS IN -- it does not silently do nothing", () => {
    const a = actionForNode({ kind: "folder", fileIds: [1, 2, 3], groupKey: "superset/commands", paths: [] });
    expect(a.kind).toBe("drill");
    if (a.kind !== "drill") throw new Error("unreachable");
    expect(a.fileIds).toEqual([1, 2, 3]);
    expect(a.groupKey).toBe("superset/commands");
  });

  it("the centre says so rather than no-opping", () => {
    const a = actionForNode({ kind: "centre", fileIds: [], groupKey: "centre", paths: [] });
    expect(a.kind).toBe("none");
    if (a.kind !== "none") throw new Error("unreachable");
    expect(a.reason).toMatch(/looking at/);
  });

  it("every action is one of the three kinds -- no undefined fallthrough", () => {
    for (const t of [
      { kind: "aggregate", fileIds: [1, 2], groupKey: "__aggregate__", paths: [] },
      { kind: "file", fileIds: [9], groupKey: "a.py", paths: ["a.py"] },
      { kind: "centre", fileIds: [], groupKey: "c", paths: [] },
    ]) {
      expect(["navigate", "drill", "none"]).toContain(actionForNode(t).kind);
    }
  });
});

describe("navigation preserves the reconciliation", () => {
  const layoutOf = (raw: unknown) => {
    const env = raw as ContextGraphInputT;
    const g = buildContextGraph(env);
    return {
      env,
      layout: buildContextLayout(
        g, new Map(env.connected_index.map((e) => [e.id, e.subsystem_modularity_id]))),
    };
  };

  it("LOADBEARING: after navigating, counts reconcile to the NEW file", () => {
    const a = layoutOf(ENV_2256);
    const b = layoutOf(ENV_2419);
    expect(a.layout.counts.connected).toBe(274);
    expect(b.layout.counts.connected).toBe(355);
    expect(reconcile(a.layout).allOk()).toBe(true);
    expect(reconcile(b.layout).allOk()).toBe(true);
    expect(b.layout.counts.connected).toBe(b.env.connected_files_distinct);
  });

  it("BREAK: keeping the prior file's counts fails against the new envelope", () => {
    const a = layoutOf(ENV_2256);
    const b = layoutOf(ENV_2419);
    // the defect this guards: a refetch that swaps the payload but leaves the
    // header rendering the previous file's numbers.
    const stale = { ...b.layout, counts: a.layout.counts };
    expect(stale.counts.connected).not.toBe(b.env.connected_files_distinct);
    expect(reconcile(stale).importerSplitOk).toBe(true);   // internally consistent...
    expect(stale.counts.connected).toBe(274);              // ...and wrong for this file
  });
});
