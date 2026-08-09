# Phase 1 Code Health — Metric Contract (rev 2)

**Status: approved for implementation.** Rev 2 incorporates review corrections;
changes from rev 1 are listed in §14. Every claim about existing data was
verified against the repo, not assumed — results in §8.

## 0. Design constraints (binding)

1. **Three separate axes. No blended score.** No single combined number, and
   none will be added without the evidence in §9.
2. **Axis 3 is "Change Hotspot — uncalibrated."** It names the signals it
   observes (change frequency × complexity), not a defect prediction. The
   terms "Defect Risk", "Defect Exposure", "bug risk" and "predicted defects"
   are forbidden in code, API payloads and UI.
3. **Absent data is N/A, never 0 and never "healthy."**
4. **Scores stay out of the primary UI until the §10 threshold sanity pass is
   complete** and `thresholds_version` v1 is frozen.
5. **No Phase 2 in this pass**: no co-change, no coverage, no external services.

## 1. The three axes, and their direction

Direction is part of each metric's name. No axis requires the reader to
mentally invert a number.

| Axis | Scale | Direction | Inputs |
|---|---|---|---|
| **Maintainability** | 1–10 | **higher is better** | tree-sitter AST |
| **Architecture Health** | 1–10 | **higher is better** | resolved import graph |
| **Change Hotspot — uncalibrated** | 0–9 exposure points | **higher means review sooner** | git history × AST complexity |

Axis 2 was "Architecture Risk" in rev 1. Renamed for exactly the reason above:
a metric called *Risk* scored so that 10 is good forces the inversion this
contract forbids. It measures structural quality, so it is named as health.

Axis 3 is deliberately the odd one out and is reported as **points, not a
score** — it is an attention ranking, not a quality grade.

**Scale note.** 1–10 is an intentional bounded scale; N/A is a separate state,
not a low score. No claim is attached to the choice of 1 as the floor.

## 2. Scoring mechanism

```
deduction        = weight × severity,  severity ∈ [0,1]
severity         = clamp((value − warn) / (saturate − warn), 0, 1)
axis_deduction   = min(AXIS_CAP, Σ_categories min(CATEGORY_CAP, Σ_markers deduction))

Maintainability      = 10 − axis_deduction        (1–10, higher better)
Architecture Health  = 10 − axis_deduction        (1–10, higher better)
Change Hotspot       =      axis_deduction        (0–9, higher = review sooner)
```

Linear ramps, not step functions. Per-category caps stop one dimension
consuming the score.

**AXIS_CAP = 9.0 on all three axes.** It currently equals the sum of each
axis's category caps, so **it never binds today** — it is a forward guard so
that adding a category later cannot silently drive a file to 0. Documented as
inert rather than presented as shaping the score.

**Symbol → file aggregation:** complexity markers take the **maximum** severity
across the file's functions, and additionally record **how many functions
breach each threshold** plus the **worst symbol's name and line**. So the
explanation reads *"3 functions over CC 10; worst `resolve_imports` at CC 34,
line 212"* — which `max` alone loses and `mean` would bury.

## 3. Markers

### 3.1 Maintainability (categories: Complexity 4.0, Size 3.0, Error 2.0)

| Marker | Value | warn → saturate | Weight |
|---|---|---|---|
| `complex_method` | max cyclomatic complexity across functions | 10 → 25 | 2.5 |
| `deep_nesting` | max block nesting depth in a function | 4 → 8 | 1.5 |
| `complex_conditional` | max operand count in one boolean expression | 4 → 10 | 1.0 |
| `large_method` | max function NLOC | 60 → 200 | 2.0 |
| `large_file` | file NLOC | 400 → 1500 | 1.5 |
| `broad_error_handling` | count of bare/broad handlers (§3.4) | 1 → 5 | 2.0 |

### 3.2 Architecture Health (categories: Cycles 4.0, Coupling 3.0)

| Marker | Value | warn → saturate | Weight |
|---|---|---|---|
| `cycle_participation` | size of the file-level import SCC it belongs to | 2 → 12 | 4.0 |
| `bidirectional_coupling_hub` | `min(fan_in, fan_out)` percentile, fires only when **both** ≥ P90 | P90 → P99 | 3.0 |

