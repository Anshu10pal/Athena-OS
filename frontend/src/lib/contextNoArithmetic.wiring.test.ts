/// <reference types="vite/client" />
import { describe, expect, it } from "vitest";
// Vite's `?raw` rather than node:fs -- tsconfig's `include` is ["src"], so a
// test living here is type-checked and node built-ins are not available to it
// without adding @types/node for one file. Same reasoning as
// elkLayoutRun.wiring.test.ts, which this follows.
import REPO_DETAIL from "../pages/RepoDetail.tsx?raw";
import CONTEXT_LOAD from "./contextLoad.ts?raw";

// D7: THE FRONTEND DISPLAYS, IT NEVER COMPUTES.
//
// Every token figure is computed server-side and returned whole, for one
// reason: two instruments measuring the same quantity will disagree, and a
// disagreement between a number in the UI and the number the tool priced is
// invisible to the person reading it (§17.28, and §17.25 on answers whose
// completeness the consumer cannot assess). The endpoint already returns
// saved_tokens and saved_ratio precisely so the browser never subtracts.
//
// LIMITS, stated as elkLayoutRun.wiring.test.ts states its own, because a
// tripwire that overstates itself is worse than none:
//   - It reads TEXT, not an AST. A sufficiently creative refactor satisfies it
//     without preserving the property -- computing into an intermediate
//     variable named something else, or doing the arithmetic in a component
//     this test does not read.
//   - It covers the two files ck2 added. It is not a repo-wide guarantee, and
//     ck3/ck4 must add their own files here as they land.
//   - It proves no arithmetic is WRITTEN, not that the displayed value is
//     correct. Correctness of the numbers is the backend's canaries' job.
// It is a tripwire against the specific, likely regression -- someone
// "helpfully" deriving a percentage in the component -- not a proof.
//
// CANARIED: adding `const x = data.connected_files_tokens - data.view_tokens;`
// to RepoDetail.tsx made this fail on the arithmetic assertion, and adding a
// literal `4.7` made it fail on the constant assertion. Both were removed.

const FILES: [string, string][] = [
  ["RepoDetail.tsx", REPO_DETAIL],
  ["contextLoad.ts", CONTEXT_LOAD],
];

/** Strip line and block comments. Without this the test fails on its own
 *  explanatory prose, and on RepoDetail's comments citing the constant. */
function code(src: string): string {
  return src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
}

const TOKEN_FIELDS = [
  "view_tokens",
  "connected_files_tokens",
  "saved_tokens",
  "saved_ratio",
];

describe("D7: the frontend never computes token figures", () => {
  it.each(FILES)("%s contains no calibration constant", (_name, src) => {
    const body = code(src);
    expect(body).not.toMatch(/\b4\.7\b/);
    expect(body).not.toMatch(/_CHARS_PER_TOKEN/);
  });

  it.each(FILES)("%s does no arithmetic on a token field", (_name, src) => {
    const body = code(src);
    for (const field of TOKEN_FIELDS) {
      // The field as an operand of + - * / , or as the target of one.
      const asLeft = new RegExp(`${field}\\s*[-+*/]\\s*[A-Za-z0-9_.(]`);
      const asRight = new RegExp(`[A-Za-z0-9_.)]\\s*[-+*/]\\s*[A-Za-z0-9_.]*${field}`);
      expect(body, `${field} used in arithmetic`).not.toMatch(asLeft);
      expect(body, `${field} used in arithmetic`).not.toMatch(asRight);
    }
  });

  it("LOADBEARING: the regexes CAN fail -- proven on synthetic sources", () => {
    // The tripwire's own canary. A grep assertion nobody has seen fail is not a
    // guard, and unlike the two above this one cannot rot silently.
    const bad = "const d = data.connected_files_tokens - data.view_tokens;";
    const asLeft = /connected_files_tokens\s*[-+*/]\s*[A-Za-z0-9_.(]/;
    expect(code(bad)).toMatch(asLeft);
    expect(code("const r = 4.7;")).toMatch(/\b4\.7\b/);
    // and that comment-stripping does not create a false negative
    expect(code("// connected_files_tokens - view_tokens\nconst a = 1;")).not.toMatch(asLeft);
  });
});
