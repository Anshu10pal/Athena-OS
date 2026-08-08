import { describe, expect, it } from "vitest";
import { DirEdgeT, DirNodeT } from "./api";
import { buildWeightLookup, findSymmetricPairs, weightBetween } from "./matrixLayout";

function makeNode(id: string): DirNodeT {
  return {
    id, path: id, short_label: id, file_count: 1, kind: "source", region: "backend",
    internal_edge_count: 0, fan_in_dirs: 0, fan_out_dirs: 0, import_count_in: 0, import_count_out: 0,
  };
}

function makeEdge(source: string, target: string, weight: number): DirEdgeT {
  return { source, target, weight, count: 1 };
}

describe("weightBetween / buildWeightLookup", () => {
  it("returns 0 for a pair with no edge, not undefined or an error", () => {
    const lookup = buildWeightLookup([makeEdge("a", "b", 5)]);
    expect(weightBetween(lookup, "b", "a")).toBe(0);
    expect(weightBetween(lookup, "a", "b")).toBe(5);
  });
});

describe("findSymmetricPairs", () => {
  it("finds a direct 2-node cycle -- the real core/db shape", () => {
    const nodes = [makeNode("core"), makeNode("db"), makeNode("api")];
    const edges = [makeEdge("core", "db", 2), makeEdge("db", "core", 1), makeEdge("api", "core", 5)];
    const pairs = findSymmetricPairs(nodes, edges);
    expect(pairs).toHaveLength(1);
    expect(new Set([pairs[0].a, pairs[0].b])).toEqual(new Set(["core", "db"]));
  });

  it("reports the asymmetric weight in each direction, not a merged total", () => {
    // This asymmetry is the actionable finding -- core -> db at 2 edges
    // against db -> core at 1 is the shape of a dependency worth
    // inverting, and the matrix must keep both numbers visible.
    const nodes = [makeNode("core"), makeNode("db")];
    const edges = [makeEdge("core", "db", 0.65), makeEdge("db", "core", 0.4)];
    const [pair] = findSymmetricPairs(nodes, edges);
    const [ab, ba] = pair.a === "core" ? [pair.weightAB, pair.weightBA] : [pair.weightBA, pair.weightAB];
    expect(ab).toBe(0.65);
    expect(ba).toBe(0.4);
  });

  it("does not report a one-directional edge as a cycle", () => {
    const nodes = [makeNode("app"), makeNode("api")];
    const edges = [makeEdge("app", "api", 3)];
    expect(findSymmetricPairs(nodes, edges)).toHaveLength(0);
  });

  it("does not report a transitive (indirect) cycle -- deliberately not SCC condensation", () => {
    // x -> y -> z -> x is a real cycle at the SCC level (H2), but no
    // single pair here has edges in BOTH directions -- the matrix's
    // pairwise check is a genuinely different, simpler computation.
    const nodes = [makeNode("x"), makeNode("y"), makeNode("z")];
    const edges = [makeEdge("x", "y", 1), makeEdge("y", "z", 1), makeEdge("z", "x", 1)];
    expect(findSymmetricPairs(nodes, edges)).toHaveLength(0);
  });

  it("reports each unordered pair only once", () => {
    const nodes = [makeNode("a"), makeNode("b")];
    const edges = [makeEdge("a", "b", 1), makeEdge("b", "a", 1)];
    expect(findSymmetricPairs(nodes, edges)).toHaveLength(1);
  });

  it("outlines a cycle even when one direction is far below the display print threshold", () => {
    // MatrixView's PRINT_THRESHOLD (8) governs only whether a cell's
    // number is drawn -- it must have zero bearing on whether a pair
    // counts as a cycle. 1 && 20 must still outline: if this were
    // threshold-gated instead of reading raw weightAB/weightBA, a real
    // cycle like core->db=2 && db->core=1 would silently fail to outline
    // on any repo where the print threshold happened to exceed 1 or 2.
    const nodes = [makeNode("core"), makeNode("db")];
    const edges = [makeEdge("core", "db", 1), makeEdge("db", "core", 20)];
    const pairs = findSymmetricPairs(nodes, edges);
    expect(pairs).toHaveLength(1);
    expect(pairs[0].weightAB + pairs[0].weightBA).toBe(21); // both real, neither dropped
  });

  it("finds multiple independent cycles in the same graph", () => {
    const nodes = [makeNode("core"), makeNode("db"), makeNode("agents"), makeNode("services")];
    const edges = [
      makeEdge("core", "db", 1), makeEdge("db", "core", 1),
      makeEdge("agents", "services", 1), makeEdge("services", "agents", 1),
    ];
    const pairs = findSymmetricPairs(nodes, edges);
    expect(pairs).toHaveLength(2);
  });
});
