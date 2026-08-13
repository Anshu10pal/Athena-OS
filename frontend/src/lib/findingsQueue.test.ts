import { describe, expect, it } from "vitest";
import { FindingsRowT } from "./api";
import { isUnexposed, shapeFindings, TOP_N } from "./findingsQueue";

function row(over: Partial<FindingsRowT> = {}): FindingsRowT {
  return {
    marker: "large_method",
    label: "Large functions",
    directory: "src",
    file_count: 3,
    score: 10,
    peak_severity: 0.9,
    churn_mean: 0.2,
    irreducible: false,
    ...over,
  };
}

describe("shapeFindings", () => {
  it("slices to TOP_N until expanded", () => {
    const rows = Array.from({ length: TOP_N + 7 }, (_, i) => row({ directory: `d${i}` }));
    expect(shapeFindings(rows, null, false).visible).toHaveLength(TOP_N);
    expect(shapeFindings(rows, null, true).visible).toHaveLength(TOP_N + 7);
  });

  it("counts findings as the sum of file counts, not distinct files", () => {
    // The same file can appear in several rows -- one per marker that fired on
    // it. Calling this sum "files" would double-count.
    const shaped = shapeFindings([row({ file_count: 3 }), row({ file_count: 4 })], null, true);
    expect(shaped.findings).toBe(7);
  });

  it("builds the marker list from ALL rows, not the filtered ones", () => {
    // Otherwise selecting a marker leaves a filter control offering only that
    // marker, and the selection cannot be changed.
    const rows = [row({ marker: "a", label: "A" }), row({ marker: "b", label: "B" })];
    const shaped = shapeFindings(rows, "a", true);

    expect(shaped.rows).toHaveLength(1);
    expect(shaped.markers.map((m) => m.marker)).toEqual(["a", "b"]);
  });

  it("orders the marker list by row count, ties by name for stability", () => {
    const rows = [
      row({ marker: "b", directory: "1" }),
      row({ marker: "a", directory: "2" }),
      row({ marker: "c", directory: "3" }),
      row({ marker: "c", directory: "4" }),
    ];
    expect(shapeFindings(rows, null, true).markers.map((m) => m.marker)).toEqual(["c", "a", "b"]);
  });

  it("counts irreducible rows within the current filter", () => {
    const rows = [
      row({ marker: "a", irreducible: true }),
      row({ marker: "b", irreducible: true }),
      row({ marker: "a", irreducible: false }),
    ];
    expect(shapeFindings(rows, null, true).irreducibleRows).toBe(2);
    expect(shapeFindings(rows, "a", true).irreducibleRows).toBe(1);
  });

  it("survives null and undefined rows", () => {
    // The view renders before the fetch resolves, and a 404 (no snapshot yet)
    // is the expected state rather than an error.
    for (const value of [null, undefined]) {
      const shaped = shapeFindings(value, null, false);
      expect(shaped.rows).toEqual([]);
      expect(shaped.findings).toBe(0);
      expect(shaped.markers).toEqual([]);
    }
  });

  it("does not mutate the rows it is given", () => {
    const rows = [row({ directory: "z", score: 1 }), row({ directory: "a", score: 9 })];
    const before = rows.map((r) => r.directory);
    shapeFindings(rows, null, true);
    expect(rows.map((r) => r.directory)).toEqual(before);
  });
});

describe("isUnexposed", () => {
  it("distinguishes a zero score from a small one", () => {
    // "Nothing depends on these and they do not change" is a different
    // statement from "this scored 0.03", and the view says so.
    expect(isUnexposed(row({ score: 0 }))).toBe(true);
    expect(isUnexposed(row({ score: 0.03 }))).toBe(false);
  });
});
