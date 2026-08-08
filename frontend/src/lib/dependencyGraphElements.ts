import { dirnameOfPath } from "./layeredLayout";
import { edgeKey, ScopeEdge, ScopeNode } from "./dependencyGraphScope";

// Phase J1: turns a scoped file graph (dependencyGraphScope.ts) into
// Cytoscape elements, collapsing folders into single nodes unless the user
// has expanded them.
//
// Folder collapsing is the second half of the anti-hairball design (the
// first being hop-scoping). Twelve files in one directory that all import
// the same module produce twelve near-identical edges; as one collapsed
// folder node they produce one edge labelled x12, which is the same
// information at a legible density. Expansion is per-folder and explicit,
// so detail appears only where it was asked for -- the same principle the
// Architecture map's expand-one-box-at-a-time already uses.
//
// Pure: no cytoscape import here. This module returns plain element
// descriptors; the component feeds them to cytoscape. That keeps the
// mapping (which is where the real logic is) unit-testable without a DOM.

export const FILE_PREFIX = "f:";
export const DIR_PREFIX = "d:";

export function fileNodeId(fileId: number): string {
  return `${FILE_PREFIX}${fileId}`;
}

export function dirNodeId(dir: string): string {
  return `${DIR_PREFIX}${dir}`;
}

export type GraphNodeKindT = "file" | "dir";

export interface CyNodeData {
  id: string;
  label: string;
  kind: GraphNodeKindT;
  /** Compound parent id -- set only for files inside an EXPANDED folder. */
  parent?: string;
  fileId?: number;
  path?: string;
  /** Files represented by this node: 1 for a file, N for a collapsed folder. */
  fileCount: number;
  /** Shortest hop distance from the focus set; 0 for the focus itself. */
  hop: number;
  isFocus: boolean;
  clusterId: number | null;
  /** True when a collapsed folder's files span more than one cluster -- the
   *  node must not be painted as if it were one clean cluster. Same honesty
   *  rule as the Architecture map's cluster_purity dashed treatment. */
  clusterMixed: boolean;
  /** Edges wholly inside this collapsed folder, hidden at this granularity.
   *  Surfaced as a count so "expanding reveals edges that weren't there
   *  before" is explained rather than surprising. */
  internalEdgeCount: number;
}

export interface CyEdgeData {
  id: string;
  source: string;
  target: string;
  /** Underlying file->file edges this one represents (>1 only when at least
   *  one endpoint is a collapsed folder). */
  count: number;
  /** True if ANY underlying file->file edge closes a cycle among the files
   *  currently on screen. Deliberately "any", not "all": a folder-to-folder
   *  edge that hides even one cyclic dependency is worth flagging, since the
   *  whole reason to look at a collapsed view is to decide where to expand. */
  cyclic: boolean;
}

export interface CyElements {
  nodes: { data: CyNodeData }[];
  edges: { data: CyEdgeData }[];
}

export interface BuildElementsInput {
  nodes: ScopeNode[];
  scopedNodeIds: number[];
  scopedEdges: ScopeEdge[];
  hopOf: Map<number, number>;
  cycleEdgeKeys: Set<string>;
  focusIds: number[];
  expandedDirs: Set<string>;
}

/** Last path segment -- a folder node labelled with its full path is
 *  unreadable inside a graph box, and the full path stays available on the
 *  node's own data for the detail panel and tooltip. */
export function shortDirLabel(dir: string): string {
  const idx = dir.lastIndexOf("/");
  return idx === -1 ? dir : dir.slice(idx + 1);
}

export function fileLabel(path: string): string {
  const idx = path.lastIndexOf("/");
  return idx === -1 ? path : path.slice(idx + 1);
}

interface DirGroup {
  dir: string;
  fileIds: number[];
  expanded: boolean;
}

/**
 * A folder is expanded when the user asked for it, OR when it contains a
 * focus file. The second clause is not a convenience -- without it,
 * focusing a file whose folder happens to be collapsed would hide the one
 * node the entire view is built around.
 *
 * A folder holding exactly one in-scope file is rendered as a bare file
 * node either way: a compound box wrapped around a single child is pure
 * visual overhead, and the two representations would otherwise differ only
 * in which label they show.
 */
function groupByDirectory(
  nodes: ScopeNode[], scopedNodeIds: number[], focusIds: number[], expandedDirs: Set<string>,
): { groups: DirGroup[]; nodeById: Map<number, ScopeNode> } {
  const nodeById = new Map(nodes.map((n) => [n.id, n]));
  const focusSet = new Set(focusIds);
  const byDir = new Map<string, number[]>();

  for (const id of scopedNodeIds) {
    const node = nodeById.get(id);
    if (!node) continue;
    const dir = dirnameOfPath(node.path);
    if (!byDir.has(dir)) byDir.set(dir, []);
    byDir.get(dir)!.push(id);
  }

  const groups: DirGroup[] = [];
  for (const [dir, fileIds] of byDir) {
    const holdsFocus = fileIds.some((id) => focusSet.has(id));
    const expanded = expandedDirs.has(dir) || holdsFocus || fileIds.length === 1;
    groups.push({ dir, fileIds: [...fileIds].sort((a, b) => a - b), expanded });
  }
  groups.sort((a, b) => a.dir.localeCompare(b.dir));
  return { groups, nodeById };
}

