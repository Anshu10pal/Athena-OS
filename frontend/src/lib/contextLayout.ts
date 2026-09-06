/** Phase 8 checkpoint 3b-2 -- tray structure and collapse for the Context view.
 *
 *  PURE. Everything the component needs to decide is decided here, so the
 *  component only draws. Vitest is environment:node and there are no component
 *  tests, so any logic left in the .tsx is logic nothing verifies.
 *
 *  THE ONE INVARIANT THIS FILE EXISTS TO HOLD: what is drawn reconciles to
 *  connected_files_distinct. Every tray reports its own total AND the sum of its
 *  visible groups, so a collapsed group that loses its count breaks an assertion
 *  rather than quietly shrinking the blast radius on screen.
 *
 *    source tray + test tray            == importers        (134 + 124 = 258)
 *    imports                            == 22
 *    imports + importers - both         == 274              == connected_files_distinct
 *    shown groups + aggregated groups   == that tray's total
 */
import { ContextGraphT, DirectionT } from "./contextGraph";

/** How many folder groups are drawn individually before the rest are folded
 *  into one explicit aggregate. 12 was measured, not guessed: on 2256's 258
 *  importers the 12 largest two-segment groups cover 91%. */
export const SHOWN_GROUPS = 12;

/** D21: TWO segments. Measured alternatives, both rejected -- top-level gives 2
 *  groups (all information lost), full dirname gives 95 with 50 singletons
 *  (more objects than the cut it was meant to avoid). */
export const FOLDER_SEGMENTS = 2;

/** D22/T1: the `tests/` PATH PREFIX, and nothing else.
 *
 *  NEVER classify on basename. Measured on 2256: a basename classifier
 *  (`test_*.py` / `*_test.py` / `conftest.py`) misclassifies
 *  `superset/commands/database/test_connection.py` -- production code that tests
 *  a database CONNECTION -- as a test, and misses 46 of the 124 real test files,
 *  because Superset uses a plural `*_tests.py` suffix plus helper modules
 *  (`base_tests.py`, `api_tests.py`, `dashboard_utils.py`). The prefix
 *  misclassifies nothing.
 */
export function isTestPath(path: string): boolean {
  return path.startsWith("tests/");
}

export function folderKey(path: string, segments = FOLDER_SEGMENTS): string {
  const parts = path.split("/");
  if (parts.length <= 1) return "(root)";
  return parts.slice(0, Math.min(segments, parts.length - 1)).join("/");
}

export interface GroupT {
  key: string;
  /** VISIBLE on the group -- D1 requires the collapsed count to be readable. */
  fileCount: number;
  fileIds: number[];
  /** Dominant subsystem, nulls excluded from the vote (the `dominantCluster`
   *  rule: two files that each failed to cluster have not agreed on anything). */
  subsystemId: number | null;
  /** True when the group spans more than one subsystem -- it must not be
   *  painted as if it were one clean cluster. */
  mixed: boolean;
}

export interface TrayT {
  id: "imports" | "source" | "tests";
  label: string;
  /** Every file on this side, whether drawn individually or aggregated. */
  total: number;
  shown: GroupT[];
  /** null when nothing was folded away. */
  aggregate: { groupCount: number; fileCount: number } | null;
}

export interface ContextLayoutT {
  centre: { id: number; path: string };
  trays: TrayT[];
  /** Files that both import and are imported by the centre. ONE node each, on
   *  the importedBy side (D16), marked. */
  bothIds: Set<number>;
  unresolved: ContextGraphT["unresolved"];
  counts: {
    imports: number;
    importers: number;
    source: number;
    tests: number;
    both: number;
    connected: number;
    unresolved: number;
  };
}

function vote(fileIds: number[], subsystemOf: Map<number, number | null>) {
  const counts = new Map<number, number>();
  for (const id of fileIds) {
    const sid = subsystemOf.get(id);
    // Nulls excluded from the vote, never treated as a cluster of their own.
    if (sid == null) continue;
    counts.set(sid, (counts.get(sid) ?? 0) + 1);
  }
  if (counts.size === 0) return { subsystemId: null, mixed: false };
  let best: number | null = null;
  let bestCount = -1;
  for (const [sid, n] of [...counts].sort((a, b) => a[0] - b[0])) {
    if (n > bestCount) { best = sid; bestCount = n; }
  }
  return { subsystemId: best, mixed: counts.size > 1 };
}

