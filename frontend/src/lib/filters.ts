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
}

export const EMPTY_FILTER_STATE: FilterState = {
  segments: [],
  languages: [],
  hideNoise: false,
  hideZeroFanIn: false,
  query: "",
};

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
    if (query && !f.path.toLowerCase().includes(query)) return false;
    return true;
  });
}

// URL <-> FilterState, so a filtered view is reloadable and shareable.
// Absent params mean "no filter" (EMPTY_FILTER_STATE), not an error.
export function filterStateFromSearchParams(params: URLSearchParams): FilterState {
  const csv = (key: string) => (params.get(key) ?? "").split(",").filter(Boolean);
  return {
    segments: csv("segments"),
    languages: csv("languages"),
    hideNoise: params.get("hideNoise") === "1",
    hideZeroFanIn: params.get("hideZeroFanIn") === "1",
    query: params.get("q") ?? "",
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
}
