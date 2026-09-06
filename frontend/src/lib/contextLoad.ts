/** Phase 8 checkpoint 2 -- the /context loader's STATUS DISCRIMINATION, extracted.
 *
 *  Extracted rather than written inline for the reason D10 exists: the shape it
 *  replaces (`loadRanking`'s `.catch(() => setRanking(null))`) collapses every
 *  failure into one state. For /context that merges "this file is not in the
 *  graph snapshot" (409, fixed by re-ingesting) with "no file is selected"
 *  (fixed by clicking a file) -- and a user cannot act on a state that does not
 *  distinguish those.
 *
 *  Living in lib/ makes the discrimination testable headlessly: vitest here is
 *  environment:node, so the branching is proven without mounting a component.
 */
import { ApiError } from "./api";

export interface ContextEnvelopeT {
  repo_id: number;
  file_id: number;
  path: string;
  neighborhood: unknown;
  connected_index: { id: number; path: string }[];
  view_tokens: number;
  view_tokens_instrument: string;
  connected_files_distinct: number;
  edge_endpoints_total: number;
  overlap_count: number;
  unresolved_excluded: number;
  priced_files: number;
  connected_bytes: number;
  connected_files_tokens: number;
  connected_tokens_instrument: string;
  calibration_status: string;
  snapshot_sha: string;
  saved_tokens: number;
  saved_ratio: number | null;
  estimator_vs_measured: number | null;
}

/** The four states the tab can be in. `idle` is NOT an error: it is the cold
 *  state before a file has been chosen, and D10 exists because the shape this
 *  replaces could not tell it apart from `notInSnapshot`. */
export type ContextStateT =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; data: ContextEnvelopeT }
  | { status: "notFound"; message: string }
  | { status: "notInSnapshot"; message: string }
  | { status: "error"; message: string };

/** Injected fetch, mirroring elkLayoutRun's `deps.compute`: the unit under test
 *  is the branching, not the network. */
export interface LoadContextDepsT {
  fetchContext: (repoId: string, fileId: number) => Promise<ContextEnvelopeT>;
}

/**
 * Maps one load attempt onto exactly one state.
 *
 * 404 and 409 are DIFFERENT ANSWERS TO DIFFERENT QUESTIONS and are kept apart:
 *   404 -- no such file in this repo. The id is wrong (a stale shared link, per
 *          D9's open item, or a typo). Re-ingesting will not help.
 *   409 -- the file exists in code_files but is absent from the graph snapshot.
 *          The id is right and the graph is behind. Re-ingesting is exactly
 *          what helps.
 * Collapsing them would tell a user to re-ingest when their link is stale, or
 * to check their link when the graph is behind.
 */
export async function loadContext(
  repoId: string,
  fileId: number | null,
  deps: LoadContextDepsT,
): Promise<ContextStateT> {
  if (fileId === null) return { status: "idle" };
  try {
    return { status: "ready", data: await deps.fetchContext(repoId, fileId) };
  } catch (err) {
    const status = err instanceof ApiError ? err.status : undefined;
    const message = err instanceof Error ? err.message : String(err);
    if (status === 404) return { status: "notFound", message };
    if (status === 409) return { status: "notInSnapshot", message };
    // Anything else is surfaced as itself rather than folded into one of the
    // above. A 500 is not a missing file, and saying so is the whole point.
    return { status: "error", message };
  }
}

/** Reads the selected file id from the URL. Integer per D9 -- see decisions.md
 *  for why a path cannot be used here (nothing to resolve it against on a cold
 *  load, and /ranking costs 2.85 MB to translate one). */
export function fileIdFromParams(params: URLSearchParams): number | null {
  const raw = params.get("fileId");
  if (raw === null || raw.trim() === "") return null;
  const n = Number(raw);
  // A non-integer in a hand-edited URL must not become NaN and then a request
  // for /files/NaN/context.
  return Number.isInteger(n) && n > 0 ? n : null;
}
