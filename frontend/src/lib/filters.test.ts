import { describe, expect, it } from "vitest";
import { RankedFileT } from "./api";
import {
  applyFilterStateToSearchParams,
  deriveLanguages,
  deriveSubsystemIds,
  deriveTopLevelSegments,
  EMPTY_FILTER_STATE,
  filterFiles,
  filterStateFromSearchParams,
  topLevelSegment,
} from "./filters";

function makeFile(overrides: Partial<RankedFileT>): RankedFileT {
  return {
    file_id: 1,
    path: "a.py",
    language: "python",
    prior_category: "source",
    rank: 1,
    score: 0,
    fan_in: 0,
    fan_out: 0,
    pagerank: 0,
    is_entry_point: false,
    commit_count: null,
    distinct_authors: null,
    days_since_last_change: null,
    computed_at: "",
    subsystem_modularity_id: null,
    subsystem_louvain_id: null,
    subsystem_hdbscan_id: null,
    ...overrides,
  };
}

describe("topLevelSegment", () => {
  it("returns the first path segment", () => {
    expect(topLevelSegment("backend/app/main.py")).toBe("backend");
  });

  it("returns (root) for a file with no directory", () => {
    expect(topLevelSegment("README.md")).toBe("(root)");
  });
});

describe("deriveTopLevelSegments / deriveLanguages", () => {
  it("derives segments from data, not a hardcoded list", () => {
    const files = [
      makeFile({ path: "lib/api.js" }),
      makeFile({ path: "bin/eslint.js" }),
      makeFile({ path: "README.md" }),
    ];
    expect(deriveTopLevelSegments(files)).toEqual(["(root)", "bin", "lib"]);
  });

  it("derives languages from data", () => {
    const files = [makeFile({ language: "python" }), makeFile({ language: "typescript" }), makeFile({ language: "python" })];
    expect(deriveLanguages(files)).toEqual(["python", "typescript"]);
  });
});

describe("deriveSubsystemIds", () => {
  it("returns distinct, sorted subsystem ids, excluding null/unclustered files", () => {
    const files = [
      makeFile({ subsystem_modularity_id: 3 }),
      makeFile({ subsystem_modularity_id: 1 }),
      makeFile({ subsystem_modularity_id: 3 }),
      makeFile({ subsystem_modularity_id: null }),
    ];
    expect(deriveSubsystemIds(files, "modularity")).toEqual([1, 3]);
  });

  it("returns an empty list when clustering hasn't run", () => {
    const files = [makeFile({ subsystem_modularity_id: null }), makeFile({ subsystem_modularity_id: null })];
    expect(deriveSubsystemIds(files, "modularity")).toEqual([]);
  });

  it("reads a different column per algorithm -- a Louvain id has no meaning under modularity's column", () => {
    const files = [
      makeFile({ subsystem_modularity_id: 1, subsystem_louvain_id: 9, subsystem_hdbscan_id: 20 }),
      makeFile({ subsystem_modularity_id: 1, subsystem_louvain_id: 8, subsystem_hdbscan_id: 20 }),
    ];
    expect(deriveSubsystemIds(files, "modularity")).toEqual([1]);
    expect(deriveSubsystemIds(files, "louvain")).toEqual([8, 9]);
    expect(deriveSubsystemIds(files, "hdbscan")).toEqual([20]);
  });
});

