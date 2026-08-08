import { DirEdgeT, DirNodeT } from "./api";

// Phase H4: the matrix stays UNCONDENSED on purpose -- H2/H3's SCC
// condensation collapses a cycle into one box specifically because a
// force/layered layout can't place two mutually-dependent nodes on
// either side of each other. A matrix has no such constraint: every real
// directory gets its own row and column, and a cycle shows up as an
// outlined pair with both directions' counts visible at once -- which is
// the actionable fact the architecture map's merged box necessarily
// hides (core -> db at one count, db -> core at a different one; the
// asymmetry is what's worth inspecting, and condensing throws it away).

export interface MatrixCell {
  rowId: string;
  colId: string;
  weight: number;
}

export function buildWeightLookup(edges: DirEdgeT[]): Map<string, number> {
  const lookup = new Map<string, number>();
  for (const e of edges) {
    lookup.set(`${e.source}=>${e.target}`, e.weight);
  }
  return lookup;
}

export function weightBetween(lookup: Map<string, number>, from: string, to: string): number {
  return lookup.get(`${from}=>${to}`) ?? 0;
}

export interface SymmetricPair {
  a: string;
  b: string;
  weightAB: number; // a -> b
  weightBA: number; // b -> a
}

// A pair where BOTH (a,b) and (b,a) have a real edge -- a direct 2-node
// cycle. This is deliberately NOT the same computation as H2's SCC
// condensation (which finds cycles of any length via transitive closure,
// e.g. x -> y -> z -> x has no direct reciprocal pair at all). The two
// are expected to agree only because, empirically, every real cycle in
// this repo happens to be a direct 2-node pair -- that agreement is a
// fact about this repo's data, not a guarantee the two algorithms make
// to each other in general. Reported once per unordered pair, not twice.
export function findSymmetricPairs(nodes: DirNodeT[], edges: DirEdgeT[]): SymmetricPair[] {
  const lookup = buildWeightLookup(edges);
  const ids = nodes.map((n) => n.id);
  const pairs: SymmetricPair[] = [];
  for (let i = 0; i < ids.length; i++) {
    for (let j = i + 1; j < ids.length; j++) {
      const a = ids[i];
      const b = ids[j];
      const weightAB = weightBetween(lookup, a, b);
      const weightBA = weightBetween(lookup, b, a);
      if (weightAB > 0 && weightBA > 0) {
        pairs.push({ a, b, weightAB, weightBA });
      }
    }
  }
  return pairs;
}