function dominantCluster(fileIds: number[], nodeById: Map<number, ScopeNode>): {
  clusterId: number | null; mixed: boolean;
} {
  const counts = new Map<number, number>();
  for (const id of fileIds) {
    const cid = nodeById.get(id)?.subsystem_modularity_id;
    // Unclustered files are excluded from the vote, never treated as a
    // cluster of their own. Two files that each failed to cluster have not
    // agreed on anything -- the same exclusion rule the backend applies in
    // _cluster_of and in the ESLint validation's recall computation.
    if (cid == null) continue;
    counts.set(cid, (counts.get(cid) ?? 0) + 1);
  }
  if (counts.size === 0) return { clusterId: null, mixed: false };
  let best: number | null = null;
  let bestCount = -1;
  for (const [cid, count] of [...counts].sort((a, b) => a[0] - b[0])) {
    if (count > bestCount) { best = cid; bestCount = count; }
  }
  return { clusterId: best, mixed: counts.size > 1 };
}

export function buildGraphElements(input: BuildElementsInput): CyElements {
  const { nodes, scopedNodeIds, scopedEdges, hopOf, cycleEdgeKeys, focusIds, expandedDirs } = input;
  const { groups, nodeById } = groupByDirectory(nodes, scopedNodeIds, focusIds, expandedDirs);
  const focusSet = new Set(focusIds);

  // file id -> the cytoscape node that REPRESENTS it on screen. For a file
  // in an expanded folder that's the file itself; for a collapsed folder
  // it's the folder. Every edge is then rewritten through this map, which
  // is what makes collapse/expand a pure relabelling rather than a
  // different graph.
  const representativeOf = new Map<number, string>();
  const cyNodes: { data: CyNodeData }[] = [];

  for (const group of groups) {
    if (group.expanded) {
      // A multi-file expanded folder gets a compound parent so its files
      // stay visually grouped; a single-file one does not (see
      // groupByDirectory).
      const useCompound = group.fileIds.length > 1;
      if (useCompound) {
        const { clusterId, mixed } = dominantCluster(group.fileIds, nodeById);
        cyNodes.push({
          data: {
            id: dirNodeId(group.dir),
            label: group.dir,
            kind: "dir",
            fileCount: group.fileIds.length,
            hop: Math.min(...group.fileIds.map((id) => hopOf.get(id) ?? 0)),
            isFocus: false,
            clusterId,
            clusterMixed: mixed,
            internalEdgeCount: 0,
          },
        });
      }
      for (const id of group.fileIds) {
        const node = nodeById.get(id)!;
        representativeOf.set(id, fileNodeId(id));
        cyNodes.push({
          data: {
            id: fileNodeId(id),
            label: fileLabel(node.path),
            kind: "file",
            ...(useCompound ? { parent: dirNodeId(group.dir) } : {}),
            fileId: id,
            path: node.path,
            fileCount: 1,
            hop: hopOf.get(id) ?? 0,
            isFocus: focusSet.has(id),
            clusterId: node.subsystem_modularity_id ?? null,
            clusterMixed: false,
            internalEdgeCount: 0,
          },
        });
      }
    } else {
      const { clusterId, mixed } = dominantCluster(group.fileIds, nodeById);
      for (const id of group.fileIds) representativeOf.set(id, dirNodeId(group.dir));
      cyNodes.push({
        data: {
          id: dirNodeId(group.dir),
          label: shortDirLabel(group.dir),
          kind: "dir",
          path: group.dir,
          fileCount: group.fileIds.length,
          hop: Math.min(...group.fileIds.map((id) => hopOf.get(id) ?? 0)),
          isFocus: false,
          clusterId,
          clusterMixed: mixed,
          internalEdgeCount: 0,
        },
      });
    }
  }

  // Rewrite every file->file edge through representativeOf, aggregating
  // duplicates. An edge whose endpoints collapse to the SAME node is
  // internal to that folder: it isn't drawn (a self-loop conveys nothing
  // here) but it is counted on the node, so the folder can honestly say
  // how much it is hiding.
  const nodeDataById = new Map(cyNodes.map((n) => [n.data.id, n.data]));
  const aggregated = new Map<string, CyEdgeData>();

  for (const e of scopedEdges) {
    const s = representativeOf.get(e.source);
    const t = representativeOf.get(e.target);
    if (s === undefined || t === undefined) continue;
    const cyclic = cycleEdgeKeys.has(edgeKey(e.source, e.target));

    if (s === t) {
      const data = nodeDataById.get(s);
      if (data) data.internalEdgeCount += 1;
      continue;
    }

    const id = `${s}=>${t}`;
    const existing = aggregated.get(id);
    if (existing) {
      existing.count += 1;
      existing.cyclic = existing.cyclic || cyclic;
    } else {
      aggregated.set(id, { id, source: s, target: t, count: 1, cyclic });
    }
  }

  return {
    nodes: cyNodes,
    // Sorted for deterministic element order -- cytoscape is not
    // order-sensitive for correctness, but a stable order keeps snapshots
    // and re-renders comparable.
    edges: [...aggregated.values()].sort((a, b) => a.id.localeCompare(b.id)).map((data) => ({ data })),
  };
}

/** Directories present in the current scope that hold more than one file --
 *  i.e. the ones where expanding actually changes anything. Drives the
 *  component's expand/collapse control list. */
export function expandableDirs(
  nodes: ScopeNode[], scopedNodeIds: number[],
): { dir: string; fileCount: number }[] {
  const nodeById = new Map(nodes.map((n) => [n.id, n]));
  const counts = new Map<string, number>();
  for (const id of scopedNodeIds) {
    const node = nodeById.get(id);
    if (!node) continue;
    const dir = dirnameOfPath(node.path);
    counts.set(dir, (counts.get(dir) ?? 0) + 1);
  }
  return [...counts.entries()]
    .filter(([, count]) => count > 1)
    .map(([dir, fileCount]) => ({ dir, fileCount }))
    .sort((a, b) => b.fileCount - a.fileCount || a.dir.localeCompare(b.dir));
}
