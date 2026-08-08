import { describe, expect, it } from "vitest";
import { RankedFileT } from "./api";
import {
  applyFilterStateToSearchParams,
  deriveLanguages,
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
    };
    const params = new URLSearchParams();
    applyFilterStateToSearchParams(params, state);
    expect(filterStateFromSearchParams(params)).toEqual(state);
  });

  it("empty search params round-trip to the empty filter state", () => {
    expect(filterStateFromSearchParams(new URLSearchParams())).toEqual(EMPTY_FILTER_STATE);
  });
});
