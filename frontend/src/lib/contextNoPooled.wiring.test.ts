/// <reference types="vite/client" />
import { describe, expect, it } from "vitest";
import NEIGHBORHOOD from "../components/NeighborhoodView.tsx?raw";
import REPO_DETAIL from "../pages/RepoDetail.tsx?raw";
import CONTEXT_GRAPH from "./contextGraph.ts?raw";
import CONTEXT_LAYOUT from "./contextLayout.ts?raw";
import CONTEXT_NAV from "./contextNav.ts?raw";

// D27: THE UI SHOWS PER-FILE FIGURES ONLY.
//
// Two bans, for two different reasons.
//
// POOLED FIGURES. The deck's 219.7x is pooled tiktoken across five files; the
// screen's ~270x is one file by the char estimator. Different quantities,
// different instruments. Put them where they appear to compete and a reader
// will compare them -- a comparison that is meaningless, and that we lose.
//
// estimator_vs_measured. It exists only for files carrying a checkpoint-3
// benchmark, so it means something different per file: 0.9225 on 2419 and
// `null` everywhere else. A field whose meaning the consumer cannot assess is
// worse than an absent one -- §17.25 by construction, which is exactly why it
// stays in the payload for auditing and off the screen.
//
// LIMITS, stated as the sibling tripwires state theirs:
//   - Reads TEXT, not an AST. A pooled figure assembled from parts, or read
//     from a variable named something else, passes this.
//   - Covers the five files the Context view is built from. ck5 and beyond must
//     add their own.
//   - Proves the strings are not WRITTEN, not that nothing pooled is displayed.
// A tripwire against the specific likely regression -- someone pasting the
// headline number onto the badge because it is more impressive -- not a proof.
//
// CANARIED: adding `const x = "219.7x";` to NeighborhoodView.tsx failed the
// pooled assertion, and printing estimator_vs_measured failed the other.

const FILES: [string, string][] = [
  ["NeighborhoodView.tsx", NEIGHBORHOOD],
  ["RepoDetail.tsx", REPO_DETAIL],
  ["contextGraph.ts", CONTEXT_GRAPH],
  ["contextLayout.ts", CONTEXT_LAYOUT],
  ["contextNav.ts", CONTEXT_NAV],
];

/** Strip comments -- otherwise the prose above and the in-file rationale that
 *  EXPLAINS why these are banned would themselves trip the check. */
function code(src: string): string {
  return src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
}

const POOLED = [
  "219.7", "219.7x",      // the pooled benchmark ratio
  "3,436,264", "3436264", // pooled naive tokens
  "15,644", "15644",      // pooled graph tokens
  "99.5%",                // the pooled reduction
];

describe("D27: no pooled figure and no validation artifact on screen", () => {
  it.each(FILES)("%s prints no pooled benchmark figure", (_n, src) => {
    const body = code(src);
    for (const p of POOLED) {
      expect(body, `pooled figure ${p} in source`).not.toContain(p);
    }
  });

  it.each(FILES)("%s never renders estimator_vs_measured", (_n, src) => {
    expect(code(src)).not.toContain("estimator_vs_measured");
  });

  it("the checks CAN fail -- proven on synthetic sources", () => {
    expect(code('const headline = "219.7x saving";')).toContain("219.7");
    expect(code("const v = d.estimator_vs_measured;")).toContain("estimator_vs_measured");
    // and comment-stripping does not create a false negative
    expect(code("// 219.7x is pooled\nconst a = 1;")).not.toContain("219.7");
  });
});