Renamed from `hub_file`: the rule intentionally ignores a pure high-fan-in
utility, so it does not measure hubness in general and must not claim to.

**Category caps now sum to 7.0**, since reachability moved to advisory (§3.5).
AXIS_CAP stays 9.0 as the forward guard.

**Deliberately excluded:** instability index and distance-from-main-sequence.
Both require **abstractness**, which needs an abstract/interface distinction
our parser does not record (verified: `CodeSymbol.kind` only ever holds
`class`/`function`/`method`). Instability without the axis it is meant to be
balanced against is a number with no interpretation.

### 3.3 Change Hotspot — uncalibrated (category: Hotspot 5.0)

**Gate: the entire axis is N/A unless the repo passes §5.2.**

| Marker | Value | warn → saturate | Weight |
|---|---|---|---|
| `churn_volume` | `commit_count` percentile in repo | P50 → P95 | 2.5 |
| `complexity_under_churn` | `severity(complex_method) × severity(churn_volume)` | 0.2 → 0.8 | 2.5 |

The nonzero `warn` matters for explanation quality more than for arithmetic: at
a 0→1 ramp the product 0.05 × 0.05 deducts ~0.006 (negligible) but the marker
still *appears in the explanation* of nearly every file with any churn and any
complexity. Requiring both signals to clear a bar keeps the marker meaningful.

**Removed from this axis in rev 2:** `change_recency` and `sole_ownership`
(now §3.6 Context). Recency is genuinely bidirectional — recent change can mean
actively maintained or freshly destabilised, and we have nothing that
distinguishes them. Ownership concentration measures knowledge distribution,
not defect likelihood; there is also reason to think a dominant owner may be
the *healthier* configuration, which would make a deduction directionally
wrong. **That literature claim is explicitly not relied upon** — the factor is
context-only regardless of how it resolves.

### 3.4 `broad_error_handling`, per language

| Language | Counts as a finding |
|---|---|
| python | bare `except:`; `except Exception`/`except BaseException` whose body is only `pass` |
| javascript, typescript, tsx | `catch` with an empty block |

A language with no rule listed here reports this marker **N/A**, not 0.

### 3.5 Advisory markers — shown, never deducted

| Marker | Definition | Why advisory |
|---|---|---|
| `possibly_unreachable_by_static_imports` | no path from any seed-eligible entry point, and not itself an entry point | Known false positives: framework discovery, plugins, generated code, reflection, dynamic import. **Confirmed firing wrongly in our own data** — see §8. Shows the evidence (importers found, entry points searched). |
| `change_impact_breadth` | `churn_volume × fan_in` percentile product | A *different* question from Axis 3's churn × complexity: this is "frequently changed with broad downstream impact", that is "frequently changed and hard to reason about". They overlap but support different actions, so both are kept. Advisory until usage shows whether it earns a score. |

### 3.6 Context factors — displayed, never deducted, rendered neutrally

`change_recency` (days since last change) · `distinct_authors` ·
`commit_count` (raw) · `fan_in` / `fan_out` (raw).

**Rendering rule:** neutral styling only. No red/amber, no warning icon, no
sort-by-worst. Colouring "1 author" as a warning would reintroduce the risk
claim that §3.3 removed.

## 4. Language coverage

Implemented for exactly **python, javascript, typescript, tsx** — verified as
the complete set of parsers in `languages.py` (extensions `.py .ts .tsx .js
.jsx`). Since discovery ingests only those extensions, every `CodeFile` today
is covered.

**Forward rule:** a marker with no rule for a file's language is
`available: false` → N/A. Adding a language must never make its files score
10.0 by default.

## 5. N/A rules, with the evidence for each

### 5.1 Substance floor — **not applied uniformly**
`NLOC < 10` → **Maintainability and Change Hotspot N/A**.
**Architecture Health is still computed** wherever graph evidence exists.

*Evidence:* repo 1 contains **9 files classified `prior_category == "barrel"`**.
A barrel is a handful of re-export lines that can sit in an import cycle or act
as a coupling chokepoint — exactly the file that is structurally significant
while being textually trivial. Excluding barrels from the architecture axis
would blind it to a category that exists to matter structurally.

