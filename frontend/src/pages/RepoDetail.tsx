import { Fragment, Suspense, lazy, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  api, DirGraphResponseT, GraphResponseT, RankedFileT, RankingResponseT, RepoJobT, RepoT, ScorerT,
  SubsystemAlgorithmT, SubsystemsResponseT, OverviewT, HealthResponseT, HealthDirectoriesT,
  streamJobProgress, timeAgo,
} from "../lib/api";
import {
  applyFilterStateToSearchParams,
  deriveLanguages,
  deriveSubsystemIds,
  deriveTopLevelSegments,
  EMPTY_FILTER_STATE,
  FilterState,
  filterFiles,
  filterStateFromSearchParams,
  NOISE_CATEGORIES,
} from "../lib/filters";
import { SlideOver } from "../components/SlideOver";
import { LayersView } from "../components/LayersView";
import { ArchitectureMap } from "../components/ArchitectureMap";
import { MatrixView } from "../components/MatrixView";
import { FocusView } from "../components/FocusView";
import { DetailPanel } from "../components/DetailPanel";
import { FileSearch } from "../components/FileSearch";
import { MermaidPanel } from "../components/MermaidPanel";
import { SubsystemsView } from "../components/SubsystemsView";
import { OverviewView } from "../components/OverviewView";

import { dirnameOfPath } from "../lib/layeredLayout";

// Phase J1: cytoscape + ELK are heavy and needed only by whoever actually
// opens the Dependency Graph tab -- so this is lazy, exactly like
// MermaidPanel's dynamic import() of mermaid and for the same reason.
// Measured against real builds, not assumed (the same standard the G4
// bundle-size note set): with a static import the main chunk built at
// 2,409 kB; lazy, it builds at 483 kB, with the graph engine moved into a
// 1,457 kB ELK chunk plus a 433 kB cytoscape chunk that are fetched only
// when this tab is first opened.
const DependencyGraph = lazy(() =>
  import("../components/DependencyGraph").then((m) => ({ default: m.DependencyGraph })),
);

type SortKey = keyof Pick<
  RankedFileT,
  "rank" | "score" | "fan_in" | "fan_out" | "pagerank" | "commit_count" | "distinct_authors" | "days_since_last_change"
>;

// Phase H5: the old force-directed "Raw" view is gone, not demoted --
// see the H5 report for the three-question evidence check (spot a
// heavily-imported utility, find a cycle, trace from an entry point) that
// decided this. Architecture/Matrix/Focus/Layers answer all three better;
// keeping a fourth tab and a d3-force dependency alive would have been
// inertia, not justification.
//
// Phase J1 adds "depgraph" -- deliberately NOT a restoration of that Raw
// view. The thing H5 deleted was "every file at once, force-directed";
// this is "one focus, N hops, folders collapsed, ELK layered layout",
// where the full graph exists only behind an explicit opt-in that warns
// about exactly the failure H5 recorded. Different default, different
// layout, different question answered -- see components/DependencyGraph.tsx.
type ViewT = "overview" | "reading" | "architecture" | "matrix" | "focus" | "layers" | "subsystems" | "depgraph";

const COLUMNS: { key: SortKey; label: string; align?: "left" | "center" | "right" }[] = [
  { key: "score", label: "Score" },
  { key: "fan_in", label: "Fan In" },
  { key: "fan_out", label: "Fan Out" },
  { key: "pagerank", label: "PageRank" },
  { key: "commit_count", label: "Commits", align: "right" },
  { key: "distinct_authors", label: "Authors", align: "right" },
  { key: "days_since_last_change", label: "Last Change", align: "right" },
];

const SCORERS: { value: ScorerT; label: string }[] = [
  { value: "legacy", label: "Legacy (weighted sum)" },
  { value: "weighted_pagerank", label: "Weighted PageRank" },
  { value: "rrf", label: "Reciprocal Rank Fusion" },
];

const VIEWS: { value: ViewT; label: string }[] = [
  { value: "overview", label: "Overview" },
  { value: "layers", label: "Layers" },
  { value: "reading", label: "Reading list" },
  { value: "architecture", label: "Architecture" },
  { value: "depgraph", label: "Dependency Graph" },
  { value: "matrix", label: "Matrix" },
  { value: "subsystems", label: "Dependency Clusters" },
  { value: "focus", label: "Focus" },
];

const VALIDATION_THRESHOLD_RANK = 20;
const COLUMN_COUNT = 3 + COLUMNS.length; // Rank + Path + Language + COLUMNS

