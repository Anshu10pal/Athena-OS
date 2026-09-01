# Phase 6 — Using the Code Graph as Context

**A guide for the team.** What we built, how it works, what it costs, what it
saves, what went wrong, and what is still open.

> **Provenance.** Unless a figure is marked otherwise, every number here was
> measured on `apache/superset` at commit **`a05a0999`** (6,584 files / 61,559
> import edges), with **tiktoken `cl100k_base`**. Figures marked *(at
> `e2bb33b1`)* predate a re-ingest on 2026-08-21 and are snapshot-specific —
> the ratios still hold, the absolute counts have moved. Last updated
> 2026-08-24. Backend suite at the time of writing: **1,180 passed / 1 skipped**.

---

## 1. The problem, in one paragraph

An agent asked to change a file needs to know what that file is connected to:
what it imports, what imports it, what breaks if its interface changes. Today
the agent finds that out by *searching* — grep for the module name, open the
hits, read them, follow what those files import, repeat. That works, and it is
expensive: the context window fills with file text that was read only to
discover a relationship. **We already computed every one of those relationships
at ingest time and stored them in a graph.** Phase 6 is about handing the agent
the answer instead of making it re-derive the answer by reading.

The sentence that ended up on the tin:

> **The graph is a targeting map for reads.** It does not save you the read. It
> tells you *which* files are worth reading.

---

## 2. What already existed before Phase 6

Phases A–K built the **atlas** — the thing Phase 6 reads. Nothing in Phase 6
changes it. For orientation:

| table | what it holds |
|---|---|
| `code_files` | one row per file: path, language, size, `fan_in`/`fan_out`, entry-point flags, subsystem ids, SCC (cycle) id |
| `code_imports` | one row per import statement: from-file, to-file (nullable), raw specifier, line number, resolved flag |
| `code_symbols` | functions/classes with signatures and line ranges |
| `code_file_ranks` | per-scorer rank and score (`legacy`, `rrf`, `weighted_pagerank`) |
| `code_subsystems` | clusters from three algorithms (modularity, louvain, hdbscan) with labels |

Ingest is deterministic, local, and **zero-LLM**: tree-sitter parses, imports
resolve by path lookup, ranks and clusters are graph algorithms. That matters
commercially — it means the whole thing can run on private client code inside
our own infrastructure with nothing leaving the network.

---

## 3. How a query actually works

### 3.1 The read boundary

Everything in Phase 6 reads through **one function**:

```python
read_repo_graph(db, repo_id, *, include_symbols=True) -> RepoGraphT
```

`backend/app/services/codebase/graph_read.py`

It returns the **whole** graph, typed, uncapped, with every file, every edge
(resolved *and* unresolved), cycles, clusters, and ranks. Three deliberate
choices in it are worth knowing:

- **Cluster membership travels as a LABEL, not a row id.** A subsystem id is
  meaningless outside the database that issued it.
- **Unresolved imports are kept**, with their raw specifier and line number. "This
  file imports something we could not map to a file" is a fact about the code.
- **A one-member SCC is normalised to `None`.** Every file is trivially its own
  strongly-connected component; reporting those would make the entire repo look
  cyclic — true of the datatype, false of the codebase.

It also **fails loudly on schema drift**: a declared `REQUIRED_COLUMNS` map is
checked before any read, so a renamed column produces an error naming the table,
the column, and the file to fix — not a silently-degraded graph.

### 3.2 The neighbourhood query

`backend/app/services/codebase/neighborhood.py`

```python
read_neighborhood(db, repo_id, path, *, second_hop=False,
                  max_enriched=25, budget_tokens=None, graph=None) -> dict
```

Given a target file **X**, it returns:

| section | contents |
|---|---|
| `file` | X's own metadata — rank, subsystem, `fan_in`/`fan_out`, entry-point, in-cycle |
| `imports` | what X depends on: resolved targets **plus** unresolved specifiers with line numbers |
| `importers` | what depends on X — the blast radius of changing its interface |
| `blast_radius` | counts of how many neighbours are inside X's subsystem vs. crossing into others |
| `second_hop` | optional, off by default, bounded — imports-of-imports and importers-of-importers |
| `snapshot` | the commit the answer was computed from |
| `budget` | whether a cap was applied, and what it shed |

