import { describe, expect, it } from "vitest";
import { shapeClusterChips, TOP_N } from "./clusterChips";

const sizes = (entries: [number, number][]) => new Map(entries);

describe("shapeClusterChips", () => {
  it("orders by size descending", () => {
    const { visible } = shapeClusterChips(
      [1, 2, 3], sizes([[1, 5], [2, 40], [3, 12]]), null, false,
    );
    expect(visible).toEqual([2, 3, 1]);
  });

  it("breaks size ties by id so the order is stable across renders", () => {
    const { visible } = shapeClusterChips(
      [9, 2, 6], sizes([[9, 7], [2, 7], [6, 7]]), null, false,
    );
    expect(visible).toEqual([2, 6, 9]);
  });

  it("caps at topN and reports how many are hidden", () => {
    const ids = Array.from({ length: 254 }, (_, i) => i + 1);
    const sizeMap = sizes(ids.map((id) => [id, 300 - id] as [number, number]));
    const { visible, hiddenCount } = shapeClusterChips(ids, sizeMap, null, false);

    expect(visible).toHaveLength(TOP_N);
    expect(hiddenCount).toBe(254 - TOP_N);
  });

  it("shows everything when expanded", () => {
    const ids = Array.from({ length: 254 }, (_, i) => i + 1);
    const sizeMap = sizes(ids.map((id) => [id, 300 - id] as [number, number]));
    const { visible, hiddenCount } = shapeClusterChips(ids, sizeMap, null, true);

    expect(visible).toHaveLength(254);
    expect(hiddenCount).toBe(0);
  });

  it("LOADBEARING: a selected chip outside the top N is still rendered", () => {
    // A selected filter that scrolled out of view is worse than an uncapped
    // list: the view is narrowed, the control that narrowed it is invisible,
    // and there is no way to switch it off except by finding it again.
    const ids = Array.from({ length: 254 }, (_, i) => i + 1);
    const sizeMap = sizes(ids.map((id) => [id, 300 - id] as [number, number]));
    const { visible, selectedPinned } = shapeClusterChips(ids, sizeMap, 231, false);

    expect(visible).toContain(231);
    expect(selectedPinned).toBe(true);
  });

  it("LOADBEARING: pinning the selection does not push a real chip out", () => {
    // The pinned chip is extra, not a replacement -- otherwise selecting a small
    // cluster silently drops the largest one from the row.
    const ids = Array.from({ length: 254 }, (_, i) => i + 1);
    const sizeMap = sizes(ids.map((id) => [id, 300 - id] as [number, number]));
    const { visible, hiddenCount } = shapeClusterChips(ids, sizeMap, 231, false);

    expect(visible).toHaveLength(TOP_N + 1);
    expect(visible.slice(0, TOP_N)).toEqual(
      shapeClusterChips(ids, sizeMap, null, false).visible,
    );
    // The pinned one is no longer hidden, so the count drops by exactly one.
    expect(hiddenCount).toBe(254 - TOP_N - 1);
  });

  it("does not pin a selection that is already in the top N", () => {
    const ids = Array.from({ length: 254 }, (_, i) => i + 1);
    const sizeMap = sizes(ids.map((id) => [id, 300 - id] as [number, number]));
    const { visible, selectedPinned } = shapeClusterChips(ids, sizeMap, 1, false);

    expect(selectedPinned).toBe(false);
    expect(visible).toHaveLength(TOP_N);
  });

  it("ignores a selected id that is not in this algorithm's cluster set", () => {
    // Switching algorithm leaves a subsystemId from the previous one in filter
    // state; it must not be pinned into a row it does not belong to.
    const { visible, selectedPinned } = shapeClusterChips(
      [1, 2, 3], sizes([[1, 9], [2, 8], [3, 7]]), 999, false, 2,
    );
    expect(visible).toEqual([1, 2]);
    expect(selectedPinned).toBe(false);
  });

  it("treats a cluster with no recorded size as smallest rather than dropping it", () => {
    // Sizes come from a separate fetch than the ids. A missing entry must not
    // remove a real, selectable cluster from the row.
    const { visible } = shapeClusterChips(
      [1, 2, 3], sizes([[1, 5], [3, 12]]), null, false,
    );
    expect(visible).toEqual([3, 1, 2]);
  });

  it("does not mutate the ids it is given", () => {
    const ids = [1, 2, 3];
    shapeClusterChips(ids, sizes([[1, 1], [2, 9], [3, 5]]), null, false);
    expect(ids).toEqual([1, 2, 3]);
  });
});
