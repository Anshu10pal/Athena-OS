# External validation: `eslint/eslint`, against the maintainers' own architecture doc

## Why this exists, and why it isn't `docs/reading-list-answer-key.md`

An answer key derived from this project's own import-graph output — even
one written by hand, after reading the files — cannot validate the claim
that the ranking is right, because every number that would go into writing
it (fan_in, PageRank, which files "obviously" matter) comes from the same
graph the ranking itself is built on. A first attempt at that document was
written and deleted for exactly this reason: it concluded the three
scorers' `models.py` #2/#9/#1 split was "correct under all three"
immediately after generating that exact split, which is the ranking
describing itself back, not an independent check.

This is the replacement: ground truth from a source that predates this
project, wasn't produced by this tool, and wasn't written by anyone
involved in building it — `eslint/eslint`'s own contributor documentation,
describing its own architecture in its own maintainers' words.

## Setup, and two caveats that qualify every number below

- **Repo**: `eslint/eslint`, `main` branch, shallow + sparse clone
  (`git clone --depth 1 --filter=blob:none --sparse`, `sparse-checkout set
  bin lib`) — 393 JS files under `lib/`, registered with
  `source_root=lib`. Full ingest/rank output: repo id 3 in this project's
  dev database.
- **Caveat 1 — this is a slice, not the whole project.** 393 files under
  `bin/`+`lib/` only. `tests/`, `docs/`, `packages/`, `tools/` — the rest
  of the real `eslint/eslint` repo — were never cloned. Any claim below is
  a claim about this slice, not about "ESLint."
- **Caveat 2 — `--depth 1` degrades legacy's history signals.** `git log`
  sees exactly one commit, so `commit_count`/`distinct_authors`/recency
  carry no real variance. This is a graph-topology test of `legacy`, not a
  full test of every signal it uses in production.
