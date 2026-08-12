import { describe, expect, it } from "vitest";
import { HealthDirectoriesT } from "./api";
import {
  bandOf,
  barFraction,
  hotCohortSentence,
  rankDirectories,
  shortPath,
} from "./healthRollup";

function dir(path: string, axes: Record<string, any>, nloc = 100, depth = 1) {
  return { path, depth, files_total: 1, nloc, axes };
}

function axis(over: Partial<any> = {}) {
  return {
    files_scored: 5,
    files_na: 0,
    weighted_mean: 8,
    mean: 8,
    worst: 6,
    worst_path: "a/b.ts",
    rankable: true,
    ...over,
  };
}

function payload(directories: any[], hot: Partial<any> = {}): HealthDirectoriesT {
  return {
    snapshot_id: 1,
    rollup_version: 1,
    files_in_snapshot: 10,
    min_files_to_rank: 3,
    directories,
    weakest: {},
    hot_cohort: {
      available: false, na_reason: null, hot_files: 0, hot_mean: null,
      baseline_files: 0, baseline_mean: null, delta: null, churn_threshold: null,
      caveat: null, paths: [], axis: "maintainability", axis_note: "note",
      ...hot,
    },
    staleness: { stale: false, reason: null, detail: null },
  } as HealthDirectoriesT;
}

describe("rankDirectories", () => {
  it("orders health axes worst-first, meaning lowest first", () => {
    const data = payload([
      dir("good", { maintainability: axis({ weighted_mean: 9.5 }) }),
      dir("bad", { maintainability: axis({ weighted_mean: 4.0 }) }),
      dir("mid", { maintainability: axis({ weighted_mean: 7.0 }) }),
    ]);
    expect(rankDirectories(data, "maintainability").ranked.map((r) => r.path))
      .toEqual(["bad", "mid", "good"]);
  });

  it("orders Change Hotspot the other way, since higher means review sooner", () => {
    const data = payload([
      dir("calm", { change_hotspot: axis({ weighted_mean: 0.5 }) }),
      dir("busy", { change_hotspot: axis({ weighted_mean: 6.0 }) }),
    ]);
    expect(rankDirectories(data, "change_hotspot").ranked.map((r) => r.path))
      .toEqual(["busy", "calm"]);
  });

  it("breaks ties on size so the bigger problem leads", () => {
    const data = payload([
      dir("small", { maintainability: axis({ weighted_mean: 5 }) }, 50),
      dir("large", { maintainability: axis({ weighted_mean: 5 }) }, 5000),
    ]);
    expect(rankDirectories(data, "maintainability").ranked[0].path).toBe("large");
  });

  it("separates unrankable directories rather than dropping them", () => {
    const data = payload([
      dir("ranked", { maintainability: axis({ rankable: true }) }),
      dir("tiny", { maintainability: axis({ rankable: false, weighted_mean: 2 }) }),
    ]);
    const { ranked, unrankable } = rankDirectories(data, "maintainability");
    expect(ranked.map((r) => r.path)).toEqual(["ranked"]);
    expect(unrankable.map((r) => r.path)).toEqual(["tiny"]);
  });

  it("omits directories with no score on the selected axis", () => {
    const data = payload([
      dir("scored", { maintainability: axis() }),
      dir("na", { maintainability: axis({ weighted_mean: null }) }),
    ]);
    const { ranked, unrankable } = rankDirectories(data, "maintainability");
    expect([...ranked, ...unrankable].map((r) => r.path)).toEqual(["scored"]);
  });

  it("carries the scored and not-measured counts onto every row", () => {
    const data = payload([
      dir("pkg", { maintainability: axis({ files_scored: 2, files_na: 38 }) }),
    ]);
    const row = rankDirectories(data, "maintainability").ranked[0];
    expect(row.filesScored).toBe(2);
    expect(row.filesNa).toBe(38);
  });

  it("returns empty lists for null data rather than throwing", () => {
    expect(rankDirectories(null, "maintainability")).toEqual({ ranked: [], unrankable: [] });
  });
});

describe("barFraction", () => {
  it("draws a longer bar for a worse health score", () => {
    expect(barFraction(4, "maintainability")).toBeGreaterThan(barFraction(9, "maintainability"));
  });

  it("draws a longer bar for higher hotspot exposure, so longer always means worse", () => {
    expect(barFraction(7, "change_hotspot")).toBeGreaterThan(barFraction(1, "change_hotspot"));
  });

  it("clamps out-of-range values", () => {
    expect(barFraction(99, "change_hotspot")).toBe(1);
    expect(barFraction(11, "maintainability")).toBe(0);
  });
});

describe("bandOf", () => {
  it("uses coarse bands on the health axes", () => {
    expect(bandOf(9, "maintainability")).toBe("good");
    expect(bandOf(8, "maintainability")).toBe("mixed");
    expect(bandOf(6, "maintainability")).toBe("poor");
  });

  it("inverts for change hotspot", () => {
    expect(bandOf(0.5, "change_hotspot")).toBe("good");
    expect(bandOf(5, "change_hotspot")).toBe("poor");
  });
});

describe("shortPath", () => {
  it("keeps two segments so a common leaf name stays identifiable", () => {
    expect(shortPath("backend/app/services/codebase")).toBe("…/services/codebase");
  });

  it("leaves short paths intact", () => {
    expect(shortPath("backend/app")).toBe("backend/app");
  });

  it("names the root sentinel readably", () => {
    expect(shortPath("(root)")).toBe("(repo root)");
  });
});

describe("hotCohortSentence", () => {
  it("returns null when the comparison was not available", () => {
    expect(hotCohortSentence(payload([], { available: false }))).toBeNull();
  });

  it("states the gap and its direction", () => {
    const s = hotCohortSentence(payload([], {
      available: true, hot_mean: 8.39, baseline_mean: 9.43, delta: -1.03,
    }));
    expect(s).toContain("8.39");
    expect(s).toContain("1.03 below");
  });

  it("names the axis, since the sentence sits above a lens-switched table", () => {
    const s = hotCohortSentence(payload([], {
      available: true, hot_mean: 8.39, baseline_mean: 9.43, delta: -1.03,
    }));
    expect(s).toContain("on Maintainability");
  });

  it("names the axis in the no-gap wording too", () => {
    const s = hotCohortSentence(payload([], {
      available: true, hot_mean: 9.0, baseline_mean: 9.0, delta: 0,
    }));
    expect(s).toContain("on Maintainability");
  });

  it("distinguishes no gap from no comparison", () => {
    const s = hotCohortSentence(payload([], {
      available: true, hot_mean: 9.0, baseline_mean: 9.0, delta: 0,
    }));
    expect(s).toContain("the same as the codebase overall");
  });

  it("handles a positive gap without saying 'below'", () => {
    const s = hotCohortSentence(payload([], {
      available: true, hot_mean: 9.8, baseline_mean: 9.0, delta: 0.8,
    }));
    expect(s).toContain("0.80 above");
  });
});
