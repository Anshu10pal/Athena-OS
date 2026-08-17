import { HealthFileT } from "./api";

// Shaping for the per-file health panel on Focus.
//
// GET /api/repos/{id}/health/files has existed since Phase H with per-file
// scores AND the stored marker explanations, and nothing in the UI called it.
// That is the third instance of the reachability pattern after clustering being
// off-path and jobs/latest never being requested -- a real feature reachable by
// no user action.
//
// Focus is where it belongs: a user there is already looking at exactly one
// file, which is the unit this endpoint reports on.
//
// DOM-free and tested, matching the convention every other lib module follows.

/** A marker that actually fired, with the numbers behind it. The endpoint
 *  returns every marker it evaluated, including the ~85% that came back clean --
 *  those are evidence the marker RAN, not findings, and a panel that listed them
 *  would bury the handful that mean something. */
export type FiredMarker = {
  key: string;
  label: string;
  severity: number;
  detail: string;
};

export type FileHealthPanelT = {
  /** Null when the axis was N/A for this file -- never coerced to 0, which
   *  would read as "measured and bad" rather than "not measured". */
  maintainability: number | null;
  architecture: number | null;
  exposure: number | null;
  nloc: number;
  /** Fired markers, worst first. */
  markers: FiredMarker[];
  /** Markers evaluated that did NOT fire. Reported as a count rather than a
   *  list: "9 markers checked, 2 fired" is the honest framing and tells a
   *  reader the clean ones were measured rather than skipped. */
  cleanMarkerCount: number;
  /** Markers with no input at all -- a coverage gap, which is a different
   *  thing from a clean result and must not be counted as one. */
  noInputMarkerCount: number;
};

const AXES = ["maintainability", "architecture_health", "change_hotspot"] as const;

export function shapeFileHealth(file: HealthFileT | null | undefined): FileHealthPanelT | null {
  if (!file) return null;

  const markers: FiredMarker[] = [];
  let clean = 0;
  let noInput = 0;

  for (const axis of AXES) {
    const block = (file.explanation ?? {})[axis] as { markers?: any[] } | undefined;
    for (const m of block?.markers ?? []) {
      const severity = typeof m.severity === "number" ? m.severity : null;
      if (m.status === "no_input" || severity === null) {
        noInput += 1;
        continue;
      }
      if (severity <= 0) {
        clean += 1;
        continue;
      }
      markers.push({
        key: m.key ?? "?",
        label: m.label ?? m.key ?? "?",
        severity,
        detail: m.detail ?? m.evidence ?? "",
      });
    }
  }

  // Worst first, ties by label so the order is stable across renders rather
  // than depending on sort implementation -- the same tie-break the cluster
  // list and the findings queue use.
  markers.sort((a, b) => b.severity - a.severity || a.label.localeCompare(b.label));

  return {
    maintainability: file.maintainability,
    architecture: file.architecture_health,
    exposure: file.adjusted_exposure,
    nloc: file.nloc,
    markers,
    cleanMarkerCount: clean,
    noInputMarkerCount: noInput,
  };
}

/** Band for display. Deliberately not a colour: the caller decides how to
 *  render, and a null score has no band at all rather than a neutral one --
 *  "not measured" is not a grade. */
export function severityBand(severity: number): "high" | "medium" | "low" {
  if (severity >= 0.75) return "high";
  if (severity >= 0.25) return "medium";
  return "low";
}
