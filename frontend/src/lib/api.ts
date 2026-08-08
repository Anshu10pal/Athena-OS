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
  total_nodes_before_cap: number;
  truncated: boolean;
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
}

export interface DirEdgeT {
  source: string;
  target: string;
  weight: number;
  count: number;
}

export interface DirGraphResponseT {
  scorer: ScorerT;
  level: "directory";
  nodes: DirNodeT[];
  edges: DirEdgeT[];
  group_rollups: number;
  total_groups_before_limit: number;
  truncated: boolean;
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
