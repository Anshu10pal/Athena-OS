/// <reference types="vite/client" />
import { describe, expect, it } from "vitest";
// Vite's `?raw`, not node:fs -- tsconfig's `include` is ["src"], so node
// built-ins are unavailable here without adding @types/node for one file. Same
// reasoning as elkLayoutRun.wiring.test.ts, which this follows.
import SOURCE from "../components/NeighborhoodView.tsx?raw";

// WIRING TRIPWIRE for NeighborhoodView's ELK lifecycle.
//
// `elkLayoutRun.test.ts` pins the cancellation MECHANISM: a late result is
// discarded once cancel is called. Nothing there fails if this component calls
// `runElkLayout(...)` as a statement and throws the returned cleanup away. That
// is the regression this file exists for, and only that.
//
// LIMITS, stated because a tripwire that overstates itself is worse than none:
//   - It reads TEXT, not an AST. A refactor that assigns the cleanup to a
//     variable and returns it later satisfies the mechanism but not this regex.
//   - It proves the cleanup is RETURNED from the effect, NOT that React invokes
//     it, and not that the layout is correct.
//   - It covers this one component. ck4's additions are not covered until
//     someone adds them here.
// A tripwire against the specific likely regression -- someone dropping the
// `return` during an edit -- not a proof of correctness.
//
// CANARIED: deleting the `return` before `runElkLayout(` made the first
// assertion fail; adding a token subtraction made the D7 assertion fail.

function code(src: string): string {
  return src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
}

describe("NeighborhoodView wires runElkLayout's cleanup", () => {
  it("LOADBEARING: the layout effect RETURNS runElkLayout(...)", () => {
    expect(code(SOURCE)).toMatch(/return\s+runElkLayout\(/);
  });

  it("reuses the shared helpers rather than reimplementing them", () => {
    const body = code(SOURCE);
    expect(body).toMatch(/from "\.\.\/lib\/elkLayoutRun"/);
    expect(body).toMatch(/from "\.\.\/lib\/elkWorkerLayout"/);
    expect(body).toMatch(/compute:\s*computeElkLayout/);
    // and does NOT reach into DependencyGraph
    expect(body).not.toMatch(/DependencyGraph/);
  });

  it("D7: no token arithmetic and no calibration constant in the component", () => {
    const body = code(SOURCE);
    expect(body).not.toMatch(/\b4\.7\b/);
    expect(body).not.toMatch(/_CHARS_PER_TOKEN/);
    for (const f of ["view_tokens", "connected_files_tokens", "saved_tokens", "saved_ratio"]) {
      expect(body, `${f} in the component`).not.toContain(f);
    }
  });

  it("D15: colour never reads the neighbourhood's own cluster field", () => {
    const body = code(SOURCE);
    // connected_index is the only permitted source
    expect(body).toMatch(/connected_index/);
    expect(body).not.toMatch(/neighborhood\s*[.[]/);
    expect(body).not.toMatch(/\.cluster\b/);
  });

  it("the regexes CAN fail -- proven on synthetic sources", () => {
    expect(code("runElkLayout(cy, {}, deps);")).not.toMatch(/return\s+runElkLayout\(/);
    expect(code("const x = a.saved_ratio - 1;")).toContain("saved_ratio");
  });
});