const GLOSSARY: { term: string; desc: string }[] = [
  {
    term: "Path",
    desc: "The file's path relative to the repo root.",
  },
  {
    term: "Rank",
    desc:
      "This file's position among ALL files in the repo under the active scorer, assigned once when the rank ran. " +
      "Stays fixed no matter how you sort or filter the table below -- filtering to a subdirectory and seeing " +
      "ranks 1, 2, 3, 5, 11 is the useful signal; it never renumbers to 1, 2, 3, 4, 5.",
  },
  {
    term: "Score",
    desc:
      "The composite ranking for this file under the active scorer. Higher score = read this file earlier. " +
      "Legacy, Weighted PageRank, and Reciprocal Rank Fusion compute this differently -- see the scorer dropdown.",
  },
  {
    term: "Language",
    desc: "The language this file was parsed as: python, javascript, typescript, or tsx.",
  },
  {
    term: "Fan In",
    desc: "How many other files in this repo import this file. High fan-in means a lot of the codebase depends on it.",
  },
  {
    term: "Fan Out",
    desc: "How many other files this file imports. High fan-out means it pulls together a lot of the codebase.",
  },
  {
    term: "PageRank",
    desc:
      "Like Fan In, but weighted by importance -- being imported by a few heavily-used files counts for more than " +
      "being imported by many rarely-used ones. The same idea search engines used to rank pages by incoming links.",
  },
  {
    term: "Entry Point",
    desc:
      "Flagged when this file is a real, detected execution start: named by deployment/build config " +
      "(a Dockerfile, Procfile, or index.html's script tag) or containing a runtime-start code pattern " +
      "(if __name__ == \"__main__\", a FastAPI/Flask app instantiation, a React root render call). " +
      "Not the same as \"nothing imports it\" -- plenty of dead code and orphaned scripts have no importers " +
      "without being an entry point.",
  },
  {
    term: "Commits",
    desc: "Number of commits in git history that touched this file. Same value regardless of which scorer is active.",
  },
  {
    term: "Authors",
    desc: "Number of distinct people who've committed a change to this file.",
  },
  {
    term: "Last Change",
    desc: "Days since the most recent commit that touched this file.",
  },
  {
    term: "Layer",
    desc:
      "BFS distance from the nearest detected entry point, following the import graph outward. Layer 0 is the " +
      "entry points themselves. Files with no path back to any entry point are Unreachable -- a structurally " +
      "different fact than \"far away,\" not just the highest layer number.",
  },
  {
    term: "Unreachable",
    desc:
      "No path exists back to any detected entry point through the import graph. A separated final column in " +
      "Layers -- a structurally different fact than \"far away,\" not just the highest layer number. The " +
      "Architecture map's own layer 0 doesn't distinguish this from a real entry point at directory granularity " +
      "(both land at layer 0 -- \"nothing imports this\" catches either case); Kind is what tells them apart there.",
  },
  {
    term: "Cross-root edge",
    desc:
      "An import that reaches directly into another package/workspace root instead of going through whatever " +
      "public entry point that root meant to expose. A file-level fact, not yet surfaced in any directory-level " +
      "view -- the old force view showed it; nothing has replaced that specific visual yet.",
  },
  {
    term: "Reduced confidence",
    desc:
      "Shown when git history isn't available for this repo's rank runs (no git binary on this machine, or this " +
      "checkout has no commit history). When it applies, Commits/Authors/Last Change are unknown for every file, " +
      "and their weight is redistributed across Fan In, PageRank, and Entry Point instead of being scored as zero.",
  },
  {
    term: "Dependency cluster",
    desc:
      "A group of files that import each other more densely than they import the rest of the repo -- found by " +
      "community detection over the import graph (Modularity and Louvain, two independent algorithms), not by " +
      "directory structure or by anyone's intent. This is a real, measured coupling group, not a confirmed " +
      "architectural subsystem -- validated against eslint/eslint's own architecture doc, one cluster genuinely " +
      "spanned five of the doc's named components at once because they form a real call chain, not because the " +
      "detector was wrong. Read a cluster as \"these files are entangled,\" not as \"this is one subsystem.\" " +
      "Labelled by whichever naming rule the card states (most common directory, highest-fan-in file, or a name " +
      "you've set yourself) -- the name is a convenience for talking about the cluster, not a claim about what " +
      "it architecturally is.",
  },
  {
    term: "Cycle-cluster coherence",
    desc:
      "For a known directory-level import cycle (two or more directories that depend on each other), what " +
      "fraction of their combined files actually landed in one dependency cluster. A low percentage doesn't mean " +
      "the clustering is broken -- it means the cycle is carried by a small number of specific edges between " +
      "specific files, not by pervasive coupling across both directories, which is a more actionable finding.",
  },
  {
    term: "Dependency Graph (hops)",
    desc:
      "The Dependency Graph never draws the whole repo by default -- it draws one focus file (or folder) and " +
      "everything within N import hops of it. Hop 1 is direct neighbours, hop 2 is neighbours-of-neighbours. This " +
      "is the deliberate difference from the old force-directed view that was deleted: at full size a file graph " +
      "is a hairball that answers nothing, so the question here is scoped to \"what does a change to THIS reach,\" " +
      "not \"show me everything.\" Left-to-right position encodes direction -- importers on the left, imports on " +
      "the right. Folders collapse to one node with an x-count until you expand them; a red edge closes a cycle " +
      "among the files currently on screen.",
  },
];

function Chip({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={
        "font-mono text-[10px] rounded px-2 py-1 border transition-colors " +
        (active ? "border-accent text-accent bg-accent/10" : "border-line text-fog hover:text-snow hover:border-fog")
      }
    >
      {children}
    </button>
  );
}

function isValidScorer(value: string | null): value is ScorerT {
  return SCORERS.some((s) => s.value === value);
}

function isValidView(value: string | null): value is ViewT {
  return VIEWS.some((v) => v.value === value);
}

const GLOSSARY_BY_TERM: Record<string, string> = Object.fromEntries(GLOSSARY.map((g) => [g.term, g.desc]));

// Phase G3: per-column tooltips, reusing the SAME glossary text the slide-over
// panel shows -- one source of truth, so a header tooltip and the full
// glossary entry can never drift apart. CSS-only (group-hover), no new
// dependency and no layout cost when not hovered.
//
// align controls which edge the tooltip anchors to, found necessary by
// actually hovering the rightmost column in a browser at 1366px: a
// centered tooltip on the last column measured 25px past the right edge
// of the viewport. "left"/"right" anchor to that edge of the header
// instead of centering, so the tooltip grows away from whichever edge of
// the table the column is near. Table-column-position-dependent, not
// something tsc or a unit test could have caught.
function HeaderLabel({ term, align = "center" }: { term: string; align?: "left" | "center" | "right" }) {
  const desc = GLOSSARY_BY_TERM[term];
  const position =
    align === "left" ? "left-0" : align === "right" ? "right-0" : "left-1/2 -translate-x-1/2";
  return (
    <span className="group relative inline-block">
      <span className={desc ? "border-b border-dotted border-fog/50 cursor-help" : undefined}>{term}</span>
      {desc && (
        <span
          role="tooltip"
          className={`pointer-events-none absolute z-30 ${position} top-full mt-2 hidden w-56 rounded border border-line bg-ink p-2.5 text-left text-[10px] normal-case tracking-normal leading-relaxed text-fog shadow-2xl group-hover:block`}
        >
          {desc}
        </span>
      )}
    </span>
  );
}

