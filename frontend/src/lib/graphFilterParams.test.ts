import { describe, expect, it } from "vitest";
import { EMPTY_FILTER_STATE, FilterState } from "./filters";
import { graphFilterParams, graphFiltersChanged } from "./graphFilterParams";

const state = (over: Partial<FilterState> = {}): FilterState => ({ ...EMPTY_FILTER_STATE, ...over });

describe("graphFilterParams", () => {
  it("always carries scorer and level", () => {
    const qs = graphFilterParams("rrf", "directory", state());
    expect(qs).toContain("scorer=rrf");
    expect(qs).toContain("level=directory");
  });

  it("LOADBEARING: emits one key per value, never a join or the first only", () => {
    // A client collapsing a multi-select to one value silently under-filters,
    // and the user reads a plausible result computed from a third of what they
    // asked for. Three values, because a two-value test passes on an
    // implementation that only writes the last.
    const qs = graphFilterParams("legacy", "file",
      state({ languages: ["python", "typescript", "tsx"] }));

    expect([...new URLSearchParams(qs).getAll("languages")])
      .toEqual(["python", "typescript", "tsx"]);
    expect(qs).not.toContain("python,typescript");
    expect(qs).not.toContain("python%2Ctypescript");
  });

  it("LOADBEARING: the same holds for segments", () => {
    const qs = graphFilterParams("legacy", "file",
      state({ segments: ["backend", "frontend", "(root)"] }));
    expect([...new URLSearchParams(qs).getAll("segments")])
      .toEqual(["backend", "frontend", "(root)"]);
  });

  it("encodes a root segment so it survives the round trip", () => {
    // "(root)" is what topLevelSegment returns for a file with no "/", and the
    // server compares against the same literal.
    const qs = graphFilterParams("legacy", "file", state({ segments: ["(root)"] }));
    expect(new URLSearchParams(qs).get("segments")).toBe("(root)");
  });

  it("omits an empty or whitespace query rather than sending it", () => {
    expect(graphFilterParams("legacy", "file", state({ query: "" }))).not.toContain("query=");
    expect(graphFilterParams("legacy", "file", state({ query: "   " }))).not.toContain("query=");
  });

  it("trims a real query", () => {
    const qs = graphFilterParams("legacy", "file", state({ query: "  chart " }));
    expect(new URLSearchParams(qs).get("query")).toBe("chart");
  });

  it("sends hide_noise only when set", () => {
    expect(graphFilterParams("legacy", "file", state({ hideNoise: true }))).toContain("hide_noise=true");
    expect(graphFilterParams("legacy", "file", state({ hideNoise: false }))).not.toContain("hide_noise");
  });

  it("LOADBEARING: never sends the two filters the endpoint cannot honour", () => {
    // Sending them would be worse than useless: the endpoint ignores unknown
    // params, so the UI would appear to filter while the graph did not.
    const qs = graphFilterParams("legacy", "file",
      state({ hideZeroFanIn: true, subsystemId: 7, subsystemAlgorithm: "louvain" }));

    expect(qs).not.toContain("fan");
    expect(qs).not.toContain("subsystem");
  });
});

describe("graphFiltersChanged", () => {
  it("is false for an unchanged state", () => {
    expect(graphFiltersChanged(state(), state())).toBe(false);
  });

  it("detects each honoured filter changing", () => {
    const cases: Partial<FilterState>[] = [
      { segments: ["a"] },
      { languages: ["python"] },
      { query: "x" },
      { hideNoise: true },
    ];
    for (const patch of cases) {
      expect(graphFiltersChanged(state(), state(patch))).toBe(true);
    }
  });

  it("LOADBEARING: ignores filters the endpoint does not honour", () => {
    // Refetching on these would discard a correct response and re-run a whole
    // directory aggregation to produce the identical answer.
    expect(graphFiltersChanged(state(), state({ hideZeroFanIn: true }))).toBe(false);
    expect(graphFiltersChanged(state(), state({ subsystemId: 3 }))).toBe(false);
    expect(graphFiltersChanged(state(), state({ subsystemAlgorithm: "hdbscan" }))).toBe(false);
  });

  it("treats whitespace-only query edits as no change", () => {
    expect(graphFiltersChanged(state({ query: "a" }), state({ query: "a  " }))).toBe(false);
  });

  it("detects reordering as no change but membership as change", () => {
    // Order comes from the chip list, not the user, so a reorder is not an
    // intent change -- but adding one is.
    expect(graphFiltersChanged(state({ languages: ["a", "b"] }), state({ languages: ["a", "b"] }))).toBe(false);
    expect(graphFiltersChanged(state({ languages: ["a"] }), state({ languages: ["a", "b"] }))).toBe(true);
  });
});
