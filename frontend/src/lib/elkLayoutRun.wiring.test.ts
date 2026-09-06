/// <reference types="vite/client" />
import { describe, expect, it } from "vitest";
// Vite's `?raw` rather than node:fs -- tsconfig's `include` is ["src"], so a
// test living here is type-checked and node built-ins are not available to it
// without adding @types/node for one file.
import SOURCE from "../components/DependencyGraph.tsx?raw";

// The §17.12 gap from checkpoint 1, closed at the honest ceiling.
//
// `elkLayoutRun.test.ts` pins the cancellation MECHANISM: given a cancel call,
// a late result is discarded. It cannot pin the WIRING -- nothing there fails
// if DependencyGraph calls `runElkLayout(...)` as a statement and throws the
// returned cleanup away. Extracting the lifecycle created two answer sites
// where there was one, and the second can rot while the first stays green.
//
// A browser-level test was attempted first and ABANDONED, for a reason worth
// keeping: the race it has to create is real but the post-interruption render
// could not be sampled reliably, and the attempt surfaced a suspected product
// defect (a rapid full-graph toggle leaves the graph sparse for at least 70s)
// that has to be understood before any test can assert on that sequence. See
// decisions.md:684.
//
// So this is a SOURCE-level check, and its limits are stated rather than
// implied: it proves the cleanup is returned from the effect, not that React
// invokes it, and it reads text rather than an AST, so a sufficiently creative
// refactor could satisfy it without preserving the behaviour. It is a tripwire
// against the specific, likely regression -- someone dropping the `return`
// during an edit -- not a proof of correctness. That is more than nothing,
// which is what checkpoint 1 shipped with.
describe("DependencyGraph wires runElkLayout's cleanup", () => {
  it("LOADBEARING: the layout effect RETURNS runElkLayout(...)", () => {
    // Canaried by deleting the `return` in DependencyGraph.tsx and confirming
    // this fails -- a wiring check that passes either way is worthless.
    expect(SOURCE).toMatch(/return\s+runElkLayout\s*\(/);
  });

  it("LOADBEARING: runElkLayout is never called as a bare statement", () => {
    // The regression this exists for is `runElkLayout(...)` on its own line,
    // which type-checks, runs, and silently leaks every superseded layout.
    const bare = SOURCE.split("\n").filter(
      (line: string) => /^\s*runElkLayout\s*\(/.test(line));
    expect(bare, `runElkLayout called without returning its cleanup: ${bare.join(" | ")}`)
      .toEqual([]);
  });

  it("the effect's dependency list still contains what drives re-layout", () => {
    // If `elements` left this list the effect would stop re-running on scope
    // changes, and the cancellation path -- correct as it is -- would never be
    // exercised. The wiring being right matters only while the effect still
    // fires.
    expect(SOURCE).toMatch(/\}, \[cy, elements, showFullGraph, focusIds\]\);/);
  });
});
