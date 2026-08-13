import { SubsystemT } from "./api";

// Pure list shaping for the Dependency Clusters view: sorting, the singleton
// split, and the top-N slice. DOM-free so it can be unit-tested, matching the
// convention every other lib module here follows.
//
// 255 clusters on apache/superset rendered as a flat grid consumed most of the
// page. The three decisions below are what make that list usable, and each is
// separable from the rendering.

/** Clusters shown before "show all". Twenty is roughly one screen at three
 * columns -- enough to see the shape of the distribution without scrolling
 * past it to reach anything else. */
export const TOP_N = 20;

/** A cluster of one is a file that couples to nothing else strongly enough to
 * group. That is a real result and worth counting, but it is not a grouping,
 * and rendering 200 of them as 200 cards would bury the clusters that are.
 *
 * VERIFIED CURRENTLY UNREACHABLE, kept deliberately. The backend's
 * `_sorted_clusters` already drops single-member groups before persisting --
 * they are reported as `unclustered_count` and the view renders them as one
 * "Unclustered" card. Confirmed on apache/superset: 255 persisted clusters,
 * **zero** with `member_count <= 1`, smallest is 2.
 *
 * So this split is defensive, not load-bearing: it holds the invariant at the
 * boundary rather than trusting a filter in another process, and it is three
 * lines. It should not be mistaken for a feature that fires. */
export function isSingleton(s: SubsystemT): boolean {
  return s.member_count <= 1;
}

/** Visible files per cluster id under an active file filter, or null when no
 * filter is active.
 *
 * Computed by the caller from the FILTERED ranked-file list, which is the only
 * collection carrying subsystem membership for all three algorithms. */
export type VisibleCountsT = ReadonlyMap<number, number> | null;

export type ClusterListT = {
  /** Multi-member clusters, largest first. */
  grouped: SubsystemT[];
  /** Single-member clusters, aggregated by the caller into one row. */
  singletons: SubsystemT[];
  /** The slice to render: top N, or all when expanded. */
  visible: SubsystemT[];
  /** Files in any cluster, singletons included -- they are still clustered.
   * Under a filter this counts VISIBLE files, so it agrees with what the view
   * renders and with the filter bar's own counter. */
  clusteredFiles: number;
  /** How many files of each cluster the filter matched, or null when no filter
   * is active. A card must render "3 of 20 files" rather than "3 files" -- see
   * the note on the sort below. */
  visibleCounts: VisibleCountsT;
};

export function shapeClusterList(
  subsystems: SubsystemT[] | null | undefined,
  showAll: boolean,
  visibleCounts: VisibleCountsT = null,
): ClusterListT {
  const all = subsystems ?? [];

  // Under a filter, a cluster with no matching files is not a small cluster --
  // it is absent from what the user asked to see, and rendering it at zero
  // would put empty cards in front of the ones that matched.
  const present = visibleCounts ? all.filter((s) => (visibleCounts.get(s.id) ?? 0) > 0) : all;

  // The singleton split uses the TRUE member_count even under a filter, never
  // the filtered one. `isSingleton` means "this file couples to nothing else
  // strongly enough to group" -- a property of the repo. A 20-member cluster
  // showing one matching file is a mostly-filtered cluster, not a singleton,
  // and conflating them would have the filter MANUFACTURE a structural finding
  // that the analysis never made.
  const sizeOf = (s: SubsystemT) => (visibleCounts ? visibleCounts.get(s.id) ?? 0 : s.member_count);

  const grouped = present
    .filter((s) => !isSingleton(s))
    // Size descending: the biggest coupling group is the one worth reading
    // first, and it is otherwise buried at whatever index the cluster id
    // happens to give it. Ties broken by id so the order is stable across
    // renders rather than depending on sort implementation.
    //
    // Ordered by VISIBLE size under a filter, because a cluster with 40 members
    // of which 1 matched should not outrank one with 12 members all matching --
    // the user is reading the filtered set.
    .sort((a, b) => sizeOf(b) - sizeOf(a) || a.id - b.id);
  const singletons = present.filter(isSingleton);

  return {
    grouped,
    singletons,
    visible: showAll ? grouped : grouped.slice(0, TOP_N),
    clusteredFiles: present.reduce((n, s) => n + sizeOf(s), 0),
    visibleCounts,
  };
}
