import { describe, expect, it } from "vitest";
import { SubsystemT } from "./api";
import { isSingleton, shapeClusterList, TOP_N } from "./clusterList";

function sub(id: number, member_count: number): SubsystemT {
  return {
    id,
    cluster_index: id,
    member_count,
    custom_label: null,
    active_label_rule: "dominant_prefix",
    dominant_prefix_label: `pkg${id}`,
    dominant_prefix_count: member_count,
    top_fan_in_label: `file${id}`,
  } as unknown as SubsystemT;
}

describe("shapeClusterList", () => {
  it("sorts multi-member clusters largest first", () => {
    const { grouped } = shapeClusterList([sub(1, 3), sub(2, 40), sub(3, 12)], true);
    expect(grouped.map((s) => s.member_count)).toEqual([40, 12, 3]);
  });

  it("breaks ties by id so the order is stable across renders", () => {
    const { grouped } = shapeClusterList([sub(9, 5), sub(2, 5), sub(6, 5)], true);
    expect(grouped.map((s) => s.id)).toEqual([2, 6, 9]);
  });

  it("splits singletons out of the grouped list", () => {
    const { grouped, singletons } = shapeClusterList([sub(1, 1), sub(2, 8), sub(3, 1)], true);
    expect(grouped.map((s) => s.id)).toEqual([2]);
    expect(singletons.map((s) => s.id)).toEqual([1, 3]);
  });

  it("treats a zero-member cluster as a singleton rather than dropping it", () => {
    expect(isSingleton(sub(1, 0))).toBe(true);
    const { grouped, singletons } = shapeClusterList([sub(1, 0)], true);
    expect(grouped).toHaveLength(0);
    expect(singletons).toHaveLength(1);
  });

  it("shows only the top N until expanded", () => {
    const many = Array.from({ length: 255 }, (_, i) => sub(i + 1, 100 - (i % 90)));
    expect(shapeClusterList(many, false).visible).toHaveLength(TOP_N);
    expect(shapeClusterList(many, true).visible.length).toBe(
      shapeClusterList(many, true).grouped.length,
    );
  });

  it("counts singletons as clustered files, because they are", () => {
    const { clusteredFiles } = shapeClusterList([sub(1, 10), sub(2, 1)], true);
    expect(clusteredFiles).toBe(11);
  });

  it("handles null data without throwing", () => {
    const r = shapeClusterList(null, false);
    expect(r.grouped).toEqual([]);
    expect(r.singletons).toEqual([]);
    expect(r.visible).toEqual([]);
    expect(r.clusteredFiles).toBe(0);
  });

  it("does not mutate the caller's array", () => {
    const input = [sub(1, 3), sub(2, 40)];
    const before = input.map((s) => s.id);
    shapeClusterList(input, true);
    expect(input.map((s) => s.id)).toEqual(before);
  });
});

describe("shapeClusterList under an active file filter", () => {
  const clusters = [sub(1, 20), sub(2, 12), sub(3, 40), sub(4, 1)];

  it("drops clusters no file matched rather than rendering them at zero", () => {
    // An empty card in front of the ones that matched is worse than absence:
    // the user asked to see a narrowed set, and a zero-match cluster is not in
    // it.
    const counts = new Map([[1, 3], [3, 5]]);
    const { grouped } = shapeClusterList(clusters, true, counts);
    expect(grouped.map((s) => s.id)).toEqual([3, 1]);
  });

  it("orders by MATCHING size, not true size", () => {
    // Cluster 3 has 40 members but only 1 matched; cluster 2 has 12 and all
    // matched. The user is reading the filtered set, so 2 leads.
    const counts = new Map([[3, 1], [2, 12]]);
    const { grouped } = shapeClusterList(clusters, true, counts);
    expect(grouped.map((s) => s.id)).toEqual([2, 3]);
  });

  it("LOADBEARING: a mostly-filtered cluster is not reclassified as a singleton", () => {
    // isSingleton means "this file couples to nothing else strongly enough to
    // group" -- a property of the repo, not of the current filter. If the split
    // used the filtered count, a 20-member cluster showing one match would be
    // rendered as a singleton, and the filter would MANUFACTURE a structural
    // finding the analysis never made.
    const counts = new Map([[1, 1]]);
    const { grouped, singletons } = shapeClusterList(clusters, true, counts);
    expect(grouped.map((s) => s.id)).toEqual([1]);
    expect(singletons).toEqual([]);
  });

  it("keeps a genuine singleton a singleton when it matches", () => {
    const counts = new Map([[4, 1]]);
    const { grouped, singletons } = shapeClusterList(clusters, true, counts);
    expect(grouped).toEqual([]);
    expect(singletons.map((s) => s.id)).toEqual([4]);
  });

  it("counts matching files, so the total agrees with the filter bar", () => {
    // The bar reports the filtered file count; this number sits beside it and
    // must describe the same population.
    const counts = new Map([[1, 3], [2, 4], [3, 5]]);
    const { clusteredFiles } = shapeClusterList(clusters, true, counts);
    expect(clusteredFiles).toBe(12);
  });

  it("returns the counts it was given so a card can show both numbers", () => {
    const counts = new Map([[1, 3]]);
    const shaped = shapeClusterList(clusters, true, counts);
    expect(shaped.visibleCounts?.get(1)).toBe(3);
  });

  it("is unchanged from the unfiltered path when counts are null", () => {
    const withNull = shapeClusterList(clusters, true, null);
    const withDefault = shapeClusterList(clusters, true);
    expect(withNull.grouped.map((s) => s.id)).toEqual(withDefault.grouped.map((s) => s.id));
    expect(withNull.clusteredFiles).toBe(withDefault.clusteredFiles);
    expect(withNull.visibleCounts).toBeNull();
  });

  it("still slices to TOP_N under a filter", () => {
    const many = Array.from({ length: TOP_N + 5 }, (_, i) => sub(i + 1, 10));
    const counts = new Map(many.map((s) => [s.id, 2]));
    expect(shapeClusterList(many, false, counts).visible).toHaveLength(TOP_N);
  });
});
