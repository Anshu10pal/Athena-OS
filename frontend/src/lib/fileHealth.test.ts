import { describe, expect, it } from "vitest";
import { HealthFileT } from "./api";
import { severityBand, shapeFileHealth } from "./fileHealth";

function marker(key: string, severity: number | null, over: Record<string, unknown> = {}) {
  return { key, label: key.replace(/_/g, " "), severity, detail: `${key} detail`, ...over };
}

// `Record<string, unknown>` rather than `Partial<HealthFileT>`: the overrides
// deliberately supply loose marker shapes (a missing field, a `status` the real
// type does not declare) to exercise how shapeFileHealth handles them, and a
// strict partial rejects exactly those cases.
function file(over: Record<string, unknown> = {}): HealthFileT {
  return {
    file_id: 1,
    path: "pkg/a.py",
    nloc: 120,
    maintainability: 7.5,
    architecture_health: 9,
    exposure: 3,
    adjusted_exposure: 1.2,
    explanation: {
      maintainability: { markers: [marker("large_file", 0.8), marker("deep_nesting", 0)] },
      architecture_health: { markers: [marker("cycle_participation", 0.4)] },
      change_hotspot: { markers: [marker("churn_volume", 0)] },
    },
    ...over,
  } as unknown as HealthFileT;
}

describe("shapeFileHealth", () => {
  it("returns null for a missing file rather than an empty panel", () => {
    // "no health data" and "health data showing nothing wrong" are different
    // claims and the caller renders them differently.
    expect(shapeFileHealth(null)).toBeNull();
    expect(shapeFileHealth(undefined)).toBeNull();
  });

  it("LOADBEARING: only markers that FIRED become findings", () => {
    // ~85% of marker slots evaluate to zero severity. They are evidence the
    // marker ran, not findings, and listing them would bury the ones that mean
    // something.
    const p = shapeFileHealth(file())!;
    expect(p.markers.map((m) => m.key)).toEqual(["large_file", "cycle_participation"]);
    expect(p.cleanMarkerCount).toBe(2);
  });

  it("LOADBEARING: a marker with no input is counted apart from a clean one", () => {
    // A coverage gap is not a clean result. Folding them together would report
    // "checked and fine" for something never measured.
    const p = shapeFileHealth(file({
      explanation: {
        maintainability: { markers: [marker("large_file", null, { status: "no_input" })] },
      },
    }))!;
    expect(p.noInputMarkerCount).toBe(1);
    expect(p.cleanMarkerCount).toBe(0);
    expect(p.markers).toEqual([]);
  });

  it("reads all three axes", () => {
    const p = shapeFileHealth(file())!;
    // architecture's marker fired and is present alongside maintainability's.
    expect(p.markers.some((m) => m.key === "cycle_participation")).toBe(true);
  });

  it("orders markers worst first with a stable tie-break", () => {
    const p = shapeFileHealth(file({
      explanation: {
        maintainability: { markers: [marker("zebra", 0.5), marker("alpha", 0.5), marker("worst", 0.9)] },
      },
    }))!;
    expect(p.markers.map((m) => m.key)).toEqual(["worst", "alpha", "zebra"]);
  });

  it("LOADBEARING: a null score stays null and is never coerced to zero", () => {
    // 0.00 reads as "measured and bad"; n/a reads as "not measured".
    const p = shapeFileHealth(file({
      maintainability: null, architecture_health: null, adjusted_exposure: null,
    }))!;
    expect(p.maintainability).toBeNull();
    expect(p.architecture).toBeNull();
    expect(p.exposure).toBeNull();
  });

  it("survives an explanation with missing axes or no markers", () => {
    const p = shapeFileHealth(file({ explanation: {} }))!;
    expect(p.markers).toEqual([]);
    expect(p.cleanMarkerCount).toBe(0);
  });
});

describe("severityBand", () => {
  it("bands at the contract's thresholds", () => {
    expect(severityBand(0.9)).toBe("high");
    expect(severityBand(0.75)).toBe("high");
    expect(severityBand(0.5)).toBe("medium");
    expect(severityBand(0.25)).toBe("medium");
    expect(severityBand(0.1)).toBe("low");
  });
});

