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