- **Ground truth**: `docs/external-validation-eslint-answer-key.md`,
  transcribed from `docs/src/contribute/architecture/index.md` in
  `eslint/eslint` (fetched via the GitHub contents API, not this
  project's tooling). 30 files across 6 of the doc's 8 named "key parts"
  — `bin/eslint.js` is out of ingest scope (`source_root` excludes it) and
  `lib/rules/` (294 files, one bullet, no internal ordering given) is
  deliberately not forced into a ranked list.

## Bug found and fixed #1: `validate_ranking.py` mixed scorers together

`get_tool_ranking` ordered `CodeFileRank` rows for a repo without
filtering by `scorer`. Invisible on every repo this project had touched
before now (each had only one scorer's rows). The moment a second
scorer's rows exist for the same repo — the normal case, since
`legacy`/`weighted_pagerank`/`rrf` coexist by design — the query silently
interleaves three incompatible scales (legacy up to ~0.75,
weighted_pagerank ~0.3, rrf ~0.08 on real repos), and whichever scorer has
the largest raw numbers dominates every "top" result regardless of which
was asked for. Fixed: `get_tool_ranking` and the script's CLI now take a
required `--scorer` argument. Three regression tests added
(`tests/test_validate_ranking.py::TestGetToolRanking`).

## Bug found and fixed #2: entry detection searched the wrong directory

Auto-seeding `weighted_pagerank` on this repo initially raised — entry
detection found nothing at all. The premise worth checking first: **E4 has
no shebang-reading logic anywhere** (verified — no `shebang`/`#!` handling
exists in `entry_detection.py`). `bin/eslint.js` does have a shebang, but
it was never a candidate for a different, more basic reason: it isn't an
ingested `CodeFile` at all (`source_root=lib` scopes ingestion below it),
so no detection mechanism — shebang or otherwise — ever gets a chance to
look at it.

`package.json`'s `bin` field pointing at `bin/eslint.js` is real and would
be read correctly, but for the same reason: even matched, it names a file
outside the ingested subtree, so it correctly cannot resolve to any
`CodeFile` row. That part is not fixable without ingesting `bin/` too —
it's a real scope limit of this run, not a bug.

The actual, verified, fixable bug: `package.json` **also** declares
`"main": "./lib/api.js"` — a target *inside* the ingested subtree — and
detection still missed it. Root cause: `_detect_entries` (ranking.py)
passed `_repo_root(repo)` (i.e. `local_path/source_root` = the `lib/`
directory) as the search root for `package.json`/`Dockerfile`/etc.
Authoritative config conventionally lives at the true repository root,
not inside a scoped `source_root` — so the search for it never looked
where `package.json` actually was, regardless of what it declared.
Confirmed directly:

```
find_js_authoritative_entry_paths(repo_root=".../lib")   -> []
find_js_authoritative_entry_paths(repo_root=".../")      -> ['.../lib/api.js', '.../bin/eslint.js']
```

Every repo this project had registered before now used `source_root=None`
(the whole repo ingested), where `_repo_root(repo) == repo.local_path` —
the two roots coincide, so this was a latent bug with zero prior chance to
surface. It surfaces the instant `source_root` scopes ingestion to a
subdirectory while authoritative config sits above it.

**Fix**: `entry_detection.detect_entry_points` gained a
`config_search_root` parameter, searched for
Dockerfile/Procfile/render.yaml/pyproject.toml/index.html/package.json/
vite.config independently of `repo_root` (which still governs how
`CodeFile.path` is resolved and matched). `ranking._detect_entries` now
passes `config_search_root=Path(repo.local_path)` — always the true root
— while `repo_root` stays source_root-scoped. A resolved candidate still
has to match a real ingested file to count, so widening the search cannot
manufacture a false positive for a target outside the ingested subtree
(verified by a dedicated test: `package.json`'s `bin` pointing outside
`source_root` correctly still detects nothing). Six regression tests
added across `test_entry_detection.py` and `test_ranking.py`; full suite
at 416 passed.

**Effect on this run**: `api.js` is now correctly auto-detected as an
authoritative entry point and `weighted_pagerank` auto-derives a valid
single-file seed (`['api.js']`) with no explicit override needed — the
scorer now runs through its normal, unmodified path, same as `legacy` and
`rrf`, not a special-cased manual seed. `cli.js` is still not detected:
its only real edge is `bin/eslint.js`'s `require("../lib/cli")`, and
`bin/eslint.js` itself remains outside the ingested subtree — a scope
limit of this experiment, not a remaining detection bug.

## Results, with the fix live

| Scorer | Overlap@20 | Overlap@10 | Spearman (intersection) | Verdict |
|---|---|---|---|---|
| `legacy` | 3/20 | 1/10 | 1.000 (n=3 — not meaningful) | **NO-GO** |
| `weighted_pagerank` (auto-derived seed, `['api.js']`) | 3/20 | 1/10 | 0.500 (n=3 — not meaningful) | **NO-GO** |
| `rrf` | 2/20 | 0/10 | 1.000 (n=2 — not meaningful) | **NO-GO** |

All three still fail the project's own GO/NO-GO threshold (Overlap@20 ≥
12). The Spearman numbers are not evidence of anything at n=2–3 and are
reported only so they aren't mistaken for a positive result at a glance.
This table is the `source_root=lib`-scoped run; "Round 2" below re-runs
after fixing a real scoping bug in the test harness itself and reports
both numbers side by side.

## The diagnostic that actually matters: where did the 30 files land?

Overlap@20 is a hard cutoff and hides the shape of the miss. Full rank
(of 393) for every one of the 30 doc-named files, under each scorer:

| Path | legacy | wpr | rrf |
|---|---:|---:|---:|
| api.js | 3 | 1 | 45 |
| cli.js | 383 | 378 | 383 |
| cli-engine/formatters/html.js | 379 | 374 | 379 |
| cli-engine/formatters/json-with-metadata.js | 380 | 375 | 380 |
| cli-engine/formatters/json.js | 381 | 376 | 381 |
| cli-engine/formatters/stylish.js | 382 | 377 | 382 |
| cli-engine/hash.js | 43 | 57 | 41 |
| cli-engine/lint-result-cache.js | 66 | 59 | 66 |
| linter/apply-disable-directives.js | 77 | 46 | 77 |
| linter/code-path-analysis/code-path-analyzer.js | 53 | 17 | 53 |
| linter/code-path-analysis/code-path-segment.js | 17 | 45 | 15 |
| linter/code-path-analysis/code-path-state.js | 51 | 60 | 51 |
| linter/code-path-analysis/code-path.js | 65 | 55 | 65 |
| linter/code-path-analysis/debug-helpers.js | 20 | 40 | 18 |
| linter/code-path-analysis/fork-context.js | 49 | 69 | 49 |
| linter/code-path-analysis/id-generator.js | 42 | 41 | 40 |
| linter/esquery.js | 47 | 58 | 47 |
| linter/file-context.js | 78 | 47 | 78 |
| linter/file-report.js | 79 | 48 | 79 |
| linter/index.js | 28 | 3 | 32 |
| linter/interpolate.js | 44 | 31 | 42 |
| linter/linter.js | 30 | 9 | 23 |
| linter/rule-fixer.js | 54 | 61 | 54 |
| linter/timing.js | 27 | 19 | 31 |
| linter/vfile.js | 35 | 39 | 34 |
| rule-tester/index.js | 64 | 5 | 64 |
| rule-tester/rule-tester.js | 46 | 7 | 46 |
| linter/source-code-fixer.js | 41 | 8 | 39 |
| linter/source-code-traverser.js | 80 | 49 | 80 |
| linter/source-code-visitor.js | 81 | 50 | 81 |

| | mean | median | min | max |
|---|---:|---:|---:|---:|
| legacy | 104.2 | 53 | 3 | 383 |
| weighted_pagerank | 93.5 | 48 | 1 | 378 |
| rrf | 105.2 | 53 | 15 | 383 |

**The mean is misleading here; the median is the real number.** 25 of the
30 files cluster between rank 3 and rank 81 out of 393 — the top ~21% of
the corpus, median ~48–53 (top ~13%) across all three scorers. That is a
**calibration** result, not a validity one: a reading list cut at top-80
or top-100 instead of a strict top-20 would show a dramatically different
— and dramatically more favorable — overlap than the headline Overlap@20
number suggests. The 20-file cutoff wasn't chosen for this repo; it's the
project's existing default, and it happens to sit right at the edge of
where this cluster starts, not past it.

The mean is dragged from ~50 to ~95–105 by exactly **5 severe outliers**,
all clustered at rank 374–383 (dead last, essentially tied with the
corpus's least-connected leaves): `cli.js` and all four
`cli-engine/formatters/*.js` files. Both outlier groups have a specific,
verified, non-mysterious cause, not "the ranking is bad here":

- **`cli.js`** has exactly one real importer anywhere in the true
  `eslint/eslint` source — `bin/eslint.js`'s `require("../lib/cli")`,
  confirmed by direct inspection. `bin/` is outside this run's
  `source_root=lib` scope, so that edge was never a candidate for
  resolution; `cli.js`'s near-zero fan_in here is an artifact of this
  experiment's ingest scope, not evidence about how the tool would rank
  it if `bin/` had been included.
- **The four `cli-engine/formatters/*.js` files** are loaded via
  `formatter = (await import(pathToFileURL(formatterPath))).default`
  in `lib/eslint/eslint.js`, with `formatterPath` built at runtime from a
  string (`path.resolve(..., "formatters", normalizedFormatName)`) —
  confirmed by direct inspection of `loadFormatter()`. This is a dynamic
  `import()` with a computed path, exactly the case this project's own
  `ingest.py` `BLIND_SPOTS` list already names ("Dynamic import(...) is
  never resolved, even with a literal string argument") — not a new gap,
  a previously-documented one, now observed firing on real external code
  exactly as predicted. No static import graph, from any tool, would find
  these edges without either executing the code or special-casing this
  loader pattern by name.

Net read: this is closer to a calibration problem than a validity
problem, with two explained, scope-bounded outlier clusters pulling the
mean far from where the median actually sits — but "closer to calibration"
is not "passing." 25-of-30 landing top-21% still isn't top-20, and RRF in
particular shows no improvement over `legacy` despite matching it almost
exactly rank-for-rank (median 53 both) — the two remain the closely
correlated pair this project's own internal comparisons already found.

## Why: what the tool measures vs. what the doc describes

The doc's "key parts" are named by **architectural role**. Once the two
explained outlier clusters are set aside, the tool's ranking puts most of
the remaining named files in a tight upper band — but the very top slots
in every scorer still go to **heavily-imported utility modules**
(`rules/utils/ast-utils.js`, fan_in 192 — the single most-imported file in
the corpus — `shared/ast-utils.js`, `shared/string-utils.js`,
`languages/js/source-code/token-store/*`), none of which the architecture
doc names at all. Not because they're unimportant — fan_in 192 is real
and load-bearing — but because the doc describes *subsystems*, and a
shared helper nearly every rule imports is not a subsystem, it's plumbing
every subsystem shares. Import-graph centrality and a maintainer's
architectural narrative are related but genuinely different axes; this
run's median-rank clustering shows they're closer than the raw Overlap@20
number implied, not that they're the same thing.

One data point worth stating plainly: none of the three scorers let the
294 individual files under `lib/rules/` (75% of the ingested corpus)
flood the top 20 — `legacy`/`rrf` place 4/20 there (below its 75% share),
`weighted_pagerank` places 0/20. Whatever else is true, "swamped by the
largest directory by file count" is not among the ways this failed.

## Round 2: a bug class, a harness fix, and testing the layer hypothesis directly

Four follow-ups, run before touching section 6.

### The shebang claim was wrong, and the check that caught it

The premise "E4 was specifically built to read shebangs" was asserted, not
verified, and it was false — `grep`-ing the whole backend for
`shebang`/`#!` turns up nothing; E4 authoritative detection only ever
reads `package.json`'s `main`/`module`/`bin` fields, `index.html`,
`vite.config.*`, and (Python) `Dockerfile`/`Procfile`/`render.yaml`/
`pyproject.toml`. The actual bug — config search scoped to `source_root`
instead of the true repo root — was real and is fixed (see above). Stated
here because the correction matters as much as the fix: a claim about
what a tool does should be checked against the tool, not asserted from
what would be reasonable for it to do.

### Bug class, confirmed: three more functions share the same defect

`find_marker_candidate_roots` (`root_discovery.py`), `find_ts_configs`,
and `find_package_json_workspace_dirs` (`js_root_discovery.py`) are all
called from `ingest.py` with `root = _repo_root(repo)` — the same
`source_root`-scoped path that caused entry detection's miss. Confirmed
by reading the call sites, not assumed from the shared "search upward for
a config file" shape.

**This is a harder fix than entry detection's, not merely a repeat of
it.** Entry detection's fix worked because the search root and the
file-matching root are independent parameters — widening the search
can't produce a false match, since a resolved candidate still has to hit
a real ingested `CodeFile.path`. These three functions don't have that
separation: their *return values* — candidate root strings, tsconfig
`dir` values, workspace directory paths — are used directly, downstream,
as paths *relative to `source_root`* (passed straight into
`resolve_python_import(..., roots=[candidate_root])`, or compared against
`from_file.path` in `config_for_file`/`workspace_of`). Pointing their
search at `repo.local_path` instead would return paths in the wrong
coordinate space entirely — a marker file one level above `source_root`
doesn't have a well-defined "root string relative to `source_root`"
unless it's re-derived (and discarded outright if it names something
outside `source_root`'s subtree, the same way `bin/eslint.js` is
correctly outside this run's ingested scope regardless of the entry
detection fix).

Not fixed here — a real, scoped follow-up, tracked but not rushed under
the same time pressure that would have made the answer key's mistake
tempting a second time. It doesn't change any number reported for
`eslint/eslint`'s `lib/`: this repo has zero Python files (the Python
marker scan never runs) and no `tsconfig.json`/workspace declarations
inside `lib/` that matter to this comparison.

### The re-scoped run: `cli.js` was a harness bug, not a tool finding

`cli.js`'s only real importer, confirmed by inspection, is
`bin/eslint.js`'s `require("../lib/cli")` — and `bin/` was present on disk
(sparse-checked-out alongside `lib/`) but excluded from ingestion by
`source_root=lib`. That's a scope choice made when setting up this test,
not evidence about the tool. Re-registered with `source_root=None`
(covering `bin/`+`lib/`+the handful of top-level config files already in
the sparse checkout, 398 files total) and reran ingest + all three
scorers on the same repo id. With `config_search_root` now fixed,
`bin/eslint.js` is also correctly auto-detected as an authoritative entry
(`package.json`'s `"bin"` field, now in scope) — `weighted_pagerank` seeds
from `['bin/eslint.js', 'lib/api.js']` with no manual override, on its
normal unmodified path.

| Path | Original (source_root=lib, 393 files) | Rescoped (source_root=None, 398 files) |
|---|---:|---:|
| `cli.js` — legacy | 383 / 393 | 49 / 398 |
| `cli.js` — weighted_pagerank | 378 / 393 | 3 / 398 |
| `cli.js` — rrf | 383 / 393 | 49 / 398 |

The two columns are on slightly different denominators — 393 files vs.
398 (the extra 5 are `bin/eslint.js` plus four top-level config files
that happened to be present in the sparse checkout, `cypress.config.js`/
`eslint.config.js`/`Makefile.js`/`webpack.config.js`) — a 1.3% difference
that doesn't materially change a percentile this large, but is worth
stating rather than implying an apples-to-apples comparison that isn't
quite exact.

Exactly as predicted: fixing the harness moved `cli.js` from dead-last to
the same top-15%–ish band the other doc-named files already occupy. One
of the five outliers is now explained away as a test-setup artifact, not
a tool limitation.

`cli.js` is also, after the fix, the single sharpest scorer disagreement
found anywhere in this exercise: `weighted_pagerank` ranks it **3rd**;
`legacy` and `rrf` both rank it **49th** — a ~16× spread on one file,
larger than any other gap measured. The mechanism is exactly the
"different questions" thesis, concretely: `cli.js` has real fan_in of
only 1 (`bin/eslint.js`'s one `require`), so pure import-count centrality
(`legacy`, and `rrf`'s fan_in-ranked term) has almost nothing to reward
it with. `weighted_pagerank` doesn't count imports, it counts *proximity
to the seed* — `cli.js` sits at BFS layer 1, one hop from `bin/eslint.js`,
and personalized PageRank hands a one-hop neighbor of the seed a large
share of propagated mass regardless of how many other files import it.
Both numbers are correct answers to their own question; a file can be
simultaneously "barely depended on" and "extremely close to where
execution starts," and this is what that looks like as a number.

The other four doc-named outliers (`cli-engine/formatters/*.js`) do not
move — rank 383–388 of 398, unchanged — and per `compute_layers` they are
now confirmed **structurally unreachable** (`layer=None`) from the entry
set, not merely low-fan-in: no edge into them exists anywhere in the
resolved graph, because none is ever created by a runtime-computed
`import()` path. Full rank/summary table, rescoped run:

| | mean | median | min | max |
|---|---:|---:|---:|---:|
| legacy | 95.9 | 53 | 4 | 387 |
| weighted_pagerank | 86.4 | 53 | 2 | 386 |
| rrf | 96.5 | 53 | 17 | 388 |

Medians are essentially unchanged from the original run (53 vs. 48–53) —
expected, since 25 of 30 files were already in the shallow cluster; only
the outlier `cli.js` moved, and it moved from the tail into the same
cluster, which barely shifts a median already computed over 30 points.

Overlap@20/@10/Spearman, re-measured via `scripts/validate_ranking.py`
against `docs/external-validation-eslint-answer-key-rescoped.md` (same 30
files, `lib/`-prefixed to match the rescoped run's paths — a companion
file, not a re-transcription, since the underlying ground truth is
unchanged):

| Scorer | Overlap@20 (398 files) | Overlap@10 | Spearman (intersection) | Verdict |
|---|---:|---:|---|---|
| `legacy` | 2/20 | 1/10 | 1.000 (n=2 — not meaningful) | **NO-GO** |
| `weighted_pagerank` (auto seed, `['bin/eslint.js', 'lib/api.js']`) | 3/20 | 2/10 | 1.000 (n=3 — not meaningful) | **NO-GO** |
| `rrf` | 2/20 | 0/10 | 1.000 (n=2 — not meaningful) | **NO-GO** |

> **Correction, 2026-08-12 — the per-scorer ordering in this table was never
> meaningful, and earlier reporting treated it as though it were.**
>
> These are counts out of **20**. The gap between `weighted_pagerank` at 3/20
> and the other two at 2/20 is **one component**. At that denominator a single
> file entering or leaving a top-20 list moves a scorer's number, and §373–383
> below documents exactly that happening in the opposite direction — `legacy`
> went 3/20 → 2/20 on a single-item swap between two runs where nothing about
> `legacy` changed.
>
> The finding of this validation was, throughout, **"all three scorers fail"**
> — 2 and 3 against a threshold of 12. It was never "weighted PageRank does
> marginally better." Both this document and subsequent summaries of it have at
> points quoted the numbers as `3/20 vs 2/20` in a way that implies a ranking
> the evidence cannot support. The Spearman column already carries
> "not meaningful" for n=2 and n=3; the Overlap@20 column needed the same
> caveat and did not have it.
>
> The general rule is now in the metric contract, §17.5c: **report the
> denominator alongside the rate, and treat a difference smaller than the
> resolution of the population as no difference.** Derived from the clustering
> agreement statistic, where 100% across 4 clusters was similarly read as
> confirmation when it was closer to a null result — the same error in a
> different measurement.
>
> Nothing about the NO-GO conclusion changes. What changes is that the scorers
> are **indistinguishable on this evidence**, and any future comparison between
> them needs a population large enough to separate them.

`legacy` moved 3/20 → 2/20 (a single-item swap, not a meaningful change
at n=20). `weighted_pagerank`'s count is unchanged at 3/20 despite
`cli.js`'s dramatic rank improvement, but not because nothing happened:
`cli.js` (rank 378 → 3) did enter the top 20, and in doing so pushed
`linter/code-path-analysis/code-path-analyzer.js` — itself one of the 30
doc-named files, previously rank 17 — down to rank 33, out of the top 20.
One doc-named file swapped for another, netting zero change in the
Overlap@20 count while the actual composition of the top 20 changed. The
full rank table above is the more informative view of what moved;
Overlap@20 alone would make this look like nothing happened.

**On plugin-style dynamic loading**: worth stating as a category, not an
edge case. Any extensible tool — a linter with pluggable output
formatters, a build tool with pluggable loaders, a framework with
pluggable adapters — tends to load exactly this kind of module by a
runtime-computed name. Static import-graph analysis has a structural,
not incidental, blind spot for this whole class of software, independent
of how good root/entry/alias discovery gets. This project's `BLIND_SPOTS`
list already named the general case; this is it firing on a real,
recognizable instance of the pattern it was written to anticipate.

### The layer hypothesis, tested directly rather than eyeballed

Hypothesis as stated: architectural components cluster at low BFS layers
from the entry points; load-bearing utilities sit at high fan-in but
*deep* layers. If true, layer is a selection signal, not merely an
ordering one.

`compute_layers` from the rescoped entry set (`bin/eslint.js`, `lib/api.js`)
against the 30 doc-named files (excluding the 4 structurally-unreachable
formatters, n=26):

    layer 0: 1   layer 1: 3   layer 2: 4   layer 3: 10   layer 4: 6   layer 5: 1   layer 6: 1

69% (18/26) sit at layer ≤3; 31% (8/26, mostly the `code-path-analysis/`
files) sit at layer 4+. A real skew toward shallow, not a clean cutoff.

Each scorer's own top-20, by layer:

| Scorer | layer ≤3 | layer 4+ |
|---|---:|---:|
| `legacy` | 11/20 (55%) | 9/20 (45%) |
| `weighted_pagerank` | 20/20 (100%) | 0/20 |
| `rrf` | 9/20 (45%) | 11/20 (55%) |

`weighted_pagerank`'s top-20 is *already* entirely shallow — expected,
since personalized PageRank's damping term decays with distance from the
seed by construction; it doesn't need a layer filter grafted on, it's
already doing the equivalent continuously. `legacy`/`rrf` are much more
spread, since raw fan_in/PageRank-on-the-unweighted-graph has no notion
of distance from any particular entry point at all.

**The direct test, not just the histogram**: restrict each scorer's
ranked list to files at or below a layer cutoff, THEN take the top 20 of
what's left, and re-measure Overlap@20 against the doc key.

| Scorer | Baseline Overlap@20 | layer≤3-restricted | layer≤2-restricted |
|---|---:|---:|---:|
| `legacy` | 2/20 | 2/20 | 3/20 |
| `rrf` | 2/20 | **0/20** | 3/20 |
| `weighted_pagerank` | 3/20 | 3/20 (no-op, already 100% shallow) | 3/20 |

**This does not support the hypothesis as a fix.** A hard layer cutoff
before selection produces at best a +1 nudge (`legacy`/`rrf` at layer≤2)
and actively makes `rrf` worse at layer≤3 — restricting to shallow files
and re-ranking by RRF's fused rank surfaces different, still-undoc'd
shallow utility-adjacent files, not the doc's named coordinators. None of
the three configurations gets remotely close to the 12/20 GO threshold.
`weighted_pagerank`'s built-in, continuous version of exactly this idea
(distance-decayed score, no hard cutoff needed) does measurably better
than `legacy`/`rrf` on median rank, but still only reaches 3/20 at the
strict cutoff.

**Conclusion, stated as the hypothesis's own criterion requires**: layer
and doc-named importance are correlated in a real but loose, partial way
— not the tight mechanism ("doc files shallow, top-20 deep, filter fixes
it") the hypothesis proposed. Per the stated rule for this exercise, this
is the stronger finding, not a weaker one: it means graph centrality and
the maintainers' architectural narrative are not reconcilable by
reweighting selection toward proximity — they are answering different
questions even after distance-from-entry is accounted for, and a reading
list that wants to answer *both* "what does this codebase most depend
on" and "what would a maintainer call architecturally central" needs both
as genuinely separate tracks, not one scorer tuned to approximate the
other. No selection mechanism was changed as a result of this test — the
result argues against making that change, not for a version of it that
wasn't tried.

## What this changes

- The `models.py` #2/#9/#1 argument from the deleted document — "these are
  different questions, not a bug" — is not overturned, but it's now doing
  less work than it was asked to do: three scorers agreeing with each
  other internally is a different claim from any of them matching an
  external description of importance, and at the strict top-20 cutoff,
  none of them do on this repo. At a wider cutoff the picture is
  meaningfully better, per the median-rank distribution above.
- **The layer hypothesis was tested directly and did not hold up as a
  fix.** A hard BFS-layer cutoff before selection gives at best a +1 on
  Overlap@20 and actively regresses `rrf` at one cutoff — the honest
  reading is that graph centrality and the doc's architectural narrative
  are different questions even after distance-from-entry is controlled
  for, not that one is a filtered version of the other. No selection
  mechanism was changed on the strength of this test, by design: the
  brief for this exercise was explicit that changing the model needs a
  stated hypothesis and a test that supports it, not tuning until a
  number clears a threshold.
- Three real, scoped bugs came directly out of running this for real
  rather than reasoning about it: `validate_ranking.py`'s scorer-mixing,
  entry detection's config search root (both fixed, 416 tests passing),
  and the same config-search-root defect confirmed present in
  `find_marker_candidate_roots`/`find_ts_configs`/
  `find_package_json_workspace_dirs` (confirmed, not yet fixed — the
  correct fix needs candidate paths re-expressed relative to
  `source_root` rather than a simple search-root swap, a real follow-up
  rather than a rushed one).
- `cli.js`'s original near-last rank was a harness bug, not a tool
  finding — confirmed by re-scoping and re-running: fixing the ingestion
  scope alone moved it from rank 378–383 of 393 to rank 3–49 of 398. One
  of five outliers fully explained and closed.
- The four `formatters/*.js` files remain unranked and unreachable
  (`layer=None`) under any scope — confirmed structural, not a fan_in
  artifact, and representative of a category (plugin-style dynamic
  loading in extensible tools) rather than an edge case specific to
  ESLint.

## Round 3: does subsystem clustering (Phase I) do better than file ranking did?

Phase I built community detection (modularity + Louvain) over the same
resolved import graph, directly motivated by this file's own §"Why: what
the tool measures vs. what the doc describes" — the hypothesis that
import-centrality ranking and the doc's architectural narrative are
answering *different questions*, and that clustering (which groups files,
rather than ranking them) is structurally closer to what the doc
describes. This round tests that hypothesis against the same ground
truth, not a new one.

### Prediction, written down before anything was computed

The existing 30-file answer key has no per-component grouping preserved,
so it was regrouped by directory prefix (the grouping already implicit in
each path — `api.js`/`cli.js` are single-file "components" excluded from
recall; `cli-engine` 6 files, `linter` 20 files — including three
`source-code-*.js` files that live under `linter/`, not a separate
directory, because ESLint's real `SourceCode` module has since moved to
`languages/js/source-code/`, the same doc/code drift Round 2 already
found, not a new one — and `rule-tester` 2 files):

- `rule-tester` (2 files, a barrel pair): recall **≥ 0.9**.
- `linter` (20 files): recall **0.45–0.65** — `code-path-analysis/` (7 of
  the 20) is a genuinely dense internal clique expected to cluster
  tightly; the other 13 peripheral files expected to be less consistent.
- `cli-engine` (6 files): recall **≤ 0.4** — the four formatters are
  independent siblings implementing a common interface, expected to share
  little code with each other and scatter.
- **Cluster homogeneity for labelled members, weighted: 0.4–0.6, not
  higher** — reasoning: `cli.js → cli-engine → linter → rule-tester` is a
  real dependency chain, not four independent subsystems, so at least one
  large cluster was expected to mix files from several named components,
  the same "architectural layering merges under modularity clustering"
  shape already found on this project's own `core⇄db`/`agents⇄services`
  pairs.

### A methodology bug caught before trusting the first real run

The first run of the recall computation let `None` (unclustered) compete
as a candidate "majority cluster" — `cli-engine`'s raw distribution was
`{None: 3, cluster 16: 1, cluster 10: 2}`, and picking the single most
common value made `None` "win" at 3/6, reporting 50% recall. That's
backwards: three files each independently failing to join *any* cluster
is absence of evidence that they belong together, not agreement between
them, and crediting it inflates recall in exactly the direction that
would make the finding look better than it is. Fixed by excluding `None`
from majority-cluster candidacy on both metrics (recall and homogeneity);
`cli-engine`'s real recall is 2/6 = 33.3%, not 50%. Reported here rather
than silently corrected, since a wrong number that happens to match a
prediction is not confirmation.

### Results, modularity (the leading algorithm; Louvain cross-check below)

| Component | Members | Recall | Majority cluster |
|---|---|---|---|
| `api` | 1 | n/a (single file) | — |
| `cli` | 1 | n/a (single file) | — |
| `cli-engine` | 6 | **33.3%** (2/6) | cluster 10 |
| `linter` | 20 | **65.0%** (13/20) | cluster 10 |
| `rule-tester` | 2 | **100%** (2/2) | cluster 10 |

`cli-engine`'s scatter is precisely the formatters, confirmed at the file
level: `html.js`/`json.js`/`json-with-metadata.js` never joined any
cluster; `stylish.js` landed alone in a cluster of one. The two
`cli-engine` files that DID join the main cluster are `hash.js` and
`lint-result-cache.js` — cache/hashing plumbing shared with the rest of
the pipeline, not formatter logic. The prediction that formatters
specifically would scatter, not `cli-engine` generally, held at the file
level, not just in aggregate.

`linter`'s 65.0% is carried by a real structural finding: `code-path-analysis/`'s
7 files (plus one shared utility, `lib/shared/assert.js`) form their OWN
separate cluster (cluster 13), 100% pure — not merged into the main
cluster at all. The predicted "genuinely dense internal clique" is
exactly what the algorithm found, as its own distinct community. The
remaining 13 `linter` files split 13-into-cluster-10 vs. these 7 held
apart, which is why the component's overall recall (65.0%, majority in
cluster 10) undercounts how cleanly `code-path-analysis` itself separated
out.

**Cluster homogeneity for labelled members, real clusters only** (3
`cli-engine` files that never clustered at all are reported separately,
not folded into this number, for the same reason `None` was excluded from
recall):

| Cluster | Labelled members | Dominant component | Homogeneity |
|---|---|---|---|
| 10 (56 files total) | 19 | `linter` | 68.4% (13/19) — mixes `api`(1), `cli`(1), `cli-engine`(2), `linter`(13), `rule-tester`(2) |
| 13 | 7 | `linter` | 100% — pure `code-path-analysis` |
| 16 | 1 | `cli-engine` | 100% (trivial, single file) |
| **Overall** | **27** | | **77.8%** (21/27) |

**Correction made after this table was first drafted: 77.8% is not
evidence that "one cluster = one subsystem" is a safe reading, and this
document should not be cited as saying it is.** The 77.8% is a weighted
average, and it is dominated by cluster 13 (7 files, 100% pure
`code-path-analysis`) pulling the number up. Cluster 10 — the *largest*
cluster, 19 of the 27 labelled files, 70% of everything this table
covers — is only 68.4% homogeneous, and the files it mixes are not a
near-miss: `api`, `cli`, `cli-engine`, `linter`, and `rule-tester` all
present in one cluster is five of the doc's named parts in one bucket. If
this were surfaced in the Architecture map as a single color, that color
would visually claim those five components are one thing, which is
exactly the claim the data contradicts. The corrected framing, and the
one now used in the app itself (`RepoDetail.tsx`'s glossary and the
Dependency Clusters tab): a cluster is a measured coupling group — "these
files are entangled" — not a confirmed architectural subsystem. Where the
UI colors or labels by cluster, it says "dependency cluster," never
"subsystem."

### The prediction, checked against the numbers

Three of four predictions landed close: `cli-engine` 33.3% (predicted
≤0.4), `rule-tester` 100% (predicted ≥0.9), and `linter`'s 65.0% sits at
the very top of the predicted 0.45–0.65 band. **The homogeneity
prediction (0.4–0.6) was wrong — the real number is 77.8%, clearly
higher.** The directional reasoning behind it was half right: cluster 10
does mix all five named components together, exactly as argued from the
real `cli → cli-engine → linter → rule-tester` dependency chain. What the
prediction missed is that `linter` alone is 13 of that cluster's 19
labelled files, so even a "mixed" cluster stays majority-linter, and
`code-path-analysis` splitting off as its own 100%-pure cluster pulls the
weighted average up further. The mixing is real; the codebase's real
architecture is more coherent than the "everything blurs into one thing"
framing predicted. A prediction landing 3-for-4 with the miss explained
by a mechanism (a large single component dominating a shared cluster) is
a stronger outcome than either an unbroken hit or an unexplained miss
would have been.

### Louvain cross-check

Same computation against Louvain's independent clustering: `cli-engine`
33.3% (identical), `linter` 50.0% (10/20, vs. modularity's 65.0% — Louvain
splits the same 20 files 10/10 instead of 13/7), `rule-tester` 100%
(identical), overall homogeneity 77.8% (identical number, different
composition: 16+10+1 vs. 19+7+1). The two algorithms agree on this repo
at 94.1% overall (`Repo.subsystem_algorithm_agreement`) — lower than
repo 1's 100%, the first real case where the two clusterings measurably
diverge, though not on the numbers that matter for this validation.

### What this means for the F7 hypothesis

Subsystem clustering does not "pass" the file-ranking's original
threshold in a directly comparable sense — there is no single Overlap@20-
style number here, by design, since recall/homogeneity measure a
different claim (does the algorithm group files the way the doc groups
them) than Overlap@20 measured (does the algorithm rank files the way the
doc implies importance). But on the terms this round set for itself:
`rule-tester` recovers essentially perfectly, `code-path-analysis`
recovers as its own clean community without being told the boundary
exists, `cli-engine`'s formatters honestly fail to cluster (correctly —
they don't share code, so an algorithm that clustered them anyway would
be the bug), and the one large mixed cluster reflects a real dependency
chain in the code, not algorithmic noise. This is meaningfully closer to
"the tool recovers real coupling structure in the doc's territory" than
file ranking's 2–3/20 ever was — but it is NOT evidence that clustering
identifies confirmed subsystems, and shouldn't be cited as such: the same
large cluster that shows the tool found something real also shows it
merged five separately-named parts of the doc together (`api`, `cli`,
`cli-engine`, `linter`, `rule-tester` — not four, corrected above) into
one bucket. `cli-engine` at 33.3% recall and a five-component mixed
cluster are real, stated limits, not smoothed over. The honest framing
this round earns is "detects dependency clusters worth looking at," not
"identifies subsystems" — which is also now the language used in the
product itself (see the correction above).

## Round 4: does HDBSCAN over embeddings do better than the import graph?

Motivated directly by this file's own Round 3 correction: modularity/
Louvain's biggest weakness on this repo is the one large cluster that mixes
five of the doc's named components, driven by a real dependency chain
(`cli -> cli-engine -> linter -> rule-tester`) the import graph can't help
but see as one connected mass. HDBSCAN clusters files by what their code's
symbol signatures and docstrings say (FastEmbed, `BAAI/bge-small-en-v1.5`,
entirely local), a signal that doesn't see import edges at all -- the
hypothesis was that this could split apart what the import graph is
structurally forced to merge, and might also unite files that share
vocabulary despite having zero import edges (`cli-engine`'s four
formatters, siblings implementing a common interface, never import each
other).

### Prediction, written down before compute_subsystems_hdbscan was run

- `cli-engine` (6 files): recall **higher** than modularity's 33.3%,
  predicted 50-80% -- the four formatters don't import each other but
  plausibly share enough vocabulary (formatter function signatures,
  "results", "messages") for embeddings to unite them where the import
  graph structurally cannot.
- `linter` (20 files): recall **lower** than modularity's 65.0%, predicted
  20-45% -- this component spans too many distinct topics (timing, file
  I/O, source-code representation, fixing, code-path-analysis) to share one
  embedding neighborhood, even though they all import each other.
- `rule-tester` (2 files): no strong directional prediction -- a 2-member
  component's recall under this formula is either 50% or 100%; leaned
  toward 50% since a thin runner entry point and its implementation likely
  read differently.
- Overall homogeneity: **lower** than modularity's published 77.8%,
  predicted 40-65% -- no reason to expect embeddings to reproduce the same
  cluster shape modularity found, since embeddings can't see dependency
  chains.
- Unclustered proportion: **higher** than modularity's 10/398 -- a
  semantically heterogeneous corpus (294 individual, largely distinct lint
  rule files) gives HDBSCAN's density estimate a lot to call noise.

### What actually happened

Re-running modularity/Louvain's own recall and homogeneity computation live
against the repo's *current* state surfaced a small, unrelated drift from
this document's originally published modularity numbers (homogeneity
21/25 = 84.0% now vs. 21/27 = 77.8% as published above) -- `cli-engine`'s
`stylish.js` no longer sits alone in a true singleton cluster the way it
did when Round 3 was written, most likely because the repo has been
re-ingested/re-ranked at least once since then. This does not change
anything about Round 3's conclusions; it means Round 4's fair comparison
uses the numbers **recomputed just now, on the same live state, for all
three algorithms side by side** -- not the number as originally published.

| Metric | Modularity (now) | Louvain (now) | HDBSCAN |
|---|---:|---:|---:|
| `cli-engine` recall | 33.3% (2/6) | 33.3% (2/6) | **16.7%** (1/6) |
| `linter` recall | 65.0% (13/20) | 50.0% (10/20) | 55.0% (11/20) |
| `rule-tester` recall | 100% (2/2) | 100% (2/2) | 100% (2/2) |
| Overall homogeneity | 84.0% (21/25) | 84.0% (21/25) | **78.6%** (11/14) |
| Cluster count | 9 | 9 | **3** |
| Unclustered files | 10/398 (2.5%) | 10/398 (2.5%) | **57/398** (14.3%) |

The headline finding isn't in this table's percentages -- it's in the
`cluster count` row. HDBSCAN's single largest cluster contains **324 of
398 files (81% of the entire repo)**: 291 of the ~294 files under
`lib/rules/` (each an individual, largely-independent lint rule
implementation) plus 33 more files scattered across nearly every other
directory (`linter`, `config`, `types`, `eslint`, `languages`,
`rule-tester`, `cli-engine`). Individual ESLint rule files share a highly
formulaic structure -- a `meta` object, a `create(context)` function, JSDoc
conventions repeated near-verbatim across hundreds of files -- and that
structural/boilerplate similarity dominates the embedding space more
strongly than each rule's actual topical content does, at least with this
configuration (whole-symbol-signature text, default `min_cluster_size=3`,
`bge-small-en-v1.5`). The two clusters that DID split off cleanly
(`lib/languages/js/source-code/token-store`, 13 files; a 4-file `lib/shared`
group) show the mechanism can work -- it just didn't work on the biggest,
most repetitive part of this particular repo, and `code-path-analysis`
(the one clean split modularity/Louvain both found) did not survive as its
own group under embeddings at all -- most of its files ended up unclustered
rather than merged into the mega-cluster or grouped together.

### The prediction, checked against the numbers

Three of five predictions missed, and not in the hoped-for direction:

- **`cli-engine` went the wrong way.** Predicted higher than modularity
  (50-80%); actual is *lower* (16.7% vs. 33.3%) -- the formatter-vocabulary
  hypothesis this round was built around did not hold. The four formatters
  did not cluster together under embeddings any more than they did under
  the import graph.
- **`linter` landed above the predicted band** -- 55.0% exceeds the
  predicted 20-45% ceiling, closer to Louvain's own 50.0% than to the low
  end predicted. Not a sharp miss, but not the predicted direction either.
- **`rule-tester`** hit the upper end of the acknowledged 50%/100% range
  (100%), matching both graph algorithms.
- **Overall homogeneity landed above the predicted band** (78.6%, vs. a
  predicted 40-65% ceiling) -- closer to modularity/Louvain's 84.0% than
  predicted. This number alone would read as "close to the baseline," but
  it is computed over only 14 labelled files (most of `cli-engine` and half
  of `linter` fell into "never clustered" and are excluded from it
  entirely, same exclusion rule as everywhere else in this document) -- a
  homogeneity number computed over a shrinking denominator, from an
  algorithm that found only 3 clusters total, is not comparable in spirit
  to modularity's even where the percentage happens to land close.
- **Unclustered proportion was directionally right** (57/398 vs. 10/398) --
  the one prediction that landed cleanly, though the real driver turned out
  to be `code-path-analysis` scattering into noise, not primarily the
  heterogeneous `lib/rules/` corpus predicted as the mechanism (most of
  `lib/rules/` in fact clustered -- into the mega-cluster).

### What this means for the "improve accuracy" goal

**On this validation repo, HDBSCAN over FastEmbed embeddings of symbol
signatures + docstrings does not improve on modularity/Louvain's baseline
-- on the metric this whole round was designed to test (does clustering
avoid the "one big mixed cluster" problem Round 3 flagged), it is
measurably worse.** Modularity's largest cluster covers 56/398 files
(14%) and is imperfectly mixed; HDBSCAN's largest cluster covers 324/398
(81%) and is barely more differentiated than "everything that isn't
`code-path-analysis`-adjacent." The one place this round hoped embeddings
would show a concrete advantage -- uniting `cli-engine`'s import-blind
formatter siblings -- didn't happen; if anything HDBSCAN did worse there
than the graph-based algorithms it was meant to complement.

This is not a reason to remove the feature -- the mechanism is now
implemented, tested, and produces a real, inspectable result, and it may
behave differently on a codebase without ESLint's extreme lib/rules/-style
repetition (hundreds of near-identically-structured files is an unusual
corpus shape, not typical of most repos this tool has been run against).
But it is a reason not to claim HDBSCAN detects dependency clusters more
accurately than the existing algorithms without further work -- candidates
for a follow-up, none attempted yet: embedding richer content than bare
signatures+docstrings (e.g. a snippet of each function's body, so two rule
files that both implement *unrelated* checks stop looking identical),
tuning `min_cluster_size` upward specifically to break up an
indiscriminate mega-cluster, or restricting HDBSCAN to a hand-picked subset
of directories rather than the whole repo when one directory's file count
and structural homogeneity dominates the corpus the way `lib/rules/` does
here.

## Round 5, 2026-08-17: every round above was measured against a stripped fixture, not `eslint/eslint`

**Every number in Rounds 1 through 4 was measured against a deliberately
scoped slice** -- `source_root=lib` (393 files) then `source_root=None`
rescoped to `bin/`+`lib/`+ four top-level config files (398 files),
exactly as Caveat 1 at the top of this document states. That caveat was
never violated by this document itself. It was dropped by downstream work:
later in the same project, this repo id's module-preview and catalogue
classification work (`module_mapping.py`) cited an "ESLint" catalogue
finding -- 74.7% of files in catalogue-flagged modules -- without carrying
the scope caveat forward. That number was real, for the corpus it was
computed against; it was never a number about `eslint/eslint`.

The catalogue finding surfaced the gap: `docs/phase4-composition.md` named
`lib/rules · index` (151 members) and `lib/rules · ast-utils` (139
members) as catalogue examples. Re-running catalogue classification
against a freshly, fully re-cloned `eslint/eslint` (`git clone
--filter=blob:none`, full working tree, no `--depth`/`--sparse`, HEAD
`9aa38732`, verified real `.git` and `package.json`) produced **zero**
catalogue-flagged modules. That is not a refinement of 74.7% -- it is a
reversal, and it is what prompted re-examining every number this document
reports, not just the catalogue one.

### What changed about the corpus

| | Rounds 1-4 | Round 5 |
|---|---|---|
| Clone | shallow (`--depth 1`) + sparse (`bin`+`lib` only) | full, unscoped |
| Files ingested | 393 -> 398 | **1,447** |
| `package.json` at repo root | present (read correctly per Bug #2's fix) | present, unchanged |
| `tests/`, `docs/`, `packages/`, `tools/` | excluded by the sparse checkout | included |
| Modularity subsystems | ~9 | **120** |
| Unclustered (modularity) | 10/398 (2.5%) | **600/1,447 (41.5%)** |

The 30 doc-named files and their component groupings are **unchanged** --
re-transcription check, below.

### Ground truth re-transcription

Checked every one of the 30 doc-named paths against the real clone's
working tree directly (`test -f`, not a query against this project's own
ingest). **All 30 exist at their original doc-named paths.** The
`source-code-*.js` / `languages/js/source-code/` drift this document
already flagged (Round 2) is confirmed unchanged in the current sense that
matters here: `lib/linter/source-code-fixer.js`, `source-code-traverser.js`,
and `source-code-visitor.js` (the three doc-named files) still exist as
real, non-trivial files (154/333/81 lines) at their original paths,
*alongside* a separate, newer `lib/languages/js/source-code/` module
(`index.js`, `source-code.js`, `token-store/`) that implements something
else. Component membership (`api` 1, `cli` 1, `cli-engine` 6, `linter` 20,
`rule-tester` 2) is unchanged from Round 3.

### Prediction, written down before this round's numbers were computed

- `cli-engine` (6 files): dynamic-`import()` formatters are a blind spot
  independent of corpus size -- predicted **similar to or worse than**
  Round 3's 33.3%.
- `linter` (20 files): `code-path-analysis`'s 7-file internal clique is a
  dense, self-contained subgraph that shouldn't be disturbed by unrelated
  peripheral growth elsewhere in the repo -- predicted it holds, and the
  component predicted at **45-65%**, similar order to Round 3's 65.0%.
- `rule-tester` (2 files): a tight, direct-import pair -- predicted
  **>=90%**, unchanged from Round 3's 100%.
- Homogeneity: genuinely uncertain between "120 subsystems (vs ~9) argues
  toward finer, cleaner separation" and "more shared test-harness plumbing
  argues toward more cross-component merging, the same mechanism that
  produced Round 3's mixed cluster 10." Predicted **70-90%**, low
  confidence, roughly Round 3's 77.8-84.0% band either way.

### Results, modularity, old and new side by side

Same methodology as Round 3 exactly: recall's denominator is every member
of the component (unclustered files count against it); the majority
cluster is chosen excluding `None` from candidacy; homogeneity is computed
over labelled members of clusters that have at least one, `None` excluded
entirely from both its numerator and denominator. Denominators stated
alongside every rate, per §17.5c.

| Component | Round 3 (398 files) | Round 5 (1,447 files) |
|---|---:|---:|
| `cli-engine` | 33.3% (2/6) | **50.0% (3/6)** |
| `linter` | 65.0% (13/20) | **95.0% (19/20)** |
| `rule-tester` | 100% (2/2) | **50.0% (1/2)** |
| Overall homogeneity | 84.0% (21/25, recomputed live in Round 4) | **80.0% (24/30)** |
| Unclustered among the 30 | 5/30 (the 3 formatters + 2 more, Round 4 live figure) | **0/30** |

Louvain cross-check, same treatment:

| Component | Round 3 Louvain | Round 5 Louvain |
|---|---:|---:|
| `cli-engine` | 33.3% (2/6) | 33.3% (2/6) |
| `linter` | 50.0% (10/20) | **100% (20/20)** |
| `rule-tester` | 100% (2/2) | 50.0% (1/2) |
| Overall homogeneity | 84.0% (21/25) | 90.0% (27/30) |

### The prediction, checked against the numbers

Two of four landed inside the predicted band; two missed, in opposite
directions, and both misses have a mechanism, not a shrug:

- **`cli-engine` landed higher than predicted** (50.0% vs. "similar to or
  worse than 33.3%"). Mechanism, from the per-file assignment: `stylish.js`,
  `hash.js`, and `lint-result-cache.js` joined the repo's large
  `lib/shared`-labelled subsystem (119 members) -- the same "shared
  plumbing merges components" mechanism Round 3 named, now pulling in more
  of `cli-engine` than it did at 398 files, not less. The three dynamic-
  `import()` formatters (`html.js`, `json.js`, `json-with-metadata.js`)
  still didn't join *each other* -- each landed in its own separate
  2-member cluster instead. The blind spot itself didn't close; the
  denominator's other half got luckier.
- **`linter` landed higher than predicted** (95.0% vs. 45-65%), and the
  *reason* directly falsifies part of Round 3's own finding: `code-path-
  analysis` did **not** split off as its own clean cluster this time --
  all 7 of its files merged into the same 119-member `lib/shared`
  subsystem as the rest of `linter`. At 398 files, that clique was dense
  enough *relative to the rest of the graph* to read as its own community;
  at 1,447 files, the same edges are less distinctive against a much
  larger graph, and modularity folded them into the bigger group instead.
  Same edges, same files, different community boundary -- a direct
  demonstration that "this subsystem split off cleanly" was a fact about
  the graph's size at the time, not a stable structural property of
  `code-path-analysis` itself.
- **`rule-tester` landed lower than predicted** (50.0% vs. >=90%) -- the
  one genuine surprise. The pair split: `rule-tester/rule-tester.js`
  joined the 266-member `lib/rules`-dominant subsystem (labelled by top
  fan-in as "rule-tester," since presumably every one of ~294 individual
  rule files touches it), while `rule-tester/index.js` joined a *separate*
  34-member `tests/fixtures/testers/rule-tester` subsystem. The "tight
  barrel pair" framing from Round 3 was true at 398 files (neither
  `lib/rules/` nor `tests/` were in scope to pull the pair apart) and is
  not true of the real repository, where `rule-tester.js`'s edge volume
  from hundreds of rule files outweighs its one-line relationship to its
  own `index.js`.
- **Homogeneity landed inside the predicted band** (80.0% vs. 70-90%
  predicted) but for a different reason than either predicted mechanism:
  it isn't finer separation NOR more merging in the aggregate -- it's that
  the same 119-member `lib/shared` cluster that used to hold ~19 labelled
  files (Round 3) now holds 24 of the 30 (api, cli, most of linter, half
  of cli-engine), while `rule-tester.js` moved OUT to the 266-member
  `lib/rules` cluster instead of staying with the group. Two large
  compositional shifts landing on a similar aggregate number by
  coincidence, not by either mechanism holding as stated.

### No tuning was performed

Modularity and Louvain ran with the same parameters already shipped in
this project (`compute_subsystems`, default settings) -- no threshold,
`min_cluster_size`, or algorithm choice was adjusted in response to a
number looking wrong. The homogeneity/recall computation itself is the
exact script logic Round 3 established (`None` excluded from majority
candidacy on both metrics), re-run against the new database state, not
rewritten.

### What this means for every number in Rounds 1-4

**Nothing about the *mechanisms* Rounds 1-4 found is overturned** -- the
dynamic-`import()` blind spot on the formatters, the "shared plumbing
merges components" pattern, layer-vs-doc-importance being a loose
correlation rather than a filter: all four re-appear or are directly
consistent with what Round 5 found. **What is overturned is treating any
specific percentage in Rounds 1-4 as a fact about `eslint/eslint`.** They
are facts about a 398-file `bin/+lib/` slice, correctly caveated as such
at the time, and incorrectly treated as representative once a different
part of this project (the catalogue classification work) cited one of
them without the caveat. Overlap@20/@10/Spearman (Rounds 1-2) were not
re-run this round -- they depend on `validate_ranking.py` and the answer-
key's rank-ordering, a separate re-validation from the clustering-only
scope requested here, tracked as a follow-up, not silently assumed to
still hold.

## Round 6: Overlap@20/@10/Spearman, re-run against the real 1,447-file corpus

Round 5 tracked this as a follow-up rather than assuming the Round 1/2
numbers still held. It isn't optional: Section 6 of the original proposal
quotes 2/20 and 3/20 as the pre-registered failure, both measured against
a 398-file fixture, and the `GO_NO_GO_THRESHOLD = 12` bar
(`scripts/validate_ranking.py`) was set against that same denominator.
§17.5c requires a rate to travel with its denominator; the same rule
applies to a threshold -- 12 out of a top-20 list means something
different when that top-20 is drawn from 398 candidates than when it's
drawn from 1,447.

### Prediction, written down before this round's numbers were computed

Overlap@20 and the full-rank distribution are not the same measurement
and should not be expected to move together. Overlap@20 only changes if
a *newly-included* file displaces one of the 30 doc-named files from the
global top 20 -- and the 1,049 newly-included files are overwhelmingly
`tests/`, `docs/`, `packages/`, and `tools/` content: test files and
fixtures with low fan-in, not imported by production code, structurally
unlikely to out-rank files like `api.js` or `linter.js` for centrality or
seed-proximity. Predicted Overlap@20 **stays flat or moves by at most one
file**, in either direction, for all three scorers. The full-rank
percentile of the 30 doc-named files is a different question -- it's
sensitive to *any* new file landing anywhere in the ranking, not just the
top 20 -- and should move more than Overlap@20 does, because the
denominator against which every one of the 30 files is ranked genuinely
tripled.

**Contrast with a plausible alternative**, since more than one
reasonable prediction exists here: the corpus proposal reasoning would say
30 files now compete against 3.6x more candidates for the same 20 slots,
so overlap should simply get worse. That reasoning is not wrong on its
face; it's testable against the same numbers below, and where it diverges
from the prediction above is the point worth checking.

### Results

| Scorer | Overlap@20, 398 files (Round 1/2) | Overlap@20, 1,447 files (Round 6) | Verdict |
|---|---:|---:|---|
| `legacy` | 2/20 | **2/20** | NO-GO |
| `weighted_pagerank` | 3/20 | **3/20** | NO-GO |
| `rrf` | 2/20 | **2/20** | NO-GO |

Every count is identical. Overlap@10 also held: 1/10, 2/10, 1/10 --
unchanged in the new run (was 1/10, 2/10, 0/10; `rrf`'s Overlap@10 moved
by one file, the only change anywhere in this table). Spearman is not
reported here at n=2/3 -- §17.0's own prior correction (line ~374) already
flags per-scorer Spearman as not meaningful at this intersection size, and
that stands regardless of corpus size.

Full-rank distribution of the same 30 files, 1,447-file denominator:

| Scorer | mean rank | median rank | min | max | median percentile |
|---|---:|---:|---:|---:|---:|
| `legacy` | 459.2 | 487.5 | 2 | 796 | **33.7%** |
| `weighted_pagerank` | 99.2 | 60.5 | 3 | 426 | **4.2%** |
| `rrf` | 193.6 | 166.5 | 2 | 548 | **11.5%** |

Against the 398-file baseline (median rank 53 for all three scorers,
Round 2's table above -- median percentile 13.3% across the board): `legacy`
got **worse** (33.7% vs. 13.3%), `weighted_pagerank` got **dramatically
better** (4.2% vs. 13.3%), `rrf` landed **close to unchanged** (11.5% vs.
13.3%).

### The prediction, checked against the numbers

The flat-Overlap@20-despite-tripled-corpus half of the prediction held
exactly: 2/20, 3/20, 2/20, all three unchanged to the file. The
"structurally unlikely for test/doc/tooling content to break into the
top 20" mechanism is the right explanation, not coincidence -- none of the
1,049 newly-included files displaced a single one of the original top-20
occupants for any scorer.

The percentile-moves-more-than-overlap half is confirmed, but the
direction split by scorer, which the prediction correctly anticipated
could happen (it predicted percentile would move, not which way) without
resolving in advance. The mechanism for each direction, read from the
per-file data:

- **`legacy` got worse (33.7%)** because it ranks by raw import fan-in/
  fan-out with no seed or distance term, and the 1,049 new files include
  hundreds of production modules (all of `lib/rules/`, all of
  `packages/js/src/`, `lib/languages/`) that generate their own import
  edges and rank ahead of some of the 30 on pure connectivity, with
  nothing in `legacy`'s formula privileging the entry-adjacent files the
  answer key actually names.
- **`weighted_pagerank` got better (4.2%)**, and this is the finding the
  Overlap@20 count alone completely hides. Seeded, personalized PageRank
  decays with graph distance from the seed set, and only 26.9% of the
  1,447-file graph is reachable at all from the five auto-detected seeds
  (`bin/eslint.js`, `lib/api.js`, `docs/_examples/.../eslint-plugin-
  example.js`, `packages/eslint-config-eslint/index.js`,
  `packages/js/src/index.js`). The 1,049 new files are disproportionately
  outside that reachable set -- test fixtures, doc examples, and
  standalone tooling with no path back to the entry points -- so they
  don't compete for `weighted_pagerank`'s top ranks even though they exist
  in the denominator. The doc-named files, which mostly *are* reachable,
  end up ranked against a smaller effective pool than the nominal 1,447,
  and their percentile improves even though the corpus tripled.
- **`rrf` landed close to unchanged (11.5%)** because it's a rank-fusion
  of `legacy` and `weighted_pagerank` (reciprocal rank fusion) -- one
  input got worse, the other got much better, and the fusion partially
  cancels both effects.

**The corpus-tripled-so-overlap-should-worsen alternative did not hold**,
for any scorer, at the Overlap@20 granularity. It isn't wrong reasoning in
the abstract -- more candidates genuinely does mean more competition for
20 slots -- but it predicts a mechanism (uniform dilution) that the actual
new files don't exercise uniformly: they concentrate in `tests/`, `docs/`,
`packages/`, and `tools/`, which are exactly the regions each scorer is
structurally least likely to rank highly (low fan-in for `legacy`,
unreachable-from-seed for `weighted_pagerank`). Aggregate corpus size
change is the wrong level to reason at when the *type* of file being added
is this lopsided.

### Why Overlap@20 alone hides more than it shows

The answer key's own documented format is most-important-first, and
`validate_ranking.py`'s `Overlap@20` is defined against the answer key's
own **first 20 lines**, not against all 30 named files -- lines 21-30
(both `rule-tester/` files and the three `source-code-*.js` files) are
structurally excluded from what counts as a hit, regardless of where the
tool ranks them.

This produces a real, checkable discrepancy: under `weighted_pagerank`,
`lib/rule-tester/index.js` ranks **15th** of 1,447 and
`lib/rule-tester/rule-tester.js` ranks **17th** -- both inside the tool's
actual top 20 -- yet neither counts toward Overlap@20, because both are
answer-key lines 26-27. Counting all 30 doc-named files rather than only
the key's first 20, `weighted_pagerank` actually has **5** of the 30
inside its real top 20 (the 3 credited + these 2), `legacy` has **3**
(2 credited + `rule-tester.js` at rank 2), and `rrf` has **3** (2 credited
+ `rule-tester.js` at rank 2). This doesn't change the NO-GO verdict --
even 5/20 is far short of 12 -- but it matters for not misreading a
doc-named file's strong rank as contradicting a low Overlap@20 count; the
two are simply answering different questions about the same 30-line list.

### No tuning was performed

Ranking ran with the same scorers, seeds, and parameters already in
production (`rank_repo`, `rank_repo_weighted_pagerank`, `rank_repo_rrf`,
`--scorer` flag unchanged) -- no seed set, decay factor, or fusion weight
was adjusted after seeing a number.

## Round 7: the γ resolution sweep -- is code-path-analysis real, or an artifact of corpus size?

Round 5 found that `code-path-analysis`'s 7-file clique, which split off
as its own clean cluster at 398 files (cited repeatedly, including in
this document, as the clearest evidence modularity finds real
architecture), merges entirely into the 119-member `lib/shared` cluster
at 1,447 files -- same files, same edges. That is exactly the modularity
**resolution limit** (Fortunato & Barthélemy, PNAS 2007): a community
whose internal edge weight sits below roughly √(2m) (m = total graph edge
weight) can be absorbed into a larger neighbor as the graph grows, not
because the community changed, but because m did. `greedy_modularity_
communities`'s default resolution, γ=1, is exactly the parameter this
result is a statement about.

Using `_build_undirected_weighted_graph` -- the same function `compute_
subsystems`'s production clustering calls, read directly, no persistence
-- the two graphs' actual sizes:

| | Round 3/4 (398 files) | Round 5 (1,447 files) |
|---|---:|---:|
| Graph nodes | 398 | 1,447 |
| Graph edges (count) | 663 | 1,482 |
| √(2 × edge count) | 36.4 | **54.4** |

> **Correction, 2026-08-17 — this table uses the wrong quantity, and the
> two numbers below it are not the ones the argument needs.**
>
> In Fortunato & Barthélemy, **m is the graph's total edge WEIGHT**, not its
> edge count. This graph is weighted and both community algorithms run with
> `weight="weight"`, so the unweighted count answers a question neither
> algorithm asks. On the same graph the correct figures are total weight
> 1,033.7 and **√(2m) = 45.5**, not 54.4 — and after Round 8's `is_test_file`
> correction, 532.4 and **32.6**.
>
> The sentence that followed ("the resolution threshold grew 1.5x while the
> corpus grew 3.6x") was computed from the count-based pair and is withdrawn.
> `subsystems.resolution_report` now computes the weighted figure on every
> clustering run, and states which it means.
>
> This is §17.5c's rule applied to units rather than denominators, and it was
> broken in the section arguing for measuring the threshold rather than
> citing it.

The question this section answers: does `code-path-analysis`
reappear as its own community once γ compensates for that growth, or was
Round 3's 398-file measurement simply wrong about the subsystem?

**If code-path-analysis reappears at γ > 1, the structure is real and γ=1
was under-resolving it on the larger graph. If it never reappears, Round
3's finding was an artifact of corpus size, not a discovery about
`code-path-analysis`.**

### Sweep, γ ∈ {1.0 .. 40.0}, tracking the cluster containing all 7 production `code-path-analysis` files

| γ | Cluster size | Composition |
|---:|---:|---|
| 1.0 (production default) | 119 | merged into `lib/shared` |
| 1.2 | 118 | merged into `lib/shared` |
| 1.5 | 21 | partial separation |
| 2.0 | 27 | partial separation |
| 3.0 | 33 | partial separation |
| 3.5 | 16 | partial separation |
| 4.0 | **11** | 7 production + 3 of its own tests + `assert.js` |
| 4.2 | 19 | transient re-merge (see below) |
| 4.5 - 20.0 | **11** | 7 production + 3 of its own tests + `assert.js`, stable |
| 40.0 | fragments into 8 + 3 | see below |

At γ=4.0 the cluster first reaches an 11-member group: the 7 real
`code-path-analysis` production files, three of its own dedicated test
files (`tests/lib/linter/code-path-analysis/{code-path-analyzer,fork-
context,id-generator}.js`), and `lib/shared/assert.js` -- the exact same
companion file Round 3's 398-file measurement found joining this clique.
γ=4.2 transiently re-merges it to 19 members before it re-separates and
holds at 11 from γ=4.5 through γ=20.0. This non-monotonicity is a known
property of greedy agglomerative modularity optimization (merge order is
locally greedy, not globally optimal at every γ) and is reported rather
than smoothed over; the point is the **stable** result from 4.5 to 20.0,
a 4.4x range in γ, not the single transient value at 4.2.

This 11-member group is arguably a *better* description of the subsystem
than Round 3's original 8-member finding (7 production files + `assert.
js`) -- the 398-file fixture never had `tests/` in scope, so it couldn't
have found the implementation-plus-its-own-tests grouping at all. At
higher resolution, on the full corpus, modularity recovers something Round
3 structurally couldn't have measured: production code, its own test
files, and the one shared utility it depends on, cleanly separated from
everything else including the rest of `linter/`.

At γ=40.0 -- well past the range where this project's clustering has ever
run in production -- the 11-member group itself starts to fragment: 6 of
the 7 production files plus 2 of the 3 tests stay together (8 members);
`fork-context.js` splits off together with `assert.js` and its own test
(3 members); `code-path.js`'s test file and `debug-helpers.js`'s test file
scatter to other groups entirely. (The much larger set of `tests/fixtures/
code-path-analysis/*.js` files -- pure test-input data with no `require`
statements of their own -- were never part of any cluster at any γ in this
sweep; they're inert fixture content, not source modules, and their
absence here isn't part of this finding.)

### What this answers

**Code-path-analysis reappears, cleanly, across a 4.4x range of γ
(4.5-20.0) as effectively its own community** -- production files, its own
tests, and its one real dependency, nothing else. Per the test this
section was run to satisfy: **the structure is real, and default γ=1 was
under-resolving it on the larger graph.** Round 3's 398-file finding was
not an artifact to be discarded -- it was a true positive that a smaller
graph made easy to see for a reason (fewer competing dense clusters)
independent of whether `code-path-analysis` is, on its own terms, a real
subsystem. It is. The 398-file measurement and the γ-sweep measurement are
both correct; they answer the question at two different resolutions, and
γ=1 on a 1,447-file graph happens to sit on the wrong side of this
particular boundary.

This does not generalize into "raise γ in production." No prediction was
made about any other cluster's behavior under a resolution change, none of
the other 119 subsystems were swept, and picking γ post hoc to recover a
result already believed true would be exactly the tuning this document has
repeatedly avoided elsewhere. What it does establish: the 398-vs-1,447
disagreement about `code-path-analysis` is resolved, specifically, by
resolution -- not by one of the two measurements being wrong.

### No tuning was performed

`greedy_modularity_communities`'s `resolution` parameter was swept across
a predetermined grid chosen to bracket the transition, read-only, against
the exact production graph-construction function. Nothing about `compute_
subsystems`'s shipped default (γ=1) was changed; this section is a
diagnostic sweep, not a proposal to change the production parameter.

## Round 8, same day: Rounds 5-7 measured a graph in which 59% of the edges were misweighted

Rounds 5, 6 and 7 all ran against a graph built from `CodeImport.kind`.
`edge_weights.is_test_file` decides which edges are `test_edge` (weight
0.05 instead of 0.4-1.0), and it matched with the substring `"/tests/"` --
**which requires a leading slash, and therefore never matched a top-level
`tests/` directory.** `eslint/eslint` keeps its entire test suite at
top-level `tests/`, so almost none of it was recognised and its edges were
weighted as ordinary production coupling.

This was found while fixing the marker list for an unrelated repo, after
Rounds 5-7 were written. It is reported here in full rather than by
correcting those sections in place, per §17.16.

Exact counts, since a first draft of this section quoted 963 files where
the measurement is 964, and mixed two different edge populations in
consecutive sentences:

- **Files:** 970 of 1,447 (67.0%) are test files under the corrected
  predicate; **964** of those were newly reclassified (6 already matched).
- **Resolved edges** (`to_file_id` non-null -- the ones that exist in the
  graph at all): **1,013 of 1,720 (58.9%)** are now `test_edge`; 1,011 newly
  reclassified.
- **All `CodeImport` rows** including unresolved: 2,304, of which 1,294 were
  updated. This is the larger number and is NOT the graph figure -- an
  unresolved import has no edge to weight.

### A second consumer, missed by this section's first draft

`dir_aggregation._kind_of` reuses `is_test_file` to label directories in the
Architecture map. Recomputing the per-directory majority vote, **173 of
eslint's 212 mapped directories (81.6%) change kind**, as do 141 of
Superset's 1,307 (10.8%) and none of Athena-OS's. Four fifths of eslint's
architecture map was mislabelled in a view whose whole purpose is to show
how a codebase is organised. Recorded as part of contract §17.28: a shared
helper's blast radius is the union of its callers.

### What the corrected graph changes

| | Rounds 5-7 (contaminated) | Round 8 (corrected) |
|---|---:|---:|
| `CodeImport` rows classed `test_edge` | 2 / 1,720 | **1,013 / 1,720** |
| Clustering-graph total edge weight (m) | 1,033.7 | **532.4** |
| √(2m) | 45.5 | **32.6** |
| Modularity clusters | 120 | **21** |
| `lib/shared` cluster size | 119 | *(does not exist in that form)* |

> The two weight figures are the CLUSTERING graph's, where
> `_build_undirected_weighted_graph` keeps the **max** weight per file pair
> across all imports between them. Summing raw `CodeImport` rows instead
> gives 1,199.7 and 545.5 -- a different quantity, not a correction of these,
> and not the one √(2m) is computed from. Stated because a draft of this
> table mixed the two.

**Round 7's conclusion survives and strengthens. Round 5's headline finding
does not.**

- **Round 7 (the γ sweep) is confirmed.** On the corrected graph
  `code-path-analysis` still converges on the same near-pure community: 11
  members at γ=8-12 (the 7 production files, 3 of its own test files,
  `lib/shared/assert.js`) and a 10-member group at γ=20 that is exactly the
  7 production files plus their own three tests. Same finding, reached on a
  graph with half the total weight -- the structure is real.
- **Round 5's "code-path-analysis merges entirely into the 119-member
  `lib/shared` cluster" is withdrawn.** On the corrected graph it does not
  merge that way at any γ: at γ=1 it is already a 26-member cluster
  containing all 7 production files. The merge Round 5 observed was
  substantially an artifact of ~1,000 test edges carrying 8-20x their
  correct weight and pulling unrelated files together -- not the resolution
  limit acting alone.

### The comparison Rounds 5-7 were built on was confounded

Rounds 1-4 measured a 398-file `bin/`+`lib/` fixture. That fixture had
**no `tests/` directory in scope at all**, so it had no test edges to
misweight and its graph was, accidentally, correct. Round 5 compared it
against a full clone in which 59% of edges were wrong. The 398-vs-1,447
comparison was therefore not "same instrument, bigger corpus" -- it was two
different instruments, and the difference between them was read entirely as
a corpus-size effect.

The resolution limit is still real, still correctly described, and still
the right frame for Round 7. What is withdrawn is the claim that Round 5
*observed* it: that specific merge had a second, larger cause that was not
controlled for. §17.0's third row (cluster boundaries are provisional to
corpus size) stands on Round 7's γ sweep, which is measured on the
corrected graph. It should not cite Round 5's 398-vs-1,447 merge as
evidence.

### What is unaffected

Round 6's Overlap@20 numbers were re-measured after the fix by re-running
all three scorers and `validate_ranking.py` again: **2/20, 3/20, 2/20 --
identical**, Overlap@10 1/10, 2/10, 1/10 identical, and all three verdicts
still NO-GO. The ranking scorers
read edge weights, so this is a real result rather than an untouched one:
the doc-named files are production code whose edges were never misclassified
either way, and the test files whose weights collapsed were not competing
for the top 20 to begin with -- the same mechanism Round 6 predicted for why
adding 1,049 files changed nothing.

---

**Reconciliation audit, 2026-08-20.** Every corpus and clustering figure in this
document was re-checked against the live database rather than re-derived from
the text. **VERIFIED:** repo 3 is `eslint` with **1,447 files** and **21
modularity clusters**, matching the corrected figures in the Round 8 table
(`Modularity clusters | 120 | 21`). The `120` and `398`-file figures elsewhere
in this document are historical readings that the text already marks as
superseded, and they are correct as history — they are not claims about the
current state. No corrections were required to this file.

**CARRIED-FORWARD-UNVERIFIED:** the Overlap@20 / Spearman / recall percentages
in Rounds 1–8 were not recomputed in this pass. Re-running them requires a full
ranking and clustering cycle against repo 3, which is runtime work rather than a
records check. They were last computed in Round 8 on the corrected graph, after
the `is_test_file` fix.
