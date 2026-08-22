<div align="center">

# ATHENA OS

**A local-first workspace for learning a subject and understanding a codebase.**

Study a topic, practise interviews, get feedback on a talk — and point it at any
Git repository to find out how that code is actually put together.

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=black)](https://react.dev/)
[![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?logo=typescript&logoColor=white)](https://www.typescriptlang.org/)
[![Tests](https://img.shields.io/badge/tests-1%2C171%20passing-3fb950)](#testing)
[![Cost](https://img.shields.io/badge/running%20cost-%240%2Fmonth-3fb950)](#cost)

</div>

---

# RESUME HERE — session entry point (updated 2026-08-22)

**What this is.** A local-first workspace with two halves: a learning/practice
side, and a **codebase agent** that ingests any Git repo and builds a queryable
graph of it (files, imports, symbols, ranks, subsystems, cycles). The active
work is Phase 6, which turns that graph into a **targeting map for reads** —
given a file you are about to change, it hands you the connected set directly
instead of you grepping around to find it. Everything runs locally with zero
LLM calls in the graph path.

**Active phase: 6 — Codebase Atlas → graph as targeting map.** Checkpoints 0,
1a, 1b, 2, 3 are DONE; 4a (MCP transport gate) passed for stdio.

**The number Phase 6 exists to produce** (checkpoint 3, measured on
apache/superset at SHA `a05a0999` with tiktoken cl100k): to understand a file's
context, reading every connected file versus querying the graph —
**0.93x on an isolated file** (the graph costs 8% MORE — this is the honest
floor and is reported deliberately), **15.9x and 53.8x** on the mid-connected
files where real work happens, **195.4x and 293.4x** on hubs. Pooled
**219.7x, a 99.5% reduction**, with **zero sufficiency misses**. The
distribution is the deliverable, not the pooled figure.

**THE IMMEDIATE NEXT ACTIONS, in order:**

1. **Close checkpoint 4a.** MCP servers load at session start, so the probe
   registered in `d:\Athena\.mcp.json` is not visible to the session that
   registered it. **Reload the VSCode window, then ask for the `ping` tool.**
   If it returns `pong`, 4a is fully closed. Protocol level is already proven
   (full `initialize` → `tools/list` → `tools/call` round trip, exit 0).
2. **Then build checkpoint 4b** — the real MCP server exposing
   `read_neighborhood`. **stdlib-only, or an isolated venv. Never install the
   `mcp` SDK into `backend/venv`** (see constraints below).

**THE SINGLE MOST IMPORTANT WARNING:** the four Phase 6 source files and their
three test files were untracked for most of this work. If you are reading this
from a fresh clone, verify they are present before assuming Phase 6 exists:
`backend/app/services/codebase/{graph_read,atlas_export,neighborhood}.py` and
`backend/tests/test_{graph_read,atlas_export,neighborhood}.py`.

---

## CONSTRAINTS — READ BEFORE RUNNING ANYTHING

These are the walls this environment has. A session that does not know them
loses its first half hour rediscovering them.

| | |
|---|---|
| **No GPU** | CPU-only, everything. Do not reach for a CUDA path. |
| **SSL-intercepting corporate proxy** | Outbound TLS is intercepted. `pip` works. Anything pinning its own certificates may not. |
| **Windows** | PowerShell (primary) and Git Bash take **different syntax**. `git` is not on the Bash tool's PATH — run git and full test suites through **PowerShell**. |
| **NEVER `pip install mcp` into `backend/venv`** | It pulls **starlette 1.6.0** over the pinned **0.46.2** and **breaks fastapi 0.115.12**, while printing `Successfully installed`. Use an isolated venv or write MCP servers stdlib-only. Recovery commands in `docs/TROUBLESHOOTING.md`; full account in contract **§17.34**. |
| **stdio MCP transport is proxy-immune** | It is a **pipe**, not a network call — the proxy is not in the path at any layer. Prefer it over HTTP. Proven on this machine 2026-08-22. |
| **MCP registration is config-file based** | The `claude` CLI is **not installed**; this is the VSCode extension. Register via `.mcp.json` at the workspace root. Write it with `json.dump`, **not a bash heredoc** — heredocs collapse escaped backslashes in Windows paths and produce invalid JSON that fails silently. |
| **Vite binds IPv6 only** | `localhost:5173` works; `127.0.0.1:5173` is **refused**. |
| **Dev servers are started by hand** | backend `:8000` (uvicorn `--reload`), frontend `:5173` (vite). |
| **Working directory** | `D:\Athena\Athenathena-os` (the git repo). The VSCode workspace root is `d:\Athena`, one level up — that is where `.mcp.json` lives, outside the repo. |

---

## How work is done here — read this before contributing

**[`docs/code-health-contract.md`](docs/code-health-contract.md) §17 is the
methodology contract, and it governs how work is done in this repo, not just
what was built.** 39 subsections (17.0 → 17.34, including lettered variants
like 17.0b and 17.5c), each a recorded instrument failure with its mechanism
and the rule it produced. The load-bearing ones:

- **§15.1 — a test that cannot fail must say so.** Every fix gets a canary:
  observe it FAIL on the broken code before trusting it green.
- **§17.0b — predict before measuring.** A prediction without a named mechanism
  is intuition and does not count.
- **§17.5c — denominators travel with rates.** Report the distribution, not the
  mean.
- **§17.16 — mark stale figures with provenance; never silently correct them.**
- **§17.25 — an answer whose completeness the consumer cannot assess is worse
  than no answer.** This one shaped all of Phase 6.
- **§17.33 — the same instrument error three times belongs in the tool, not in
  your memory.**

The habit that matters most: **when a measurement disagrees with the code,
establish which one is broken before recording a defect.** In this repo the
instrument has been wrong far more often than the code.

---

## Current state snapshot — 2026-08-22

Stamped so staleness is detectable. If today is much later than this date,
re-verify before trusting it.

| | |
|---|---|
| **Branch** | `codebase-agent/phase4-5-and-682` |
| **HEAD before this handoff commit** | `106e90b` — "Give comprehension cards their first user surface" |
| **Backend suite** | **1,171 passed / 1 skipped / 0 failed**, full run 2026-08-22 (24m55s), against superset at `a05a0999`. Green. |
| **Frontend** | 231 vitest across 18 files + 6 Playwright; `npx tsc --noEmit` clean |
| **Migrations** | 37, chain intact, head `d9f014c8a26b` |
| **Superset graph** | re-ingested to `a05a0999`, **6,584 files / 61,559 imports** (was `e2bb33b1`, 6,523 / 60,873) |
| **Repos in the atlas** | 1 = Athena-OS (280 files), 3 = eslint (1,447), 6 = apache/superset (6,584) |

**Committed in this handoff** — the four Phase 6 modules and their three test
files, which were untracked until now:

```
backend/app/services/codebase/graph_read.py      the stable whole-graph read boundary
backend/app/services/codebase/atlas_export.py    the compact artifact emitter
backend/app/services/codebase/neighborhood.py    THE DELIVERABLE - read_neighborhood()
backend/tests/test_graph_read.py                 11 tests
backend/tests/test_atlas_export.py               17 tests
backend/tests/test_neighborhood.py               23 tests
```

**Not in the repo, and deliberately so:** `d:\Athena\.mcp.json` (the MCP
registration) lives at the VSCode workspace root, one level ABOVE the repo. A
fresh clone on a new machine will not have it and must recreate it — see the
constraints table above.

**Phase 6 files that do NOT exist yet:** there is no MCP server for the
neighbourhood query (that is 4b), no PreToolUse enforcement hook, and no
migration of `ranking._build_graph`'s five callers onto the read boundary.

---

## Documentation map — what to read, and when

| Read this | When |
|---|---|
| [`docs/decisions.md`](docs/decisions.md) | **Start here after this README.** Every phase, every decision, why, and what was rejected. Has a START HERE section at the end with the live phase table and suite state. |
| [`docs/code-health-contract.md`](docs/code-health-contract.md) | The §17 methodology contract (how to work) and the health-metric definition (what it measures). |
| [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) | Environment constraints and setup failures, in the order they bite. |
| [`docs/codebase-agent-handoff.md`](docs/codebase-agent-handoff.md) | Deep implementation notes for the ATLAS (phases A–K). **Pre-Phase-6** — it has a banner saying so. |
| [`docs/API.md`](docs/API.md) · [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Endpoint reference and system architecture. |
| [`docs/external-validation-eslint.md`](docs/external-validation-eslint.md) | Validating the ranking against a third-party repo, including where it failed. |
| [`docs/ranking-methodology.md`](docs/ranking-methodology.md) · [`docs/calculations-explained.md`](docs/calculations-explained.md) | How the scores are derived. |
| [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) | Operations. **Pushing to this repo auto-deploys to Render — confirm before pushing.** |

---

## What this is


Two things live in one application, because they solve the same problem at
different scales.

**Learning.** Structured modules and roadmaps, a chat assistant with long-term
memory, practice interviews with scored feedback, and analysis of presentations
and speaking practice. It remembers what you have covered and builds on it.

**Codebase understanding.** Point it at a Git repository and it reads the code
directly — no model involved — then tells you what to read first, how the pieces
depend on each other, and where the structure is strained.

Everything runs on your own machine. It is designed to cost nothing to operate.

---

## Who this README is for

| If you are… | Start here |
|---|---|
| Curious what the project does | [What it can do](#what-it-can-do) |
| Wanting to run it | [Quick start](#quick-start) |
| Reading the code | [How it is built](#how-it-is-built) |
| Reviewing the engineering | [Design principles](#design-principles) · [decisions.md](docs/decisions.md) |

---

## What it can do

### Learning and practice

| | What it does |
|---|---|
| **Hub & Modules** | Curated learning modules with topics, resources and progress tracking. Content is plain YAML in [`content/`](content/) — version-controlled, editable by hand. |
| **Roadmaps** | Generates a dependency-ordered learning path. Nodes unlock as prerequisites complete. Built as a LangGraph workflow that generates, then validates and repairs its own output. |
| **Chat** | Streaming assistant that retrieves relevant past context before answering and saves what matters to long-term memory. |
| **Knowledge Vault** | Your notes, plus semantic search across everything you have done in the app. |
| **Interview Arena** | Adaptive interview that adjusts to your answers, then scores across five dimensions. |
| **Presentation Arena** | Upload a `.pptx` or `.pdf` and get per-slide feedback, speaker notes and an executive summary. |
| **Oratory & Communication** | Speaking practice with structured feedback on delivery. |
| **Missions, Review, Achievements** | Daily objectives, spaced review, and progress milestones. |

### Codebase agent

Register a repository by URL or local path. It clones, parses and analyses —
then answers four questions.

| Question | How it answers |
|---|---|
| **What should I read first?** | Ranks every file by how load-bearing it is, using import-graph centrality weighted by entry points, file role and change history. |
| **How does this fit together?** | An interactive dependency graph, a directory-level architecture map, a layer view by distance from entry points, and a dependency matrix. |
| **What groups belong together?** | Clusters files that depend on each other densely — three algorithms, including one over local embeddings. |
| **Where is the structure strained?** | A code-health read across three separate measures, with an explicit account of what it could not measure. |

**No code is sent anywhere.** The entire codebase pipeline — parsing, graph
building, ranking, clustering, health scoring — makes **zero calls to any
language model**, local or remote. This is enforced by a test that fails the
build if any model call happens during the pipeline, not by convention.

---

## Quick start

**You need:** [Python 3.12](https://www.python.org/downloads/), [Node.js 18+](https://nodejs.org/), and [Git](https://git-scm.com/).

### 1 · Get free API keys

Only the learning features need these. The codebase agent works without them.

| Provider | Where | Free tier |
|---|---|---|
| **Gemini** (primary) | [aistudio.google.com](https://aistudio.google.com) → *Get API key* | ~1,500 requests/day, 1M context, vision |
| **Groq** (fallback) | [console.groq.com](https://console.groq.com) → *API Keys* | Llama 3.3 70B, very fast |

No credit card required for either.

### 2 · Backend

```powershell
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1          # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
Copy-Item .env.example .env          # then edit: GEMINI_API_KEY, GROQ_API_KEY, SECRET_KEY
python run.py
```

Runs at **http://127.0.0.1:8000** · interactive API docs at `/docs`.

Database migrations apply automatically on startup — there is no separate
migration step. The first chat or vault call downloads a small embedding model
(~80 MB, once).

### 3 · Frontend

```powershell
cd frontend
npm install
npm run dev
```

Open **http://127.0.0.1:5173**. Vite proxies `/api` to the backend.

### 4 · Voice (optional)

The app is fully usable with text and push-to-talk transcription. For local
speech:

```powershell
cd backend
pip install -r requirements-voice.txt
```

Speech-to-text (faster-whisper) downloads on first use and runs fine on CPU.
For text-to-speech, drop a [Piper voice](https://huggingface.co/rhasspy/piper-voices)
into `backend/voices/` or set `PIPER_VOICE`.

---

## How it is built

```
backend/
  app/
    core/llm.py              Gemini → Groq router (one SDK, two base URLs)
    agents/                  commander (intent routing), roadmap_graph (LangGraph), prompts
    api/                     21 routers: auth, chat, roadmap, interview, repos, …
    services/
      vector_store.py        embedded Qdrant + FastEmbed — local, CPU-only
      seed.py                idempotent YAML → DB content loader
      codebase/              the repository analysis engine (below)
    db/models.py             SQLAlchemy models
  alembic/                   schema migrations, applied on startup
  tests/                     28 test modules

frontend/src/
  pages/                     Dashboard, Chat, Hub, Roadmap, Repos, RepoDetail, …
  components/                views, panels, the voice orb
  lib/                       pure logic modules, unit-tested without a DOM

content/                     modules and roadmaps as YAML — Git is the record
docs/                        contract, decision log, architecture, API, deployment
```

### Inside the codebase agent

`backend/app/services/codebase/` — 28 modules, each with one job.

| Stage | Modules | What happens |
|---|---|---|
| **Acquire** | `registry` · `git_ops` · `policy` | Clone or register a path. Credentials never touch a URL, an argv or a config file. |
| **Parse** | `discovery` · `extract_python` · `extract_js` · `languages` | tree-sitter over Python, JavaScript, TypeScript and TSX. Real parse trees, not regex. |
| **Resolve** | `resolve_imports` · `root_discovery` · `js_root_discovery` | Turn import statements into edges. Evidence-based root discovery for Python; nearest governing `tsconfig` for JS/TS. |
| **Rank** | `ranking` · `edge_weights` · `node_priors` · `entry_detection` | Weighted PageRank seeded from real entry points, plus two alternative scorers to compare against. |
| **Structure** | `graph_structure` · `ordering` · `dir_aggregation` · `subsystems` | Strongly connected components, layering, directory rollup, and three clustering algorithms. |
| **Health** | `ast_metrics` · `health_scoring` · `health_snapshots` | Complexity measurement, a pure scoring engine, and versioned snapshots. |

Two separations are load-bearing:

- `ast_metrics` **measures** and never scores. It returns `None` for an
  unsupported language, so a caller cannot mistake "not measured" for "fine".
- `health_scoring` is a **pure function** — no database, no filesystem, no
  parser. The same code produces the product's scores and its analysis reports,
  so the two cannot drift.

---

## Design principles

These are not aspirations. They are enforced, and where one was broken it is
recorded in [`docs/decisions.md`](docs/decisions.md).

### Absent data is never scored as good

If a signal cannot be measured — unsupported language, shallow clone with no
history, a file too small to judge — it is **excluded from the calculation
entirely**, from the numerator *and* the denominator. It is never scored zero
(which reads as "measured and terrible") and never given full marks (which
reads as "measured and fine").

### A number is withheld rather than caveated

When the dominant input to a score is missing, the score is not served at all.
A caveat beside a large confident number still leaves the number on screen
doing the persuading. A user interface cannot render a value it was never
given.

### Every score explains itself

Each result carries the markers that produced it — their weight, the thresholds
actually applied, and what each contributed. Stored *with* the result, because
thresholds are versioned and explaining an old score with today's numbers
explains it wrongly.

### Nothing claims to predict defects

There is no defect data in this system: no issue tracker, no bug-fix commit
classification, no failure history. So the terms *defect risk* and *bug
prediction* are forbidden in the code, the API and the interface. The change
hotspot measure is labelled **uncalibrated**, because it is.

### Predict, then measure

Before a measurement run, the expected result is written down. When the
prediction was wrong — and it has been — the gap gets investigated and
recorded rather than quietly discarded.

---

## Testing

| Suite | Count | Command |
|---|---|---|
| Backend | **777** | `cd backend && pytest -q` |
| Frontend | **119** | `cd frontend && npx vitest run` |
| Types | — | `cd frontend && npx tsc --noEmit` |

Tests run against real inputs: real repositories written to temporary
directories, real tree-sitter parses, a real database. The parser and
filesystem are not mocked — the failure mode being guarded against is
silently-empty extraction that looks like success.

Two guards worth naming:

- **Zero-model enforcement.** A test patches every model entry point to raise,
  then runs the whole codebase pipeline. Any call fails the build.
- **Migration parity.** Tests build their schema directly from the models,
  which makes migration drift structurally invisible to them. A separate test
  runs the real migration chain against a scratch database and refuses to run
  if its resolved URL is anything but that scratch path.

---

## Configuration

Everything is environment variables, read by `backend/app/core/config.py`.

| Variable | Default | Notes |
|---|---|---|
| `GEMINI_API_KEY` | — | Learning features only |
| `GROQ_API_KEY` | — | Fallback, and fast path for short internal calls |
| `SECRET_KEY` | `dev-secret-change-me` | **Change this** outside local development |
| `DATABASE_URL` | `sqlite:///./athena.db` | Point at Postgres in production |
| `REPO_CLONE_ROOT` | app-data dir | Where repositories are cloned |
| `RESOURCES_DIR` | app-data dir | Uploaded files |
| `QDRANT_PATH` | app-data dir | Local vector database |
| `ATHENA_GIT_PATH` | auto-detected | Explicit path to the git binary |
| `ATHENA_GIT_TOKEN_<HOST>` | — | Token for a private repo host, e.g. `ATHENA_GIT_TOKEN_GITHUB_COM` |

Runtime data deliberately lives **outside** the repository tree, in a per-OS
application-data directory. A clone cache nested inside a project you then
register and analyse would be ingested as part of that project's own source.
The application refuses to start if the resolved clone root ends up inside a
registered repository.

Private repository tokens are deliberately **per host**. A single generic token
variable would be offered to whatever host a submitted URL names, turning one
mistyped URL into a credential disclosure.

---

## Deployment

Full notes in [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md). The essentials for a
hosted instance:

```
Build:  pip install -r requirements.txt
Start:  uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Migrations run automatically at startup — no extra step.

**Attach a persistent disk.** A managed host's filesystem is ephemeral. Without
a disk mounted for `REPO_CLONE_ROOT`, `RESOURCES_DIR` and `QDRANT_PATH`, clones
and uploads vanish on every redeploy while the database rows describing them
survive.

<a id="cost"></a>
**Cost.** Both model providers have free tiers that cover normal use: one chat
turn is a short intent call plus one stream. The router exists so a provider
can be swapped in one file when a free tier changes. Do not put sensitive data
through a free tier — inputs may be used for training.

---

## Documentation

| Document | What is in it |
|---|---|
| [`docs/decisions.md`](docs/decisions.md) | Every non-obvious choice, why, and what it cost. Includes what turned out to be wrong. |
| [`docs/code-health-contract.md`](docs/code-health-contract.md) | The exact metric definition: markers, thresholds, weights, N/A rules, and every threshold change with its evidence. |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | System architecture and data flow. |
| [`docs/API.md`](docs/API.md) | Endpoint reference. |
| [`docs/codebase-agent-handoff.md`](docs/codebase-agent-handoff.md) | Deep implementation notes, including real bugs found and what they taught. |
| [`docs/external-validation-eslint.md`](docs/external-validation-eslint.md) | Validating the ranking against a third-party repository — including where it failed. |
| [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) · [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) | Operations. |

---

## Known limitations

Stated rather than buried.

- **Four languages** are parsed: Python, JavaScript, TypeScript, TSX. Anything
  else is reported as not applicable, never as clean.
- **Dynamic imports, reflection and runtime plugin loading are invisible** to
  static analysis. Files reachable only that way may be flagged as possibly
  unreachable — which is why that flag never affects a score.
- **The health thresholds are reasoned defaults**, not fitted to any outcome.
  They are labelled uncalibrated because calibration needs defect-labelled
  history this project does not have.
- **Architecture Health discriminates on large repositories, and the earlier
  claim that it does not was drawn from too small a sample.** The original
  finding — zero file-level import cycles across 599 files — was real for
  those repos, but 398 of the 599 were a stripped fixture, and Apache Superset
  since measured **828 of 6,516 files in import cycles**, the largest spanning
  604. Corrected 2026-08-12/17; see [decisions.md](docs/decisions.md) K3 and
  [the metric contract](docs/code-health-contract.md) §17.0.
- **A shallow clone carries no change history**, so anything derived from churn
  is reported as unavailable rather than computed from a constant.

---

<div align="center">

Built to be understood, not just to run.

</div>
