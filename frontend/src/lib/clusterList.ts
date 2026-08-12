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

export type ClusterListT = {
  /** Multi-member clusters, largest first. */
  grouped: SubsystemT[];
  /** Single-member clusters, aggregated by the caller into one row. */
  singletons: SubsystemT[];
  /** The slice to render: top N, or all when expanded. */
  visible: SubsystemT[];
  /** Files in any cluster, singletons included -- they are still clustered. */
  clusteredFiles: number;
};

export function shapeClusterList(
  subsystems: SubsystemT[] | null | undefined,
  showAll: boolean,
): ClusterListT {
  const all = subsystems ?? [];
  const grouped = all
    .filter((s) => !isSingleton(s))
    // Size descending: the biggest coupling group is the one worth reading
    // first, and it is otherwise buried at whatever index the cluster id
    // happens to give it. Ties broken by id so the order is stable across
    // renders rather than depending on sort implementation.
    .sort((a, b) => b.member_count - a.member_count || a.id - b.id);
  const singletons = all.filter(isSingleton);

  return {
    grouped,
    singletons,
    visible: showAll ? grouped : grouped.slice(0, TOP_N),
    clusteredFiles: all.reduce((n, s) => n + s.member_count, 0),
  };
}