Separately: a file with **zero function/method symbols** reports the Complexity
category N/A (size and error-handling markers still apply).

### 5.2 Degenerate churn → whole Change Hotspot axis N/A
Require **≥ 3 distinct `commit_count` values** across the repo.

| Repo | distinct `commit_count` | distinct `distinct_authors` | Axis 3 |
|---|---|---|---|
| 1 Athena-OS | 7 | 3 | **usable** |
| 2 AFDE…LMS | 2 | 1 | **N/A — degenerate** |
| 3 eslint | 1 | 1 | **N/A — shallow clone** |

Consequence accepted knowingly: **this axis is N/A on 2 of our 3 repos.** An
often-empty axis looks weak; scoring files against a constant would be worse.

### 5.3 Per-file missing history
`commit_count == 0` → that file's Axis 3 is N/A even when the repo passes §5.2.
*Verified:* **71 of 173 files (41%) on repo 1.**

**Label: "No history available in this clone."** Rev 1 said "uncommitted at
rank time", which was asserted without evidence. The cause may equally be a
shallow clone, a pathspec exclusion, or **our own documented rename blind
spot** — `_collect_git_history` notes that `--numstat` never reconnects
renames, so pre-rename history stays attributed to the old path. Claiming
"new and least reviewed" would require `git status` to prove it, which we do
not run.

### 5.4 Missing ownership
`distinct_authors == 0` → ownership context shows N/A, not "healthy".

### 5.5 No graph yet
No completed rank run → Architecture Health N/A.

### 5.6 Coverage
Not ingested in Phase 1. Coverage markers are **absent**, not zero. No
coverage-shaped placeholder in the UI.

## 6. Default weights: source and standing

**These are reasoned defaults, not fitted to any outcome on any repository.
Nothing in Phase 1 validates them.**

| Threshold | Basis |
|---|---|
| Cyclomatic warn = 10 | McCabe's original high-risk recommendation |
| Nesting warn = 4 | Common linter default (`max-depth`) |
| `large_method` 60 NLOC, `large_file` 400 NLOC | Convention; no empirical basis claimed |
| Percentile markers (churn, coupling hub) | **Repo-relative** — adapts to each codebase's own distribution instead of importing another project's absolute cutoffs. UI must say "relative to this repository" and show the raw count alongside the percentile. |
| All weights and caps | **Our judgement**, chosen so no category dominates. Not learned. |

