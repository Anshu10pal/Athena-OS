export interface PageInfoT {
  /** Clamped into [1, totalPages] -- always a page that actually exists for
   * the current row count, even if the URL asks for one that doesn't. */
  page: number;
  totalPages: number;
  /** Slice bounds into the full sorted row array. */
  start: number;
  end: number;
}

// `totalRows` is the count AFTER filtering and sorting -- the same number
// "Page 3 of 13 · 248 files" states. Clamping here (rather than trusting
// whatever page the URL names) is what keeps a stale `?page=40` from a
// since-narrowed filter from rendering an empty table instead of the last
// real page.
export function computePageInfo(requestedPage: number, totalRows: number, pageSize: number): PageInfoT {
  const totalPages = Math.max(1, Math.ceil(totalRows / pageSize));
  const page = Math.min(Math.max(1, requestedPage), totalPages);
  const start = (page - 1) * pageSize;
  const end = Math.min(totalRows, start + pageSize);
  return { page, totalPages, start, end };
}

export type PageWindowItemT = number | "ellipsis";

// The page-number row: always the first and last page, the current page and
// one sibling on each side, "ellipsis" standing in for whatever is skipped.
// A bare list of every page number is what the cluster chip row already
// proved doesn't scale -- apache/superset's reading list is 13 pages, which
// is fine to spell out in full, but a repo an order of magnitude bigger
// should not turn this row into a second wall of controls.
export function computePageWindow(page: number, totalPages: number, siblingCount: number = 1): PageWindowItemT[] {
  if (totalPages <= 1) return [1];

  const left = Math.max(2, page - siblingCount);
  const right = Math.min(totalPages - 1, page + siblingCount);

  const items: PageWindowItemT[] = [1];
  if (left > 2) items.push("ellipsis");
  for (let p = left; p <= right; p++) items.push(p);
  if (right < totalPages - 1) items.push("ellipsis");
  items.push(totalPages);
  return items;
}
