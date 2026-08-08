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
