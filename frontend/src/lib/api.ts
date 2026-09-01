const TOKEN_KEY = "athena_token";

export const getToken = () => localStorage.getItem(TOKEN_KEY);
export const setToken = (t: string) => localStorage.setItem(TOKEN_KEY, t);
export const clearToken = () => localStorage.removeItem(TOKEN_KEY);

export async function api<T = any>(path: string, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string>),
  };
  if (!(options.body instanceof FormData)) headers["Content-Type"] = "application/json";
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(path, { ...options, headers });
  if (res.status === 401) {
    clearToken();
    window.location.href = "/login";
    throw new Error("Session expired");
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${res.status})`);
  }
  return res.json();
}

export type SSEEvent =
  | { type: "meta"; intent: string }
  | { type: "token"; text: string }
  | { type: "error"; message: string }
  | { type: "done" };

// ---------------- codebase agent ----------------

export interface RepoT {
  id: number;
  host: string;
  owner: string;
  name: string;
  url: string | null;
  local_path: string;
  source_kind: "clone" | "local";
  default_branch: string;
  source_root: string | null;
  last_ingested_sha: string | null;
  last_ingested_at: string | null;
  file_count: number | null;
  added_at: string;
  seed_exclude_paths: string[];
}

export interface RepoJobT {
  id: number;
  repo_id: number;
  status: "queued" | "running" | "done" | "failed";
  stage: string;
  progress_current: number;
  progress_total: number;
  message: string;
  result: Record<string, any> | null;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export type ScorerT = "legacy" | "weighted_pagerank" | "rrf";

export interface RankedFileT {
  file_id: number;
  path: string;
  // Phase G1: 1-indexed position among ALL of this repo's files under
  // this scorer, assigned once when the rank ran. Never recompute this
  // from a filtered or sorted view -- it is the file's position in the
  // whole repo, not among whatever subset happens to be on screen.
  rank: number;
  score: number;
  language: string;
  prior_category: string;
  fan_in: number;
  fan_out: number;
  pagerank: number;
  is_entry_point: boolean;
  commit_count: number | null;
  distinct_authors: number | null;
  days_since_last_change: number | null;
  computed_at: string;
  // Phase I1 (extended I6): same "property of the file, not the scorer"
  // shape as fan_in above -- null until POST /subsystems (or, for
  // hdbscan, POST /subsystems/hdbscan) has run, or if this file landed in
  // a singleton (never given a CodeSubsystem row).
  subsystem_modularity_id: number | null;
  subsystem_louvain_id: number | null;
  subsystem_hdbscan_id: number | null;
}

// Phase G1: reduced_confidence is repo-wide (one git-log call per rank
// run), not per file -- it lives at the top of this response, not
// duplicated onto every RankedFileT.
export interface RankingResponseT {
  scorer: ScorerT;
  reduced_confidence: boolean;
  files: RankedFileT[];
}

// Phase G4: nodes share the file-level-signal shape RankedFileT already
// has (path, language, prior_category, fan_in) so the SAME filterFiles
// utility works on either without a cast -- see lib/filters.ts.
export interface GraphNodeT {
  id: number;
  path: string;
  language: string;
  score: number;
  rank: number;
  layer: number | null;
  prior_category: string;
  fan_in: number;
  fan_out: number;
  pagerank: number;
  is_entry_point: boolean;
  // Phase H1.5: true for a seed-eligible entry, false for a prior-only
  // one, null for a non-entry or a file no rank run has touched yet --
  // mirrors CodeFile.seed_eligible exactly, not derived client-side.
  seed_eligible: boolean | null;
  reachable: boolean;
  // Phase J1: the backend's level=file node dict has sent this since I2
  // (get_graph in api/repos.py) -- it was only ever consumed server-side
  // by aggregate_to_directories, so this type never declared it. The
  // Dependency Graph's "same cluster" filter reads it directly.
  // Modularity only, deliberately: it is the same algorithm the
  // Architecture map and Matrix already color by (dir_aggregation.py's
  // _cluster_of reads no other), so the graph can't disagree with the map
  // about which cluster a file is in. Null until POST /subsystems has run,
  // or if the file landed in a singleton.
  subsystem_modularity_id: number | null;
}

export interface GraphEdgeT {
  source: number;
  target: number;
  weight: number;
  kind: string;
  cross_root: string | null;
}

// Phase H1: the backend's default is now level=directory; this type
// describes only the level=file shape RepoDetail's Raw view fetches
// explicitly (see loadGraph). The directory-level shape is a distinct
// payload, not yet consumed here -- introduced alongside the H3
// architecture map.
export interface GraphResponseT {
  scorer: ScorerT;
  level: "file";
  /** POST-filter count. The cap applies to whatever survived filtering, so this
   *  is the denominator the truncation notice must use in both cases. */
  total_nodes_before_cap: number;
  truncated: boolean;
  files_matched: number;
  filters: GraphFiltersT;
  filters_active: boolean;
  nodes: GraphNodeT[];
  edges: GraphEdgeT[];
}

// Phase H1: directory-level nodes/edges from dir_aggregation.py -- `id` is
// the directory's own path (a string), not a file id, since there's no
// integer id for a virtual group. Consumed starting with H2's layered
// layout.
export type DirKindT = "entry" | "tooling" | "test" | "migration" | "source";

export interface DirNodeT {
  id: string;
  path: string;
  short_label: string;
  file_count: number;
  kind: DirKindT;
  region: string;
  internal_edge_count: number;
  fan_in_dirs: number;
  fan_out_dirs: number;
  import_count_in: number;
  import_count_out: number;
  // Phase I2: dominant dependency-cluster id among this directory's files,
  // plus purity -- see backend/app/services/codebase/dir_aggregation.py's
  // _cluster_of. Both null if clustering has never run, or if every file
  // in this directory is itself unclustered. purity < 1 means this
  // directory's files genuinely split across multiple clusters -- do not
  // render it as if the whole directory were one clean cluster.
  cluster_id: number | null;
  cluster_purity: number | null;
  cluster_unclustered_count: number;
}

export interface DirEdgeT {
  source: string;
  target: string;
  weight: number;
  count: number;
}

/** Which filters the endpoint applied. Echoed so a client can tell WHICH
 *  population a total describes — "400 of 6,523" and "400 of 6,523 matching"
 *  are otherwise indistinguishable in the payload. */
export interface GraphFiltersT {
  segments: string[];
  languages: string[];
  query: string;
  hide_noise: boolean;
  language: string | null;
  path_prefix: string | null;
  min_score: number | null;
}

export interface DirGraphResponseT {
  scorer: ScorerT;
  level: "directory";
  nodes: DirNodeT[];
  edges: DirEdgeT[];
  group_rollups: number;
  total_groups_before_limit: number;
  truncated: boolean;
  /** Files behind the aggregate, post-filter. Directory counts roll up from
   *  these, and neither number can be derived from the other. */
  files_matched: number;
  filters: GraphFiltersT;
  filters_active: boolean;
}

export interface NeighborT {
  file_id: number;
  path: string;
  rank: number | null;
  score: number | null;
  weight: number;
  kind: string;
  cross_root: string | null;
}

export interface NeighborsResponseT {
  file_id: number;
  path: string;
  importers: NeighborT[];
  importers_total_before_cap: number;
  imports: NeighborT[];
  imports_total_before_cap: number;
}

// Phase I1 (extended I6): subsystem clustering -- modularity/louvain over
// the resolved import graph, hdbscan over FastEmbed embeddings of symbol
// text (see backend/app/services/codebase/subsystems.py's module
// docstring for why three independent algorithms run and what each
// answers).
export type SubsystemAlgorithmT = "modularity" | "louvain" | "hdbscan";

export type SubsystemLabelRuleT = "dominant_prefix" | "top_fan_in" | "numeric" | "custom";

export interface SubsystemT {
  id: number;
  algorithm: SubsystemAlgorithmT;
  cluster_index: number;
  member_count: number;
  dominant_prefix_label: string;
  dominant_prefix_count: number;
  top_fan_in_label: string;
  top_fan_in_file_id: number | null;
  custom_label: string | null;
  active_label_rule: SubsystemLabelRuleT;
  computed_at: string;
}

export interface CycleCoherenceEntryT {
  directories: string[];
  total_files: number;
  majority_cluster_index: number;
  majority_count: number;
  coherence: number;
  weak: boolean;
}

// The shape of POST /subsystems specifically -- modularity+louvain only,
// always both keys present. HDBSCAN is a separate endpoint (POST
// /subsystems/hdbscan) with its own response shape below, not a third key
// here -- it's compared against modularity, not run alongside it in the
// same call.
export interface ComputeSubsystemsResultT {
  agreement: number | null;
  algorithms: Record<"modularity" | "louvain", {
    cluster_count: number;
    unclustered_count: number;
    labels_carried_over: number;
    labels_reset: number;
  }>;
  cycle_coherence: CycleCoherenceEntryT[];
}

// The shape of POST /subsystems/hdbscan -- see subsystems.py's
// compute_subsystems_hdbscan. agreement_with_modularity is null when
// modularity hasn't been computed yet for this repo.
export interface ComputeSubsystemsHdbscanResultT {
  algorithm: "hdbscan";
  cluster_count: number;
  unclustered_count: number;
  labels_carried_over: number;
  labels_reset: number;
  agreement_with_modularity: number | null;
  cycle_coherence: CycleCoherenceEntryT[];
  embedded_file_count: number;
  embedding_seconds: number;
}

export interface SubsystemsResponseT {
  algorithm: SubsystemAlgorithmT;
  agreement: number | null;
  cycle_coherence: CycleCoherenceEntryT[] | null;
  unclustered_count: number;
  subsystems: SubsystemT[];
}

export interface SubsystemMemberT {
  id: number;
  path: string;
  language: string;
  fan_in: number | null;
}

export interface SubsystemMembersResponseT {
  files: SubsystemMemberT[];
}

// Phase K1: the repo landing page. `health` is STRUCTURAL health, not
// defect prediction -- this system holds no defect data, and the backend
// carries that caveat in the payload itself so the UI can't quietly drop
// it (see backend/app/services/codebase/overview.py).
export interface HealthFactorT {
  key: string;
  label: string;
  weight: number;
  detail: string;
  available: boolean;
  /** Null when the factor could not be measured for this repo -- excluded
   *  from the score entirely rather than counted as zero. */
  value: number | null;
}

export interface HotspotFileT {
  file_id: number;
  path: string;
  score: number;
  commit_count: number | null;
  distinct_authors: number | null;
  fan_in: number | null;
  lines: number;
}

// Phase 1 code health. Three axes, never blended, each carrying its own
// direction -- see backend/app/services/codebase/health_scoring.py and
// docs/code-health-contract.md.
//
// `mean` is absent (not null) when an axis had nothing presentable to score:
// either every file was N/A, or a required marker had no data and the backend
// withheld the value structurally. Rendering code must branch on its absence
// rather than defaulting it to 0.
export interface HealthAxisT {
  axis: string;
  scored: number;
  na: number;
  na_reasons: Record<string, number>;
  /** "every marker IN THIS CONTRACT had its input" -- never "complete
   *  evidence about the architecture". */
  inputs_complete: boolean;
  resolution_limited: boolean;
  mean?: number;
  median?: number;
  p10?: number;
  p90?: number;
  coverage?: HealthCoverageT;
  /** Every marker the axis considered, with the threshold and weight that
   *  were actually applied and how much each contributed. Stored with the
   *  snapshot, so a historical score is explained by the thresholds of its
   *  own era rather than today's. Absent on snapshots taken before this
   *  existed. */
  markers?: HealthAxisMarkerT[];
  category_caps?: Record<string, number>;
}

export interface HealthAxisMarkerT {
  key: string;
  label: string;
  category: string;
  weight: number;
  /** For percentile-derived markers these are the repo-relative values that
   *  were actually used, not an absolute pair the marker does not have. */
  warn: number | null;
  saturate: number | null;
  evaluated: number;
  fired: number;
  fire_rate: number | null;
  /** Reported alongside fire rate deliberately: fire rate alone cannot tell a
   *  marker that fires often and contributes nothing from one that dominates. */
  mean_deduction: number | null;
  max_deduction: number | null;
  state: "fired" | MarkerStateT;
}

/** The mandatory Architecture Health scope block. Ships as data so a UI
 *  cannot receive a score while omitting what it applies to. */
export interface HealthCoverageT {
  inputs_complete: boolean;
  file_level_cycle_count: number;
  directory_cycle_count: number | null;
  active_markers: string[];
  /** Never a flat list: "never computed", "measured and found nothing" and
   *  "cannot apply here" license different conclusions about coverage and are
   *  easy to conflate once flattened. */
  inactive_markers: InactiveMarkerT[];
  limitations: string[];
}

export type MarkerStateT =
  | "no_input"
  | "input_available_zero_severity"
  | "not_applicable";

export interface InactiveMarkerT {
  key: string;
  state: MarkerStateT;
  detail: string;
}

export interface HealthSnapshotT {
  id: number;
  branch: string;
  head_sha: string | null;
  /** For a local repo the live working directory is analysed, so HEAD may not
   *  describe the analysed bytes. */
  working_tree_dirty: boolean | null;
  analyzer_version: number;
  thresholds_version: number;
  weights_version: number;
  computed_at: string;
  files_scored: number;
  /** Files N/A on EVERY axis. Never render this without files_partially_na --
   *  alone it reads as "everything else was scored", and on apache/superset it
   *  is 0 while 782 files are scored on architecture only. */
  files_na: number;
  /** Files scored on some axes but not all. NULL -- not 0 -- on snapshots
   *  taken before this field existed: 0 means "measured, none found", null
   *  means "never measured". Render them differently. */
  files_partially_na: number | null;
  inputs_complete: boolean;
}

export interface HealthTrendT {
  comparable: boolean;
  /** Present whenever comparable is false. Never a 0.0 delta meaning
   *  "unknown". */
  reason: string | null;
  previous_snapshot_id?: number;
  previous_head_sha?: string | null;
  deltas: Record<string, number>;
}

export interface RollupAxisT {
  files_scored: number;
  files_na: number;
  weighted_mean: number | null;
  mean: number | null;
  worst: number | null;
  worst_path: string | null;
  rankable: boolean;
}

export interface DirectoryRollupT {
  path: string;
  depth: number;
  files_total: number;
  nloc: number;
  axes: Record<string, RollupAxisT>;
}

export interface HotCohortT {
  available: boolean;
  na_reason: string | null;
  hot_files: number;
  hot_mean: number | null;
  baseline_files: number;
  baseline_mean: number | null;
  delta: number | null;
  churn_threshold: number | null;
  caveat: string | null;
  paths: string[];
  axis: string;
  axis_note: string;
}

export interface HealthDirectoriesT {
  snapshot_id: number;
  rollup_version: number;
  files_in_snapshot: number;
  min_files_to_rank: number;
  directories: DirectoryRollupT[];
  weakest: Record<string, string[]>;
  hot_cohort: HotCohortT;
  staleness: HealthStalenessT;
}

export interface HealthStalenessT {
  stale: boolean;
  reason: "no_files_ingested" | "scoring_changed" | "source_changed" | null;
  detail: string | null;
}

export interface HealthResponseT {
  snapshot: HealthSnapshotT;
  axes: Record<string, HealthAxisT>;
  trend: HealthTrendT;
  staleness: HealthStalenessT;
}

/** One row of the findings queue: a marker, an area, and the files in it.
 *  Keyed on (marker x directory) rather than on files -- see
 *  backend/app/services/codebase/findings_queue.py for why a per-file queue
 *  cannot be ordered. */
/** What DELETE /api/repos/{id} reports. Rendered in full rather than reduced to
 *  a success toast: "what was removed, and whether the directory went and why"
 *  is the part that makes an irreversible action auditable after the fact. */
export interface RepoDeletionReportT {
  repo_id: number;
  label: string;
  source_kind: string;
  rows_deleted: Record<string, number>;
  rows_total: number;
  directory_deleted: boolean;
  directory_path: string | null;
  /** Always populated, including on success — a boolean does not carry why. */
  directory_reason: string;
}

export interface FindingsRowT {
  marker: string;
  label: string;
  directory: string;
  /** Also the finding count: a marker fires at most once per file, so these
   *  are identically equal and only one is served. */
  file_count: number;
  /** Sum over the row of severity x exposure x (1 + churn). Zero means every
   *  file in the row has no exposure -- nothing depends on them and they do
   *  not change -- which ranks last rather than being hidden. */
  score: number;
  peak_severity: number;
  /** Mean churn severity, 0..1. Churn is the ordering weight, never a row of
   *  its own; shown so the weighting is visible rather than folded in. */
  churn_mean: number;
  /** Every file in this row shares one directory, so no cap divides it. A
   *  stated property, not a tuning failure. */
  irreducible: boolean;
}

export interface FindingsResponseT {
  snapshot_id: number;
  floor: number;
  max_files_per_row: number;
  shown: number;
  /** Findings below the floor. Served so the UI can say what it is hiding --
   *  a filter a user cannot see is indistinguishable from a missed finding. */
  hidden_below_floor: number;
  churn_weighted_files: number;
  rows: FindingsRowT[];
  staleness: HealthStalenessT;
}

export interface FindingsFilesT {
  snapshot_id: number;
  marker: string;
  directory: string;
  file_count: number;
  files: { file_id: number; path: string; severity: number }[];
}

export interface HealthMarkerT {
  key: string;
  label: string;
  category: string;
  available: boolean;
  na_reason: string | null;
  raw_value: number | null;
  severity: number | null;
  deduction: number;
  effective_warn: number | null;
  effective_saturate: number | null;
}

export interface HealthFileT {
  file_id: number;
  path: string;
  nloc: number;
  maintainability: number | null;
  architecture_health: number | null;
  exposure: number | null;
  adjusted_exposure: number | null;
  explanation: Record<string, {
    available: boolean;
    na_reason: string | null;
    inputs_complete: boolean;
    resolution_limited: boolean;
    resolution_note: string | null;
    markers: HealthMarkerT[];
  }>;
}

export interface HealthFilesResponseT {
  snapshot_id: number;
  sort: string;
  excluded_na: number;
  files: HealthFileT[];
}

export interface OverviewT {
  repo: {
    id: number;
    name: string;
    owner: string;
    host: string;
    source_kind: string;
    description: string | null;
    description_source: string | null;
    last_ingested_at: string | null;
    last_ingested_sha: string | null;
    reduced_confidence: boolean | null;
  };
  counts: {
    files: number;
    lines: number;
    bytes: number;
    directories: number;
    test_files: number;
    languages: Record<string, number>;
    categories: Record<string, number>;
    symbols_total: number;
    symbol_kinds: Record<string, number>;
    imports_total: number;
    imports_resolved: number;
    imports_unresolved: number;
    import_resolution_rate: number;
  };
  cluster_count: number;
  health: {
    score: number | null;
    factors: HealthFactorT[];
    factors_used: number;
    factors_total: number;
    caveat: string;
  };
  hotspots: {
    available: boolean;
    reason: string | null;
    files: HotspotFileT[];
  };
}

export function timeAgo(iso: string | null): string {
  if (!iso) return "never";
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export type JobSSEEvent =
  | { type: "progress"; status: string; stage: string; current: number; total: number; message: string }
  | { type: "done"; result: Record<string, any> | null }
  | { type: "error"; message: string };

export async function streamJobProgress(repoId: number, jobId: number, onEvent: (e: JobSSEEvent) => void) {
  const res = await fetch(`/api/repos/${repoId}/jobs/${jobId}/stream`, {
    headers: { Authorization: `Bearer ${getToken()}` },
  });
  if (!res.ok || !res.body) throw new Error("Job stream request failed");
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n\n");
    buffer = lines.pop() || "";
    for (const line of lines) {
      if (line.startsWith("data: ")) {
        try {
          onEvent(JSON.parse(line.slice(6)));
        } catch {
          /* skip malformed frame */
        }
      }
    }
  }
}

export async function streamChat(
  message: string,
  history: { role: string; content: string }[],
  onEvent: (e: SSEEvent) => void
) {
  const res = await fetch("/api/chat/stream", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${getToken()}`,
    },
    body: JSON.stringify({ message, history }),
  });
  if (!res.ok || !res.body) throw new Error("Chat request failed");
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n\n");
    buffer = lines.pop() || "";
    for (const line of lines) {
      if (line.startsWith("data: ")) {
        try {
          onEvent(JSON.parse(line.slice(6)));
        } catch {
          /* skip malformed frame */
        }
      }
    }
  }
}
// ---------------- Interview Arena (Phase A) ----------------
//
// Namespaced `arena`, not `interview`: /api/interview is the original MVP flow,
// still mounted and still feeding the dashboard readiness tile, achievements
// and the activity streak. Keeping both lets the two be compared side by side.

