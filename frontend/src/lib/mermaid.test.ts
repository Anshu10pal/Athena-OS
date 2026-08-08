import { describe, expect, it } from "vitest";
import { NeighborT, NeighborsResponseT } from "./api";
import { buildMermaidNeighborhood, MERMAID_GROUP_CAP_PER_DIRECTION, truncationNote } from "./mermaid";

function makeNeighbor(overrides: Partial<NeighborT>): NeighborT {
  return { file_id: 1, path: "a.py", rank: 1, score: 0.1, weight: 1, kind: "light_use", cross_root: null, ...overrides };
}

function makeData(overrides: Partial<NeighborsResponseT>): NeighborsResponseT {
  return {
    file_id: 0,
    path: "center.py",
    importers: [],
    importers_total_before_cap: 0,
    imports: [],
    imports_total_before_cap: 0,
    ...overrides,
  };
}

describe("buildMermaidNeighborhood", () => {
  it("generates a graph LR with the center file and one group per direction", () => {
    const data = makeData({
      importers: [makeNeighbor({ file_id: 1, path: "backend/app/api/repos.py" })],
      importers_total_before_cap: 1,
      imports: [makeNeighbor({ file_id: 2, path: "backend/app/db/models.py" })],
      imports_total_before_cap: 1,
    });
    const result = buildMermaidNeighborhood(data);
    expect(result.text.startsWith("graph LR")).toBe(true);
    expect(result.text).toContain('c0["center.py"]');
    expect(result.text).toContain('i0["api/ ×1"]');
    expect(result.text).toContain("i0 --> c0");
    expect(result.text).toContain('o0["db/ ×1"]');
    expect(result.text).toContain("c0 --> o0");
  });

  it("uses generated IDs, never a raw path or directory name, as node identifiers", () => {
    const data = makeData({
      importers: [makeNeighbor({ path: "backend/app/db/models.py" })],
      importers_total_before_cap: 1,
    });
    const result = buildMermaidNeighborhood(data);
    expect(result.text).toMatch(/^\s*i0\[/m);
    expect(result.text).not.toMatch(/^\s*db\[/m); // directory name is a LABEL, never an id
  });

  it("escapes quotes in the center file's label", () => {
    const data = makeData({ path: 'weird"file.py' });
    const result = buildMermaidNeighborhood(data);
    expect(result.text).toContain('c0["weird&quot;file.py"]');
  });

  it("the security.py case: 14 same-directory importers collapse to one node, not fourteen", () => {
    // The exact motivating shape: repeating "backend/app/api/" fourteen
    // times is what made the old per-file diagram unreadable at panel
    // width. Grouped, this is one node: "api/ ×14".
    const apiImporters = Array.from({ length: 14 }, (_, i) => makeNeighbor({ file_id: i, path: `backend/app/api/f${i}.py` }));
    const data = makeData({
      importers: apiImporters,
      importers_total_before_cap: 14,
      imports: [makeNeighbor({ file_id: 100, path: "backend/app/db/models.py" })],
      imports_total_before_cap: 1,
    });
    const result = buildMermaidNeighborhood(data);
    expect(result.importerGroupsShown).toHaveLength(1);
    expect(result.importerGroupsShown[0]).toEqual({ dir: "backend/app/api", label: "api/ ×14", count: 14 });
    expect(result.text).toContain('i0["api/ ×14"]');
    expect(result.text).not.toContain("f0.py"); // individual filenames never appear
  });

  it("caps at 8 GROUPS per direction, not files, and reports the true group total", () => {
    // 10 distinct importing directories, one file each -- more directories
    // than the cap, unlike the single-huge-directory case above.
    const importers = Array.from({ length: 10 }, (_, i) => makeNeighbor({ file_id: i, path: `dir${i}/f.py` }));
    const data = makeData({ importers, importers_total_before_cap: 10 });
    const result = buildMermaidNeighborhood(data);
    expect(result.importerGroupsShown).toHaveLength(MERMAID_GROUP_CAP_PER_DIRECTION);
    expect(result.importerGroupsTotal).toBe(10);
  });

  it("caps each direction independently, not pooled -- the models.py shape", () => {
    // fan-in 44 (all one directory), fan-out 1: the single outgoing group
    // must never be crowded out by the importer side.
    const manyImporters = Array.from({ length: 44 }, (_, i) => makeNeighbor({ file_id: i, path: `backend/app/api/f${i}.py` }));
    const data = makeData({
      importers: manyImporters,
      importers_total_before_cap: 44,
      imports: [makeNeighbor({ file_id: 999, path: "backend/app/core/config.py" })],
      imports_total_before_cap: 1,
    });
    const result = buildMermaidNeighborhood(data);
    expect(result.importerGroupsShown).toHaveLength(1); // one directory -> one group
    expect(result.importerGroupsShown[0].count).toBe(44);
    expect(result.importGroupsShown).toHaveLength(1);
    expect(result.text).toContain('o0["core/ ×1"]');
  });

  it("sorts groups by count descending -- the largest, most informative group first", () => {
    const importers = [
      makeNeighbor({ file_id: 1, path: "small/f.py" }),
      ...Array.from({ length: 5 }, (_, i) => makeNeighbor({ file_id: 10 + i, path: `big/f${i}.py` })),
    ];
    const data = makeData({ importers, importers_total_before_cap: 6 });
    const result = buildMermaidNeighborhood(data);
    expect(result.importerGroupsShown[0].dir).toBe("big");
    expect(result.importerGroupsShown[0].count).toBe(5);
  });

  it("reports the backend's own file-level cap independently of group truncation", () => {
    const data = makeData({ importers: [makeNeighbor({ path: "a/f.py" })], importers_total_before_cap: 87 });
    const result = buildMermaidNeighborhood(data);
    expect(result.importerFilesTotal).toBe(87); // backend capped before this ever saw the data
  });
});

describe("truncationNote", () => {
  it("returns null when nothing was truncated", () => {
    expect(truncationNote(3, 3, "importers")).toBeNull();
  });

  it("reports shown vs. true total when truncated", () => {
    expect(truncationNote(8, 10, "directories")).toBe("Showing 8 of 10 directories");
  });
});