**The traversal is not a search.** It is a single pass over the edge list
filtering on `from_path == X` and `to_path == X`, then a dictionary lookup for
each neighbour's metadata. No text matching, no file opening, no recursion.
The graph was built once at ingest; a query is a filter over it.

### 3.3 What the answer looks like

Real output, trimmed:

```jsonc
{
  "repo": "github.com/apache/superset",
  "snapshot": { "last_ingested_sha": "a05a0999…", "last_ingested_at": "2026-08-21T15:00:21" },
  "file": { "p": "superset/models/core.py", "rank": 6, "cluster": "superset/migrations/versions",
            "fan_in": 258, "fan_out": 22, "entry_point": false, "in_cycle": true },
  "imports":   { "total": 22, "enriched": 22, "files": [ … ],
                 "unresolved": [ { "spec": "flask_appbuilder", "line": 41 }, … ] },
  "importers": { "total": 258, "enriched": 25, "files": [ … 25 with metadata … ],
                 "additional_paths": [ … 233 bare paths … ], "truncated_metadata": true },
  "blast_radius": { "importers": { "same_subsystem": 244, "other_subsystems": 14, "unknown": 0 } },
  "budget": { "limit": 9000, "applied": false }
}
```

Two things to notice, because they are the whole design philosophy:

1. **`total` is always exact.** 258 means 258, even though only 25 carry full
   metadata.
2. **The remaining 233 appear as bare paths.** Nothing is hidden.

---

## 4. Where the token saving comes from

### 4.1 The benchmark

We used the same shape as Graphify's published benchmark so the number is
comparable to a known reference:

- **Naive cost** = the full text of the file **plus every file directly connected
  to it**, read in full. This is what an agent loads to understand the file's
  context by reading.
- **Graph cost** = the neighbourhood query's output for that file.
- **Ratio** = naive ÷ graph.

File selection was fixed **before** measuring, by connectivity from the graph: a
leaf (no connections), two mid-connected files at the median, and two hubs by
fan-in.

### 4.2 The results

| kind | file | connected files | naive (tokens) | graph (tokens) | ratio | saving |
|---|---|---:|---:|---:|---:|---:|
| leaf | `scripts/__init__.py` | 0 | 174 | 188 | **0.93×** | **−8%** |
| mid | `superset/commands/annotation_layer/annotation/create.py` | 6 | 7,754 | 489 | **15.9×** | 93.7% |
| mid | `superset/commands/chart/delete.py` | 10 | 30,206 | 561 | **53.8×** | 98.1% |
| hub | `superset/__init__.py` | 524 | 1,651,458 | 8,452 | **195.4×** | 99.5% |
| hub | `superset/utils/core.py` | 355 | 1,746,672 | 5,954 | **293.4×** | 99.7% |

**Pooled: 3,436,264 → 15,644 tokens = 219.7× (99.5% reduction).**

### 4.3 Read the distribution, not the pooled number

**The 0.93× floor is real and we report it deliberately.** On a file with no
connections, the graph costs *8% more* than simply reading the file. A benchmark
that showed only the 293× hub would be less credible, not more — the pooled
figure is dominated by two hubs, and anyone who checks will find the floor
themselves.

The honest summary for a stakeholder:

> On isolated files the graph is break-even or slightly worse. On the files
> where real work happens it saves 94–98%. On hub files it saves 99.5%. The
> pooled figure across a representative spread is 219.7×.

### 4.4 Why the ratio grows with connectivity

Naive cost scales with **the total size of the connected files** — 524 connected
files is 1.65 million tokens of source. Graph cost scales with **the number of
neighbours**, at roughly 14.5 tokens per bare path. One grows by kilobytes per
neighbour, the other by a dozen tokens.

### 4.5 The targeting value, in one number

`superset/models/core.py`'s neighbourhood costs **4,403 tokens** *(at `e2bb33b1`)*
and points at **22 files worth 141,525 tokens** to read.

