import { describe, expect, it } from "vitest";
import { computePageInfo, computePageWindow } from "./tablePagination";

describe("computePageInfo", () => {
  it("slices the first page from index 0", () => {
    const p = computePageInfo(1, 248, 20);
    expect(p).toEqual({ page: 1, totalPages: 13, start: 0, end: 20 });
  });

  it("LOADBEARING: page 2 starts at the 21st row, not row 0 renumbered", () => {
    const p = computePageInfo(2, 248, 20);
    expect(p.start).toBe(20);
    expect(p.end).toBe(40);
  });

  it("the last page is a short slice, not padded to a full page", () => {
    const p = computePageInfo(13, 248, 20);
    expect(p.start).toBe(240);
    expect(p.end).toBe(248); // 8 rows, not 20
  });

  it("LOADBEARING: a stale page beyond the current row count clamps to the last real page", () => {
    // The URL can name a page from before a filter narrowed the set --
    // this must not render an empty table.
    const p = computePageInfo(40, 12, 20);
    expect(p.page).toBe(1);
    expect(p.totalPages).toBe(1);
  });

  it("clamps a page below 1 up to 1", () => {
    expect(computePageInfo(0, 100, 20).page).toBe(1);
    expect(computePageInfo(-5, 100, 20).page).toBe(1);
  });

  it("an empty row set is one (empty) page, not zero pages", () => {
    const p = computePageInfo(1, 0, 20);
    expect(p).toEqual({ page: 1, totalPages: 1, start: 0, end: 0 });
  });

  it("an exact multiple of the page size has no trailing short page", () => {
    const p = computePageInfo(2, 40, 20);
    expect(p.totalPages).toBe(2);
    expect(p.end).toBe(40);
  });
});

describe("computePageWindow", () => {
  it("a single page is just [1]", () => {
    expect(computePageWindow(1, 1)).toEqual([1]);
  });

  it("two pages shows both with no ellipsis", () => {
    expect(computePageWindow(1, 2)).toEqual([1, 2]);
    expect(computePageWindow(2, 2)).toEqual([1, 2]);
  });

  it("LOADBEARING: the page row never grows with the page count, unlike the chip row it replaced", () => {
    // The cluster chip row's failure mode was exactly this: one row per
    // item, unbounded. Whatever the current page, the window stays small --
    // at most 2 ellipses + first + last + 2*siblingCount+1 around current.
    for (const totalPages of [13, 100, 5000]) {
      for (const page of [1, Math.ceil(totalPages / 2), totalPages]) {
        expect(computePageWindow(page, totalPages).length).toBeLessThanOrEqual(7);
      }
    }
  });


  it("a large page count collapses the middle with one ellipsis on the far side", () => {
    const w = computePageWindow(3, 100);
    expect(w).toEqual([1, 2, 3, 4, "ellipsis", 100]);
  });

  it("near the end, the ellipsis is on the near-start side instead", () => {
    const w = computePageWindow(100, 100);
    expect(w).toEqual([1, "ellipsis", 99, 100]);
  });

  it("in the middle of a large range, both ellipses appear", () => {
    const w = computePageWindow(50, 100);
    expect(w).toEqual([1, "ellipsis", 49, 50, 51, "ellipsis", 100]);
  });

  it("always includes page 1 and the last page", () => {
    for (const page of [1, 25, 50, 75, 100]) {
      const w = computePageWindow(page, 100);
      expect(w[0]).toBe(1);
      expect(w[w.length - 1]).toBe(100);
    }
  });
});