Absolute vs. relative is split by what the metric is: complexity and size use
absolute thresholds (CC 25 is bad in any codebase); churn and coupling use
repo-relative percentiles (a "high" commit count only means something against
that repo's distribution). Cost: Axis 3 is not comparable across repos.

## 7. Snapshots, identity, and trend

**Snapshot identity — all fields required:**

| Field | Source | Why |
|---|---|---|
| `repo_id` | — | |
| `branch` | `Repo.default_branch` (verified present) | |
| `head_sha` | `Repo.last_ingested_sha` (verified present) | |
| `working_tree_dirty` | `git status --porcelain` | **Correctness, not nicety.** For `source_kind == "local"` we analyse the user's live working directory, so HEAD may not describe the analysed bytes at all. |
| `analyzer_version` | constant in code | AST rules change |
| `thresholds_version` | constant in code | see §10 |
| `weights_version` | constant in code | |

Without threshold/weights versions a trend line silently mixes incomparable
scoring regimes the moment a constant is tuned.

**Immutability:** append-only. A re-ingest at the same SHA writes a new row.
Per-file marker explanations are stored with the snapshot, so a historical
score can always be explained by the markers that produced it.

**Trend delta** = current vs. most recent *earlier* snapshot on the same
branch, **and only when `thresholds_version` and `weights_version` match**.
Otherwise: "Not comparable — scoring changed since the previous snapshot."
A single snapshot shows "No previous snapshot on this branch," never "0.0".

## 8. Verification of existing data

**Confirmed present** — `CodeFile`: `path, language, content_sha256,
size_bytes, line_count, prior_category, prior_source, fan_in, fan_out,
is_entry_point, seed_eligible, commit_count, distinct_authors,
days_since_last_change`. `Repo`: `default_branch, last_ingested_sha,
last_ingested_at, subsystem_cycle_coherence`. `CodeSymbol`: `name, kind,
signature, docstring, line_start, line_end, parent_symbol_id`.

**Confirmed ABSENT — built by Phase 1:** all complexity/nesting/conditional/
error-handling metrics; per-file reachability (`layer` is computed live in
`get_graph`, never stored); file-level import SCCs (only *directory*-level
exist, in `subsystems.py`); the snapshot table; `working_tree_dirty`.

**Confirmed ABSENT, out of scope:** per-commit SHA, commit subject, co-change
pairs, coverage.

**Findings that shaped this contract:**
1. `_collect_git_history` runs one
   `git log --format=@@%an|%aI --numstat -- .`, parses per-file added/deleted
   line counts and **discards them**. Line-level churn is one line of code
   away — deliberately not taken in Phase 1.
2. The same call already groups files by commit, so **co-change is nearly free
   in Phase 2**.
3. It captures neither commit SHA nor subject, so Tier A defect labelling
   would require changing the `--format` string.
4. **Reachability already fires wrongly on our own validation data.**
   `external-validation-eslint.md` records that the four
   `cli-engine/formatters/*.js` files are `layer=None` purely because they are
   loaded by dynamic `import()` with a runtime-computed path — the plugin
   pattern our own `BLIND_SPOTS` list predicted. They are not dead code.
   Supporting figure: repo 1 reports **59 of 173 files (34%)** as
   imported-by-nothing-and-not-an-entry-point, far too high to be mostly dead.
   This is why §3.5 demotes it to advisory.

## 9. Calibration is out of scope; preconditions predeclared

Tier A may only be claimed if **all** hold:
1. ≥ 200 labelled files and ≥ 50 defect-labelled commits on the target repo.
2. Time-ordered holdout: fit before time T, evaluate strictly after T. Never
   fit and evaluate on the same commits.
3. Must beat **both** NLOC-only and churn-only ranking on the same holdout.
4. AUC, 95% CI and n shown in the UI, not buried in a doc.

**Note against optimism:** our repo has **0 conventional `fix:` commits**
(verified), so Tier A would not engage here today.

**Evidence that would change direction:** a validated calibration dataset
showing a combined score improves review prioritisation beyond the three
separate signals, without concealing unsupported or degenerate inputs.

## 10. Threshold sanity pass — required gate

Scores **must not appear in the primary UI** until this completes:

1. Build the analyzer.
2. Run across all three repos.
3. Produce a **distribution report**: per axis, per marker — histogram, median,
   p10/p90, % of files at the extremes, % N/A with reasons.
4. Adjust thresholds **only with a recorded rationale** written into this
   document.
5. Freeze `thresholds_version = 1`.

**Failure conditions requiring adjustment:** >90% of files at 9–10 (thresholds
inert, axis decorative) or median < 4 (too harsh).

**Prohibited:** tuning against defect outcomes. That is calibration, and doing
it while still labelling the result "uncalibrated" would be the exact
misrepresentation this contract exists to prevent.

### 10.1 Results — run 2026-08-09, `thresholds_version = 1` FROZEN

Corpus: **596 files / 8,002 functions** across all three repos (Athena-OS 170
files, AFDE-LMS 28, eslint 398). 33 files excluded by the substance floor,
**563 scored**.

**Prediction, written before the run:** >80% of files would land at 9–10,
breaching the "thresholds inert" condition. **This was wrong**, and the reason
is worth recording: it was reasoned from *per-function* rates (CC > 10 fires on
3.2% of functions), but every complexity marker consumes the **max across a
file's functions**. At file level that becomes 28.8% of files — a 9× gap. Per
-function statistics are actively misleading about marker behaviour whenever
the marker aggregates by max.

File-level marker inputs (the values markers actually see):

| Input | p50 | p75 | p90 | p95 | p99 | max |
|---|---|---|---|---|---|---|
| max cyclomatic | 7 | 11 | 18 | 23 | 51 | 68 |
| max nesting | 2 | 3 | 4 | 4 | 6 | 10 |
| max conditional operands | 2 | 4 | 6 | 7 | 10 | 20 |
| max function NLOC | 49 | 102 | 175 | 239 | 512 | 1236 |

Maintainability distribution under rev-2 defaults:

| Band | Files | Share |
|---|---:|---:|
| 9.5–10 | 360 | 63.9% |
| 9.0–9.5 | 53 | 9.4% |
| 8.0–9.0 | 59 | 10.5% |
| 7.0–8.0 | 40 | 7.1% |
| 5.0–7.0 | 35 | 6.2% |
| 1.0–5.0 | 16 | 2.8% |

median 9.87 · p10 7.17 · min 3.00 · **≥9.5 = 63.9%** (gate fails above 90%)
· <5.0 = 2.8%

**Verdict: gate passed. No thresholds changed.**

A tuned alternative (CC 8/20, nesting 3/6, conditional 3/8, method 40/150, file
300/1000) was evaluated and produced a more spread distribution — 47.2%
pristine, median 9.39, 6.0% poor. **It was rejected.** Those numbers have no
external justification; they were chosen to reshape a histogram. Substituting a
distribution preference for McCabe's threshold would be tuning to aesthetics
and would leave the constants unjustifiable to the next reader. The rev-2
values keep their stated basis (§6).

**Recorded caveat — fire rate is not impact.** `large_method` "fires" on 44.4%
of files at warn = 60, which looks alarming until severity is accounted for: a
70-line function sits at severity 0.07 and deducts 0.14. Because severity ramps
from zero, a high fire rate with low mean severity is invisible in the score.
Any future review of these thresholds should measure **mean deduction per
marker**, not fire rate — the report used to freeze v1 measured fire rate, and
that is a known limitation of this run.

**Also observed:** the corpus's median file has a longest function of 49 NLOC,
so the conventional 60-line "large method" line sits near the 55th percentile
of real code rather than in the tail. Kept anyway, per the reasoning above, but
recorded so the next revision starts from evidence rather than convention.

### 10.2 Per-marker deduction report — run 2026-08-09 → `thresholds_version = 2`

Produced by `backend/scripts/health_distribution_report.py`, which drives the
**real scoring engine** rather than reimplementing the arithmetic — a report
with its own copy of the formula can disagree with production and still be
believed. §10.1 measured fire rate; this measures **deduction**, which is what
fire rate could not answer.

#### Change made: `broad_error_handling` warn 1 → 0

A genuine semantic defect, not a distribution preference. At `warn = 1`:

| broad handlers | severity | deduction |
|---:|---:|---:|
| 0 | 0.00 | 0.00 |
| **1** | **0.00** | **0.00** |
| 2 | 0.25 | 0.50 |

**The first bare `except:` was free** — the marker silently required two before
it said anything. Evidence: repo 1 had 14 files with ≥1 broad handler but only
7 firing; eslint's 3 such files produced a 0.0% fire rate.

Before / after:

| Repo | v1 fire rate | v1 files firing | v2 fire rate | v2 files firing |
|---|---:|---:|---:|---:|
| 1 Athena-OS | 4.4% | 7 | **8.9%** | **14** |
| 2 AFDE-LMS | 0.0% | 0 | 0.0% | 0 |
| 3 eslint | 0.0% | 0 | **0.8%** | **3** |

Both now match the raw handler counts exactly. No other threshold changed.

#### Findings recorded but deliberately NOT acted on

**1. `large_method` does dominate Size — but not by compounding with
`large_file`.** It takes **92.9%** of the Size category on eslint (91.4% on
repo 1) and fires on 53.9% of files; `large_file` contributes just 7.6%.
Crucially, **89.3% of `large_file` firings co-occur with `large_method`**
(25 of 28 on eslint), so Size is effectively a single marker. `large_file` is
kept regardless, because its independent value is precisely where
`large_method` is N/A — a long module of constants with **no functions at all**
still deserves to register as large. Low contribution here is not the same as
no purpose.

**2. Complexity and Size measure strongly correlated properties.**
`complex_method` ∩ `large_method` = **111 of 128** eslint firings (86.7%). A
single big complicated function is therefore charged in two categories with
two separate caps. This is the strongest candidate for a future revision, but
fixing it means restructuring categories — not moving a threshold — so it needs
its own version with a before/after, not a patch here.

**3. Caps are near-inert.** Category caps bound on 0.5% (complexity) and 1.1%
(size) of eslint files, and 0.0% on repo 1. The axis cap bound on nothing,
consistent with §2's note that it cannot currently bind. No change: caps exist
as guards, and a guard that rarely engages is working.

**4. Architecture Health cannot be judged yet, and must not be.** It reports
mean 9.98 with 98.7% ≥ 9.5 — but `cycle_participation`, its heaviest marker
(weight 4.0), reads 0 for every file because file-level SCCs are not persisted
yet. The axis is currently carried by one marker firing on ~1% of files. **No
conclusion about this axis is valid until cycles are wired**, and the report
prints that caveat rather than letting the numbers imply health.

**5. `deep_nesting` is weak but language-varying**, not broken: 1.3% on the
mostly-Python repo 1 versus 6.1% on all-JavaScript eslint, mean deduction 0.04.
Below the bar for "never contributes meaningfully", and the variation is
plausibly real (JS callback nesting) rather than a rule inconsistency. Watched,
not changed.

**6. Change Hotspot discriminates well where it applies but is near-binary.**
On repo 1: 46.2% of eligible files carry >0 points, 19.4% carry >2, median 0,
p90 2.50. However churn P50=1 and P95=3, so the ramp spans two commits — any
file with 3+ commits takes the full 2.5. That is honest (it reflects a repo
with thin history) but means the marker behaves closer to a flag than a scale
here. Recorded as a property of the corpus, not a threshold fault.

**7. N/A rates behave as designed.** Change Hotspot: 100% N/A on eslint
(shallow clone), 38.2% "No history available in this clone" plus 7.1% trivial
on repo 1. Maintainability: 4.5–7.1% trivial-file exclusions. Nothing silently
scored as healthy.

### 10.3 File-level SCCs wired — and `cycle_participation` is empirically inert

`graph_structure.py` now computes and persists file-level SCC membership/size
and reachability, so the Architecture Health evidence gate can open. Result
across all three repos:

| Repo | Files | Edges | File-level cycles | Files in cycles |
|---|---:|---:|---:|---:|
| 1 Athena-OS | 173 | 422 | **0** | 0 |
| 2 AFDE-LMS | 28 | — | **0** | 0 |
| 3 eslint | 398 | 663 | **0** | 0 |

**Zero file-level import cycles in 599 files.** Verified as a real finding, not
a broken detector, in two independent ways: `compute_file_sccs` correctly
identifies a synthetic 3-cycle, and networkx's own `find_cycle` agrees both
real graphs are acyclic.

**This is consistent with — not contradicted by — the directory-level cycles
that do exist.** Repo 1 has 3 directory-level cycles (`core⇄db` and others).
A directory cycle needs only `a1.py → b1.py` and `b2.py → a2.py`; no single
file is in a cycle. That is exactly what the Round-3 cycle-coherence numbers
already measured — `core⇄db` scored 38% coherence, meaning the cycle is
carried by a few specific edges rather than by pervasive file-level coupling.
The two measurements agree; they answer different questions.

**Consequence, stated plainly: `cycle_participation` fires on 0 of 599 files.**
Architecture Health now has **complete coverage of the current static
file-level contract** — which is a much narrower claim than "complete
evidence about the architecture", and must never be worded as the latter. It
reports mean 9.98–10.00 with 98.7–100% of files at ≥9.5, carried entirely by
`bidirectional_coupling_hub` firing on 0.6–1.3%. The axis is honest about what
it measured and does not discriminate on this corpus.

The engine field is therefore named `inputs_complete`, not
`evidence_complete`: it asserts that every marker **in this contract** had its
input, and nothing more. A 10.00 here means "no file-level cycles and no
bidirectional coupling hub were found", not "the architecture is healthy" —
particularly not when the same product shows the user three directory-level
cycles elsewhere.

**Not fixed here, deliberately.** The obvious candidate is a
`directory_cycle_participation` marker — directory cycles are the ones that
actually exist, and `subsystems.py` already computes them. But adding a marker
is a contract change with its own before/after obligation, and the file-level
marker is not *wrong*: a file genuinely inside an import cycle is a real
finding, it simply does not occur here. Three repos is also too small a corpus
to conclude that file-level cycles are rare in general. Recorded as the leading
Architecture-axis candidate for the next revision.

**Reachability persisted as evidence only**, never scored: 66/173 unreachable
on repo 1, 19/398 on eslint, 3/28 on repo 2. With no entry points at all the
value is `None` ("could not be determined"), not `False` — asserting that every
file is possibly-dead would be an artifact of having nothing to search from.

### 10.4 Two gates added to the engine

**Architecture Health evidence gate — structural, not advisory.** When
`cycle_participation` has no data, the axis sets `evidence_complete = False`,
`missing_evidence = ["cycle_participation"]`, and **withholds `score` entirely**
(the provisional number is parked in `provisional_value` for diagnostics). An
inline caveat would still leave a prominent 9.98 on screen anchoring the reader
on a conclusion the evidence does not support; a UI cannot render a value it
was never given.

**Change Hotspot resolution badge.** `CHURN_RESOLUTION_MIN_SPAN = 5`: when
P95 − P50 is narrower than that, the axis sets `resolution_limited = True` with
a note. On repo 1 the span is P50=1 → P95=3, so a file hits **maximum exposure
at three commits**. Ranking within the repo stays usable, so this is a badge
rather than a gate — unlike the architecture case, where the missing marker was
the dominant one. Deliberately a **span** check, not a distinct-value check:
§5.2 asks whether churn varies at all, which is a weaker question than whether
it varies enough to grade. A future revision should consider promoting spread
to a first-class eligibility rule.

## 11. Effort-aware ranking

```
raw_exposure      = Change Hotspot points (0–9)
review_cost_units = max(NLOC, REVIEW_COST_FLOOR) / 100
adjusted_exposure = raw_exposure / review_cost_units
```

**`REVIEW_COST_FLOOR = 30` NLOC** — without it a 4-line file divides by ~0.04
and tops the ranking purely for being small.

Both columns always shown; default sort `adjusted_exposure`. Files with an N/A
axis appear in neither ranking and are counted separately as "N/A (n)".

## 12. Repo-level aggregation

Per axis, **never across axes**: NLOC-weighted mean over scoreable files,
median, p10, count below 5.0 (or above 5.0 points for Axis 3), and count N/A
with the dominant reason. A lone mean cannot distinguish five catastrophic
files from uniform mediocrity.

## 13. Exact UI wording

| Element | Text |
|---|---|
| Axis 1 | `Maintainability` · `1–10 · higher is better` |
| Axis 2 | `Architecture Health` · `1–10 · higher is better` |
| Axis 3 | `Change Hotspot` + badge `UNCALIBRATED` · `0–9 exposure · higher means review sooner` |
| Axis 3 subtitle | "Frequently changed code that is also complex. Weights are defaults, not fitted to this repository — this ranks where to look first, not where bugs are." |
| N/A axis | "Not measurable for this repo — <reason>." Never 0, never a bare dash |
| Degenerate churn | "Every file reports the same commit count, so change frequency carries no information here — typical of a shallow clone (`git clone --depth 1`)." |
| No file history | "No history available in this clone." |
| Trivial file | "Excluded from Maintainability — under 10 lines." |
| Advisory reachability | "Possibly unreachable by static imports" + evidence + "Dynamic imports, plugins, reflection and generated code are not visible to static analysis." |
| Percentile markers | "<n> commits — P<xx> relative to this repository" |
| Trend, no baseline | "No previous snapshot on this branch." |
| Trend, version change | "Not comparable — scoring changed since the previous snapshot." |
| Effort columns | `Exposure` and `Exposure / 100 LOC reviewed` |
| Weights disclosure | Always visible on the Axis 3 panel, never behind a tooltip |

**Architecture Health coverage disclosure — mandatory, always visible.** A
high score on a narrow contract still reads as "the architecture is healthy",
especially to a user who has just seen directory-level cycles elsewhere in this
same product. The panel must therefore state its own scope, not just its
number:

```
Static file-graph evidence:            0 file-level cycles
Separate directory-cycle observations: 3   (see Dependency Clusters)
Active Architecture Health markers:    bidirectional coupling only
```

**It ships as structured API data, not only as a rendering rule.** The
`architecture_health` axis object carries a `coverage` block with these
fields, computed at snapshot time and stored immutably with the result:

| Field | Meaning |
|---|---|
| `inputs_complete` | every marker in this contract had its input — **not** "complete evidence" |
| `file_level_cycle_count` | non-trivial file-level SCCs found (the scored fact) |
| `directory_cycle_count` | directory-level cycles observed separately (**not** scored) |
| `active_markers` | which markers actually had data and carried the score |
| `inactive_markers` | markers with no data in this run |
| `limitations` | plain-language scope statements, always non-empty |

A documented rendering rule alone is insufficient: a future UI could receive a
non-null score and simply omit the scope. `TestArchitectureDisclosureContract`
in `test_repos_api.py` asserts that a non-null Architecture Health score is
never servable without every field above, on both the compute and the read
endpoint.

Rules:
- Rendered **next to the score, not behind a tooltip or expander.**
- The directory-cycle count links to where those cycles are already shown, so
  the two facts are visibly reconciled rather than appearing to contradict.
- When `inputs_complete` is False the score is absent entirely (§2), and this
  block states which marker had no data.
- The wording "complete evidence" is forbidden here. Permitted phrasing is
  "complete coverage of the current file-level checks".

**Forbidden strings:** "Defect Risk", "Defect Exposure", "bug risk",
"predicted defects", "code health score", or any single combined number across
the three axes.

## 14. Changes from rev 1

1. Axis 3 renamed **Defect Exposure Heuristic → Change Hotspot**; direction now
   stated as exposure points (higher = review sooner) rather than an inverted
   score.
2. Axis 2 renamed **Architecture Risk → Architecture Health** for the same
   direction-consistency reason.
3. `unreachable_file` **demoted to advisory** (§3.5), evidence-backed by §8.4.
4. Substance floor **no longer disables Architecture Health** (§5.1).
5. `change_recency` and `sole_ownership` **removed from scoring**, moved to
   neutral context (§3.6). Ownership literature explicitly not relied upon.
6. `churn × fan_in` **retained** as the `change_impact_breadth` advisory — it
   answers a different question from churn × complexity and supports different
   actions.
7. `hub_file` renamed `bidirectional_coupling_hub`.
8. `complexity_under_churn` warn raised 0 → 0.2.
9. Snapshot identity extended with `working_tree_dirty`, `analyzer_version`,
   `thresholds_version`, `weights_version`; trend requires version match.
10. `commit_count == 0` relabelled "No history available in this clone."
11. AXIS_CAP values stated and documented as currently inert.
12. 1–10 documented as an intentional bounded scale, with no claim attached to
    the floor.
13. §10 threshold sanity pass added as a **required gate** before UI rollout.
14. AST golden tests per language × construct required (§15).

## 15. Test requirements

**AST golden tests are mandatory before the analyzer is trusted**, per language
× construct, with hand-verified expected counts:

- **python**: `if`/`elif`/`else`, `for`, `while`, `try`/`except`/`finally`,
  ternary, `and`/`or`, comprehension `if`, `match`/`case`, nested functions,
  decorators, bare `except:`, `except Exception: pass`
- **javascript / typescript**: `if`/`else if`, `for`/`for..in`/`for..of`,
  `while`/`do`, `switch`/`case`, `try`/`catch`, ternary, `&&`/`||`/`??`,
  optional chaining (must **not** count as a branch), arrow functions, empty
  `catch {}`
- **tsx**: JSX conditional rendering (`&&` and ternary inside JSX)

Each fixture asserts exact cyclomatic complexity, nesting depth, conditional
operand count and handler count — these are precisely the values that drift
silently when a grammar changes.
