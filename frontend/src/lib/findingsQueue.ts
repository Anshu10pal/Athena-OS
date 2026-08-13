import { FindingsRowT } from "./api";

// Pure list shaping for the Findings queue: the above-the-fold slice, the
// marker filter, and the summary counters. DOM-free so it can be unit-tested,
// matching the convention every other lib module here follows.
//
// The ordering itself is NOT here. Rows arrive scored and sorted from the
// backend, where the aggregation lives -- re-sorting them client-side would put
// a second, drifting copy of the ranking rule in a second language. This module
// only decides what is shown.

/** Rows above the fold before "show all". apache/superset produces 109 rows at
 * the default cap; 20 is roughly one screen and enough to see the shape of the
 * distribution without scrolling past it. Same figure and same reasoning as the
 * cluster list. */
export const TOP_N = 20;

export type FindingsSummaryT = {
  /** Rows after the marker filter. */
  rows: FindingsRowT[];
  /** The slice to render: top N, or all when expanded. */
  visible: FindingsRowT[];
  /** Files across the filtered rows. NOT distinct files -- one file appears in
   * as many rows as it has markers, and saying "N files" of a sum that
   * double-counts would be wrong. Labelled as findings for that reason. */
  findings: number;
  /** Distinct markers present, for the filter control. */
  markers: { marker: string; label: string; count: number }[];
  /** Rows no cap can divide. Surfaced as a count so the UI can explain them
   * once rather than per row. */
  irreducibleRows: number;
};

export function shapeFindings(
  rows: FindingsRowT[] | null | undefined,
  markerFilter: string | null,
  showAll: boolean,
): FindingsSummaryT {
  const all = rows ?? [];

  // Built from ALL rows, not the filtered set: a filter control that only
  // offers the marker already selected cannot be used to change the selection.
  const counts = new Map<string, { marker: string; label: string; count: number }>();
  for (const r of all) {
    const seen = counts.get(r.marker);
    if (seen) seen.count += 1;
    else counts.set(r.marker, { marker: r.marker, label: r.label, count: 1 });
  }

  const filtered = markerFilter ? all.filter((r) => r.marker === markerFilter) : all;

  return {
    rows: filtered,
    visible: showAll ? filtered : filtered.slice(0, TOP_N),
    findings: filtered.reduce((n, r) => n + r.file_count, 0),
    markers: [...counts.values()].sort((a, b) => b.count - a.count || a.marker.localeCompare(b.marker)),
    irreducibleRows: filtered.filter((r) => r.irreducible).length,
  };
}

/** A row scoring exactly zero has no exposure anywhere in it. Worth showing
 * differently from a low score: "nothing depends on these and they do not
 * change" is a different statement from "this scored 0.03". */
export function isUnexposed(row: FindingsRowT): boolean {
  return row.score === 0;
}
