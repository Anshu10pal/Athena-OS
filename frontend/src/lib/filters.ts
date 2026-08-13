import { SubsystemAlgorithmT } from "./api";

// Phase G4: the minimal shape filterFiles/deriveTopLevelSegments/
// deriveLanguages actually need -- both RankedFileT and GraphNodeT satisfy
// this structurally, so the same filter logic (and the same URL state)
// applies to the Reading list and the Layers/Graph views without a cast
// or a duplicated second implementation.
export interface Filterable {
  path: string;
  language: string;
  prior_category: string;
  fan_in: number;
  // Phase I1 (extended I6): optional -- only RankedFileT (the Reading
  // list) carries subsystem membership; GraphNodeT/DirNodeT (Layers/
  // Architecture) don't, and filtering them by subsystem is out of scope
  // (the subsystem filter control is wired into the Reading list only --
  // see RepoDetail.tsx). Left optional here rather than duplicating a
  // second Filterable-like interface, so the same filterFiles keeps
  // working on every existing caller unchanged. One column per algorithm,
  // same shape as RankedFileT itself -- which one filterFiles/
  // deriveSubsystemIds actually reads is chosen by FilterState's own
  // subsystemAlgorithm, not hardcoded to modularity.
  subsystem_modularity_id?: number | null;
  subsystem_louvain_id?: number | null;
  subsystem_hdbscan_id?: number | null;
}

// Phase I6: which algorithm's cluster id a given Filterable carries for
// the currently active filter -- kept as a plain function (not inlined at
// every call site) since deriveSubsystemIds and filterFiles both need the
// exact same mapping.
export function subsystemIdOf(f: Filterable, algorithm: SubsystemAlgorithmT): number | null | undefined {
  if (algorithm === "louvain") return f.subsystem_louvain_id;
  if (algorithm === "hdbscan") return f.subsystem_hdbscan_id;
  return f.subsystem_modularity_id;
}

// Phase G2: prior_category values that are noise for reading-order purposes
// -- config/build/generated files, never real reading material -- kept as
// a named constant (not a magic list inline) since both the filter UI and
// its tests need the same three values.
export const NOISE_CATEGORIES = ["config", "migration", "generated"];

export interface FilterState {
  segments: string[]; // selected top-level path segments; empty = show all
  languages: string[]; // selected languages; empty = show all
  hideNoise: boolean; // hide prior_category in NOISE_CATEGORIES
  hideZeroFanIn: boolean; // hide the dangling floor
  query: string; // substring match against path
  // Phase I1 (extended I6): null = show all (no subsystem filter active).
  // A specific CodeSubsystem id, not a cluster_index -- ids are stable
  // identifiers, cluster_index is only stable within one compute_
  // subsystems run. subsystemAlgorithm records WHICH algorithm's id this
  // is -- a Louvain or HDBSCAN cluster id means nothing compared against
  // subsystem_modularity_id, so the two travel together.
  subsystemId: number | null;
  subsystemAlgorithm: SubsystemAlgorithmT;
}

export const EMPTY_FILTER_STATE: FilterState = {
  segments: [],
  languages: [],
  hideNoise: false,
  hideZeroFanIn: false,
  query: "",
  subsystemId: null,
  subsystemAlgorithm: "modularity",
};

// Whether any filter is narrowing the file set right now.
//
// `subsystemAlgorithm` is deliberately NOT part of this: it records WHICH
// algorithm's ids a subsystem filter refers to, and on its own selects nothing.
// Treating it as a filter would make every view believe it was filtered from
// first render, since it always has a value.
//
// Stated as one function rather than re-derived per caller: a view that suppresses
// a repo-wide statistic under a filter and a counter that reports a filtered
// total must agree about whether a filter is active, or one of them is lying.
export function isFilterActive(state: FilterState): boolean {
  return (
    state.segments.length > 0 ||
    state.languages.length > 0 ||
    state.hideNoise ||
    state.hideZeroFanIn ||
    state.query.trim() !== "" ||
    state.subsystemId !== null
  );
}

// "(root)" for a file with no "/" at all -- a repo's own top-level files
// (README.md, package.json) need a segment too, not to be silently dropped
// from the derived chip list.
export function topLevelSegment(path: string): string {
  const idx = path.indexOf("/");
  return idx === -1 ? "(root)" : path.slice(0, idx);
}

