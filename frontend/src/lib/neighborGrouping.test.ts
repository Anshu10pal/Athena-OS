import { describe, expect, it } from "vitest";
import { NeighborT } from "./api";
import { groupNeighborsByDirectory, shortDirLabel } from "./neighborGrouping";

function makeNeighbor(path: string, fileId: number): NeighborT {
  return { file_id: fileId, path, rank: fileId, score: 0.1, weight: 1, kind: "light_use", cross_root: null };
}

describe("shortDirLabel", () => {
  it("returns the basename of a nested directory", () => {
    expect(shortDirLabel("backend/app/api")).toBe("api");
  });

  it("passes the root sentinel through unchanged", () => {
    expect(shortDirLabel("(root)")).toBe("(root)");
  });
});

describe("groupNeighborsByDirectory", () => {
  it("groups the security.py shape: 14 files under one directory into one group", () => {
    const neighbors = Array.from({ length: 14 }, (_, i) => makeNeighbor(`backend/app/api/f${i}.py`, i));
    const groups = groupNeighborsByDirectory(neighbors);
    expect(groups).toHaveLength(1);
    expect(groups[0]).toMatchObject({ dir: "backend/app/api", count: 14 });
    expect(groups[0].files).toHaveLength(14);
  });

  it("keeps distinct directories as separate groups", () => {
    const neighbors = [makeNeighbor("a/x.py", 1), makeNeighbor("b/y.py", 2)];
    const groups = groupNeighborsByDirectory(neighbors);
    expect(groups.map((g) => g.dir).sort()).toEqual(["a", "b"]);
  });

  it("sorts groups by count descending", () => {
    const neighbors = [
      makeNeighbor("small/a.py", 1),
      makeNeighbor("big/a.py", 2), makeNeighbor("big/b.py", 3), makeNeighbor("big/c.py", 4),
    ];
    const groups = groupNeighborsByDirectory(neighbors);
    expect(groups[0].dir).toBe("big");
  });

  it("returns an empty list for no neighbors, not an error", () => {
    expect(groupNeighborsByDirectory([])).toEqual([]);
  });
});
