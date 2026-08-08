# Codebase Agent — Status & Handoff (Phases A–H complete; H5 was the last checkpoint)

**Hand this file to a fresh Claude Code session to resume work with full
context. It supersedes any memory of the conversation that produced it.**
This version replaces the previous handoff (which only covered Phases A–D)
and folds forward everything through Phase H5. If you are the assistant
reading this in a new session: read this entire file before doing anything
else, then wait for the user's next instruction — **do not assume there is
a Phase I brief.** There isn't one yet (see "What's NOT done" at the
bottom).

## Read this first — three things that will bite you if you skip them

1. **This entire feature (Phases A through H) is UNCOMMITTED.** `git log`
   on this repo shows the last real commit is `e12e7c8` ("Add content
   library..."), which predates the codebase agent entirely. Every file
   below is either modified-uncommitted or untracked-new — `git status
   --short` at the time this doc was written showed **79 changed/new
   paths**. There is no safety net. Do not run `git checkout .`, `git
   reset --hard`, `git clean`, or anything destructive, ever, without
   explicit confirmation — it would delete weeks of work with no recovery
   path. If you get the chance, recommend the user commit this work soon.
2. **Two dev servers may already be running**: backend on `:8000`
   (`uvicorn app.main:app --reload`, started from `backend/`), frontend on
   `:5173` (`npm run dev` from `frontend/`). Check with
   `Get-CimInstance Win32_Process -Filter "Name='python.exe'"` /
   `netstat -ano | findstr :8000` before starting new ones — starting a
   second instance on top of a live one is a real, previously-hit failure
   mode (see "Real bugs" below, the uvicorn double-process incident). A
   boot-time tripwire now exists specifically to catch this
   (`app/main.py`'s `_fail_loudly_if_port_already_bound`) — if backend
   startup raises `RuntimeError: 127.0.0.1:8000 is already answering`,
   that's it firing correctly; find and kill the existing process instead
   of working around the check.
3. **Browser-verify every UI checkpoint, not just `tsc`/tests.** Eleven
   real bugs across Phases G and H were invisible to TypeScript and the
   test suite and were only found by actually opening the app in a real
   browser (Playwright driving the system's installed Chrome — see
   "Environment facts"). This is not optional process ceremony; it has
   paid for itself every single time it's been done. See "Standing
   process discipline" below for the full list of what this caught.

## What this is

A tool that ingests a git repository, builds its import graph, and
produces both a ranked "reading list" of its most important files AND
(as of Phase H) an interactive architecture map, dependency matrix, and
per-file focus view — **zero LLM calls, purely deterministic local
computation** throughout. Lives inside the existing ATHENA OS monorepo at
`d:\Athena\Athena\athena-os` (FastAPI backend + React/Vite/TS frontend,
unrelated to the codebase agent's own purpose — that app is a separate
learning-platform product this feature was added into).

Scope has grown phase by phase:
- **A–D**: repo registration/acquisition, parsing + import graph, ranking,
  a reading-list UI with background jobs.
- **E**: entry-point detection (real config/code-pattern based, replacing
  an old fan-in==0-or-basename heuristic), later revised in E4.
- **F1–F6**: edge weighting/kinds, node priors, weighted-PageRank scorer,
  RRF (reciprocal rank fusion) scorer, comparison harness, cross-root
  import detection for monorepos. (Detail on F1–F6 individually is not in
  this session's memory — only their surviving code and F7's validation
  of the result. Git blame / earlier session transcripts are the source
  of truth if you need F1–F6's own rationale.)
- **F7**: external validation against a hand-authored ESLint answer key —
  the project's ranking failed its own pre-registered threshold, and the
  diagnosis (not a fix) was written up and externally reported.
- **G1–G4**: fixed a real duplicate-files-shown-per-scorer bug on the repo
  page, added filters, a glossary slide-over, and a graph/layers view
  (force-directed, later deleted in H5).
- **H1–H5**: replaced the unreadable 159-node force-directed graph with a
  directory-level architecture map, a dependency matrix, a per-file focus
  view, search, and a persistent detail panel — and deleted the old force
  view once it demonstrably lost on every comparison that mattered.

Explicitly OUT of scope, per the original A–D brief and never revisited:
LLM summaries, review cards, 3D visualization, drift detection.

## Environment facts (still true, don't re-verify)

- Windows/PowerShell primary; Bash tool (Git Bash/MSYS) also available and
  is what most of Phases G–H were actually done through. **Bash heredocs
  mangle literal Windows backslash paths** (`C:\Program Files\...`) —
  silently strips backslashes. Never use a heredoc to write a file
  containing a literal Windows path; use the Write tool instead. This bit
  repeatedly during Phase G4/H3's browser-verification scripting.
- Git for Windows at `%LOCALAPPDATA%\Programs\Git\cmd\git.exe` — absent
  from PATH.
- Python venv at `backend\venv`. `Activate.ps1` is blocked by execution
  policy — call `.\venv\Scripts\python.exe` directly instead of
  activating.
- Real dev DB is SQLite at `backend\athena.db`. Alembic migrations run at
  import time in `app/main.py`. **Current alembic head: `2d10dc1df104`**
  ("phase H1.5 persist seed_eligible on code_files").
- Frontend: Vite dev server on `:5173`, proxies `/api` to the backend on
  `:8000` (see `frontend/vite.config.ts`). React + TypeScript + Tailwind.
- No GPU, CPU-only. Corporate SSL-intercepting proxy:
  - Pure-Python dependencies strongly preferred over compiled ones
    (backend).
  - **Playwright's own browser-binary download fails** with
    `SELF_SIGNED_CERT_IN_CHAIN` through this proxy. Do not attempt
    `NODE_TLS_REJECT_UNAUTHORIZED=0` — that was explicitly blocked by the
    Claude Code auto-mode classifier as a workaround attempt. Instead:
    `npm install playwright-core` (standalone, in the scratchpad
    directory, not as a project dependency) and launch the **system's
    installed Chrome** directly:
    ```js
    import { chromium } from "playwright-core";
    const browser = await chromium.launch({
      executablePath: "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
      headless: true,
    });
    ```
    This works with no download needed and is how every browser-pass
    screenshot/verification in Phases G–H was actually taken.
- The validation/dogfooding target is this same repo,
  `D:\Athena\Athena\athena-os` — real local git history, remote
  `github.com/Anshu10pal/Athena-OS`. `backend/` is a subdirectory of the
  actual git root, not the root itself.
- This repo is registered in the dev DB as **repo id=1**,
  `local_path=D:\Athena\Athena\athena-os`, kind=`local`, and has a
  completed ingest+rank from live testing — **173 files** as of the end
  of Phase H5 (this number has grown steadily across the whole session as
  the codebase itself grew; don't be surprised if it's different again by
  the time you read this — re-run Sync & Rank if numbers look stale).

## Non-negotiable requirements (still binding for any future phase)

1. **Git binary resolution**, checked once at import time — order:
   `ATHENA_GIT_PATH` env var → PATH → known Windows locations → `pygit2`
   fallback (history ranking runs degraded/reduced-confidence). Fail
   loudly at boot, never mid-ingest. `git_ops.py`.
2. **Always `--no-pager`** on every git invocation — enforced in
   `git_ops.run_git()`, the single wrapper every git.exe call goes
   through.
3. **Clone with** `--filter=blob:none --config core.autocrlf=false
   --config core.longpaths=true`.
4. **Never put a token in a clone URL.** Credential helper / `GIT_ASKPASS`,
   tokens via `keyring`, never a config file.
5. **Zero LLM calls, anywhere, ever**, in this entire feature — this was
   re-stated as a hard requirement at the start of Phase H and holds for
   everything before it too.
6. **All queries scoped by `repo_id`, and by `scorer` wherever they touch
   `code_file_ranks`** — this exact scoping bug (reading `code_file_ranks`
   by `repo_id` alone, sorting three incompatible scorers' rows together)
   is what triggered the entire Phase G rewrite. Never regress it.

## House rules (still in effect, expanded across G–H)

- Explain the plan before writing code.
- One sub-phase at a time; stop at each checkpoint for sign-off.
- Complete replacement files were the convention through Phase D; Phases
  G–H mostly used targeted Edit-tool diffs instead once the codebase was
  large enough that full-file pastes stopped being the more legible
  option — either is fine, use judgment, but never leave a half-applied
  edit.
- Tell the user directly when something asked for is wrong — this came up
  concretely in H1 (the brief assumed `prior_category` had `test`/`script`
  values; it doesn't) and was corrected in the plan-before-code step, not
  silently worked around.
- Reuse existing design tokens (`frontend/src/index.css` `:root`,
  `tailwind.config.js`) — no new colors/hardcoded hex, with one
  consistently-applied exception: canvas/SVG fill/stroke and Mermaid's
  `themeVariables` require literal CSS color strings, not Tailwind class
  names, so those specific spots duplicate the existing token hex values
  verbatim (documented inline every time, e.g. `GraphView`'s [deleted in
  H5] and `ArchitectureMap`'s `KIND_COLOR`, `MermaidPanel`'s
  `MERMAID_THEME_VARIABLES`).
- No new state library/CSS framework/component library — three explicit,
  approved exceptions across the project: `vitest` (test runner, G2),
  `mermaid` (diagram rendering, lazy-loaded, G4), `d3-force` (force
  simulation, G4 — **later removed entirely in H5**, see below).
- Pure-Python / pure-JS dependencies preferred; hand-rolled algorithms
  over compiled/heavy deps where reasonable (PageRank, Tarjan's SCC,
  barycenter crossing-minimization — all hand-rolled, no library).

### Standing process discipline (learned the hard way, keep doing these)

1. **Browser-pass every UI checkpoint, not just at the end.** Originated
   from a G3 finding (a global `Escape` handler swallowing a panel's own
   Escape and navigating away — invisible to tsc/tests, looked correct on
   inspection). Confirmed valuable **eleven more times** across G4–H5:
   two focus-return bugs in slide-over panels (G3, G4), a `space-y-6`
   margin bug on a `position:fixed` element (G4), a nav-bar z-index
   overlap (G4), a satellite-arc-overlapping-real-content bug (H3), a
   rollup-algorithm overshoot bug caught by a *unit test* rather than the
   browser this time (H1) — the pattern generalizes to "verify by
   measuring, not by eyeballing" regardless of which tool does the
   measuring.
2. **Cheap staleness/environment tripwires pay for themselves.** Added
   after a uvicorn process ran for hours without `--reload` and served
   silently-stale code with no error: `--reload` by default now, plus
   `process_started_at` in `/api/health`. Added again after a genuine
   double-uvicorn-process incident (see Real Bugs): a boot-time port
   check in `main.py`.
3. **Write a prediction before running the verification that would
   confirm or refute it.** Used explicitly in H2 (layer histogram shape,
   core/db-at-highest-layer) and H4 (matrix should show exactly 3
   symmetric pairs, matching H2's 3 SCCs). Both predictions were checked
   against real data via standalone scripts *before* building any UI on
   top of the assumption, and both matched exactly. This is the same
   discipline as the ESLint external-validation protocol, applied at
   feature-design granularity instead of whole-project granularity.
4. **A test passing for the wrong reason is a distinct bug category from
   a test failing.** Caught twice: once in G1 (a fixture mutated the
   target file's own content between rank runs, which reset
   `prior_source` via an unrelated code path and accidentally exercised
   the OLD branch instead of the NEW one being tested — fixed by mutating
   an external signal instead), once implicitly reinforced by the
   `bg-void` non-existent-Tailwind-class incident (G3) where a design
   violation was harmless in effect but wrong in kind, and was only found
   by checking, not by anything breaking.
5. **When a bug's root cause is a loop trusting a between-passes check
   instead of gating each operation, look for the same shape elsewhere.**
   `_migrate_entry_priors`'s staleness bug (G1) and the H1 directory
   rollup's overshoot bug are the *same shape*: a loop that only
   re-evaluates its stopping condition between whole passes, not before
   each individual operation within a pass. Both were fixed the same way
   (check before each operation, not just between batches).
6. **Extracting shared logic prevents the two-implementations-drift bug
   class.** Done explicitly three times: `SlideOver.tsx` (G3/G4, one
   open/close/focus implementation instead of two copies that could
   diverge), the glossary text (G3, one source of truth for the slide-over
   panel AND the per-column header tooltips), `neighborGrouping.ts` (H4,
   one directory-grouping implementation shared by Focus view and the
   Mermaid export, so "api/ ×14" can never disagree between the two).

## Architecture — Database (SQLAlchemy models, `backend/app/db/models.py`)

| Table | Phase | Purpose |
|---|---|---|
| `repos` | A, +G1 | Registered repos (`clone` or `local`). G1 added `reduced_confidence` (repo-wide, moved off `code_file_ranks`). Has `seed_exclude_paths` (E4) for per-repo seed-eligibility overrides. |
| `code_files` | B, +G1, +H1.5 | One row per source file at last successful parse. `content_sha256` is the re-ingest cache key. G1 moved `fan_in`/`fan_out`/`is_entry_point`/`commit_count`/`distinct_authors`/`days_since_last_change` here from `code_file_ranks` (identical regardless of scorer). H1.5 added `seed_eligible` (nullable bool: True=seed-eligible entry, False=prior-only entry, None=not an entry / not yet ranked) — see "Phase H1.5" below for why. |
| `code_symbols` | B | Functions/classes/methods, `parent_symbol_id` for methods. |
| `code_imports` | B, +F1 | Unified file-level + symbol-level import edges. F1 added `kind` (categorical edge-weight-relevant fact, e.g. `inherits`/`calls`/`heavy_use`/`light_use`/`type_only`/`reexport`/`test_edge`/`unresolvable_binding`) and `cross_root_kind` (nullable, set for a monorepo cross-package import that bypasses the target package's own public entry point). |
| `code_file_ranks` | C, +G1 | One row per (file, scorer) pair now (previously ambiguous scoping — see the G1/Phase-G-motivating-bug below). G1 reduced this table to just `id, repo_id, file_id, scorer, score, rank, pagerank, computed_at` — `rank` is new (1-indexed position among ALL files for that repo+scorer at write time, stored not recomputed). |
| `repo_jobs` | D | Background resync+ingest+rank job state; this row IS what a reconnecting SSE client reads. |

Migrations exist in `backend/alembic/versions/` — **all untracked in git**
(see the critical warning at the top). Current head: `2d10dc1df104`. Run
`alembic heads` / `alembic current` to confirm; run `alembic upgrade head`
if a fresh checkout of these migration files is ever needed (they're
already applied to the live `athena.db`, so this is a no-op unless the DB
file itself is reset — don't reset it).

## Architecture — Backend service modules (`backend/app/services/codebase/`)

Phase-tagged; A–D modules unchanged in spirit since the original handoff,
noted briefly, followed by everything added since.

- **`git_ops.py`** (A) — binary resolution, `keyring`-backed credentials,
  `run_git()`.
- **`policy.py`** (A) — blocklist check against `config/repo_policy.yaml`.
- **`registry.py`** (A, +H1.5) — `register_from_url`/`register_from_path`/
  `resync`/LRU eviction. H1.5 added a boot-time `check_clone_root_safety`
  call from `main.py` (refuses to start if the clone cache root would be
  ingested as part of a registered repo's own code).
- **`discovery.py`** (A) — file walk, `.gitignore` handling, file-count
  cap.
- **`languages.py`** (B) — tree-sitter parser setup.
- **`extract_python.py`** / **`extract_js.py`** (B) — symbol + import
  extraction.
- **`resolve_imports.py`** (B) — Python/JS import resolution.
- **`root_discovery.py`** / **`js_root_discovery.py`** (later, exact
  phase not in this session's memory) — multi-root/monorepo root
  promotion, referenced by F1's cross-root edge detection.
- **`ingest.py`** (B, +ongoing) — orchestrator, hash-based re-parse skip,
  `BLIND_SPOTS` list, `on_progress` callback.
- **`edge_weights.py`** (F1) — `classify_edge()` (kind classification,
  precedence rules), `resolve_weight()` (kind → numeric weight from
  `config/edge_weights.yaml`, resolved at scoring time not parse time so
  retuning never requires re-ingesting), `is_test_file()` (path-marker
  heuristic — `("test_", "_test.", "/tests/", ".test.", ".spec.",
  "__tests__/")` — **reused directly in H1's directory-kind derivation**,
  not a new heuristic).
- **`node_priors.py`** (F2) — `prior_category` classification
  (`config`/`migration`/`generated`/`barrel`/`source`, checked in that
  order; never returns `"entry"` — that's graph/detection-dependent and
  handled only by `ranking.py`'s write-back), `resolve_prior()` (numeric
  multiplier from `config/node_priors.yaml`).
- **`entry_detection.py`** (E, rewritten E4, **fixed for a real
  performance bug in H1.5**) — `detect_entry_points()`: authoritative
  (Dockerfile CMD/ENTRYPOINT, Procfile, render.yaml, `pyproject.toml`
  `[project.scripts]`, `package.json` main/module/bin, `index.html`
  script tags, `vite.config` rollupOptions.input) vs. fallback (code
  pattern: `if __name__ == "__main__"`, FastAPI/Flask app instantiation,
  `createRoot(...).render(`/`ReactDOM.render(`) detection. Returns
  `{file_id: {"method": "authoritative"|"fallback", "seed_eligible":
  bool}}`. `_is_seed_eligible()`: authoritative is always seed-eligible; a
  fallback detection is seed-eligible UNLESS its path sits under a
  conventionally-auxiliary marker (`seed_ineligible_path_markers` in
  `config/entry_detection.yaml`: `scripts/`, `tools/`, `tests/`, `test/`)
  — this seed-eligible/prior-only split is **the single most-reused idea
  in Phase H** (drives H1's `entry` vs `tooling` directory kind). **H1.5
  fix**: `_iter_files_named()` used to be `repo_root.rglob(name)` filtered
  AFTER the walk — `rglob` still descended into `node_modules`/`.venv`
  before the filter discarded matches found there. Rewritten to
  `os.walk()` with in-place `dirnames[:]` pruning, and
  `_IGNORED_DIR_NAMES` broadened from `{node_modules, dist, build, .git}`
  to also include `venv`, `.venv`, `__pycache__`. This took a live
  `/graph` request from **15–20 seconds to ~0.6 seconds**.
- **`dir_aggregation.py`** (H1, new file) — pure functions, no DB/
  filesystem access, collapsing a file-level graph payload into
  directory-level nodes/edges:
  - `dirname_of(path)` — everything before the last `/`, or `"(root)"`.
  - `region_of(path)` — top-level path segment.
  - `_roll_up_to_cap(groups, max_groups=24)` — merges the deepest
    group(s) into their parent, one whole depth level per outer-loop
    pass, but **checks the cap before each individual merge within a
    pass** (fixed after a real overshoot bug — see Real Bugs). Returns
    the rollup count.
  - `_kind_of(files)` — reads `is_entry_point`/`seed_eligible` directly
    off each file dict (persisted columns, not a live scan): `entry` if
    any file is a seed-eligible entry; `tooling` if any file is an entry
    at all but none are seed-eligible (this is the E4 seed-eligible/
    prior-only split, reused, not a new signal); else a migration/test/
    source plurality vote (migration via `prior_category`, test via
    `edge_weights.is_test_file`, tie-break priority migration > test >
    source).
  - `aggregate_to_directories(nodes, edges, max_groups=24, limit=None)` —
    the main entry point. Runs over the FULL node list; `limit` caps
    DIRECTORIES after aggregation, never files before it (see Real Bugs
    for why this distinction is load-bearing). Returns `{"nodes",
    "edges", "group_rollups", "total_groups_before_limit", "truncated"}`.
    Directory node fields: `id` (= its own path, a string — no integer id
    for a virtual group), `path`, `short_label`, `file_count`, `kind`,
    `region`, `internal_edge_count`, `fan_in_dirs`, `fan_out_dirs`,
    `import_count_in`, `import_count_out` (the last four all derived
    purely from the aggregated edge list, deliberately NOT a raw sum of
    member files' own `fan_in`/`fan_out` — see Real Bugs).
- **`ordering.py`** (F4) — `compute_layers()` (file-level, entry-seeded
  BFS via `networkx.condensation` for SCC handling), `build_reading_order()`.
  Not the same algorithm as H2's directory-level layering (see below) —
  file-level layers are "distance from an entry point"; directory-level
  layers are "longest path from a source" with no entry-point seed at
  all. Both condense SCCs, using the same `networkx.condensation`
  technique, for the same reason (a cycle's "depth" is undefined).
- **`ranking.py`** (C, F3 weighted-pagerank + F5 comparison support,
  G1 restructured, **H1.5 threaded `seed_eligible` through**) —
  `legacy_signal_snapshot()` / `rank_repo()` (legacy weighted-sum scorer),
  `rank_repo_weighted_pagerank()` (personalized PageRank seeded from
  seed-eligible entries only, excluding structurally-inert fan_out==0
  seeds — an F7 finding), `rank_repo_rrf()` (reciprocal rank fusion,
  reuses `legacy_signal_snapshot`). `_write_file_level_signals()` (shared
  helper, G1) now takes a required `seed_eligible` dict alongside
  `is_entry`, written onto `CodeFile.seed_eligible` by whichever scorer
  runs. `_migrate_entry_priors()` (E4, **rewritten in G1** to re-check
  every rank run instead of freezing after a file's first migration —
  this was Phase G's single biggest bug, see Real Bugs).
- **`comparison.py`** (F5) — leave-one-out ablation harness for the
  scoring weights.
- **`repo_lock.py`** — advisory per-repo lock so a rank read can't land
  inside an in-flight ingest's two-stage resolution window.
- **`jobs.py`** (D) — background job execution, own `SessionLocal()` per
  thread, throttled progress writes, dedup against an already-running job.

### Config files (`backend/config/`)

`repo_policy.yaml`, `ranking_weights.yaml`, `edge_weights.yaml` (F1),
`node_priors.yaml` (F2), `weighted_pagerank.yaml` (F3), `rrf.yaml` (F3),
`entry_detection.yaml` (E4 — `fan_in_contradiction_threshold`,
`seed_ineligible_path_markers`).

## Architecture — Backend API (`backend/app/api/repos.py`, prefix `/api/repos`)

```
GET    /                          list repos
POST   /                          register (url or local_path + optional source_root)
GET    /{id}                      single repo
PUT    /{id}/seed-exclude-paths   set per-repo seed-eligibility overrides (E4)
POST   /{id}/resync               fetch + checkout (clone repos only)
POST   /{id}/ingest               synchronous ingest
POST   /{id}/rank                 synchronous rank (all three scorers computed separately, see VALID_SCORERS)
GET    /{id}/ranking?scorer=...   stored ranking for ONE scorer, ordered by stored rank (G1: scoped by repo_id AND scorer)
GET    /{id}/graph?scorer=&level=directory|file&limit=&language=&path_prefix=&min_score=
                                   nodes+edges. level=directory is the DEFAULT (H1). level=file is the
                                   original G4 shape, kept alive for LayersView. See "Phase H1" below
                                   for the full field list and the limit-after-not-before-aggregation rule.
GET    /{id}/files/{file_id}/neighbors?scorer=...
                                   importers/imports for ONE file, capped at NEIGHBORS_ENDPOINT_CAP=100
                                   per direction independently, with *_total_before_cap fields (G4).
POST   /{id}/jobs                 start a background resync+ingest+rank job -> {job_id}
GET    /{id}/jobs/latest          most recent job for a repo
GET    /{id}/jobs/{job_id}/stream SSE progress
```

Key constants in `repos.py`: `VALID_SCORERS = ("legacy",
"weighted_pagerank", "rrf")`, `VALID_GRAPH_LEVELS = ("directory", "file")`,
`GRAPH_NODE_LIMIT_DEFAULT = 400`, `NEIGHBORS_ENDPOINT_CAP = 100`,
`DEFAULT_MAX_GROUPS = 24` (imported from `dir_aggregation.py`).

`/api/health` returns `process_started_at` (a staleness tripwire, see
Standing Process Discipline). `main.py` also has a boot-time port
preflight (`_fail_loudly_if_port_already_bound`) — see Real Bugs.

## Architecture — Frontend (`frontend/src/`)

### Pages
- **`pages/Repos.tsx`** — add-by-URL/path form, repo list.
- **`pages/RepoDetail.tsx`** — the main page this whole project lives on.
  Owns ALL shared cross-view state: `scorer`, `filters` (URL-reflected,
  G2), `view` (G4: `"reading" | "architecture" | "matrix" | "focus" |
  "layers"` — **`"graph"` was removed in H5**), `selectedFileId`,
  `selectedDirId` (H5), `pairFilter` (H4), `mermaidFileId`. `selectFile`/
  `selectDir` helper functions (H5) always clear the other one when
  setting one, so the persistent DetailPanel can't get stuck showing a
  stale selection kind. Fetches `ranking` (file-level, per scorer),
  `graph` (file-level, `&level=file` pinned — still needed by
  `LayersView`), `dirGraph` (directory-level, default `level=directory` —
  used by `ArchitectureMap`/`MatrixView`).

### Components, by the view they belong to

**Shared / cross-cutting**
- **`SlideOver.tsx`** (G3, extracted; **portal fix in G4**) — the ONE
  slide-over implementation (Glossary panel, Mermaid modal). `createPortal`
  to `document.body` (a `space-y-6` ancestor's margin was corrupting a
  `position:fixed;inset:0` child — see Real Bugs), positioned at
  `top: NAV_H` (the app's fixed nav height constant from `lib/layout.ts`,
  not a new magic number) so it doesn't render underneath the nav bar.
  Capture-phase Escape + `stopPropagation()` to defeat the app's global
  `EscToHub` handler. `triggerRef` is typed `RefObject<HTMLElement>` (not
  `HTMLButtonElement`) so a non-button trigger (a canvas/SVG container)
  can still receive focus back on close.
- **`DetailPanel.tsx`** (H5, new) — the persistent (NOT slide-over)
  right-hand panel, rendered once by `RepoDetail` beside whichever view
  is active, driven by shared `selectedFileId`/`selectedDirId`. File mode:
  fetches `/neighbors`, groups by directory (`neighborGrouping.ts`), shows
  stats + grouped dependency lists + Mermaid source text + a button to
  open the full rendered `MermaidPanel` modal. Directory mode: stats,
  cycle warning if the directory is part of a `findSymmetricPairs` pair,
  depends-on list with weights.
- **`FileSearch.tsx`** (H5, new) — top-bar substring search over file
  paths. `/` focuses (skipped if another input is already focused),
  arrow keys + Enter, click-outside closes. Deliberately NOT fuzzy-scored,
  per explicit instruction ("the mockup version is enough").
- **`MermaidPanel.tsx`** (G4, **rewritten in H4** for directory grouping)
  — the slide-over MODAL (heavier, lazy-loaded `mermaid` library, full
  rendered SVG preview). Reuses `SlideOver`.

**Reading list** — the original table, largely unchanged since G2 (URL-
reflected filters, path-segment chips, language filter, hide-noise/hide-
zero-fan-in toggles, per-column glossary tooltips).

**Architecture map** (H3, new — `ArchitectureMap.tsx`)
- Consumes `dirGraph` (directory-level). Runs `computeLayeredLayout` (H2)
  then `buildRenderNodes` (H3, merges SCC cycle members into one box).
- Deterministic layered layout, NOT force simulation — column-stacking:
  each `(region, layer)` pair is an independent vertical column;
  expanding a box only grows ITS box and pushes later-in-column siblings
  down, never sideways, never into another column, never reflowing
  anything outside its own column. This is THE property the whole
  redesign exists for — browser-verified by diffing every box's x/y
  before and after expanding the largest real box (`core ⇄ db`): zero
  horizontal movement anywhere, zero vertical movement in any other
  column.
- Cycle groups (3 real ones on this repo — see Phase H2): doubled dashed
  inner border (not a distinct color — color already carries `kind`), a
  `⇄` glyph in the label, a `CYCLE GROUP · N DIRS` sublabel in rose.
- Semantic zoom, three explicit tiers with a visible `DETAIL: SHAPES /
  LABELS / FILES` indicator (`TIER_1_MIN = 0.72`, `TIER_2_MIN = 1.45`).
- Type chips double as legend and filter (`activeKinds` state).
- Satellite arc for isolated directories (whole REGION has zero touching
  edges — `voice_listener`, `(root)`): placed in a dedicated row strictly
  above the topmost grounded content (`minY - 60`), independent of graph
  width — **fixed after a real overlap bug**, see Real Bugs.
- Core-density toggle (◉, hides directories with degree < 3 that aren't
  `entry` kind) and fullscreen (⛶).
- Hover isolation fades unrelated nodes/edges to ~0.3 opacity, **never to
  invisible** — the specific thing the old force view's dimming got
  wrong.
- `pairFilter` prop (H4): a pinned pair-isolation from a Matrix cell
  click, mapped from raw directory ids through to whichever render node
  (possibly merged) each belongs to.
- Clicking a file dot inside an expanded box sets shared selection AND
  navigates to Focus (completed in H4 once Focus existed to receive it;
  H3 only set state).

**Matrix** (H4, new — `MatrixView.tsx`, pure logic in
`lib/matrixLayout.ts`)
- **Deliberately UNCONDENSED** — every real directory gets its own row
  and column (21 of them on this repo), unlike the Architecture map's
  merged cycle boxes. This is the whole point: a cycle shows both
  directions' actual counts (`core→db=0.65` vs `db→core=0.4`), which
  condensing throws away.
- `findSymmetricPairs(nodes, edges)`: a pair where BOTH `(a,b)` and
  `(b,a)` have a real edge — **deliberately NOT the same computation as
  H2's SCC condensation** (which finds cycles of any length transitively).
  The two happen to agree on this repo (3 pairs, matching 3 SCCs member-
  for-member) because every real cycle here is a direct 2-node pair; this
  is a fact about the data, not a guarantee between the algorithms.
  Structurally independent of the display print threshold (a separate
  `PRINT_THRESHOLD=8` constant in `MatrixView.tsx` only) — pinned with a
  test (weights 1 and 20 still outline).
- Sticky row/column headers, "ROWS DEPEND ON COLUMNS · OUTLINED CELLS ARE
  CYCLES · N FOUND" stated on screen, cells shaded by weight, value
  printed above `PRINT_THRESHOLD`.
- Diagonal (self) cells show `internal_edge_count` (real H1 data), not
  clickable, not a silent dead cell — fixed after being flagged as a UX
  cliff (see Real Bugs).
- Clicking an off-diagonal cell calls `onSelectPair(a, b)` → `RepoDetail`
  sets `pairFilter` + `selectedDirId` + switches to Architecture.

**Focus** (H4, new — `FocusView.tsx`)
- One file centered; importers-left/imports-right columns of directory
  groups collapsed to counts (`api/ ×21`), click-to-expand listing real
  files. Depth-1 default; opt-in depth-2 toggle bounded to
  `MAX_DEPTH2_FETCHES = 10` additional requests, with a truncation note
  if more depth-1 files existed than that.
- Fetches the SAME `/neighbors` endpoint G4 built, groups via the shared
  `neighborGrouping.ts`.

**Layers** (G4, unchanged in spirit through H) — BFS-layer columns,
unreachable files in a final separated column, `LAYER_COLUMN_CAP = 20`
per column with a "+N more" affordance. Still consumes the file-level
`graph` (`level=file`) fetch.

**~~Graph (Raw, force-directed)~~ — DELETED in H5.** Was `GraphView.tsx` +
`lib/graphLayout.ts` (d3-force based, G4). Deleted after an explicit
three-question evidence comparison against the four new views (spot a
heavily-imported utility / find a cycle / trace from an entry point) —
Raw won none of the three. `d3-force`/`@types/d3-force` fully removed
from `package.json` (still present as `mermaid`'s own internal transitive
dependency, lazy-loaded, unrelated). **If you see any reference to
`GraphView`, `graphLayout.ts`, or a "Graph" tab anywhere, it's stale —
that code no longer exists.**

### Pure logic modules (`frontend/src/lib/`) — no DOM dependency, all unit-tested

- **`filters.ts`** (G2) — `FilterState`, URL-reflection, `filterFiles`/
  `deriveTopLevelSegments`/`deriveLanguages`, generic over a `Filterable`
  structural interface so both file-level and (later) directory-level
  nodes work without a cast.
- **`mermaid.ts`** (G4, **rewritten H4**) — `buildMermaidNeighborhood()`:
  groups importers/imports by directory (via shared
  `neighborGrouping.ts`) before capping, `MERMAID_GROUP_CAP_PER_DIRECTION
  = 8` (groups, not files — the old G4 cap was 15 FILES per direction;
  grouping mostly obsoletes that problem at the source). Sanitized
  generated ids kept from G4 (`c0` center, `i0..` importer groups, `o0..`
  import groups). `truncationNote()` unchanged shape, now used for BOTH
  group-count truncation and the backend's own file-level cap
  independently.
- **`neighborGrouping.ts`** (H4, new) — `groupNeighborsByDirectory()`,
  `shortDirLabel()`. Shared by `FocusView` and `mermaid.ts` so the two
  can never disagree about what a "group" is.
- **`layeredLayout.ts`** (H2, extended H3) — the layered-layout pure
  functions:
  - `condenseSCCs()` — hand-rolled ITERATIVE Tarjan's algorithm (explicit
    work stack, no recursion-depth risk; irrelevant at ≤24 nodes but
    reads the same either way).
  - `assignLayers()` — `layer(d) = 0` if nothing imports it, else
    `1 + max(layer(u))` over every `u` with an edge `u → d`. Computed via
    Kahn's-algorithm topological order over the condensed (now acyclic)
    graph. Every SCC member shares its SCC's layer.
  - `orderWithinLayers()` — barycenter crossing-minimization, 4 sweeps
    alternating direction, median of reference-layer neighbor positions,
    neighborless nodes keep their prior relative position.
  - `groupByRegion()` — partitions by region, flags a region isolated if
    zero edges touch any node in it.
  - `buildRenderNodes()` (H3) — merges non-trivial SCC members into one
    render node (drops internal edges, redirects+sums cross-cycle edges).
  - `dirnameOfPath()` — client-side mirror of the backend's
    `dir_aggregation.dirname_of`, same rule, same `"(root)"` sentinel.
  - `layerHistogram()`, `nonTrivialSCCs()` — the two report helpers used
    for the H2 verification.
  - `placeSatelliteArc()` — still exported/tested but **no longer called
    by `ArchitectureMap`** after the H3 overlap bug fix (the component now
    computes satellite positions inline with a width-independent formula
    instead). Left in the lib as a correct, tested, generically-useful
    utility.
- **`matrixLayout.ts`** (H4, new) — `buildWeightLookup`, `weightBetween`,
  `findSymmetricPairs` (see Matrix section above for the "deliberately
  not SCC" note).

### Types (`lib/api.ts`)
`RepoT`, `RepoJobT`, `RankedFileT`, `RankingResponseT`, `GraphNodeT`/
`GraphEdgeT`/`GraphResponseT` (file-level, `level: "file"` — still used
by `LayersView`), `DirKindT = "entry" | "tooling" | "test" | "migration" |
"source"`, `DirNodeT`/`DirEdgeT`/`DirGraphResponseT` (directory-level, H1),
`NeighborT`/`NeighborsResponseT` (G4).

## Real bugs found via testing, chronological — worth internalizing

*(Items 1–9 are from Phases A–D and unchanged from the original handoff;
summarized here, full detail in git blame / that era's own记录 if needed.
Everything from "10" on is new since that doc was written.)*

1–9. Tree-sitter-languages broken vs. modern tree-sitter; `pygit2.clone_repository()`
has no blob-filter param; `shutil.rmtree(ignore_errors=True)` silently
fails on Windows read-only files; several tree-sitter grammar shapes
wrong when assumed from memory; `networkx.pagerank()` hard-imports scipy;
`git log`'s pathspec is CWD-relative not root-relative; uncommitted files
misread as "history unavailable" for the WHOLE repo; `register_from_path`
could raise a raw 500 on a shared-origin path collision; Spearman
correlation came out as -9.800 due to un-reindexed rank positions.

10. **(Phase G1) The motivating bug for the whole Phase G rewrite**:
    `/repos/:id` read `code_file_ranks` by `repo_id` alone, without also
    filtering by `scorer` — three scorers' incompatible score scales
    sorted together as one, showing every file 2–3 times.
11. **(Phase G1) The entry-prior staleness bug — 57 files affected on
    this repo.** `_migrate_entry_priors`'s guard `if f.prior_source !=
    "graph": continue` was built to stop an old graph-based write-back
    from clobbering E4's real detection, but it ALSO froze detection's
    own result forever after a file's first migration. Files migrated
    under a pre-E4 heuristic before E4 shipped never got re-examined by
    E4's correct detector. Fixed: live re-check every run for files
    currently `"entry"` or `"source"` (never touching
    config/migration/generated/barrel, which are structural facts decided
    once). Confirmed idempotent (zero flips on a second consecutive run).
12. **(Phase G1) A test passing for the wrong reason.** The first
    regression tests for #11 mutated the target file's OWN content
    between rank runs, which reset `prior_source` back to `"graph"` via
    an unrelated re-parse code path, silently re-triggering the OLD
    branch instead of the NEW one. Fixed by mutating an EXTERNAL
    authoritative signal (a Dockerfile CMD line) instead, leaving the
    target file's own content/hash untouched.
13. **(Phase G3) Global Escape handler swallowing a panel's own Escape.**
    App-level `EscToHub` navigated away on Escape whenever focus wasn't
    in an input/textarea; the new glossary panel wasn't an input, so
    Escape "closed" it by actually navigating to `/`. Fixed with capture-
    phase + `stopPropagation()`.
14. **(Phase G3) Escape bypassing the shared close() helper**, so focus-
    return only worked on 2 of 3 exit paths. Fixed by routing all three
    (Escape, outside-click, close button) through one function.
15. **(Phase G3) `bg-void` — a non-existent Tailwind class** (`void` is a
    CSS variable name; the actual token is `ink`). Harmless in effect,
    wrong in kind — found by checking, not by anything visibly breaking.
16. **(Phase G4) `space-y-6` + `position:fixed;inset:0` margin bug.** A
    distant ancestor's `space-y-6` utility set `margin-top:24px` on the
    slide-over panel (a later sibling); CSS does NOT discard a non-auto
    margin on an over-constrained (`inset-0`) fixed box, so the panel
    rendered 24px too low, clipping its own header. Ruled out a
    Playwright/headless-Chrome quirk with a plain control div before
    finding the real cause. Fixed via `createPortal` to `document.body`.
17. **(Phase G4) Nav-bar z-index overlap**, surfaced immediately after
    fixing #16: the portal escaped `<main>`'s own nav-height padding
    compensation, so the panel's header rendered behind the fixed-
    position, higher-z-index top nav. Fixed with `top: NAV_H` (the
    existing shared constant, not a new magic number).
18. **(Phase G4) Unattached ref / unwired focus-return.** A
    `mermaidTriggerRef` was declared but never actually attached to any
    button — found by inspection before it ever ran, not by a failure.
19. **(Phase H1) Stray/duplicate uvicorn processes.** Two overlapping
    `uvicorn --reload` processes were both bound to `:8000` from
    different points in one long session, producing several minutes of
    requests that appeared to hang with no error (landing on whichever
    worker happened to still be alive). Root-caused as normal `--reload`
    supervisor+worker architecture on Windows (the differing command
    lines were expected, not a duplication bug) COMBINED with a genuine
    case of a stray earlier instance never having been killed. Fixed
    procedurally (kill + restart clean) and structurally (the port
    preflight tripwire in `main.py`, which "guards the symptom —
    something already listening — and correctly ignores the process
    architecture by testing the symptom," not the mechanism).
20. **(Phase H1) The directory rollup overshoot bug.** The first
    `_roll_up_to_cap` implementation merged an ENTIRE depth level
    unconditionally once started; for 30 sibling packages each with one
    subdirectory, this collapsed all 30 into a single `"(root)"` node
    instead of stopping the instant the 24-group cap was satisfied. Same
    shape as bug #11 (a loop trusting a between-passes check instead of
    gating each operation). Fixed by checking the cap before each
    individual merge within a pass, not just between passes. Caught by a
    unit test, not the browser — "the check is cheap, do it regardless of
    which tool does the measuring."
21. **(Phase H1.5) The 15–20 second `/graph` request.** Root cause:
    `entry_detection._iter_files_named` used `Path.rglob()`, which walks
    INTO a directory before a post-hoc filter discards matches found
    there — fully traversing `frontend/node_modules` (~300+ nested
    `package.json` files) and `backend/venv` (~1,700 subdirectories) on
    every call. Two fixes, both kept: (a) rewrote the walk to prune
    ignored directories DURING traversal via `os.walk()` +
    `dirnames[:]` mutation (16s → ~0.6s alone); (b) persisted
    `seed_eligible` on `CodeFile` so `/graph` never calls live entry
    detection at all anymore (closes a staleness/duplication risk
    independent of speed — a directory's `kind` could otherwise reflect a
    fresher filesystem scan than the ranking it's describing). Verified
    with `monkeypatch`ing the live detection call to raise, proving the
    read path genuinely never touches it. Two new regression tests spy on
    `os.walk` itself to prove pruning happens DURING the walk, not just
    that results get filtered afterward (a wall-clock assertion would
    have been flaky).
22. **(Phase H1) `limit` applied to files before aggregation, not after.**
    Would have computed a directory graph from whatever fraction of a
    large repo survived a file-level cap — invisible at 159 files,
    silently wrong at 5,000 (a plausible-looking architecture map built
    from an eighth of the repo, with no indication anything was cut).
    Fixed: `aggregate_to_directories` always sees every filtered file,
    uncapped; `limit` only trims the resulting DIRECTORY list afterward.
    Regression-tested directly (`total_groups_before_limit` must report
    the true pre-limit count).
23. **(Phase H1) `fan_in`/`fan_out` as a raw sum of member files' own
    values would have double-counted intra-directory edges** — a heavily
    self-coupled directory would report a large number matching nothing
    actually drawn. Caught before shipping (by the person planning the
    fix, not by running anything) and replaced with `fan_in_dirs`/
    `fan_out_dirs`/`import_count_in`/`import_count_out`, all derived
    purely from the aggregated edge list so they can't disagree with
    what's on screen.
24. **(Phase H3) The satellite-arc overlap bug.** The first placement
    used a circular arc centered ON the grounded content with a radius
    PROPORTIONAL TO the content's width — correct trigonometry, wrong
    parameters. On this repo's real, larger-than-the-mockup 18-node
    layout, the arc swept back and placed `(root)` directly on top of the
    `core ⇄ db` box. "Exactly the shape of failure that would slip past a
    unit test because the coordinates are internally consistent, they
    just happen to overlap" (the user's own framing). Fixed by placing
    satellites in a dedicated row strictly ABOVE the topmost content
    (`minY - 60`), independent of graph width — removes the size-
    dependence from the constraint rather than re-tuning the trig against
    one repo's specific layout.
25. **(Phase H4) The Matrix diagonal cell was a silent UX cliff.** No
    styling, no click handler, no information — just blank. Fixed to show
    the real `internal_edge_count` (H1 data), non-interactive (a "filter
    to a pair" has no meaning against itself), with a tooltip.

## Testing status

**486 backend tests, all passing.** Run with:
```
cd backend
.\venv\Scripts\python.exe -m pytest tests/ -q
```
Notable suites added since the original A–D handoff: `test_edge_weights.py`,
`test_node_priors.py`, `test_root_discovery.py`, `test_js_root_discovery.py`,
`test_comparison.py`, `test_repo_lock.py`, `test_ordering.py`,
`test_entry_detection.py` (42 tests, including 2 that spy on `os.walk`
itself to prove ignored-directory pruning — see bug #21),
`test_dir_aggregation.py` (27 tests, pure functions, no DB),
`test_repos_api.py` (extended through H4 with `TestGetGraphEndpoint`
[file-level regression] and `TestGetGraphEndpointDirectoryLevel`
[directory-level, including the limit-after-aggregation regression test
and a test that monkeypatches live entry detection to RAISE, proving the
read path never calls it]).

**56 frontend vitest tests, all passing** (was 70 before Phase H5 deleted
`graphLayout.test.ts`'s 14 tests along with the Raw view). Run with:
```
cd frontend
npm test
```
Suites: `filters.test.ts` (12), `layeredLayout.test.ts` (20 — layer
assignment on a known DAG, SCC condensation with a deliberate cycle,
barycenter provably eliminating a crafted crossing, determinism across
repeated calls, `buildRenderNodes` cycle-merging, `placeSatelliteArc`),
`matrixLayout.test.ts` (8, including the threshold-independence pin),
`neighborGrouping.test.ts` (6), `mermaid.test.ts` (10, rewritten for
group-based aggregation).

`npx tsc --noEmit` is clean. `npm run build` succeeds (main chunk ~466KB/
143KB gzip as of H5; `mermaid` itself lazy-loads separately, ~152KB gzip,
only fetched when a Mermaid panel is actually opened — confirmed via
network-request interception, not assumed).

**Browser verification**: unlike the A–D era (no graphical browser tool
available then), Phases G–H had full Playwright-driven browser access via
the system Chrome workaround (see Environment facts). Every UI checkpoint
from G3 onward was browser-verified with real screenshots and DOM/style
assertions, not just `tsc`+tests. This is how bugs #13–18, #24, #25 were
found.

## Known limitations (by design, reported not hidden)

From Phases A–D (`IngestReport.blind_spots`, still true): dynamic
`import(...)` never resolved; decorator-registered routes/DI/
monkeypatching create no static edge; `package.json` workspace
`"exports"` field not resolved; Python absolute imports checked against
`source_root`/repo-root/`src/` only, no live interpreter `sys.path`;
webpack/Vite custom aliases outside `tsconfig.json` paths not read;
default imports resolve to file not a specific default-exported symbol;
module-level variables/constants aren't extracted as symbols.

From `docs/ranking-methodology.md`: hand-rolled PageRank not numerically
identical to `networkx.pagerank()` by design; history signals undercount
across renames; a shallow clone (pygit2 fallback path only) undercounts
older files' history; one `local`-kind registration per distinct git
remote (use `source_root` to scope a subdirectory instead).

**New since Phase H:**
- **Cross-root edge visualization has no home.** `CodeImport.cross_root_kind`
  is a real, computed, file-level fact (F1) that the old deleted Raw view
  used to color distinctly. No directory-level view (Architecture, Matrix)
  currently surfaces it — `DirEdgeT` doesn't even carry the field. Flagged
  explicitly in the H5 report as an honest gap, not silently dropped. If a
  future phase wants this back, it needs a new field on the directory-
  level edge aggregation (H1's `dir_aggregation.py`) plus a rendering
  decision in whichever view should show it.
- **`dir_aggregation`'s `_kind_of` has no `"script"`/`"barrel"`/
  `"config"`/`"generated"` distinction at directory granularity** — only
  `entry`/`tooling`/`test`/`migration`/`source`. File-level `prior_category`
  still has all six of its own categories; the directory-level `kind`
  vocabulary is intentionally coarser (matches the reference mockup's own
  5-kind legend).
- **Focus view's depth-2 is capped at 10 additional fetches** — bounded to
  avoid a request storm on a file with a very large depth-1 neighbor set;
  reports a truncation note when this cap engages.
- **`placeSatelliteArc` in `layeredLayout.ts` is dead code from
  `ArchitectureMap`'s perspective** (still exported, still tested, no
  longer called there after the bug-24 fix) — a future caller could
  reasonably use it with better-chosen parameters (small fixed radius,
  center well outside content bounds) if a genuinely circular arc look is
  wanted somewhere else.

## What's NOT done — next steps

**There is no Phase I brief.** Phase H (H1 through H5) is complete, fully
tested, and fully browser-verified as of this document. The user has not
yet defined what comes next. **If you are a fresh session reading this:
do not invent a Phase I. Summarize this document back to the user briefly
to confirm you've absorbed it, then wait for their actual next
instruction.**

Carried-forward, never-fully-closed items from earlier phases (still true):

1. **The answer-key validation protocol** (F7's own machinery) is
   reusable for any future repo, not just the ESLint one already run —
   `backend/scripts/validate_ranking.py <repo_id> <answer_key_path>`,
   reporting Overlap@20/@10, Spearman, and a go/no-go verdict (≥12/20).
   The ESLint run's own answer key and result docs live in
   `docs/external-validation-eslint*.md`. The project's own ranking
   FAILED this threshold on ESLint (2/20, 3/20, 2/20 across the three
   scorers) — this was diagnosed (not fixed) and written up honestly;
   whether/how to actually improve ranking quality is still open.
2. **`docs/API.md` doesn't document `/api/repos/*`** — every other API
   surface in this app is documented there; this one still isn't, despite
   having grown substantially since the original handoff noted the gap.
3. **This entire feature is uncommitted** (see the critical warning at
   the top). Committing it is a decision for the user, not something to
   do unprompted, but it is increasingly overdue given the size of the
   working-tree diff (79 paths) and the total absence of a safety net.

## How to resume, concretely

1. Confirm dev server state (don't blindly start new ones — see critical
   warning #2).
2. Confirm current test counts match this document (486 backend, 56
   frontend) — if they don't, something changed outside this document's
   knowledge and you should investigate before trusting anything else
   here.
3. Read this document's "Standing process discipline" section again
   before writing any code — it's the distilled cost of eleven real bugs
   and is cheaper to re-read than to re-learn.
4. Wait for the user's actual next request. If they say "go ahead" without
   further specifics, ask what Phase I should cover — there's no brief to
   default to.
