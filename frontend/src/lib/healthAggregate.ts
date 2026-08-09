import { HealthAxisT, HealthResponseT } from "./api";

// Overview tiles: an aggregate out of 100 plus each axis on its own.
//
// The aggregate is a real departure from docs/code-health-contract.md §0.1
// ("three separate axes, no blended score"), made deliberately as a product
// decision. What it does NOT do is quietly blend things that cannot be
// blended, so two rules are enforced here rather than left to the caller:
//
// 1. **Only the health axes are aggregated.** Change Hotspot is excluded --
//    not because it is uncalibrated (that alone would be an argument for a
//    caveat), but because it is a different KIND of quantity. It is a review
//    -priority ranking where higher means worse, against two quality scores
//    where higher means better. Averaging them would require silently
//    inverting one, and the result would answer no question at all. It still
//    gets its own tile; it just is not part of "health out of 100".
//
// 2. **Unavailable axes are excluded from the mean, never counted as zero
//    or as full marks.** The tile reports how many axes it is actually based
//    on, so "100 from one axis" can never be mistaken for "100 from all of
//    them" -- the same exclude-don't-zero rule the backend applies per marker.

export const AGGREGATE_AXES = ["maintainability", "architecture_health"] as const;
export const HOTSPOT_AXIS = "change_hotspot";

export interface AxisTileT {
  key: string;
  label: string;
  /** Value on the axis's own scale (1-10, or 0-9 exposure). Null when N/A. */
  value: number | null;
  /** Higher-is-better, 0-100. Null for the hotspot axis (wrong direction to
   *  normalise this way) and for any unavailable axis. */
  outOf100: number | null;
  direction: "higher_is_better" | "higher_needs_attention";
  available: boolean;
  naReason: string | null;
  resolutionLimited: boolean;
  includedInAggregate: boolean;
  exclusionReason: string | null;
}

export interface HealthAggregateT {
  /** 0-100, higher is better. Null when no health axis was measurable. */
  score: number | null;
  axesUsed: number;
  axesPossible: number;
  /** Present only when score is null -- never a stand-in for a number. */
  naReason: string | null;
  /** True when at least one health axis could not be measured, so the score
   *  is a partial view even though it rendered. */
  partial: boolean;
}

const LABELS: Record<string, string> = {
  maintainability: "Maintainability",
  architecture_health: "Architecture",
  change_hotspot: "Change Hotspot",
};

function axisValue(axis: HealthAxisT | undefined): number | null {
  if (!axis || axis.mean === undefined || axis.mean === null) return null;
  return axis.mean;
}

export function buildAxisTiles(data: HealthResponseT | null): AxisTileT[] {
  const axes = data?.axes ?? {};
  const keys = [...AGGREGATE_AXES, HOTSPOT_AXIS];

  return keys.map((key) => {
    const axis = axes[key];
    const value = axisValue(axis);
    const isHotspot = key === HOTSPOT_AXIS;
    return {
      key,
      label: LABELS[key] ?? key,
      value,
      // 1-10 maps to 10-100. The floor is 1, not 0, so the bottom of the
      // scale shows as 10 rather than implying a zero that the engine
      // cannot produce.
      outOf100: !isHotspot && value !== null ? Math.round(value * 10) : null,
      direction: isHotspot ? "higher_needs_attention" : "higher_is_better",
      available: value !== null,
      naReason: axis?.na_reasons
        ? Object.keys(axis.na_reasons)[0] ?? null
        : null,
      resolutionLimited: axis?.resolution_limited ?? false,
      includedInAggregate: !isHotspot && value !== null,
      exclusionReason: isHotspot
        ? "A review-priority ranking, not a quality score — higher means review sooner. Averaging it with the health axes would require inverting it, and the result would answer no question."
        : value === null
        ? "Not measurable for this repo."
        : null,
    };
  });
}

export function aggregateHealth(tiles: AxisTileT[]): HealthAggregateT {
  const candidates = tiles.filter((t) => AGGREGATE_AXES.includes(t.key as any));
  const used = candidates.filter((t) => t.includedInAggregate && t.outOf100 !== null);

  if (used.length === 0) {
    return {
      score: null,
      axesUsed: 0,
      axesPossible: candidates.length,
      naReason:
        "No structural axis could be measured for this repo — nothing to aggregate.",
      partial: false,
    };
  }

  const score = Math.round(
    used.reduce((sum, t) => sum + (t.outOf100 as number), 0) / used.length
  );
  return {
    score,
    axesUsed: used.length,
    axesPossible: candidates.length,
    naReason: null,
    partial: used.length < candidates.length,
  };
}

/** Band for colouring only. Deliberately coarse: the underlying axes are not
 *  calibrated against any outcome, so a finer gradient would imply precision
 *  the numbers do not have. */
export function aggregateBand(score: number): "good" | "mixed" | "poor" {
  if (score >= 70) return "good";
  if (score >= 45) return "mixed";
  return "poor";
}
