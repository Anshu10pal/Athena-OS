import { NeighborT } from "./api";
import { dirnameOfPath } from "./layeredLayout";

// Phase H4: shared by the Focus view and the Mermaid export -- "group
// neighbours by directory and collapse to a count" is explicitly the SAME
// aggregation principle in both places (the brief's own words), so both
// call this one function rather than keeping two implementations that
// could silently drift (Focus showing "api/ ×14" while Mermaid's own
// count came out different because its grouping logic diverged).
export interface NeighborGroup {
  dir: string;
  count: number;
  files: NeighborT[];
}

export function shortDirLabel(dir: string): string {
  if (dir === "(root)") return "(root)";
  return dir.split("/").pop() ?? dir;
}

export function groupNeighborsByDirectory(neighbors: NeighborT[]): NeighborGroup[] {
  const byDir = new Map<string, NeighborT[]>();
  for (const n of neighbors) {
    const dir = dirnameOfPath(n.path);
    if (!byDir.has(dir)) byDir.set(dir, []);
    byDir.get(dir)!.push(n);
  }
  return [...byDir.entries()]
    .map(([dir, files]) => ({ dir, count: files.length, files }))
    .sort((a, b) => b.count - a.count); // largest, most-informative group first
}
