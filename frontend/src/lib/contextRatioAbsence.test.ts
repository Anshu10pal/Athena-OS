import { describe, expect, it } from "vitest";

import { ContextGraphInputT } from "./contextGraph";
import ENV_2256 from "./__fixtures__/context-2256.json";
import ENV_1107 from "./__fixtures__/context-1107.json";
import ENV_ZERO from "./__fixtures__/context-zeroconn.json";

// D29: a file with no connected files gets NO ratio.
//
// The defect this closes, measured at ck4-bis: an 18KB unconnected file
// displayed `~10.9x` captioned "cheaper than reading every connected file" --
// a sentence about an empty set. The ratio was arithmetically correct and
// semantically void, because with zero connections the denominator collapses to
// the file's own bytes and the comparison stops being about substitution.
//
// Fixtures are REAL, captured over authenticated HTTP:
//   2256      274 connections, the regression guard
//   zeroconn  AlertReportList.test.tsx, 18KB, 0 connections -- the defect file
//   1107      scripts/__init__.py, 785B, 0 connections -- ck4's amber floor

const AS = (x: unknown) => x as ContextGraphInputT & {
  ratio_absent_reason: string | null; connected_files_distinct: number;
  graph_cost_display: string; read_cost_display: string;
};

describe("D29: the ratio is ABSENT at zero connections, not clamped", () => {
  it("LOADBEARING: the 18KB unconnected file has NO ratio", () => {
    const d = AS(ENV_ZERO);
    expect(d.connected_files_distinct).toBe(0);
    expect(d.ratio_display).toBeNull();
    // the defect, pinned so it cannot come back
    expect(d.ratio_display).not.toBe("~10.9x");
    expect(JSON.stringify(d.ratio_display)).not.toContain("10.9");
  });

  it("null, not a sentinel string -- nothing renderable as a number", () => {
    for (const d of [AS(ENV_ZERO), AS(ENV_1107)]) {
      expect(d.ratio_display).toBeNull();
      expect(typeof d.ratio_display).not.toBe("string");
    }
  });

  it("ck4's amber ~0.99x is RETIRED on the small unconnected file too", () => {
    const d = AS(ENV_1107);
    expect(d.ratio_display).toBeNull();
    expect(d.ratio_display).not.toBe("~0.99x");
  });

  it("NOT clamped to 1.0x -- that would be a plausible meaningless number", () => {
    for (const d of [AS(ENV_ZERO), AS(ENV_1107)]) {
      for (const bad of ["~1x", "~1.0x", "~1.00x", "1.0x"]) {
        expect(d.ratio_display).not.toBe(bad);
      }
    }
  });

  it("the component costs STAY -- they are real and checkable", () => {
    expect(AS(ENV_ZERO).graph_cost_display).toBe("351 tokens");
    expect(AS(ENV_ZERO).read_cost_display).toBe("3,844 tokens");
    // 168 vs 167: the small file's loss is still legible in the components
    expect(AS(ENV_1107).graph_cost_display).toBe("168 tokens");
    expect(AS(ENV_1107).read_cost_display).toBe("167 tokens");
  });

  it("the reason is supplied by the backend, not composed in the browser", () => {
    for (const d of [AS(ENV_ZERO), AS(ENV_1107)]) {
      expect(d.ratio_absent_reason).toBeTypeOf("string");
      expect(d.ratio_absent_reason).toContain("nothing for the graph to substitute for");
      expect(d.ratio_absent_reason).toContain("two different questions");
    }
  });

  it("REGRESSION GUARD: suppression is scoped to zero, not universal", () => {
    // Break this by suppressing everywhere and 2256 loses its ratio.
    const d = AS(ENV_2256);
    expect(d.connected_files_distinct).toBe(274);
    expect(d.ratio_display).toBe("~270x");
    expect(d.ratio_absent_reason).toBeNull();
  });
});

describe("the costs CAPTION is conditional too, and the backend owns it", () => {
  // Found by looking at the rendered page, not by a test: with zero connected
  // files the caption still said "reading every connected file would cost 3,844
  // tokens" -- about an empty set, and 3,844 is the cost of reading THIS file.
  // The ratio fix suppressed the number and left the sentence around it.
  it("says 'this file' when there are no connections", () => {
    for (const d of [AS(ENV_ZERO), AS(ENV_1107)]) {
      expect(d.costs_line).toContain("reading this file would cost");
      expect(d.costs_line).not.toContain("every connected file");
    }
  });
  it("says 'every connected file' when there are", () => {
    expect(AS(ENV_2256).costs_line).toContain("reading every connected file would cost");
  });
  it("carries the real numbers either way", () => {
    expect(AS(ENV_ZERO).costs_line).toContain("351 tokens");
    expect(AS(ENV_ZERO).costs_line).toContain("3,844 tokens");
    expect(AS(ENV_2256).costs_line).toContain("1,368,803 tokens");
  });
});
