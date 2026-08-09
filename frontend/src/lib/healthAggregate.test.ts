import { describe, expect, it } from "vitest";
import { HealthResponseT } from "./api";
import {
  aggregateBand,
  aggregateHealth,
  buildAxisTiles,
  HOTSPOT_AXIS,
} from "./healthAggregate";

function response(axes: Record<string, any>): HealthResponseT {
  return {
    snapshot: {
      id: 1, branch: "main", head_sha: "abc", working_tree_dirty: false,
      analyzer_version: 1, thresholds_version: 3, weights_version: 1,
      computed_at: "", files_scored: 10, files_na: 0, inputs_complete: true,
    },
    axes: axes as any,
    trend: { comparable: false, reason: null, deltas: {} },
  };
}

const axis = (mean: number | undefined, over: Record<string, any> = {}) => ({
  axis: "x", scored: 5, na: 0, na_reasons: {}, inputs_complete: true,
  resolution_limited: false, ...(mean === undefined ? {} : { mean }), ...over,
});

describe("buildAxisTiles", () => {
  it("returns a tile per axis, hotspot last", () => {
    const tiles = buildAxisTiles(response({
      maintainability: axis(9), architecture_health: axis(10), change_hotspot: axis(2),
    }));
    expect(tiles.map((t) => t.key)).toEqual([
      "maintainability", "architecture_health", "change_hotspot",
    ]);
  });

  it("maps a 1-10 health axis onto 10-100", () => {
    const tiles = buildAxisTiles(response({ maintainability: axis(9.45) }));
    expect(tiles[0].outOf100).toBe(95);
  });

  it("never normalises the hotspot axis, whose direction is opposite", () => {
    const tiles = buildAxisTiles(response({ change_hotspot: axis(2.5) }));
    const hotspot = tiles.find((t) => t.key === HOTSPOT_AXIS)!;
    expect(hotspot.value).toBe(2.5);
    expect(hotspot.outOf100).toBeNull();
    expect(hotspot.direction).toBe("higher_needs_attention");
  });

  it("marks an axis with no mean as unavailable rather than zero", () => {
    const tiles = buildAxisTiles(response({ maintainability: axis(undefined) }));
    expect(tiles[0].available).toBe(false);
    expect(tiles[0].value).toBeNull();
    expect(tiles[0].outOf100).toBeNull();
  });

  it("handles a missing snapshot entirely", () => {
    const tiles = buildAxisTiles(null);
    expect(tiles).toHaveLength(3);
    expect(tiles.every((t) => !t.available)).toBe(true);
  });

  it("carries the resolution-limited flag through to the tile", () => {
    const tiles = buildAxisTiles(response({
      change_hotspot: axis(1, { resolution_limited: true }),
    }));
    expect(tiles.find((t) => t.key === HOTSPOT_AXIS)!.resolutionLimited).toBe(true);
  });
});

describe("aggregateHealth", () => {
  it("averages the two health axes onto 0-100", () => {
    const tiles = buildAxisTiles(response({
      maintainability: axis(9), architecture_health: axis(10),
    }));
    const agg = aggregateHealth(tiles);
    expect(agg.score).toBe(95);
    expect(agg.axesUsed).toBe(2);
    expect(agg.partial).toBe(false);
  });

  it("EXCLUDES the hotspot axis from the aggregate", () => {
    // Not a calibration quibble: it is a review-priority ranking where higher
    // is worse, against quality scores where higher is better. Averaging them
    // would require silently inverting one.
    const withHotspot = buildAxisTiles(response({
      maintainability: axis(9), architecture_health: axis(10), change_hotspot: axis(9),
    }));
    const withoutHotspot = buildAxisTiles(response({
      maintainability: axis(9), architecture_health: axis(10),
    }));
    expect(aggregateHealth(withHotspot).score).toBe(aggregateHealth(withoutHotspot).score);
    expect(aggregateHealth(withHotspot).axesUsed).toBe(2);
  });

  it("hotspot tile states why it is excluded", () => {
    const tiles = buildAxisTiles(response({ change_hotspot: axis(3) }));
    const hotspot = tiles.find((t) => t.key === HOTSPOT_AXIS)!;
    expect(hotspot.includedInAggregate).toBe(false);
    expect(hotspot.exclusionReason).toMatch(/review-priority/);
  });

  it("excludes an unmeasurable axis from the mean instead of scoring it zero", () => {
    // Scoring it 0 would drag a genuinely-9 repo to 45; scoring it full marks
    // would invent evidence. Excluding it and saying so is the only honest
    // option -- the same rule the backend applies per marker.
    const tiles = buildAxisTiles(response({
      maintainability: axis(9), architecture_health: axis(undefined),
    }));
    const agg = aggregateHealth(tiles);
    expect(agg.score).toBe(90);
    expect(agg.axesUsed).toBe(1);
    expect(agg.axesPossible).toBe(2);
    expect(agg.partial).toBe(true);
  });

  it("reports null with a reason when nothing is measurable", () => {
    const agg = aggregateHealth(buildAxisTiles(null));
    expect(agg.score).toBeNull();
    expect(agg.naReason).toMatch(/nothing to aggregate/);
    expect(agg.axesUsed).toBe(0);
  });

  it("a hotspot-only repo still aggregates to null, not to the hotspot value", () => {
    const agg = aggregateHealth(buildAxisTiles(response({ change_hotspot: axis(4) })));
    expect(agg.score).toBeNull();
  });
});

describe("aggregateBand", () => {
  it("bands coarsely, since the axes are not calibrated against any outcome", () => {
    expect(aggregateBand(95)).toBe("good");
    expect(aggregateBand(70)).toBe("good");
    expect(aggregateBand(69)).toBe("mixed");
    expect(aggregateBand(45)).toBe("mixed");
    expect(aggregateBand(44)).toBe("poor");
  });
});