describe("filterFiles", () => {
  it("preserves original rank values, producing gaps -- this is correct, not a bug", () => {
    // A file's rank is its position among ALL files in the repo, not among
    // whatever subset a filter happens to leave visible. Hiding
    // config/generated/migration files must never renumber the survivors
    // to a contiguous 1..N -- that would destroy the information a gap
    // like "1, 2, 3, 7, 9" actually carries.
    const files: RankedFileT[] = [
      makeFile({ file_id: 1, rank: 1, prior_category: "source" }),
      makeFile({ file_id: 2, rank: 2, prior_category: "source" }),
      makeFile({ file_id: 3, rank: 3, prior_category: "source" }),
      makeFile({ file_id: 4, rank: 4, prior_category: "config" }),
      makeFile({ file_id: 5, rank: 5, prior_category: "generated" }),
      makeFile({ file_id: 6, rank: 6, prior_category: "migration" }),
      makeFile({ file_id: 7, rank: 7, prior_category: "source" }),
      makeFile({ file_id: 8, rank: 8, prior_category: "config" }),
      makeFile({ file_id: 9, rank: 9, prior_category: "source" }),
    ];

    const visible = filterFiles(files, { ...EMPTY_FILTER_STATE, hideNoise: true });

    expect(visible.map((f) => f.rank)).toEqual([1, 2, 3, 7, 9]);
  });

  it("filters by selected path segments", () => {
    const files = [
      makeFile({ file_id: 1, path: "backend/main.py" }),
      makeFile({ file_id: 2, path: "frontend/App.tsx" }),
      makeFile({ file_id: 3, path: "backend/db.py" }),
    ];
    const visible = filterFiles(files, { ...EMPTY_FILTER_STATE, segments: ["backend"] });
    expect(visible.map((f) => f.file_id)).toEqual([1, 3]);
  });

  it("filters by selected languages", () => {
    const files = [
      makeFile({ file_id: 1, language: "python" }),
      makeFile({ file_id: 2, language: "typescript" }),
      makeFile({ file_id: 3, language: "python" }),
    ];
    const visible = filterFiles(files, { ...EMPTY_FILTER_STATE, languages: ["typescript"] });
    expect(visible.map((f) => f.file_id)).toEqual([2]);
  });

  it("hides zero fan-in files when toggled", () => {
    const files = [
      makeFile({ file_id: 1, fan_in: 0 }),
      makeFile({ file_id: 2, fan_in: 3 }),
    ];
    const visible = filterFiles(files, { ...EMPTY_FILTER_STATE, hideZeroFanIn: true });
    expect(visible.map((f) => f.file_id)).toEqual([2]);
  });

  it("filters by subsystem id when one is selected", () => {
    const files = [
      makeFile({ file_id: 1, subsystem_modularity_id: 5 }),
      makeFile({ file_id: 2, subsystem_modularity_id: 9 }),
      makeFile({ file_id: 3, subsystem_modularity_id: null }),
    ];
    const visible = filterFiles(files, { ...EMPTY_FILTER_STATE, subsystemId: 5 });
    expect(visible.map((f) => f.file_id)).toEqual([1]);
  });

  it("filters by the selected algorithm's own column, not modularity's, when subsystemAlgorithm is louvain/hdbscan", () => {
    // Same shape as the real bug this closed: a file whose LOUVAIN cluster
    // matches the selected id but whose MODULARITY cluster doesn't (or is
    // null) must still show up when subsystemAlgorithm is "louvain".
    const files = [
      makeFile({ file_id: 1, subsystem_modularity_id: null, subsystem_louvain_id: 7, subsystem_hdbscan_id: 3 }),
      makeFile({ file_id: 2, subsystem_modularity_id: 7, subsystem_louvain_id: 2, subsystem_hdbscan_id: 3 }),
    ];
    const louvain = filterFiles(files, { ...EMPTY_FILTER_STATE, subsystemId: 7, subsystemAlgorithm: "louvain" });
    expect(louvain.map((f) => f.file_id)).toEqual([1]);
    const hdbscan = filterFiles(files, { ...EMPTY_FILTER_STATE, subsystemId: 3, subsystemAlgorithm: "hdbscan" });
    expect(hdbscan.map((f) => f.file_id)).toEqual([1, 2]);
  });

  it("shows all files, including unclustered ones, when no subsystem filter is active", () => {
    const files = [
      makeFile({ file_id: 1, subsystem_modularity_id: 5 }),
      makeFile({ file_id: 2, subsystem_modularity_id: null }),
    ];
    const visible = filterFiles(files, EMPTY_FILTER_STATE);
    expect(visible.map((f) => f.file_id)).toEqual([1, 2]);
  });

  it("matches path search as a case-insensitive substring", () => {
    const files = [
      makeFile({ file_id: 1, path: "backend/app/Security.py" }),
      makeFile({ file_id: 2, path: "backend/app/models.py" }),
    ];
    const visible = filterFiles(files, { ...EMPTY_FILTER_STATE, query: "security" });
    expect(visible.map((f) => f.file_id)).toEqual([1]);
  });

  it("combines filters with AND semantics", () => {
    const files = [
      makeFile({ file_id: 1, path: "backend/main.py", language: "python", fan_in: 0 }),
      makeFile({ file_id: 2, path: "backend/db.py", language: "python", fan_in: 5 }),
      makeFile({ file_id: 3, path: "frontend/App.tsx", language: "typescript", fan_in: 5 }),
    ];
    const visible = filterFiles(files, {
      ...EMPTY_FILTER_STATE,
      segments: ["backend"],
      languages: ["python"],
      hideZeroFanIn: true,
    });
    expect(visible.map((f) => f.file_id)).toEqual([2]);
  });
});

describe("URL round-trip", () => {
  it("reconstructs the same filter state from search params it produced", () => {
    const state = {
      segments: ["backend", "frontend"],
      languages: ["python"],
      hideNoise: true,
      hideZeroFanIn: true,
      query: "security",
      subsystemId: 7,
      subsystemAlgorithm: "louvain" as const,
    };
    const params = new URLSearchParams();
    applyFilterStateToSearchParams(params, state);
    expect(filterStateFromSearchParams(params)).toEqual(state);
  });

  it("empty search params round-trip to the empty filter state", () => {
    expect(filterStateFromSearchParams(new URLSearchParams())).toEqual(EMPTY_FILTER_STATE);
  });

  it("an invalid subsystem param round-trips to null rather than NaN", () => {
    const params = new URLSearchParams({ subsystem: "not-a-number" });
    expect(filterStateFromSearchParams(params).subsystemId).toBeNull();
  });

  it("does not encode subsystemAlgo when no subsystem filter is active, even if non-default", () => {
    const params = new URLSearchParams();
    applyFilterStateToSearchParams(params, { ...EMPTY_FILTER_STATE, subsystemAlgorithm: "hdbscan" });
    expect(params.get("subsystemAlgo")).toBeNull();
  });

  it("an unrecognized subsystemAlgo param falls back to modularity", () => {
    const params = new URLSearchParams({ subsystem: "1", subsystemAlgo: "not-a-real-algorithm" });
    expect(filterStateFromSearchParams(params).subsystemAlgorithm).toBe("modularity");
  });
});