It does not save you the 141,525. It tells you *which* 141,525 to spend out of a
6,584-file repository — and, just as importantly, that there are 258 files that
will be affected if you change the interface.

---

## 5. The road here — what we tried and rejected

This is the part most worth reading, because the obvious design is wrong.

### 5.1 Checkpoint 0 — the feasibility gate

A threshold was fixed **before** measuring: proceed only if the median saving was
≥5× **and** at least 2 question classes were impossible for grep.

Result: **median 34.3×** across 7 structural questions, spread 3.1×–3,113×, with
**2 grep-impossible classes** — subsystem membership and import cycles, both
computed graph properties that no text pattern can express. Gate passed.

**A first pass produced ratios up to 52,000× and was thrown away.** It compared
the graph against "read every candidate file", which is a strawman — a competent
agent greps first. Re-measured against grep, the number fell from 52,000× to
34.3×. The honest number is the one we kept.

The gate also produced a **corrected headline**: whole-graph-as-context is a
token **loss** on Superset — 962,330 tokens for the compact whole graph versus
560,768 to simply read the top-100 ranked files.

### 5.2 The size measurement — tokens track edges, not files

Compact whole-graph serialisation *(at `e2bb33b1`)*:

| repo | files | edges | full-fidelity | compact |
|---|---:|---:|---:|---:|
| Athena-OS | 280 | 2,265 | 253,046 | **31,315** |
| eslint | 1,447 | 2,304 | 482,876 | **73,953** |
| apache/superset | 6,523 | 60,873 | 5,011,882 | **962,330** |

eslint has **5× Athena-OS's files but only 2.4× its tokens**. Superset has 4.5×
eslint's files and **13× its tokens** — because its edges grew 26×. The crossover
where a whole graph stops being affordable sits around **1,500–2,000 files**.

### 5.3 The candidate comparison — and why bounded artifacts were retired