export type {
  ArenaGraphT,
  MergeSuggestionT,
  SkillNodeT,
  TargetTier,
} from "./arenaGraphEdits";

import type { ArenaGraphT, EditSet } from "./arenaGraphEdits";

export interface ArenaJobTargetSummaryT {
  id: number;
  title: string;
  created_at: string | null;
  graph_confirmed_at: string | null;
  extractor_version: string;
  node_count: number;
}

export interface ArenaReadinessT {
  confirmed: boolean;
  confirmed_at: string | null;
  node_count: number;
  pending_merge_suggestions: number;
  can_start: boolean;
  blocking_reason: string | null;
}

export const arenaCreateJobTarget = (title: string, jdText: string) =>
  api<ArenaGraphT>("/api/arena/job-target", {
    method: "POST",
    body: JSON.stringify({ title, jd_text: jdText }),
  });

export const arenaGetJobTarget = (id: number) =>
  api<ArenaGraphT>(`/api/arena/job-target/${id}`);

export const arenaListJobTargets = () =>
  api<ArenaJobTargetSummaryT[]>("/api/arena/job-targets");

/** One PATCH for the whole accumulated edit set. The user can rename several
 *  nodes, reparent one and delete another, see the result, and still abandon
 *  the lot — which matters because this screen is the module's only validation
 *  path and a user afraid to experiment on it will not validate anything. */
export const arenaPatchGraph = (id: number, edits: EditSet, confirm = false) =>
  api<ArenaGraphT & { edits_applied: number }>(`/api/arena/job-target/${id}/graph`, {
    method: "PATCH",
    body: JSON.stringify({ ...edits, confirm }),
  });

/** Accept or reject one review-band merge suggestion. A rejection is the
 *  valuable outcome to record — hand-labelled negative data on exactly the
 *  band where the instrument is weakest. */
export const arenaDecideMerge = (
  targetId: number,
  suggestionId: number,
  decision: "accepted" | "rejected",
) =>
  api<ArenaGraphT>(`/api/arena/job-target/${targetId}/merge-suggestion/${suggestionId}`, {
    method: "POST",
    body: JSON.stringify({ decision }),
  });

/** The Start-interview gate reads the SERVER's answer rather than re-deriving
 *  the rule client-side. Two copies of a gate is one too many, and the copy
 *  that drifts is always the one on screen. */
export const arenaReadiness = (id: number) =>
  api<ArenaReadinessT>(`/api/arena/job-target/${id}/readiness`);