export default function RepoDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [repo, setRepo] = useState<RepoT | null>(null);
  const [scorer, setScorer] = useState<ScorerT>(() => {
    const fromUrl = searchParams.get("scorer");
    return isValidScorer(fromUrl) ? fromUrl : "legacy";
  });
  const [view, setView] = useState<ViewT>(() => {
    const fromUrl = searchParams.get("view");
    // Overview is the landing view again now that code health lives on it as
    // tiles rather than behind its own tab. A stale `?view=health` link fails
    // isValidView and falls back here rather than rendering nothing.
    return isValidView(fromUrl) ? fromUrl : "overview";
  });
  const [filters, setFilters] = useState<FilterState>(() => filterStateFromSearchParams(searchParams));
  const [ranking, setRanking] = useState<RankingResponseT | null>(null);
  const [graph, setGraph] = useState<GraphResponseT | null>(null);
  const [dirGraph, setDirGraph] = useState<DirGraphResponseT | null>(null);
  const [error, setError] = useState("");
  const [job, setJob] = useState<RepoJobT | null>(null);
  const [running, setRunning] = useState(false);
  const [sortKey, setSortKey] = useState<SortKey>("score");
  const [sortDesc, setSortDesc] = useState(true);
  const [showGlossary, setShowGlossary] = useState(false);
  const [selectedFileId, setSelectedFileId] = useState<number | null>(null);
  const [mermaidFileId, setMermaidFileId] = useState<number | null>(null);
  // Phase H4: set by clicking a Matrix cell, consumed by the Architecture
  // map to isolate that pair -- shared selection state, same seam used
  // for selectedFileId, not a new event threaded between the two views.
  const [pairFilter, setPairFilter] = useState<[string, string] | null>(null);
  // Phase H5: feeds the shared, persistent DetailPanel -- a raw directory
  // id, set by clicking a box in the Architecture map.
  const [selectedDirId, setSelectedDirId] = useState<string | null>(null);
  // Phase I1: scorer-independent -- clustering runs over the import graph,
  // not any scorer's output, so unlike ranking/graph/dirGraph these are
  // fetched once per repo load, not once per scorer change. Both
  // algorithms' responses are kept (not just the currently-displayed one)
  // since agreement/cycle_coherence are identical repo-wide values on
  // either response and the algorithm toggle should feel instant, not
  // trigger a new fetch on every click.
  const [subsystemAlgorithm, setSubsystemAlgorithm] = useState<SubsystemAlgorithmT>("modularity");
  // Phase I2: shared between Architecture and Matrix so switching tabs
  // keeps the same coloring active, same pattern as pairFilter/
  // selectedDirId. Always modularity-based -- the algorithm toggle on
  // the Dependency Clusters tab is a separate, deliberately-not-widened
  // concern (a third toggle dimension here would overcomplicate what was
  // asked to stay a small piece of work).
  const [colorMode, setColorMode] = useState<"kind" | "cluster">("kind");
  const [subsystemsModularity, setSubsystemsModularity] = useState<SubsystemsResponseT | null>(null);
  const [subsystemsLouvain, setSubsystemsLouvain] = useState<SubsystemsResponseT | null>(null);
  // Phase I6: HDBSCAN is a separate, on-demand, heavier computation (real
  // CPU embedding work, not near-instant graph math) -- its own response
  // state and its own "computing" flag, not shared with the modularity+
  // Louvain pair's computeSubsystems/computingSubsystems below.
  const [subsystemsHdbscan, setSubsystemsHdbscan] = useState<SubsystemsResponseT | null>(null);
  const [computingSubsystems, setComputingSubsystems] = useState(false);
  const [computingSubsystemsHdbscan, setComputingSubsystemsHdbscan] = useState(false);
  // Phase J1: the Dependency Graph's focus is deliberately SEPARATE state
  // from selectedFileId. Selection drives the detail panel; focus drives
  // which neighbourhood is scoped and laid out. Collapsing them into one
  // would mean every click meant to read a node's label also re-scoped
  // and re-laid-out the whole graph, which is the single fastest way to
  // make a graph explorer unusable. Seeded from the current selection when
  // the tab opens (see the effect below), then moved only by double-click.
  const [graphFocusFileId, setGraphFocusFileId] = useState<number | null>(null);
  const [graphFocusDir, setGraphFocusDir] = useState<string | null>(null);
  const [overview, setOverview] = useState<OverviewT | null>(null);
  const [health, setHealth] = useState<HealthResponseT | null>(null);
  const [directories, setDirectories] = useState<HealthDirectoriesT | null>(null);
  const [computingHealth, setComputingHealth] = useState(false);

  // DetailPanel shows file details whenever selectedFileId is set,
  // regardless of how stale -- without clearing the other one on every
  // selection, clicking a directory after ever having selected a file
  // would leave the panel stuck showing that old file forever.
  const selectFile = (fileId: number | null) => {
    setSelectedFileId(fileId);
    if (fileId !== null) setSelectedDirId(null);
  };
  const selectDir = (dirId: string) => {
    setSelectedDirId(dirId);
    setSelectedFileId(null);
  };

  const glossaryTriggerRef = useRef<HTMLButtonElement>(null);
  const mermaidTriggerRef = useRef<HTMLButtonElement | null>(null);

  const loadRepo = () => {
    api<RepoT>(`/api/repos/${id}`)
      .then(setRepo)
      .catch((e) => setError(e.message));
  };

  // Phase K1: scorer-independent (it aggregates ingest/rank output, not any
  // one scorer's ranking), so it is fetched once per repo load rather than
  // on every scorer change -- same reasoning as loadSubsystems.
  const loadOverview = () => {
    api<OverviewT>(`/api/repos/${id}/overview`)
      .then(setOverview)
      .catch(() => setOverview(null));
  };

  // 404 before any snapshot is the expected state, not an error worth
  // surfacing -- the view renders its own "no snapshot yet" prompt. The
  // directory rollup 404s under exactly the same condition, so it is loaded
  // alongside rather than gated on the first call succeeding.
  const loadHealth = () => {
    api<HealthResponseT>(`/api/repos/${id}/health`)
      .then(setHealth)
      .catch(() => setHealth(null));
    api<HealthDirectoriesT>(`/api/repos/${id}/health/directories`)
      .then(setDirectories)
      .catch(() => setDirectories(null));
  };

  const computeHealth = async () => {
    setComputingHealth(true);
    try {
      setHealth(await api<HealthResponseT>(`/api/repos/${id}/health`, { method: "POST" }));
      // Derived from the snapshot that was just written, so it has to be
      // re-read after a compute or the detail would describe the previous one.
      loadDirectories();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setComputingHealth(false);
    }
  };

  const loadDirectories = () => {
    api<HealthDirectoriesT>(`/api/repos/${id}/health/directories`)
      .then(setDirectories)
      .catch(() => setDirectories(null));
  };

  const loadRanking = (activeScorer: ScorerT) => {
    api<RankingResponseT>(`/api/repos/${id}/ranking?scorer=${activeScorer}`)
      .then(setRanking)
      .catch(() => setRanking(null));
  };

  // Fetched alongside the reading list, not only when the Layers tab is
  // opened -- both tabs share one fetch per scorer change, so switching
  // tabs is instant and both views are always looking at the same data.
  //
  // Phase H1: the backend's default flipped to level=directory (the new
  // architecture-map payload shape, not yet consumed anywhere in this
  // file). &level=file pins this fetch to the file-level shape this view
  // was actually built against, so it keeps working unchanged through H2
  // and H3 -- a one-line stopgap until H5 relegates this view to "Raw".
  const loadGraph = (activeScorer: ScorerT) => {
    api<GraphResponseT>(`/api/repos/${id}/graph?scorer=${activeScorer}&level=file`)
      .then(setGraph)
      .catch(() => setGraph(null));
  };

  // Phase H3: the Architecture tab's own fetch, at the (now-default)
  // level=directory shape -- deliberately separate from loadGraph's
  // level=file pin above, not a shared response reused across both, since
  // the two views need genuinely different payloads (directory nodes
  // carry no per-file id/rank; file nodes carry no kind/region/cycle info).
  const loadDirGraph = (activeScorer: ScorerT) => {
    api<DirGraphResponseT>(`/api/repos/${id}/graph?scorer=${activeScorer}&level=directory`)
      .then(setDirGraph)
      .catch(() => setDirGraph(null));
  };

  // Phase I1: reads ONLY what a prior POST /subsystems already persisted --
  // same "GET must never recompute" discipline H1.5 established for
  // entry detection. Both algorithms fetched together so the toggle in
  // SubsystemsView is instant.
  const loadSubsystems = () => {
    api<SubsystemsResponseT>(`/api/repos/${id}/subsystems?algorithm=modularity`)
      .then(setSubsystemsModularity)
      .catch(() => setSubsystemsModularity(null));
    api<SubsystemsResponseT>(`/api/repos/${id}/subsystems?algorithm=louvain`)
      .then(setSubsystemsLouvain)
      .catch(() => setSubsystemsLouvain(null));
    api<SubsystemsResponseT>(`/api/repos/${id}/subsystems?algorithm=hdbscan`)
      .then(setSubsystemsHdbscan)
      .catch(() => setSubsystemsHdbscan(null));
  };

  const computeSubsystems = async () => {
    setComputingSubsystems(true);
    try {
      await api(`/api/repos/${id}/subsystems`, { method: "POST" });
      loadSubsystems();
      loadRanking(scorer); // subsystem_modularity_id/louvain_id on each file just changed
    } catch (e: any) {
      setError(e.message);
    } finally {
      setComputingSubsystems(false);
    }
  };

  // Phase I6: deliberately its own POST, not folded into computeSubsystems
  // above -- embedding every file is real CPU work (see api/repos.py's
  // POST /subsystems/hdbscan docstring), so this stays a separate,
  // explicitly-triggered action with its own loading state.
  const computeSubsystemsHdbscan = async () => {
    setComputingSubsystemsHdbscan(true);
    try {
      await api(`/api/repos/${id}/subsystems/hdbscan`, { method: "POST" });
      loadSubsystems();
      loadRanking(scorer); // subsystem_hdbscan_id on each file just changed
    } catch (e: any) {
      setError(e.message);
    } finally {
      setComputingSubsystemsHdbscan(false);
    }
  };

  useEffect(() => {
    loadRepo();
    loadSubsystems();
    loadOverview();
    loadHealth();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  useEffect(() => {
    loadRanking(scorer);
    loadGraph(scorer);
    loadDirGraph(scorer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, scorer]);

  // Phase G2/G4: filter state, the active scorer, and the active view all
  // round-trip through the URL, so a filtered/selected view is reloadable
  // and shareable -- replace, not push, so every keystroke or tab switch
  // doesn't pollute browser history.
  useEffect(() => {
    const next = new URLSearchParams(searchParams);
    next.set("scorer", scorer);
    next.set("view", view);
    applyFilterStateToSearchParams(next, filters);
    setSearchParams(next, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scorer, view, filters]);

  // Phase G4: selection sync -- switching to the reading list while a
  // file is selected (e.g. clicked in Layers) scrolls it into view and
  // highlights it, the same way clicking a row does directly.
  useEffect(() => {
    if (view !== "reading" || selectedFileId === null) return;
    document.getElementById(`file-row-${selectedFileId}`)?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [view, selectedFileId]);

  const sync = async () => {
    if (!repo) return;
    setRunning(true);
    setError("");
    try {
      const { job_id } = await api<{ job_id: number }>(`/api/repos/${repo.id}/jobs`, { method: "POST" });
      await streamJobProgress(repo.id, job_id, (evt) => {
        if (evt.type === "progress") {
          setJob((j) => ({
            ...(j as RepoJobT),
            status: evt.status as RepoJobT["status"],
            stage: evt.stage,
            progress_current: evt.current,
            progress_total: evt.total,
            message: evt.message,
          }));
        } else if (evt.type === "done") {
          setRunning(false);
          loadRepo();
          loadRanking(scorer);
          loadGraph(scorer);
          loadDirGraph(scorer);
        } else if (evt.type === "error") {
          setRunning(false);
          setError(evt.message);
        }
      });
    } catch (e: any) {
      setRunning(false);
      setError(e.message);
    }
  };

  const files = ranking?.files ?? [];
  const graphNodes = graph?.nodes ?? [];
  const segments = useMemo(() => deriveTopLevelSegments(files), [files]);
  const languages = useMemo(() => deriveLanguages(files), [files]);
  // Phase I6: which SubsystemsResponseT backs a given algorithm -- used
  // both for the Reading-list filter chips below (which must follow
  // whichever algorithm is currently selected in the Subsystems tab) and
  // for building per-algorithm label maps, so there's one place that
  // knows the algorithm -> state-variable mapping.
  const subsystemsResponseFor = (algorithm: SubsystemAlgorithmT): SubsystemsResponseT | null =>
    algorithm === "louvain" ? subsystemsLouvain : algorithm === "hdbscan" ? subsystemsHdbscan : subsystemsModularity;

  const labelMapFrom = (data: SubsystemsResponseT | null): Map<number, string> => {
    const map = new Map<number, string>();
    for (const s of data?.subsystems ?? []) {
      map.set(s.id, s.custom_label || (s.active_label_rule === "top_fan_in" ? s.top_fan_in_label : s.dominant_prefix_label) || `Cluster ${s.cluster_index}`);
    }
    return map;
  };

  // Phase I1: chip labels come from the persisted CodeSubsystem rows
  // (dominant_prefix/top_fan_in/custom label), not derived from files
  // alone -- unlike segments/languages, a subsystem id has no meaning
  // without looking up what compute_subsystems named it. Always
  // modularity, regardless of which algorithm is selected in the
  // Subsystems tab -- ArchitectureMap/MatrixView's cluster color mode
  // (colorMode state above) only ever colors by subsystem_modularity_id
  // (dir_aggregation.py's _cluster_of never looks at Louvain/HDBSCAN), so
  // its legend labels must come from the SAME algorithm as the colors
  // themselves, not whatever the Subsystems tab happens to be showing.
  const modularityLabelById = useMemo(() => labelMapFrom(subsystemsModularity), [subsystemsModularity]);
  // Phase I6: by contrast, the Reading-list "Cluster" filter chips (below)
  // exist to let you view files from whichever cluster the Subsystems tab
  // is currently showing -- these DO need to follow subsystemAlgorithm,
  // or clicking a Louvain/HDBSCAN card's "view files" would silently
  // filter against the wrong id space (a real gap this phase closed: it
  // existed for Louvain the moment a second algorithm was added, and
  // would have repeated for HDBSCAN otherwise).
  const activeSubsystemLabelById = useMemo(
    () => labelMapFrom(subsystemsResponseFor(subsystemAlgorithm)),
    [subsystemAlgorithm, subsystemsModularity, subsystemsLouvain, subsystemsHdbscan]
  );
  const subsystemIds = useMemo(() => deriveSubsystemIds(files, subsystemAlgorithm), [files, subsystemAlgorithm]);
  const visible = useMemo(() => filterFiles(files, filters), [files, filters]);
  const visibleGraphNodes = useMemo(() => filterFiles(graphNodes, filters), [graphNodes, filters]);

  // Phase J1: opening the Dependency Graph adopts whatever is already
  // selected -- click a directory on the Architecture map (or a file
  // anywhere) and switching tabs explores THAT, rather than dropping the
  // user on an empty canvas and making them re-pick what they just picked.
  // Only seeds when the graph has no focus of its own yet; once the user
  // has re-centered inside the view, later selections must not yank the
  // focus out from under them.
  useEffect(() => {
    if (view !== "depgraph") return;
    if (graphFocusFileId !== null || graphFocusDir !== null) return;
    if (selectedFileId !== null) setGraphFocusFileId(selectedFileId);
    else if (selectedDirId !== null) setGraphFocusDir(selectedDirId);
  }, [view, selectedFileId, selectedDirId, graphFocusFileId, graphFocusDir]);

  // Phase J1: the Dependency Graph honours the same filter chips every
  // other tab does, so "hide config/migration/generated" narrows the graph
  // too instead of silently applying to nothing -- and the page's own
  // "Showing X of Y" counter stays true of what the graph is drawn from.
  // Focus files are exempt: filtering away the node the view is centred on
  // would empty the graph and look like a bug rather than a filter result,
  // the same reasoning as scopeGraph's own focus exemption for clusters.
  const depGraphNodes = useMemo(() => {
    const visibleIds = new Set(visibleGraphNodes.map((n) => n.id));
    const focusSet = new Set(graphFocusFileId !== null ? [graphFocusFileId] : []);
    return graphNodes.filter((n) => visibleIds.has(n.id) || focusSet.has(n.id));
  }, [graphNodes, visibleGraphNodes, graphFocusFileId]);

  const graphFocus = useMemo((): { ids: number[]; label: string } => {
    if (graphFocusFileId !== null) {
      const node = graphNodes.find((n) => n.id === graphFocusFileId);
      return { ids: [graphFocusFileId], label: node?.path ?? `file ${graphFocusFileId}` };
    }
    if (graphFocusDir !== null) {
      // A directory focus seeds from every file in it -- the question
      // "what does this folder depend on" is genuinely about the union of
      // its files, not about any one representative file.
      const ids = graphNodes.filter((n) => dirnameOfPath(n.path) === graphFocusDir).map((n) => n.id);
      return { ids, label: `${graphFocusDir} (${ids.length} files)` };
    }
    return { ids: [], label: "" };
  }, [graphFocusFileId, graphFocusDir, graphNodes]);

  const sorted = useMemo(() => {
    const copy = [...visible];
    copy.sort((a, b) => {
      const av = a[sortKey] ?? -Infinity;
      const bv = b[sortKey] ?? -Infinity;
      return sortDesc ? (bv as number) - (av as number) : (av as number) - (bv as number);
    });
    return copy;
  }, [visible, sortKey, sortDesc]);

  const toggleSort = (key: SortKey) => {
    if (key === sortKey) setSortDesc((d) => !d);
    else {
      setSortKey(key);
      setSortDesc(true);
    }
  };

  const toggleSegment = (seg: string) => {
    setFilters((f) => ({
      ...f,
      segments: f.segments.includes(seg) ? f.segments.filter((s) => s !== seg) : [...f.segments, seg],
    }));
  };

  const toggleLanguage = (lang: string) => {
    setFilters((f) => ({
      ...f,
      languages: f.languages.includes(lang) ? f.languages.filter((l) => l !== lang) : [...f.languages, lang],
    }));
  };

  const scorerLabel = SCORERS.find((s) => s.value === ranking?.scorer)?.label ?? ranking?.scorer ?? "";

  return (
    <div className="w-full max-w-none space-y-6">
      <button onClick={() => navigate("/repos")} className="font-mono text-[11px] text-fog hover:text-snow">
        ← back to repos
      </button>

      {error && <p className="text-danger text-sm">{error}</p>}

      {repo && (
        <div className="card p-5">
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div>
              <h2 className="font-display text-2xl font-semibold tracking-tight text-snow/90">
                {repo.owner ? `${repo.owner}/${repo.name}` : repo.name}
              </h2>
              <div className="flex gap-2 mt-2 flex-wrap font-mono text-[10px]">
                <span className="text-fog border border-line rounded px-1.5 py-0.5">{repo.source_kind}</span>
                <span className="text-fog border border-line rounded px-1.5 py-0.5">{repo.host}</span>
                <span className="text-fog border border-line rounded px-1.5 py-0.5">
                  {repo.file_count ?? "?"} files
                </span>
                <span className="text-fog border border-line rounded px-1.5 py-0.5">
                  synced {timeAgo(repo.last_ingested_at)}
                </span>
                {repo.last_ingested_sha && (
                  <span className="text-fog border border-line rounded px-1.5 py-0.5">
                    {repo.last_ingested_sha.slice(0, 7)}
                  </span>
                )}
              </div>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <button
                ref={glossaryTriggerRef}
                onClick={() => setShowGlossary(true)}
                className="font-mono text-[10px] uppercase tracking-widest text-fog hover:text-accent border border-line rounded px-3 py-2"
              >
                Glossary
              </button>
              <button className="btn-accent disabled:opacity-50" disabled={running} onClick={sync}>
                {running ? "Syncing…" : "Sync & Rank"}
              </button>
            </div>
          </div>
          {running && job && (
            <p className="font-mono text-[10px] text-accent mt-3 animate-pulse">
              {job.stage}
              {job.progress_total > 0 ? ` (${job.progress_current}/${job.progress_total})` : ""} — {job.message}
            </p>
          )}
        </div>
      )}

      {ranking?.reduced_confidence && (
        <div className="card p-4 border-warning/40 bg-warning/5">
          <p className="text-warning text-sm font-medium">Reduced confidence</p>
          <p className="text-fog text-xs mt-1">
            Git history wasn't available for this repo's rank runs (no git binary, or this checkout has no commit
            history) -- history-based signals are redistributed across the graph-only signals below.
          </p>
        </div>
      )}

      {!repo?.last_ingested_at && !running && (
        <p className="text-fog text-sm font-mono">Not yet synced -- click "Sync & Rank" to build the reading list.</p>
      )}

      {files.length > 0 && (
        <div className="flex flex-wrap items-center gap-3">
          <div className="inline-flex rounded border border-line p-1 gap-1">
            {VIEWS.map((v) => (
              <button
                key={v.value}
                onClick={() => setView(v.value)}
                className={
                  "font-mono text-[10px] uppercase tracking-widest rounded px-3 py-1.5 transition-colors " +
                  (view === v.value ? "bg-accent/15 text-accent" : "text-fog hover:text-snow")
                }
              >
                {v.label}
              </button>
            ))}
          </div>
          <FileSearch
            files={files.map((f) => ({ file_id: f.file_id, path: f.path }))}
            onSelectFile={(fileId) => {
              selectFile(fileId);
              setView("focus");
            }}
          />
        </div>
      )}

      {/* Phase K1: the filter bar is hidden on Overview. It filters the FILE
          set, and nothing on the overview is a filtered file list -- leaving
          it there would offer controls that visibly do nothing, which is the
          same class of confusion as the "Showing 0 of 173" counter bug an
          earlier browser pass caught. */}
      {files.length > 0 && view !== "overview" && (
        <div className="card p-5 space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-[10px] uppercase tracking-widest text-fog w-24 shrink-0">Path</span>
            {segments.map((seg) => (
              <Chip key={seg} active={filters.segments.includes(seg)} onClick={() => toggleSegment(seg)}>
                {seg}
              </Chip>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-[10px] uppercase tracking-widest text-fog w-24 shrink-0">Language</span>
            {languages.map((lang) => (
              <Chip key={lang} active={filters.languages.includes(lang)} onClick={() => toggleLanguage(lang)}>
                {lang}
              </Chip>
            ))}
          </div>
          {subsystemIds.length > 0 && (
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-[10px] uppercase tracking-widest text-fog w-24 shrink-0">Cluster</span>
              {subsystemIds.map((sid) => (
                <Chip
                  key={sid}
                  active={filters.subsystemId === sid && filters.subsystemAlgorithm === subsystemAlgorithm}
                  onClick={() =>
                    setFilters((f) => ({
                      ...f,
                      subsystemId: f.subsystemId === sid && f.subsystemAlgorithm === subsystemAlgorithm ? null : sid,
                      subsystemAlgorithm,
                    }))
                  }
                >
                  {activeSubsystemLabelById.get(sid) ?? `Cluster ${sid}`}
                </Chip>
              ))}
            </div>
          )}
          <div className="flex flex-wrap items-center gap-5">
            <label className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-widest text-fog cursor-pointer">
              <input
                type="checkbox"
                checked={filters.hideNoise}
                onChange={(e) => setFilters((f) => ({ ...f, hideNoise: e.target.checked }))}
                className="accent-accent"
              />
              Hide {NOISE_CATEGORIES.join("/")}
            </label>
            <label className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-widest text-fog cursor-pointer">
              <input
                type="checkbox"
                checked={filters.hideZeroFanIn}
                onChange={(e) => setFilters((f) => ({ ...f, hideZeroFanIn: e.target.checked }))}
                className="accent-accent"
              />
              Hide zero fan-in
            </label>
            <input
              type="text"
              value={filters.query}
              onChange={(e) => setFilters((f) => ({ ...f, query: e.target.value }))}
              placeholder="Search path…"
              className="bg-transparent border border-line rounded px-2 py-1 text-snow text-xs font-mono flex-1 min-w-[160px]"
            />
          </div>
          <p className="font-mono text-[10px] text-fog">
            {/* Phase I1: the subsystem filter only carries meaning for the
                ranking-based file list (visible) -- GraphNodeT (behind
                visibleGraphNodes, used by every other tab) doesn't carry
                subsystem membership at all, so falling through to it while
                a subsystem filter is active would always read 0 regardless
                of tab, which is exactly what a browser pass caught. */}
            Showing {view === "reading" || filters.subsystemId !== null ? visible.length : visibleGraphNodes.length} of{" "}
            {files.length} files
          </p>
        </div>
      )}

      {/* Phase H5: persistent side panel, not a slide-over -- lives beside
          whichever view is active rather than covering it, and stays put
          across tab switches since it's driven by shared selection state
          (selectedFileId/selectedDirId), not view-local state. */}
      <div className="flex items-start gap-4">
      <div className="flex-1 min-w-0 space-y-6">
      {view === "overview" && overview && (
        <OverviewView
          data={overview}
          health={health}
          directories={directories}
          onComputeHealth={computeHealth}
          computingHealth={computingHealth}
          onSelectFile={(fileId) => {
            selectFile(fileId);
            setView("reading");
          }}
          onGoToView={(next) => setView(next)}
        />
      )}
      {view === "overview" && !overview && (
        <p className="text-fog text-sm font-mono">Loading overview…</p>
      )}

      {files.length > 0 && view === "reading" && (
        <div className="card overflow-x-auto">
          <div className="flex items-center justify-between gap-4 flex-wrap px-4 py-3 border-b border-line">
            <div className="flex items-center gap-2">
              <span className="font-mono text-[10px] uppercase tracking-widest text-fog">Scorer</span>
              <span className="font-mono text-xs text-accent border border-accent/40 rounded px-2 py-0.5">
                {scorerLabel}
              </span>
            </div>
            <label className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-widest text-fog">
              Switch scorer
              <select
                value={scorer}
                onChange={(e) => setScorer(e.target.value as ScorerT)}
                className="bg-transparent border border-line rounded px-2 py-1 text-snow text-xs font-mono normal-case tracking-normal"
              >
                {SCORERS.map((s) => (
                  <option key={s.value} value={s.value} className="bg-ink">
                    {s.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line">
                <th className="text-right px-4 py-3 font-mono text-[10px] uppercase tracking-widest text-fog whitespace-nowrap">
                  <HeaderLabel term="Rank" align="left" />
                </th>
                <th className="text-left px-4 py-3 font-mono text-[10px] uppercase tracking-widest text-fog">
                  <HeaderLabel term="Path" align="left" />
                </th>
                <th className="text-left px-4 py-3 font-mono text-[10px] uppercase tracking-widest text-fog whitespace-nowrap">
                  <HeaderLabel term="Language" />
                </th>
                {COLUMNS.map((c) => (
                  <th
                    key={c.key}
                    onClick={() => toggleSort(c.key)}
                    className="text-right px-4 py-3 font-mono text-[10px] uppercase tracking-widest text-fog cursor-pointer hover:text-accent select-none whitespace-nowrap"
                  >
                    <HeaderLabel term={c.label} align={c.align} />
                    {sortKey === c.key ? (sortDesc ? " ▾" : " ▴") : ""}
                  </th>
                ))}
                <th className="px-2 py-3" aria-hidden="true" />
              </tr>
            </thead>
            <tbody>
              {sorted.length === 0 && (
                <tr>
                  <td colSpan={COLUMN_COUNT + 1} className="px-4 py-6 text-center font-mono text-xs text-fog">
                    No files match the current filters.
                  </td>
                </tr>
              )}
              {sorted.map((f, i) => {
                const next = sorted[i + 1];
                const showDividerAfter =
                  f.rank <= VALIDATION_THRESHOLD_RANK && next && next.rank > VALIDATION_THRESHOLD_RANK;
                const isSelected = selectedFileId === f.file_id;
                return (
                  <Fragment key={f.file_id}>
                    <tr
                      id={`file-row-${f.file_id}`}
                      onClick={() => selectFile(f.file_id)}
                      className={
                        "group border-b border-line/50 cursor-pointer transition-colors " +
                        (isSelected ? "bg-accent/10" : "hover:bg-glass")
                      }
                    >
                      <td className="px-4 py-2.5 text-right font-mono text-xs text-fog">{f.rank}</td>
                      <td className="px-4 py-2.5 font-mono text-xs text-snow">
                        {f.path}
                        {f.is_entry_point && (
                          <span className="ml-2 text-[9px] uppercase tracking-widest text-accent border border-accent/40 rounded px-1 py-0.5">
                            entry
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-2.5 font-mono text-xs text-fog whitespace-nowrap">{f.language}</td>
                      <td className="px-4 py-2.5 text-right font-mono text-xs text-snow">{f.score.toFixed(3)}</td>
                      <td className="px-4 py-2.5 text-right font-mono text-xs text-fog">{f.fan_in}</td>
                      <td className="px-4 py-2.5 text-right font-mono text-xs text-fog">{f.fan_out}</td>
                      <td className="px-4 py-2.5 text-right font-mono text-xs text-fog">{f.pagerank.toFixed(4)}</td>
                      <td className="px-4 py-2.5 text-right font-mono text-xs text-fog">{f.commit_count ?? "—"}</td>
                      <td className="px-4 py-2.5 text-right font-mono text-xs text-fog">{f.distinct_authors ?? "—"}</td>
                      <td className="px-4 py-2.5 text-right font-mono text-xs text-fog">
                        {f.days_since_last_change ?? "—"}
                      </td>
                      <td className="px-2 py-2.5 text-right">
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            mermaidTriggerRef.current = e.currentTarget;
                            setMermaidFileId(f.file_id);
                          }}
                          aria-label={`Show ${f.path}'s neighborhood as a Mermaid diagram`}
                          className="font-mono text-[9px] text-fog hover:text-accent opacity-0 group-hover:opacity-100 transition-opacity"
                        >
                          LR
                        </button>
                      </td>
                    </tr>
                    {showDividerAfter && (
                      <tr aria-hidden="true">
                        <td colSpan={COLUMN_COUNT + 1} className="p-0">
                          <div className="border-t-2 border-dashed border-accent/50 relative">
                            <span className="absolute -top-2 right-4 bg-ink px-2 font-mono text-[9px] uppercase tracking-widest text-accent">
                              rank 20 -- validation threshold
                            </span>
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {files.length > 0 && view === "architecture" && dirGraph && (
        <ArchitectureMap
          nodes={dirGraph.nodes}
          edges={dirGraph.edges}
          files={files}
          selectedFileId={selectedFileId}
          onSelectFile={(fileId) => {
            selectFile(fileId);
            setView("focus");
          }}
          pairFilter={pairFilter}
          onClearPairFilter={() => setPairFilter(null)}
          onSelectDir={selectDir}
          colorMode={colorMode}
          onColorModeChange={setColorMode}
          clusterLabelById={modularityLabelById}
        />
      )}

      {files.length > 0 && view === "depgraph" && graph && (
        <Suspense
          fallback={<p className="text-fog text-sm font-mono">Loading graph engine…</p>}
        >
          <DependencyGraph
            nodes={depGraphNodes}
            edges={graph.edges}
            focusIds={graphFocus.ids}
            focusLabel={graphFocus.label}
            onSelectFile={selectFile}
            onFocusFile={(fileId) => {
              setGraphFocusDir(null);
              setGraphFocusFileId(fileId);
              selectFile(fileId);
            }}
          />
        </Suspense>
      )}

      {files.length > 0 && view === "matrix" && dirGraph && (
        <MatrixView
          nodes={dirGraph.nodes}
          edges={dirGraph.edges}
          onSelectPair={(a, b) => {
            setPairFilter([a, b]);
            selectDir(a);
            setView("architecture");
          }}
          colorMode={colorMode}
          onColorModeChange={setColorMode}
        />
      )}

      {files.length > 0 && view === "focus" && id && (
        <FocusView
          repoId={id}
          fileId={selectedFileId}
          scorer={scorer}
          onSelectFile={selectFile}
        />
      )}

      {files.length > 0 && view === "layers" && (
        <LayersView
          nodes={visibleGraphNodes}
          selectedFileId={selectedFileId}
          onSelect={selectFile}
          onOpenMermaid={(fileId, trigger) => {
            mermaidTriggerRef.current = trigger;
            setMermaidFileId(fileId);
          }}
        />
      )}

      {files.length > 0 && view === "subsystems" && id && (
        <SubsystemsView
          repoId={id}
          algorithm={subsystemAlgorithm}
          onAlgorithmChange={setSubsystemAlgorithm}
          data={subsystemsResponseFor(subsystemAlgorithm)}
          onCompute={subsystemAlgorithm === "hdbscan" ? computeSubsystemsHdbscan : computeSubsystems}
          computing={subsystemAlgorithm === "hdbscan" ? computingSubsystemsHdbscan : computingSubsystems}
          onDataChanged={loadSubsystems}
          onSelectSubsystem={(subsystemId) => {
            setFilters((f) => ({ ...f, subsystemId, subsystemAlgorithm }));
            setView("reading");
          }}
        />
      )}

      </div>

      {/* Phase K1: hidden on Overview for the same reason as the filter bar
          -- the overview has no selection concept, so the panel could only
          ever show its "select something" placeholder, spending a 320px
          column to say nothing on the one page whose whole purpose is
          orientation rather than detail. */}
      {files.length > 0 && id && view !== "overview" && (
        <div className="w-80 shrink-0">
          <DetailPanel
            repoId={id}
            scorer={scorer}
            selectedFileId={selectedFileId}
            selectedDirId={selectedDirId}
            dirNodes={dirGraph?.nodes ?? []}
            dirEdges={dirGraph?.edges ?? []}
            onSelectFile={selectFile}
            onOpenMermaidModal={(fileId, trigger) => {
              mermaidTriggerRef.current = trigger;
              setMermaidFileId(fileId);
            }}
          />
        </div>
      )}
      </div>

      <SlideOver open={showGlossary} onClose={() => setShowGlossary(false)} triggerRef={glossaryTriggerRef} title="Glossary">
        <dl className="space-y-4">
          {GLOSSARY.map((g) => (
            <div key={g.term}>
              <dt className="font-mono text-[10px] uppercase tracking-widest text-accent">{g.term}</dt>
              <dd className="text-fog text-sm mt-1 leading-relaxed">{g.desc}</dd>
            </div>
          ))}
        </dl>
      </SlideOver>

      {id && (
        <MermaidPanel
          repoId={id}
          fileId={mermaidFileId}
          scorer={scorer}
          onClose={() => setMermaidFileId(null)}
          triggerRef={mermaidTriggerRef}
        />
      )}
    </div>
  );
}
