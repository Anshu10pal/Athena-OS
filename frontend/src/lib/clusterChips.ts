// The CLUSTER row of the file filter bar: which chips to render.
//
// On apache/superset this row renders 254 chips and consumes the entire
// viewport, pushing the content of every file-keyed view below the fold. The
// Reading list, Layers, Dependency Clusters and the graph views are all affected
// -- a user scrolls past the filter bar to reach the thing they came for, on
// every tab.
//
// The cluster LIST solved this already (top-N with "show all"); the cluster
// FILTER never did. Same treatment, same reasoning.
//
// PATH (12 chips) and LANGUAGE (4) are naturally bounded by the repo's shape
// and are deliberately left alone -- capping a list that never grows adds a
// control that never does anything.

/** Chips shown before "show all". Twenty is roughly two rows at this size --
 * enough to cover the clusters worth filtering by without the row becoming the
 * page. Same figure as the cluster list and the findings queue, for the same
 * reason. */
export const TOP_N = 20;

export type ClusterChipsT = {
  /** The chips to render, in order. */
  visible: number[];
  /** How many are not shown. Zero when everything fits or `showAll` is set. */
  hiddenCount: number;
  /** True when the selected cluster is only present because selection forces
   * it -- i.e. it fell outside the top N. Lets the caller explain why a chip
   * appears out of size order rather than looking like a sort bug. */
  selectedPinned: boolean;
};

/**
 * Largest clusters first, capped at `topN`, with the SELECTED chip always
 * present.
 *
 * The selection guarantee is the important part. A selected filter that
 * scrolled out of view is worse than an uncapped list: the view is narrowed,
 * the control that narrowed it is invisible, and there is no way to switch it
 * off except by finding it again. Cluster 231 of 254 is exactly the case --
 * choosing it from "show all" and then collapsing must not hide it.
 */
export function shapeClusterChips(
  ids: number[],
  sizeById: ReadonlyMap<number, number>,
  selectedId: number | null,
  showAll: boolean,
  topN: number = TOP_N,
): ClusterChipsT {
  // Size descending, ties by id so the order is stable across renders rather
  // than depending on sort implementation -- the same tie-break the cluster
  // list and the findings queue use.
  const ordered = [...ids].sort(
    (a, b) => (sizeById.get(b) ?? 0) - (sizeById.get(a) ?? 0) || a - b,
  );

  if (showAll || ordered.length <= topN) {
    return { visible: ordered, hiddenCount: 0, selectedPinned: false };
  }

  const head = ordered.slice(0, topN);
  const selectedOutsideHead =
    selectedId !== null && ordered.includes(selectedId) && !head.includes(selectedId);

  return {
    // Appended rather than inserted by size: a chip that jumped into the middle
    // of a size-ordered row would read as a sort bug. At the end, after the
    // largest ones, it reads as what it is -- pinned because it is selected.
    visible: selectedOutsideHead ? [...head, selectedId] : head,
    hiddenCount: ordered.length - head.length - (selectedOutsideHead ? 1 : 0),
    selectedPinned: selectedOutsideHead,
  };
}