Baseline to beat: **560,768** tokens (Superset's top-100 files by `legacy` rank).

| candidate | tokens | vs baseline |
|---|---:|---|
| (a) top-100 files, all edges | 38,757 | **14.5× better** |
| (a) top-250 files, all edges | 109,833 | 5.1× better |
| (b) whole graph, resolved edges only | 929,193 | **1.66× worse** |
| (c) top-100 files, resolved only | 20,798 | **27.0× better** |
| (c) top-250 files, resolved only | 52,145 | 10.8× better |
| (d) five-question query bundle | 36,328 | 15.4× better |

The bounded artifacts (a) and (c) win on cost by 14–27×. **Then we asked them
the onboarding questions:**

| question | top-100 artifact answered | truth |
|---|---|---|
| What imports `models/core.py`? | **24** importers | 253 |
| What files are in a cycle? | **44** files | 832 |
| What is the largest subsystem? | `superset/migrations/versions`, **54 members** | same label, **1,287 members** |

**They do not fail loudly. They answer fluently, and wrong.** The subsystem case
is the sharpest: the *right label* with the *wrong magnitude*, and nothing in the
artifact distinguishes "this subsystem has 54 files" from "this artifact contains
54 of its files".

No budget fixes that — the error is the boundedness itself, not its size. And
(b), the one candidate that stays complete, costs more than reading the source.

**Conclusion: scoped-artifact mode is retired for large repos.** Whole-graph
artifacts remain right for small/mid repos (Athena-OS 42,936 tokens, eslint
79,027 — complete *and* cheap). Large repos get queries. That split is clean
architecture, not a compromise.

---

## 6. Design decisions that cost us something to learn

### 6.1 56% of Superset's import edges do not resolve

| repo | unresolved edges | share |
|---|---|---|
| apache/superset | 34,311 of 60,873 | **56.4%** |
| Athena-OS | 939 of 2,265 | 41.5% |
| eslint | 584 of 2,304 | 25.3% |

The pre-existing `ranking._build_graph` filters these out, so PageRank,
clustering, and three persistence modules all work from the resolved 44% **with
no signal that the rest exist**.

**This is an open question, not a settled one.** An unresolved edge has no target
file, so it cannot carry a PageRank contribution — excluding it may be *correct*
for the ranking consumers. But an agent asking "what does this file import" wants
to know about the import that did not resolve. So: the boundary carries them, and
whether each consumer uses them is a **per-consumer decision** deferred to the
migration checkpoint.

A candidate connection, recorded but **not established**: Superset's known 13.2%
layer-reachability ceiling was diagnosed as Flask dynamic-blueprint registration
producing no static edges. The 56% figure is *consistent* with that and worth
investigating — it is not proof of cause.

### 6.2 The hub bound — bound the metadata, never the paths

The spec said "rank-and-truncate the importers: return *412 importers, top 20 by
rank*". **Measurement withdrew it.** Listing *all 515* importer paths of the worst
hub costs **7,458 tokens — 1.3% of the baseline**. Paths are cheap; per-neighbour
metadata is what scales.

So `MAX_ENRICHED = 25` bounds *enrichment*, and a path is **never** dropped.
`enriched + additional_paths == total` on every hub, asserted by a test.

### 6.3 The budget cap — refuse rather than lie

Graphify's default query budget is 2,000 tokens. On Superset that **cannot hold a
hub**: `superset/__init__.py` needs 8,452 tokens for 524 importer paths, and after
shedding the second hop and every scrap of metadata it is still **5,806 tokens
over**.

The only way to reach 2,000 is to drop ~500 dependents. So the implementation
**refuses**: it sheds the second hop, then metadata, then stops and reports
`sufficiency_sacrificed: true` with an exact shortfall.

`DEFAULT_BUDGET_TOKENS = 9000` clears the worst measured hub with headroom, so the
cap is *met* for real files — flat and predictable for a demo — while the
refuse-don't-cut mechanism stays underneath for any future mega-hub.

Verified real costs, tiktoken: `models/core.py` 4,529 · `utils/core.py` 5,967 ·
`__init__.py` 8,465 · `chart/delete.py` 574. *(These four are checkpoint-4b
measurements and are not yet in `decisions.md` — 4b is uncommitted pending an
extension-level confirmation.)*

### 6.4 Caching — load once per repo

The MCP server loads a repo's graph once and reuses it:

```
1st query (cold, loads graph): 1.19s
2nd query, same repo (warm)  : 0.01s   →  79× faster
different repo (cold again)  : 0.12s
```

The honesty property: every answer is stamped with the SHA **of the graph it was
given**, so a cached answer reports the snapshot it actually came from. A
re-ingest mid-session does not silently change answers — it makes the stamp
visibly older than `git rev-parse HEAD`.

---

## 7. Challenges — the instrument was wrong more often than the code

This is recorded because it is the most transferable lesson in the phase. Nearly
every "bug" we found first turned out to be the measuring tool.

### 7.1 grep produced phantom failures three times

1. **Unescaped `.`** — an interpolated module name `superset.config` matched the
   `_` in `from superset_config import *`. Five sufficiency failures reported; all
   five were the regex.
2. **Loose `import superset\b`** — attributed `import superset.utils.database` to
   `superset/__init__.py`. The resolver was right; grep was wrong.
3. **Grep-adjudicating package `__init__.py`** — `from superset import config`
   imports `superset/config.py`, *not* the package. Six misses reported, all six
   the instrument's; one was a match inside a docstring.

Instances 1 and 2 were "fixed" by remembering not to do it again. That did not
survive one checkpoint. **The fix that held was structural**: a
`NOT_GREP_ADJUDICABLE` set in the script with the reason inline. Recorded as
contract **§17.33** — *the same instrument error three times belongs in the tool,
not in your memory.*

### 7.2 Installing a tool to test something changed the thing being tested

`pip install mcp` reported `Successfully installed` — and upgraded **starlette
0.46.2 → 1.6.0**, breaking **fastapi 0.115.12**. The full test suite was running
against that interpreter at the time, so its result was void.

Recovery: 13 packages uninstalled, starlette restored, `pip check` verified clean.
**Never install the `mcp` SDK into `backend/venv`** — use an isolated venv or write
MCP servers stdlib-only. Contract **§17.34**.

### 7.3 Windows defaults substituted silently, three ways

All three produced output that was **well-formed and wrong**, with nothing raised:

1. A bash heredoc **collapsed escaped backslashes** in Windows paths, producing
   invalid JSON that would have failed MCP registration silently.
2. SQLite returned a datetime as a **string** where PostgreSQL returns a
   `datetime` — one field, two shapes, decided by backend.
3. **stdio spawned as cp1252**, mangling every multi-byte character on the MCP
   wire. `U+2014` (bytes `e2 80 94`) came back as three separate characters, and
   the round trip *succeeded*.

Defense is structural: set UTF-8 explicitly at every boundary, and **test with a
non-ASCII payload** — ASCII survives cp1252 unharmed and hides the bug. Contract
**§17.35**.

### 7.4 A gate must exercise the variable that can be wrong

Two instances, both instructive:

- The MCP transport probe had two tools, `ping` and `echo`. **A `ping`-only gate
  would have passed clean** — it proves connectivity, not correctness. `echo` sent
  data in and compared what came back, and that is what caught the cp1252 bug.
- The graph MCP server passed every protocol-level test, then **failed on the
  first real call from the VSCode extension**: `no such table: repos`. Settings
  carry relative paths, and the extension spawns from a different working
  directory. **SQLite creates a missing database file rather than refusing**, so
  the server started cleanly and left a 0-byte `athena.db` behind. Our test could
  not catch it because it spawned with `cwd=backend` — *it fixed the exact
  variable that was broken.*

Fixed with `os.chdir(BACKEND_DIR)` before the app imports, plus a regression test
that spawns from a temp directory and asserts no stray database appears.

### 7.5 The UTF-8 canary was vacuous twice before it worked

Worth its own note because it happened *inside the test written to catch the
encoding bug*:

- Version 1 wrote the broken copy to a temp directory, where the server died on
  import — failing for a reason unrelated to encoding.
- Version 2 used `json.dumps` with its default `ensure_ascii=True`, which escapes
  non-ASCII to `\uXXXX` **before it reaches the stream**. The bytes on the wire
  were pure ASCII, so *neither arm could fail*. The real MCP client sends raw
  UTF-8; the test client had to as well.

**A canary that has not been observed failing proves nothing.**

---

## 8. What exists in code today

| file | lines | tests | purpose |
|---|---:|---:|---|
| `backend/app/services/codebase/graph_read.py` | 336 | 12 | the stable whole-graph read boundary |
| `backend/app/services/codebase/atlas_export.py` | 191 | 17 | compact artifact emitter + mode switch |
| `backend/app/services/codebase/neighborhood.py` | 317 | 23 | **the deliverable** — `read_neighborhood()` |
| `backend/mcp_graph_server.py` | 276 | 9 | MCP server exposing `neighborhood` over stdio |

**61 tests across the four**, of which 15 are load-bearing canaries — each one
observed FAILING on deliberately broken code before its green was trusted.

**Tuning constants**, all named and justified in code:

```python
WHOLE_GRAPH_MAX_FILES = 1500   # the measured crossover
MAX_ENRICHED          = 25     # neighbours carrying full metadata; paths are never cut
MAX_SECOND_HOP        = 200    # the one bounded part, and it reports its own truncation
DEFAULT_BUDGET_TOKENS = 9000   # clears the worst measured hub (8,452) with headroom
ARTIFACT_SCORER       = "legacy"
```

Everything reads through `read_repo_graph`. Tests enforce it: stub the boundary
and **no real data may survive**, plus a grep-level backstop against `db.execute`
and model imports.

---

## 9. Status and what is next

**Done:** checkpoint 0 (gate) · 1a (boundary) · 1b (emitter) · 2 (neighbourhood
query) · 3 (benchmark) · 4a (MCP transport gate) · **4b (the graph MCP server)**.

**Checkpoint 4b — CLOSED 2026-09-01, at both layers.** The server is built and
committed (`6ae89c8`), 9 tests green, stdlib-only, registered in `.mcp.json`.
Protocol level was proven first; the cwd bug is fixed and verified from the
directory that broke it. The **extension-level confirmation** then ran on the
Linux VM — a real `neighborhood` call through the MCP client, for
`superset/models/core.py` on `apache/superset` — and **every field matched the
protocol proof exactly**: 258 importers, 22 imports, 51 unresolved, 25 enriched
+ 233 additional paths (= 258, no path dropped), snapshot `a05a0999`, budget
9,000 with `applied: false`. The server's own log confirmed it resolved the
real 6,584-node graph rather than an empty database, and reported
`stdin=utf-8 stdout=utf-8`, so the §17.35 reconfigure holds on Linux too.

Both machines are now represented: the server was built on Windows and closed
on Linux, and the two agree.

**Next — checkpoint 5, the last piece of Phase 6:** the PreToolUse enforcement
hook, so the graph is consulted *before* a read rather than only when asked.
Without it the saving is theoretical: a tool nobody invokes saves nothing. One
design decision precedes the build — **nudge** (soft, overridable suggestion)
versus **strict** (blocks the first raw source read of a session and redirects
it to the graph). Strict demonstrates the mechanism provably; nudge never
breaks an existing workflow. Not defaulted into.

**Deferred, with reasons:**

- `path` and `explain` query primitives — additive over the same cached graph, cheap
- Migrating `_build_graph`'s five callers onto the boundary — its own checkpoint,
  opening with the per-consumer unresolved-edge question
- Onboarding-question queries and subsystem summaries — parked, not cut
- **Phase 7, multi-language expansion** (Go, Rust, Java, C#) — deliberately after
  the demo lands. *Proven-then-expanded*: adding a language is "wire the grammar's
  node types to node/edge extraction", not "write a parser"

**Open question:** whether Superset's 56% unresolved edges explain part of its
reachability ceiling. An investigation to run, not a finding made.

**A partial data point on that question, from ONE file (2026-09-01).** The 4b
extension-layer confirmation queried `superset/models/core.py`, which reports
**51 unresolved imports**. Inspected individually, all 51 are **third-party or
stdlib** — `sqlalchemy` ×10 on one line, `typing` ×5, `contextlib` ×4,
`flask` ×3, plus `numpy`, `pandas`, `sshtunnel`, `flask_appbuilder`,
`marshmallow`, `logging`, `datetime` and friends. **On this file, unresolved
means external**: no first-party Superset structure is being silently dropped,
and the resolver is behaving correctly rather than failing quietly.

**What this does and does not establish.** It is **one file out of 6,584**, and
a deliberately atypical one — a hub with a heavy third-party surface. It is not
a repo-level answer and must not be quoted as one. What it does is change the
*shape* of the question worth asking: from "how much of Superset's real
internal structure is invisible to the graph" toward "**unresolved-means-
external held here — is that repo-wide, or a property of this file?**" Those
need different investigations, and the second is much cheaper to run: classify
the unresolved specifiers repo-wide against a known-external list rather than
re-deriving reachability. **Worth doing later; blocking nothing.**

---

## 10. Honest positioning

**The mechanism is not novel.** Bounded-subgraph queries in place of file reads is
what Graphify (108k stars) does, and it is proven at scale. Nothing here should be
pitched as an invention.

**Three things are genuinely ours:**

1. **A ranking layer** — PageRank / RRF / weighted-pagerank, against their raw
   degree centrality, so a subgraph can be *ordered by what matters* rather than
   returned whole.
2. **Validation rigor** — the §17 contract, 39 recorded failure modes, denominators
   that travel with rates, canaries observed failing before green is trusted. No
   equivalent is published by the alternatives.
3. **Fully-local, zero-LLM operation** — which is what makes it usable on private
   client code behind a corporate proxy.

> **The claim: we do the proven thing, on private client code, backed by analysis
> rigor standalone tools lack.** Not "we invented it", and not "we are broader than
> Graphify" — we are neither, and a pitch that says so loses the moment anyone
> checks.

---

## Further reading

| document | when |
|---|---|
| [`decisions.md`](decisions.md) | the full phase history, every decision and what was rejected |
| [`code-health-contract.md`](code-health-contract.md) | the §17 methodology contract — how work is done here |
| [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md) | environment constraints, in the order they bite |
| [`codebase-agent-handoff.md`](codebase-agent-handoff.md) | atlas implementation notes (pre-Phase-6) |
