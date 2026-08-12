import { DirectoryRollupT, HealthDirectoriesT, RollupAxisT } from "./api";

// Sort, format and lens logic for the directory health view. No DOM, no React
// -- the interesting decisions here are about direction and about what happens
// when a directory has nothing to report, and both are worth testing without a
// renderer in the way.

export const ROLLUP_AXES = [
  { key: "maintainability", label: "Maintainability", higherIsWorse: false },
  { key: "architecture_health", label: "Architecture", higherIsWorse: false },
  { key: "change_hotspot", label: "Change Hotspot", higherIsWorse: true },
] as const;

export type RollupAxisKeyT = (typeof ROLLUP_AXES)[number]["key"];

export function axisMeta(key: RollupAxisKeyT) {
  return ROLLUP_AXES.find((a) => a.key === key)!;
}

export type DirRowT = {
  path: string;
  label: string;
  depth: number;
  value: number;
  unweighted: number | null;
  filesScored: number;
  filesNa: number;
  nloc: number;
  worst: number | null;
  worstPath: string | null;
  rankable: boolean;
};

function axisOf(d: DirectoryRollupT, key: RollupAxisKeyT): RollupAxisT | undefined {
  return d.axes?.[key];
}

/** Last two path segments, so a long path stays identifiable without wrapping.
 * Never the leaf alone: half this repo's leaves are called `lib`, `api` or
 * `components`, and a list of those names identifies nothing. */
export function shortPath(path: string): string {
  if (path === "(root)") return "(repo root)";
  const parts = path.split("/");
  return parts.length <= 2 ? path : `…/${parts.slice(-2).join("/")}`;
}

function toRow(d: DirectoryRollupT, key: RollupAxisKeyT): DirRowT | null {
  const a = axisOf(d, key);
  if (!a || a.weighted_mean === null) return null;
  return {
    path: d.path,
    label: shortPath(d.path),
    depth: d.depth,
    value: a.weighted_mean,
    unweighted: a.mean,
    filesScored: a.files_scored,
    filesNa: a.files_na,
    nloc: d.nloc,
    worst: a.worst,
    worstPath: a.worst_path,
    rankable: a.rankable,
  };
}

/** Directories ordered worst-first for the given axis.
 *
 * Direction is per axis: Change Hotspot counts up, the health axes count down.
 * Getting this wrong would put the calmest directory at the top of a list
 * headed "review these first". Ties break on size, so the larger of two
 * equally-scored directories leads -- it is more code to fix. */
export function rankDirectories(
  data: HealthDirectoriesT | null,
  key: RollupAxisKeyT,
): { ranked: DirRowT[]; unrankable: DirRowT[] } {
  if (!data) return { ranked: [], unrankable: [] };
  const rows = data.directories.map((d) => toRow(d, key)).filter((r): r is DirRowT => r !== null);
  const { higherIsWorse } = axisMeta(key);

  const cmp = (a: DirRowT, b: DirRowT) =>
    (higherIsWorse ? b.value - a.value : a.value - b.value) || b.nloc - a.nloc;

  return {
    ranked: rows.filter((r) => r.rankable).sort(cmp),
    // Reported, never hidden: a directory held back from the ranking for
    // sample size has still been measured, and dropping it silently would read
    // as "nothing found here".
    unrankable: rows.filter((r) => !r.rankable).sort(cmp),
  };
}

/** Fraction of the axis's own scale, for a bar. Health axes run 1-10 and are
 * drawn as "how much is missing"; Change Hotspot runs 0-9 and is drawn as how
 * much has accumulated. Both therefore render "longer bar = worse". */
export function barFraction(value: number, key: RollupAxisKeyT): number {
  const f = key === "change_hotspot" ? value / 9 : (10 - value) / 9;
  return Math.max(0, Math.min(1, f));
}

/** Bands are coarse on purpose. The thresholds behind these numbers are
 * reasoned defaults, not fitted to any outcome, so a finer gradient would imply
 * precision they do not have. */
export function bandOf(value: number, key: RollupAxisKeyT): "good" | "mixed" | "poor" {
  if (key === "change_hotspot") {
    if (value >= 4) return "poor";
    if (value >= 1.5) return "mixed";
    return "good";
  }
  if (value < 7) return "poor";
  if (value < 8.5) return "mixed";
  return "good";
}

export function compactNloc(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

/** The one-sentence summary of the change cohort, or null when the comparison
 * could not honestly be made. Never returns a sentence built from a gap of
 * zero -- "the files you change most score exactly the same" is a real result
 * and reads differently from a missing one. */
export function hotCohortSentence(data: HealthDirectoriesT | null): string | null {
  const h = data?.hot_cohort;
  if (!h || !h.available || h.hot_mean === null || h.baseline_mean === null || h.delta === null) {
    return null;
  }
  const direction = h.delta < 0 ? "below" : "above";
  const magnitude = Math.abs(h.delta).toFixed(2);
  // Names the axis. The cohort is always Maintainability -- the only axis with
  // no change-history input, so the comparison is not circular -- but the
  // sentence sits above a table that follows the lens selector. On the
  // Architecture lens a reader would otherwise connect "8.49" to the
  // architecture numbers directly beneath it.
  if (Math.abs(h.delta) < 0.005) {
    return `The files you change most score ${h.hot_mean.toFixed(
      2,
    )} on Maintainability — the same as the codebase overall.`;
  }
  return `The files you change most score ${h.hot_mean.toFixed(
    2,
  )} on Maintainability — ${magnitude} ${direction} the codebase overall.`;
}