// Derived from the data every time, never hardcoded -- this repo happens to
// have backend/frontend, ESLint has lib/bin, and neither this function nor
// its caller should know or care which.
export function deriveTopLevelSegments(files: Filterable[]): string[] {
  return Array.from(new Set(files.map((f) => topLevelSegment(f.path)))).sort();
}

export function deriveLanguages(files: Filterable[]): string[] {
  return Array.from(new Set(files.map((f) => f.language))).sort();
}

// Distinct subsystem ids actually present among these files for ONE
// algorithm, sorted -- the caller looks up display labels from the
// fetched SubsystemsResponseT (this module has no knowledge of labels,
// same separation as deriveTopLevelSegments not knowing which segment is
// "important").
export function deriveSubsystemIds(files: Filterable[], algorithm: SubsystemAlgorithmT): number[] {
  const ids = files
    .map((f) => subsystemIdOf(f, algorithm))
    .filter((id): id is number => id != null);
  return Array.from(new Set(ids)).sort((a, b) => a - b);
}

// Deliberately does NOT touch or recompute `rank` -- a filtered-out file is
// simply absent from the result, and every surviving file keeps the exact
// rank value the rank run assigned it. A visible sequence like 1, 2, 3, 7, 9
// after filtering is the correct output, not a rendering bug: rank is a
// file's position among ALL of the repo's files, never among whatever
// subset a filter happens to be showing right now.
export function filterFiles<T extends Filterable>(files: T[], state: FilterState): T[] {
  const query = state.query.trim().toLowerCase();
  return files.filter((f) => {
    if (state.segments.length > 0 && !state.segments.includes(topLevelSegment(f.path))) return false;
    if (state.languages.length > 0 && !state.languages.includes(f.language)) return false;
    if (state.hideNoise && NOISE_CATEGORIES.includes(f.prior_category)) return false;
    if (state.hideZeroFanIn && f.fan_in === 0) return false;
    if (state.subsystemId !== null && subsystemIdOf(f, state.subsystemAlgorithm) !== state.subsystemId) return false;
    if (query && !f.path.toLowerCase().includes(query)) return false;
    return true;
  });
}

// URL <-> FilterState, so a filtered view is reloadable and shareable.
// Absent params mean "no filter" (EMPTY_FILTER_STATE), not an error.
const VALID_SUBSYSTEM_ALGORITHMS: SubsystemAlgorithmT[] = ["modularity", "louvain", "hdbscan"];

export function filterStateFromSearchParams(params: URLSearchParams): FilterState {
  const csv = (key: string) => (params.get(key) ?? "").split(",").filter(Boolean);
  const subsystemRaw = params.get("subsystem");
  const subsystemId = subsystemRaw !== null && subsystemRaw !== "" ? Number(subsystemRaw) : null;
  const algorithmRaw = params.get("subsystemAlgo");
  const subsystemAlgorithm = VALID_SUBSYSTEM_ALGORITHMS.includes(algorithmRaw as SubsystemAlgorithmT)
    ? (algorithmRaw as SubsystemAlgorithmT)
    : "modularity";
  return {
    segments: csv("segments"),
    languages: csv("languages"),
    hideNoise: params.get("hideNoise") === "1",
    hideZeroFanIn: params.get("hideZeroFanIn") === "1",
    query: params.get("q") ?? "",
    subsystemId: subsystemId !== null && !Number.isNaN(subsystemId) ? subsystemId : null,
    subsystemAlgorithm,
  };
}

export function applyFilterStateToSearchParams(params: URLSearchParams, state: FilterState): void {
  if (state.segments.length) params.set("segments", state.segments.join(","));
  else params.delete("segments");
  if (state.languages.length) params.set("languages", state.languages.join(","));
  else params.delete("languages");
  if (state.hideNoise) params.set("hideNoise", "1");
  else params.delete("hideNoise");
  if (state.hideZeroFanIn) params.set("hideZeroFanIn", "1");
  else params.delete("hideZeroFanIn");
  if (state.query) params.set("q", state.query);
  else params.delete("q");
  if (state.subsystemId !== null) params.set("subsystem", String(state.subsystemId));
  else params.delete("subsystem");
  // Only encoded when a subsystem filter is actually active and the
  // algorithm isn't the default -- keeps the common case's URL unchanged
  // from before this field existed.
  if (state.subsystemId !== null && state.subsystemAlgorithm !== "modularity") {
    params.set("subsystemAlgo", state.subsystemAlgorithm);
  } else {
    params.delete("subsystemAlgo");
  }
}