function buildTray(
  id: TrayT["id"], label: string, paths: { id: number; path: string }[],
  subsystemOf: Map<number, number | null>, collapse: boolean,
): TrayT {
  const total = paths.length;
  if (!collapse) {
    // Imports side: 22 nodes, each its own group, so the same reconciliation
    // arithmetic applies uniformly rather than branching in the component.
    const shown = paths.map((p) => ({
      key: p.path, fileCount: 1, fileIds: [p.id],
      ...vote([p.id], subsystemOf),
    }));
    return { id, label, total, shown, aggregate: null };
  }

  const byFolder = new Map<string, number[]>();
  for (const p of paths) {
    const k = folderKey(p.path);
    if (!byFolder.has(k)) byFolder.set(k, []);
    byFolder.get(k)!.push(p.id);
  }
  const all: GroupT[] = [...byFolder.entries()]
    .map(([key, fileIds]) => ({ key, fileCount: fileIds.length, fileIds, ...vote(fileIds, subsystemOf) }))
    // Largest first, then by name so the order is stable across renders.
    .sort((a, b) => b.fileCount - a.fileCount || a.key.localeCompare(b.key));

  const shown = all.slice(0, SHOWN_GROUPS);
  const folded = all.slice(SHOWN_GROUPS);
  const aggregate = folded.length
    ? { groupCount: folded.length, fileCount: folded.reduce((s, g) => s + g.fileCount, 0) }
    : null;
  return { id, label, total, shown, aggregate };
}

export function buildContextLayout(
  graph: ContextGraphT,
  subsystemOf: Map<number, number | null>,
): ContextLayoutT {
  const centreNode = graph.nodes.find((n) => n.id === graph.centreId)!;
  const dirOf = (id: number): DirectionT => graph.directionOf.get(id)!;

  const neighbours = graph.nodes.filter((n) => n.id !== graph.centreId);
  const importSide = neighbours.filter((n) => {
    const d = dirOf(n.id);
    return d === "imports";
  });
  // D16: "both" renders ONCE, on the importedBy side.
  const importerSide = neighbours.filter((n) => {
    const d = dirOf(n.id);
    return d === "importedBy" || d === "both";
  });
  const bothIds = new Set(neighbours.filter((n) => dirOf(n.id) === "both").map((n) => n.id));

  // D22: the split is on the tests/ prefix only.
  const testSide = importerSide.filter((n) => isTestPath(n.path));
  const sourceSide = importerSide.filter((n) => !isTestPath(n.path));

  const trays: TrayT[] = [
    buildTray("imports", "Imports", importSide, subsystemOf, false),
    buildTray("source", "Imported by — source", sourceSide, subsystemOf, true),
    buildTray("tests", "Imported by — tests", testSide, subsystemOf, true),
  ];

  return {
    centre: { id: centreNode.id, path: centreNode.path },
    trays,
    bothIds,
    unresolved: graph.unresolved,
    counts: {
      // NOTE: `imports` here counts the IMPORT SIDE AS DRAWN, which excludes
      // "both" files (they are drawn on the importer side). The payload's
      // imports.total INCLUDES them, which is why the reconciliation below is
      // stated as imports + importers - both and not as a sum of these two.
      imports: importSide.length,
      importers: importerSide.length,
      source: sourceSide.length,
      tests: testSide.length,
      both: bothIds.size,
      connected: neighbours.length,
      unresolved: graph.unresolved.length,
    },
  };
}

/** Every tray's visible groups must account for its whole total. Returned
 *  rather than thrown so a caller can assert on it and the component can
 *  display it -- a reconciliation nobody can see is not a reconciliation. */
export function reconcile(layout: ContextLayoutT) {
  const perTray = layout.trays.map((t) => {
    const shownFiles = t.shown.reduce((s, g) => s + g.fileCount, 0);
    const aggFiles = t.aggregate?.fileCount ?? 0;
    return { id: t.id, total: t.total, accounted: shownFiles + aggFiles,
             ok: shownFiles + aggFiles === t.total };
  });
  const c = layout.counts;
  return {
    perTray,
    trayTotalsOk: perTray.every((t) => t.ok),
    // 134 + 124 = 258, the D22 binding constraint
    importerSplitOk: c.source + c.tests === c.importers,
    // the ck3b-1 identity, restated on the drawn structure
    connectedOk: c.imports + c.importers === c.connected,
    allOk(): boolean {
      return this.trayTotalsOk && this.importerSplitOk && this.connectedOk;
    },
  };
}
