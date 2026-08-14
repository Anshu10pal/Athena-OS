# Phase 1 Code Health — Metric Contract (rev 2)

**Status: approved for implementation.** Rev 2 incorporates review corrections;
changes from rev 1 are listed in §14. Every claim about existing data was
verified against the repo, not assumed — results in §8.

> This document specifies **what the metric is**. `decisions.md` records **why
> each choice was made and what it cost**, across the whole codebase agent
> rather than just this contract. Where the two overlap, this file is
> normative and the log is the reasoning behind it.

> **Amendment 2026-08-09 — a blended aggregate now ships on Overview.**
> §0.1 below said no combined number would be added without §9's evidence.
> One was added anyway, as an explicit product decision, before that evidence
> exists. It is recorded here rather than left as an undocumented divergence
> between this contract and the running product. See §16 for exactly what the
> blend does and does not include, and the compensating constraints it
> carries.

## 0. Design constraints (binding)

1. **Three separate axes. No blended score** *(amended — see §16)*. No single
   combined number, and none will be added without the evidence in §9.
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

> **Corrected 2026-08-12 (decisions.md K11/K12).** That sentence measured the
> wrong thing. Absence of a *conventional prefix* is not absence of defect
> history: hand-classifying all 25 commits found **4 genuine defect fixes**,
> touching 32 of 281 files. Three detectors were measured rather than assumed —
> conventional prefix 100% precision / 50% recall, subject keyword 100% / 75%,
> full-message keyword **40% precision** (6 of its 10 matches are feature
> commits whose prose mentions a fix).
>
> Tier A still does not engage, but for the accurate reason: **4 defect-labelled
> commits against a required 50, and no history to hold out from.** Unblocked,
> not calibratable — see K12.
>
> **Do not respond to this by widening the keyword list.** Message-based defect
> labelling has a ceiling on this corpus that no keyword reaches. The evidence
> is `003e2e6` — *"Stop serving a stale health score as current; stop ingest
> wiping a repo"* — the most substantive defect fix in the history, containing
> no fix-like word at all. That is not an omission from the pattern; it is a
> consequence of commit messages here describing **the behaviour change rather
> than the category of work**, which is better practice generally and
> specifically defeats keyword classification. The two failures are mirror
> images: the original detector under-counted by requiring a format nobody
> uses, the widened one over-counts at 40% precision by matching narrative
> prose. Tuning between them does not produce a usable labeller.
>
> **If defect labelling is ever needed here it requires a different source:**
> issue links, PR labels, a `Fixes #N` convention adopted going forward, or
> hand-labelling. The extractor is not the constraint and improving it will not
> move §9's precondition.

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

### 10.2b `cycle_participation` warn 2 → 1 (`thresholds_version = 3`)

**The same defect class as §10.2, found a second time.** `cycle_participation`
had `warn = 2`; a file cannot cycle with itself (the graph builder drops
self-edges), so the smallest possible real cycle is a 2-file mutual import —
and at `warn = 2` that deducted **exactly 0.00**:

| SCC size | v2 deduction | v3 deduction |
|---:|---:|---:|
| 1 (not in a cycle) | 0.00 | 0.00 |
| **2 (mutual import)** | **0.00** | **0.36** |
| 3 | 0.40 | 0.73 |
| 6 | 1.60 | 1.82 |
| 12+ | 4.00 | 4.00 |

`scc_size == 1` means "measured, not in a cycle" and still correctly scores
zero at `warn = 1`.

**The generalisable lesson, now observed twice: a linear ramp whose `warn`
sits AT the minimum meaningful value silently exempts the first real
occurrence.** Any future marker should be checked against its own minimum
observable value before its threshold is frozen.

**Found by a test, not by inspection** — the disclosure test asserting that a
firing marker appears in `active_markers` failed, because on a fixture with a
genuine mutual import the marker never fired.

**Before/after on the three real repos is unchanged** (all still report 0
file-level cycles, so nothing moved). That is precisely why this could not
have been caught from the distribution report alone, and why the fix is
verified against a purpose-built cycle fixture instead.

### 10.2c Incident: a test migrated the live development database

**What happened.** The first version of `test_migration_parity.py` set
`sqlalchemy.url` on the Alembic `Config` and called `command.upgrade(cfg,
"head")`. But `alembic/env.py` overwrites that option from
`settings.DATABASE_URL` (lines 16–19), so the Config value was ignored and the
migration chain ran against the **configured development database**.

**Why it was discovered.** The scratch database came back empty, so the parity
assertions failed. Had they passed, the run would have been invisible.

**Verified impact: none.** Read-only inspection of the development database
afterwards:

| Check | Result |
|---|---|
| `alembic_version` | `263062fc7f7f` — the expected head |
| `code_health_snapshots` columns | all expected, incl. `inputs_complete` and `source_fingerprint`; no `evidence_complete` |
| `code_files` phase-1 columns | `scc_id`, `scc_size`, `reachable_from_entry` present |
| Row counts | 5 repos / 608 files / 2,474 imports / 2,217 symbols — intact |
| Stray temp tables | only `_alembic_tmp_interview_sessions`, documented as pre-existing drift since the Phase I1 migration |

The run was a **no-op**: it happened after the rename migration had already
been applied, so the database was already at head. Nothing was rolled back;
state was established rather than altered.

**It was a no-op by luck, not by design.** A chain with any unapplied
revision would have mutated real data from a test run.

**Hardening.** The guard is now an extracted, directly-tested function
(`assert_isolated`) rather than an inline assertion, since an inline check can
only be tested by copy-pasting it — which tests the copy. It refuses unless
`settings.DATABASE_URL` (the value env.py actually reads) is the scratch path
AND is not the configured development URL, and after the upgrade it asserts
the scratch file exists and carries a stamped `alembic_version`, so a future
env.py change fails loudly instead of quietly moving the real database. A
further test asserts the development database's mtime is unchanged by a parity
run.

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
| `active_markers` | markers that **fired at least once** — i.e. actually carried the score. "Had input available" is a different fact and does not belong in a score explanation. |
| `inactive_markers` | `[{key, state, detail}]` — **never a flat list of keys** (see below) |
| `limitations` | plain-language scope statements, always non-empty |

**`inactive_markers` preserves a per-marker reason.** The three states license
different conclusions and are trivially conflated once flattened:

| State | Meaning | Consequence |
|---|---|---|
| `no_input` | the input was never computed | A **coverage gap**. Nothing is known either way. This is what withholds an axis score entirely. |
| `input_available_zero_severity` | measured, and genuinely found nothing | A **result**. Evidence of absence, not absence of evidence. |
| `not_applicable` | the marker cannot apply here (no functions, no rule for the language) | **Permanent** for these files; re-running changes nothing. |

Collapsing these would let a coverage gap read as a clean bill of health — the
exact failure the Architecture gate exists to prevent, reintroduced one level
down. The same `state` is stored per marker inside each snapshot's
`explanation`, so a historical result can still distinguish them.

The UI renders them distinctly: `not computed` (warning-coloured),
`found nothing`, and `n/a here`.

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

### 15.1 A test that cannot fail must say so in its name

Adopted 2026-08-12, after the encoding fix (§17.4) produced one test of each
kind and the difference nearly went unlabelled.

| Prefix | Meaning |
|---|---|
| `test_LOADBEARING_…` | Pins the behaviour. **Fails on every platform if the fix is reverted.** This is the coverage |
| `test_DOCUMENTS_INTENT_…` | Demonstrates the intended behaviour but **cannot fail** in some environments. Legitimate, but not coverage |

Every `DOCUMENTS_INTENT` test carries a docstring naming the condition under
which it cannot fail.

**Why this is a contract-level rule and not a style preference.** This project
has repeatedly shipped tests that passed for the wrong reason — a golden
fixture that was invalid source and only parsed via error recovery; two stubs
that asserted nothing; a marker test that patched a field the endpoint
overwrites; a credential test that passed alone and failed in the suite. The
encoding case is the sharpest instance: `test_DOCUMENTS_INTENT_a_non_latin1_
author_name_survives_the_round_trip` passes on Linux **with the defect fully
present**, because there the platform default already *is* UTF-8. Read as
coverage, it would certify a bug as fixed on the very platform we deploy to.

The intent-documenting class is worth keeping — it proves the round trip works
and explains what the code is for. It just must never be mistaken for a guard.

**Verification requirement:** a `LOADBEARING` test is only load-bearing once it
has been *observed* failing. Reintroduce the defect, watch it fail, restore.
An assertion whose failure mode has never been exercised is an assumption in
test clothing.

**And the inverse, which the requirement above does not cover:**

> **A negative result is only informative if the stimulus is first shown to
> produce the condition being checked for.** Otherwise *"nothing caught it"*
> and *"nothing happened"* are indistinguishable.

The instance. Error boundaries were verified by intercepting an API response
and returning `{ files: null }`, expecting a render throw the boundary would
catch. No boundary fired — and the reason was not the boundary. `RepoDetail`
does `const files = ranking?.files ?? []`, which coerces `null` to `[]`, so
nothing ever threw. The stimulus could not produce the condition.

Read as written, the run said *"the boundary did not catch a throw"*. What
actually happened was *"there was no throw"*. Those support opposite
conclusions, and the output looks the same either way — the failure mode is
that a broken boundary and a defensive component under test are
indistinguishable from outside.

It is the mirror of the canary rule and needs its own check. The canary asks:
*can this check fail?* This asks: *does my stimulus reach the code I am
checking?* The boundary was ultimately verified by injecting a real
`throw new Error(...)` into a component body — a stimulus that cannot fail to
produce the condition — rather than by hoping a malformed payload would.

**This rule found a violation of itself within two hours of being written.**
`test_the_stage_is_reported_in_the_job_result`, covering the new clustering
stage, asserted only `status == "computed"`. The canary run deleted the stage
and substituted a hard-coded result of the same shape — and the test passed. It
was verifying the *report*, not the work. Left alone it would have shipped
green and certified a deleted feature as present indefinitely. It now asserts
real integer cluster counts and fails under the same canary.

Worth recording next to §17.5's mojibake incident, for the same reason: the
author of the rule violated it immediately after writing it. **Knowing a
principle confers no immunity. Only the mechanical check does** — and in both
cases the check was cheap and the thing it caught was not.

## 16. Amendment: the Overview aggregate (2026-08-09)

A **Code health** tile scored out of 100 now sits on the repo Overview,
alongside a tile per axis. This is a deliberate product decision that departs
from §0.1, taken **before** the §9 evidence that §0.1 said would be required.
Recording it here rather than letting the contract and the product silently
disagree.

The separate Code Health tab was removed; the tiles live on Overview and each
opens an insights panel.

### What the aggregate is

The **mean of the two health axes** — Maintainability and Architecture Health
— each rescaled from 1–10 onto 10–100.

### What it deliberately excludes, and why that is not a caveat

**Change Hotspot is not in the number.** Not because it is uncalibrated —
that alone would justify a footnote — but because it is a **different kind of
quantity**: a review-priority ranking where *higher is worse*, against two
quality scores where *higher is better*. Averaging them requires silently
inverting one, and the result answers no question. A repo could raise its
aggregate by becoming *more* urgent to review.

It keeps its own tile on its native 0–9 scale, and its panel states why it is
excluded.

### Compensating constraints (these are what make the blend acceptable)

1. **The blend can never hide its own composition.** The tile face always
   reads `out of 100 · N of M axes`, and appends `· partial` when an axis
   could not be measured. The panel lists what went in *before* anything else.
2. **An unmeasurable axis is excluded from the mean** — never scored 0 (which
   would drag a genuinely healthy repo down) and never full marks (which would
   invent evidence). Same exclude-don't-zero rule the engine applies per
   marker.
3. **No aggregate at all when no health axis is measurable** — `N/A` with a
   reason, not a zero.
4. **Bands are coarse** (≥70 / ≥45 / below). The axes are not calibrated
   against any outcome, so a finer gradient would imply precision the numbers
   do not have.
5. **The panel states it is "a convenience summary, not a validated measure"**
   and carries the analyzer/thresholds/weights versions.

### What would retire this amendment

Either §9's calibration evidence arriving (making a defensible weighted
combination possible), or observation that the aggregate is being read as a
verdict despite the disclosures — in which case the tile should go back to
being three separate numbers.

### Axis panels show what was considered

Each axis panel lists **every marker the axis evaluated**, grouped by
category with that category's cap, showing weight, the `fires above` /
`maxes at` thresholds actually applied, how many files it fired on, and its
mean and worst deduction.

Mean deduction is shown **beside** fire rate, not instead of it — fire rate
alone cannot distinguish a marker that fires often and contributes nothing
from one that dominates its category, which is precisely what §10.2's
deduction report existed to resolve.

These are **stored with the snapshot**, like the per-file explanations and for
the same reason: thresholds are versioned, so explaining a historical score
with today's numbers would explain it wrongly. Snapshots taken before this
existed simply omit the field and render nothing, rather than being
back-filled with current values.

Percentile-derived markers report the **repo-relative** warn/saturate actually
used (e.g. `churn_volume` reads "fires above 1 · maxes at 3" on repo 1), not an
absolute pair they do not have — which also makes the low-resolution badge
legible, since the ramp is visibly two commits wide.

## 17. Corrections from the first large-repo test — apache/superset, 2026-08-12

Every threshold and every conclusion in §10 was derived from **599 files across
three small, young repositories**. The first mature large codebase to go
through the analyser — apache/superset, **6,516 files, 22,119 commits** —
reversed two of them. This section records the reversals, and the general rule
that should have prevented the overreach.

### What in this section is measured, and what is inferred

Written in a single session, which is exactly when a record is most likely to
be mistaken later for settled context. It is not uniformly settled.

| | Kind | Re-verifiable how |
|---|---|---|
| §17.1 cycle reversal | **measurement** | `scc_size` on repo 6; re-run the analyser |
| §17.2 coupling fire rate | **measurement** | marker `fired` counts on snapshot 7 |
| §17.3 rename cost (18,000 paths) | **measurement** | `_collect_git_history` path count vs `code_files` |
| §17.4 timing table | **measurement** | re-run the four git commands |
| §17.6 superset 95 < Athena 97 | **measurement** | axis summaries on both snapshots |
| §17.0 the sampling rule | **inference** | an argument from two instances. Could be wrong |
| §17.0b prediction mechanism rule | **inference** | an argument from two predictions in one session |
| §17.8 the real job path | **measurement** | job 19's SSE timeline and stored result |
| §17.5 encoding lesson | **inference** | generalised from two incidents in one session |
| §17.5b non-ASCII path loss | **inference** | latent; not observed on superset (zero non-ASCII paths) |
| §17.5c agreement / unclustered rates | **measurement** | cluster counts on snapshot 9; `scc`/degree columns on repo 6 |
| §17.5d adjacent-is-not-attached | **inference** | three instances; the structural claim rests on two independent readers missing the same caveat |
| §17.9 check-shaped-wrong | **inference** | five instances, each with its own transcript evidence |
| §17.10 name-versus-structure | **measurement** | pathspec match table; InsurIQ 7,698/7,715 skipped, 67 kept |
| §17.11 signal must discriminate | **measurement** | top-directory shares across all six repos in this DB |
| §17.12 verified-a-different-thing | **measurement** | two verifications of the same fix returned 67 and 7,715 |
| §17.7 prediction derivation | **inference** | the method; the number it produced is a measurement |

A later session should treat the measurements as settled and the inferences as
claims to re-test. Two of the inferences are one-corpus generalisations, which
is precisely the error §17.0 exists to warn about.

### 17.0 The general rule (this is the important part)

> **Thresholds and inertness claims calibrated on small young repositories are
> PROVISIONAL until a mature large repository has been through them.**

Not "may need adjustment" — provisional. Two independent axes reversed on first
contact with a real corpus, and both reversals ran the same way: a signal that
looked absent was merely absent *at that scale*.

The failure was never in the measurements. §10.1 and §10.3 correctly described
their sample. The failure was in the inference — reading "did not occur in this
corpus" as "does not occur", and then acting on it by calling an axis
decorative and deferring the work to fix it.

Small repos are biased in ways that specifically suppress structural signals:
fewer modules (fewer chances to form a cycle), shorter history (churn is
degenerate), fewer contributors (ownership carries no information). Every one
of those is a **sampling** property, not a property of software.

**Two different bars, and conflating them would repeat the mistake in a new
costume:**

| Claim | Evidence required |
|---|---|
| *"This marker does not discriminate"* | **one** repository above roughly 2,000 files with several years of history. One counter-example refutes an inertness claim outright |
| *"This marker fires at rate X"* / any threshold set from that rate | **several** repositories, across **different language ecosystems and architectural styles** |

Superset establishes that `cycle_participation` fires. It does **not** establish
that 12.7% is typical. Superset is a Python monolith with Django-style import
patterns — circular imports between models, views and registries are idiomatic
there. A Go or Rust corpus could legitimately show near-zero, and a JS monorepo
something else again.

Refuting inertness needs one counter-example. Calibrating a threshold needs a
sample. Treating this single large repo as calibration would replace
"calibrated on three small repos" with "calibrated on one large one" — a
different error of the same kind, and a more confident-sounding one.

### 17.0b A prediction is only evidence if you had a mechanism for it

Predict-before-measuring is load-bearing in this project. It degrades into
theatre the moment it covers guesses as well as derivations, and both happened
in the same session:

| Prediction | Basis | Result |
|---|---|---|
| Architecture mean **95** (94–96) | SCC sizes were already persisted, so the severity ramp could be applied to the real distribution in advance (§17.7) | **7 of 7 correct** |
| Job wall clock **4–9 min**, ingest dominant | Intuition about runtime — on a machine whose timing had been called unmeasurable an hour earlier | **114 s**, health dominant. **1 of 5 correct** |

The difference is not luck or care. The first was **arithmetic over data
already in the database**; the second was a feel for how long something takes.

**The rule:** before writing a prediction down, name its mechanism. If the
mechanism is "an existing table plus a formula", the prediction is evidence and
a miss is informative. If it is "roughly, from experience", say so, or **decline
to predict** — a soft number offered with a confidence rating still reads as a
derivation to anyone reading the record later, including you.

**And a third clause, which the two examples above do not illustrate:
naming a mechanism is not sufficient. The mechanism must be checked against
what the instrument actually measured.**

The case that produced this clause, from the cold-ingest planning:

> `files_parsed: 5` in a `parsing` stage lasting 14.4 s. The obvious per-file
> parse cost is `14.4 / 5 = 2.9 s`.

That has a mechanism, is arithmetic over measured quantities, and is wrong by
roughly three orders of magnitude. The stage reads and SHA-256s **all 6,516
files** to decide which changed; the 14.4 s is 6,516 hashes plus 5 parses.
Dividing by 5 attributes the hashing to parsing. Dividing by 6,516 measures
hashing and calls it parsing. **Neither denominator is the population the
numerator was generated over** — which is §17.5d's shape, arriving in a
prediction instead of a document.

A prediction of this kind fails *more* convincingly than an intuited one,
because it presents as a derivation. The check is one question: **what
population did this number get measured over, and is it the population I am
dividing by?**

#### A fourth clause: a prediction that lands does not validate its model

Repo 4's cold ingest was predicted at **15–35 s** from per-stage costs measured
on superset. Actual: **22.7 s** — inside the range. The model was still wrong:

| Stage | Predicted | Actual | |
|---|---|---:|---|
| discovering | 3–8 s | **1.6 s** | over-estimated by ~4 s |
| cleanup | *not modelled at all* | **6.7 s** | second-largest stage, omitted |
| resync / parsing / ranking / health | — | — | close |

Two errors of opposite sign, roughly equal size, cancelling. **The range held
because the mistakes offset, not because the reasoning was right.**

This is not bad luck; it is what a range does. The wider the interval, the more
room there is for offsetting errors, and the more likely a hit becomes
independent of whether the model is any good. A prediction that lands is
evidence about the *number*; it is not evidence about the *derivation*.

**The rule: check the components, not just the total.** A prediction with named
per-stage costs must be scored per stage. If only the total is compared, a
model with a missing term and a compensating over-estimate is indistinguishable
from a correct one — and the model is the reusable part.

Consequence for the open work: **the cold-ingest model is unvalidated despite
the prediction holding.** The per-file figure derived from that run
(0.5 s / 67 files ≈ 7.5 ms per file for parse plus extract) is an
order-of-magnitude estimate from a Python-heavy 67-file sample against a mixed
6,516-file corpus, and it omits `cleanup` entirely — a stage now known to cost
6.7 s on a repo with **zero deletions**, i.e. one whose cost is not
proportional to work done.

#### The correct decomposition, for when cold ingest is measured

Three components with different behaviours, which is why a single "cold is
slower" multiplier would be wrong in both directions at once:

| Component | Cold vs warm | Measured basis |
|---|---|---|
| Read + hash | **unchanged** — every file is hashed either way | inside `parsing`'s 14.4 s |
| Parse + extract | **the only part that grows** | nearest real figure is `collect_inputs`: 35.5 s / 6,516 files ≈ **5.4 ms/file** full tree-sitter parse — adjust upward, since ingest's extractors also emit symbols and import rows |
| Resolve | **already at full cost** | re-resolves every row on every ingest by design; 20.4 s over 60,672 rows is not a warm-path saving |

Resolution is the component most likely to be double-counted by someone
reasoning that cold means everything is slower. It does not change at all.

The second prediction also failed for a reason worth keeping separate from its
mechanism: **it described a cold ingest and measured a warm one.**
`files_parsed: 5, files_skipped_unchanged: 6511` — a 99.9% cache hit. The cold
path, which is what a new user hits and where parse and resolve scale by orders
of magnitude, **remains untested at this scale**. "How long does first analysis
take" is the first question any user asks and the answer is currently unknown.

*(Since resolved: the cold run is §17.14. It cost 477.9 s and produced the
fifth clause below.)*

#### A fifth clause: structure and magnitude are separately predictable, and only one of them was

The cold-ingest prediction (§17.14) was scored per stage, per the rule above.
The result splits cleanly in a way a single score would have hidden:

| What was predicted | Score |
|---|---|
| **Structure** — which stages scale with a cold cache, which are flat | **8 of 10** |
| **Magnitude** — the seconds per stage | **2 of 10**, and every miss low, by 1.8× to 4.7× |

Eight misses in one direction is a bias, not error. A model wrong at random
overshoots somewhere.

The two halves came from different places. The structural claims were reasoning
about **what the code does**: parsing is gated on a content hash so it scales
with a cold cache; resolution re-resolves every row by design so it does not.
Those held. The magnitudes were **arithmetic over a 67-file Python sample**
extrapolated to a mixed 6,516-file corpus — the same too-small, too-unlike
sample §17.5d warns about, used as a rate.

**The rule: score structure and magnitude separately, and report them
separately.** They have different mechanisms, different failure modes, and
different worth. A structural claim is reusable and falsifiable — "resolution is
flat" is either true or not, and the warm run settled it. A magnitude carried
from an unrepresentative sample is a guess wearing arithmetic, and per the third
clause the check is the same one: *what population was this rate measured over,
and is it the population I am applying it to?*

Note also that one of the two magnitude "hits" does not count. `clustering` was
predicted at 20 s and came in at 16.2 s, but had been labelled *widest
uncertainty, never timed* before the run. **A hit inside a band declared
unreliable is not evidence of a model** — it is the fourth clause again, at the
level of a single stage.

### 17.1 `cycle_participation` — reversed

§10.3 concluded the marker was **empirically inert**: zero file-level cycles
across 599 files, verified two independent ways.

| Corpus | Files | Files in cycles |
|---|---:|---:|
| §10.3 | 599 (3 repos) | **0** (0.0%) |
| superset | 6,516 | **828** (12.7%) |

Largest strongly connected component: **604 files**. Size distribution: 604,
100, 30, 12, 9, 7, 6, 5, then a tail of 2–4.

**The honest phrasing, and the one adopted:** the §10.3 finding held for the
corpus tested and does not generalise. It was correct about its sample and
wrong about the world. Not a refinement — a reversal.

Consequences, now measured rather than projected:

- Architecture Health on superset: **9.499**, with **p10 = 6.00** — the
  tenth-percentile file sits exactly at the saturated cycles-category cap. The
  axis produced a distribution for the first time in its existence.
- `cycle_participation` mean deduction **0.4732**, against **0.0000** across all
  three small repos.

### 17.2 `bidirectional_coupling_hub` — same shape, smaller magnitude

Described in analysis as "looking for a shape that does not exist in practice",
on the evidence that eslint's most-imported file (fan-in 192) had
`min(fan_in, fan_out) = 4`.

| Corpus | Fire rate |
|---|---|
| small repos | 0.6 – 1.3% |
| superset | **2.3%** (152 of 6,516), warn 4 → saturate 16 |

**Correct phrasing: rare, not absent.** The marker works and identifies an
uncommon configuration. "Does not exist in practice" was too strong and is
withdrawn.

### 17.3 The rename limitation, with a number

`_collect_git_history` now runs `--name-only --no-renames` (§17.4). With rename
detection off, A renamed to B appears as A deleted and B created: churn on A
stops at the rename, B starts fresh.

Measured on superset: history covers **24,835 paths against 6,516 files
currently in the tree** — roughly **18,000 paths that no longer exist**,
comprising deletions and pre-rename names.

Cost, stated plainly: a renamed file carries only the commits made under its
current name. On a repo mid-way through a rename-heavy refactor this
underweights exactly the files most recently reorganised. Accepted because the
alternative is that large repositories cannot be ranked at all — but it is a
real cost, and any reading of churn numbers should carry it.

**Verified not to lose data here:** all 6,516 current files matched a history
entry; none was orphaned.

### 17.4 Why the history pass was rewritten

Four defects, nested, each masking the one beneath it:

```
180-second timeout
  masking a UnicodeDecodeError
    masking a None stdout
      masking an AttributeError
```

**The ordering is the lesson.** The obvious response to a timeout is to raise
the budget. Doing so would have produced a *fast* run returning **no history,
silently, via None** rather than loudly via timeout — supporting the conclusion
that superset has no usable git history. The bug would have become permanent
and invisible. Fixing the symptom would have destroyed the evidence.

| Command, on a `--filter=blob:none` clone | Time |
|---|---|
| `git log` (no diff) | 2.3 s |
| `git log --numstat` | ~427 s (extrapolated; timed out at 180 s, twice) |
| `git log --name-only`, rename detection on | > 600 s, killed |
| `git log --name-only --no-renames` | **8.45 s** |
| full history pass, after both fixes | **4.2 s** |

Rename detection compares file **contents**. On a blob-filtered clone the blobs
are not local, so every rename check became a lazy fetch from the remote —
thousands of network round trips disguised as CPU cost. Our own clone
optimisation was breaking our own history pass; the two decisions were made in
different modules and never met.

The decode failure was separate and **Windows-specific**: `text=True` decodes
with the system codepage (cp1252 here) and git emits UTF-8 author names. It
would **not** reproduce on Linux, where the default is UTF-8 — so any test
pinning it must force a non-UTF-8 decode or feed bytes directly, or it passes
on CI for the wrong reason.

### 17.5 Every text I/O boundary needs an explicit encoding — including the ones that don't look like boundaries

Two incidents, one lesson, and the second one is the evidence.

**Incident A — the one we were documenting.** `subprocess.run(text=True)`
decoded git's UTF-8 output with the system codepage (cp1252). Recorded as §17.4.

**Incident B — committed while writing that record.** Appending §17 and the
decision-log entries was done with PowerShell:

```powershell
$s = Get-Content scratch.md -Raw          # BOM-less file -> read as cp1252
Add-Content docs/contract.md -Value $s -Encoding utf8   # re-encoded
```

`Get-Content` in PowerShell 5.1 defaults to the ANSI codepage for a file with
no BOM. It read UTF-8 bytes as cp1252, and `Add-Content` faithfully re-encoded
the mojibake, so every em-dash in the new sections became `â€"`. Both documents
were truncated at the section marker and re-appended through Python with an
explicit encoding; verified afterwards as zero mojibake markers, 102 and 132
em-dashes intact, no stray BOM.

**Why this belongs in the record rather than in a process note.** The second
incident happened roughly twenty minutes after documenting the first, in the
same session, by the same author, through a different tool with the same wrong
default. That is not irony — it is the actual evidence about this failure mode:

> **Knowing about a defect class does not protect you from it when the default
> is wrong and the failure is silent.** Only an explicit encoding at the
> boundary does. And the boundaries you will miss are the incidental ones —
> reading a scratch file to append to a doc does not feel like a text I/O
> boundary, which is exactly why it bit.

Both incidents share the mechanism with §17.5b below: a Windows default that is
correct for local text and wrong for anything that has travelled.

#### The audit, and why its result is a coverage finding rather than a clean bill

A grep for text I/O without an explicit encoding returned **48 hits across
`app/`, `tests/`, `scripts/` and `alembic/`**. Both hits in production code
were **false positives** — the `encoding=` sat on the continuation line of a
multi-line call, which a line-based regex cannot see:

```python
(MODULES_DIR / f"{module.slug}.yaml").write_text(
    yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
)
```

The read side is explicit too. The remaining 46 are test fixtures writing pure
ASCII. **Production Python was already clean.**

That is not a clean bill of health. It is a **coverage finding**, and the gap
is the point:

> This project does text I/O in **two** languages. Python, which is explicit
> and clean. And PowerShell, which defaults to the ANSI codepage for BOM-less
> files and has now caused **both** encoding incidents. The audit only speaks
> Python. It checked the place the bug was not, found nothing, and returned a
> 100% false-positive rate on the two hits it did surface.

So the fix is not a better grep — a line-based regex against multi-line calls
will always produce that error shape, and knowing the audit's blind spot
matters more than its output. The fix is a rule about the *tool*:

> **Standing rule.** PowerShell that touches project text passes
> `-Encoding UTF8` explicitly on every read *and* write, or the operation goes
> through Python instead. Prefer the second. Recovering from incident B meant
> re-appending through Python — that should have been the default, not the
> recovery.

`Get-Content` needs `-Encoding UTF8` just as much as `Add-Content` does. The
general form is worth stating on its own, because it explains why the failure
was silent:

> **A correct operation faithfully preserves whatever an earlier one got
> wrong.** The write in incident B specified `-Encoding utf8` and did exactly
> what it was told — it encoded the mojibake perfectly. Inspecting the write
> side showed nothing amiss, because nothing *was* amiss there. Correctness at
> one layer disguises failure at another, and the layer that looks healthy is
> the one you check first.

**Is this cascade suppression?** No — and the distinction is worth keeping
sharp, because a pattern that absorbs every nearby defect stops being a useful
check. Cascade suppression's defining property is a **discard**: signal exists,
is correct, and is thrown away by a coarser guard. Its diagnostic question —
*is this discard necessary, or merely convenient?* — has something to bite on.

Here nothing is discarded. Every byte is preserved, faithfully, including the
corruption. Call it **faithful propagation**: a correct operation carrying an
upstream error forward without signalling. The shared symptom is that a healthy
layer masks a sick one; the mechanisms are opposites — one loses data that
exists, the other keeps data that is already wrong. They need different
diagnostics, so they are recorded as siblings rather than merged.

### 17.5c Clustering agreement is uninformative below a certain cluster count

A third small-corpus artifact, same family as §17.1 and §17.2.

| Repo | Clusters (modularity / Louvain) | Agreement |
|---|---|---|
| Athena-OS | 4 / 4 | **100%** |
| superset | **255 / 240** | **83.3%** |

Perfect agreement on repo 1 was read as two independent algorithms confirming
each other. It is closer to the null result: **there are not many ways to
partition a tiny graph**, so two methods landing on the same answer is nearly
forced. Agreement only carries information once the space of possible
partitions is large enough for the algorithms to disagree.

83.3% across 255 clusters is a real measurement about the methods. 100% across
4 is a measurement about the corpus.

**Applies to any agreement or concordance statistic in this project**, not just
this one. Report the denominator alongside the rate, treat a perfect score on a
small population as evidence of a small population, and **treat a difference
smaller than the resolution of the population as no difference.**

Applied retroactively to the ESLint validation, where the scorers were reported
as `weighted_pagerank` 3/20 against `legacy` and `rrf` at 2/20. That is a
**one-component** gap at n=20 — and the same document records `legacy` moving
3/20 → 2/20 on a single-item swap between runs in which nothing about `legacy`
changed. The finding was always "all three fail against a threshold of 12",
never "weighted PageRank does marginally better"; the ordering was quoted as if
it meant something and it did not. Correction recorded in
`external-validation-eslint.md`.

Note what the two cases have in common: the Spearman column in that table
already said "not meaningful" for n=2 and n=3, and the Overlap@20 column beside
it did not. The caveat existed, on the neighbouring statistic, and was not
carried across.

#### Related: the unclustered rate is structural, not a threshold judgement

superset leaves **1,064 of 6,516 files unclustered (16.3%)**, under the 30%
"clustering is not working here" threshold. But the aggregate is not the
evidence — the breakdown by graph degree is:

| Graph degree | Unclustered |
|---|---|
| 0 edges | **1064 / 1064 (100%)** |
| 1 edge | 0 / 1503 |
| 2+ edges | **0 / 3949** |

Clustering runs over the co-import graph, so a file with no edges **cannot** be
clustered. Every unclustered file is a genuine singleton and no file with any
edge is missed. That is a structural certainty rather than a threshold that
happened to pass. Composition confirms it: 163 are `superset/migrations/
versions`, Alembic files that import nothing and are imported by nothing.

**One number in that breakdown must not be quoted alone:** javascript reads
66.2% unclustered — which is 45 of **68 files**, root-level config scripts. A
base-rate artifact, not a language-specific gap. The denominator is the finding.

### 17.5d Adjacent is not attached — a caveat that exists and does not travel

Third recurring shape, distinct from cascade suppression and from faithful
propagation (§17.5). Here **nothing is discarded and nothing is corrupted**.
The needed information exists, is correct, and sits near the place it is
needed — and does not reach it.

**Instances:**

1. **§10.3's sample-size limit.** The section itself said three repos was too
   small a corpus to conclude file-level cycles are rare in general. That
   sentence was written, then reasoned past within the same document, and the
   marker was declared inert.
2. **The `evidence_complete` → `inputs_complete` rename.** Applied correctly to
   the models. Not applied to the database. Correct in one representation of
   the schema, absent from the other, one file away.
3. **The Spearman caveat, one column over.** In the ESLint results table, the
   Spearman column reads *"1.000 (n=2 — not meaningful)"*. The Overlap@20
   column beside it, in the same row, computed over the same population of 20,
   carried no such note — and its 3-vs-2 ordering was then quoted as if it
   meant something.

#### Why this is a defect in the artifact, not a lapse in attention

Instance 3 has evidence the others do not. The 3/20-vs-2/20 ordering was read
as meaningful **by two people in different roles** — the author writing the
record and a reader working directly from the document — repeatedly, across
multiple turns. And the disconfirming evidence was in the same file: the same
document records `legacy` moving 3/20 → 2/20 on a single-item swap between two
runs in which nothing about `legacy` changed. That is the resolution of the
measurement, demonstrated by the measurement, sitting ten lines below the
table.

Two independent readers, disconfirming evidence present, both missing it. That
rules out attention as the explanation. **The document was structured so that
the caveat was not where the number was read.**

#### Two fixes, and only one of them works without anyone remembering

**For authors — the question:** *is there a caveat elsewhere in this document
that applies to what I am writing now?*

Honest about its weakness: it requires the reader to already suspect a caveat
exists. It is also uncomfortably hard to check mechanically, which is probably
why the shape recurs. Useful, but it depends on the very attention whose
absence it is meant to cover.

**For artifacts — the layout rule:** *a caveat about a population belongs in
the same cell or row as **every** statistic computed over that population,
repeated rather than referenced.*

Redundant. Ugly. Puts "(n=20)" beside numbers that share a table header already
saying so. And it would have worked — in instance 3 the fix is literally
copying six characters one column to the left, and no one would have needed to
remember anything.

**Prefer the second.** The first depends on a person; the second is a property
of the document. Where they conflict, ugliness loses.

### 17.5b Known, unfixed: non-ASCII paths lose their history silently

`core.quotepath` defaults to true, so git emits a non-ASCII path escaped and
quoted (`"src/\303\251t\303\251.py"`). That string matches no `CodeFile.path`,
so the file's history is dropped with no error and no marker.

**Not observed on superset** — it has zero non-ASCII paths, which is why all
6,516 files matched. Latent, not theoretical: one accented filename in a future
repo and that file silently reports no churn.

Recorded as unfixed. The likely fix is `-c core.quotepath=false`, which trades
escaping for raw UTF-8 and moves the burden to the decoder — where
`errors="replace"` could then put U+FFFD in a path, failing the same way. Needs
its own pass, not a one-liner.

### 17.6 What superset validates about the model

Aggregate: **superset ~95, Athena-OS 97.**

This is the first time the large mature codebase has scored **below** the small
young one, and the architecture axis is what does it. Every prior comparison had
the model rewarding youth — a repo with too little history for churn to resolve
and too few modules to form a cycle scored well by having nothing measurable
held against it.

No amount of further small-repo testing could have produced this result. It is
the strongest evidence the scoring approach has, and it arrived only because a
real corpus was put through it.

### 17.7 How the Architecture prediction was derived

Recorded because the reasoning is reusable and the number is not.

Before the run, the SCC size distribution was already known from the persisted
`scc_size` column. `cycle_participation` ramps `severity = (size − 1) / (12 − 1)`
and carries weight 4.0, capped by the cycles category at 4.0. So:

- sizes ≥ 12 saturate → full 4.0 deduction → score 6.0. That is 604 + 100 + 30 +
  12 = **746 files**.
- sizes 5–9 → roughly 1.45–2.91 deduction → ~7.9 average, **27 files**.
- sizes 2–4 → 0.36–1.09 deduction → ~9.3 average, **55 files**.
- the remaining **5,688 files** score 10.0.

Weighted mean: `(746×6.0 + 27×7.9 + 55×9.3 + 5688×10.0) / 6516 = 9.53`.

Predicted **95** with a 94–96 band; actual **9.499 → 95**. The band existed
because `bidirectional_coupling_hub`'s contribution was unknown — it turned out
to add 0.0276 mean deduction, pulling the result to the lower half of the band.

The generalisable part: when a marker's inputs are already persisted, its
distribution is computable in advance and a prediction becomes arithmetic
rather than intuition. That is the difference between calibration and a guess.

### 17.8 The real job path at scale — job 19, apache/superset

Everything in §17.1–§17.7 was measured by calling `rank_repo` and
`create_snapshot` **directly from a script**. That verifies the algorithm. It
does not verify the product: the per-repo lock, SSE stage transitions,
transaction boundaries, progress throttling and tripwires all live in
`jobs.py`, wrapping the call. The timeout fixed in §17.4 lived in exactly that
layer.

Job 19 ran the path a user actually triggers — `resync → ingest → rank →
health` — end to end on 6,516 files.

| Stage | Duration |
|---|---:|
| resyncing | 19.4 s |
| discovering | 2.1 s |
| parsing | 14.4 s |
| resolving | 20.4 s |
| ranking_graph | 8.2 s |
| ranking_history | 11.3 s |
| ranking_scoring | 2.9 s |
| health | 35.5 s |
| **total** | **114.1 s** |

No tripwire fired, no stage hung, no lock contention, no failure. **And the
numbers match the direct-script run to three decimals** — 9.61 / 9.499 / 0.471
across both. That retires the concern that §17.1–§17.7's findings were an
artifact of bypassing the job layer; they stand without re-derivation.

**Warm, not cold.** `files_parsed: 5, files_skipped_unchanged: 6511`. This
measured an incremental ingest with a 99.9% cache hit. A first ingest of a repo
this size is still untested and is the largest remaining unknown about real
product behaviour — see §17.0b.

#### Two defects it exposed

**48% of wall clock had no progress reporting.** `resolving` (20.4 s) and
`health` (35.5 s) each emitted one message and never updated — 55.9 s of 114.1 s
where the UI cannot distinguish work from a hang, confirmed live at
`stage=resolving, progress=0/0`. Both stages have natural units to count, so
this was instrumentation, not architecture: `resolving` now reports against the
import-row count (known before the loop starts), and `collect_inputs` samples
through the AST pass. On a cold ingest these two stages dominate, so the
problem was worst exactly where it mattered most.

**Subsystem clustering was not in the pipeline at all.** It was reachable only
through `POST /subsystems`, which nothing in the normal path calls — so every
repo analysed the way a user analyses one had an empty Dependency Clusters tab
and `CLUSTERS: 0` on the Overview, with a complete import graph sitting right
there. A whole phase of work invisible to anyone who did not know to invoke it
directly.

Now a stage between rank and health, with the same error boundary as health: a
clustering failure is recorded as retryable and never costs the completed
ingest. Only modularity and Louvain run there — HDBSCAN stays on demand,
because it embeds every file's symbol text where the other two are near-instant
graph maths over a graph that already exists.

#### Verified by refresh, not by assertion

A fresh page load taken while job 21 sat in `resolving`, with no in-memory job
state — i.e. a refresh:

```
+0.0s   resolving (1000/60672)
+9.0s   resolving (4500/60672)
+18.0s  resolving (9500/60672)
+35.1s  resolving (19500/60672)
```

40 samples, counter advancing 1000 → 19500, non-zero denominator throughout, no
page errors. The failure that would have passed a weaker check — recovering
into a frozen `resolving 0/60672` and then jumping to complete — did not occur,
and the sample sequence shows that rather than asserting it.

**One honest note about the method.** The sampling interval was tightened from
1.5 s to 600 ms out of a fear of collecting too few samples in a 20-second
stage. In this run the concurrent test suite stretched `resolving` to 35
seconds, so the original interval would have produced ~23 samples and been
perfectly adequate. The tightening was correct against the timing that had
actually been measured (the warm run's 20.4 s) and unnecessary against the
timing that occurred. Recorded because "the fix worked" and "the fix was needed
for the reason given" are different claims, and only the first is demonstrated
here.

This is a different failure shape from cascade suppression, and worth naming as
such: nothing was discarded and nothing was wrong. **The feature simply was not
on the path anyone takes.** It worked perfectly whenever tested deliberately,
which is why it survived. The check it suggests: *for each feature, which
user-triggered path reaches it?* — and if the answer is "none", the tests are
measuring an unreachable capability.

### 17.9 Check-shaped-wrong — the instrument assumed a guarantee the system doesn't make

Eight instances. None was a defect in the system under test; all were defects
in the instrument used to check it. **Cost: time.** Split from §17.12, which is
a distinguishable and more dangerous failure — see there.

| # | Instrument | What it assumed | What was true |
|---|---|---|---|
| 1 | `grep` for `open(` without `encoding=` | text does not wrap | `encoding="utf-8"` sat on a continuation line → 100% false positives |
| 2 | `grep` verifying a doc edit landed | text does not wrap | probe spanned a line break → false negative on present text |
| 3 | Reading a background task's output file | a file read is complete | read an accumulating file mid-write, concluded the run had not started, launched a redundant 30-minute suite |
| 4 | `page.waitForTimeout(4000)` | the page paints within a fixed time | repo 6 takes ~5 s for a 6,516-file payload → read a loading page as a failure state |
| 5 | `Stop-Process -Force` | a command's report is its outcome | printed "killing PID 32536" four times while the process was already gone and a draining socket kept answering 200 |
| 6 | `discover_files_with_stats` called directly | a direct call and the running server execute the same code | see §17.12 — this one produced a false finding, not just lost time |
| 7 | a malformed API payload as a boundary stimulus | the payload will throw | `?? []` coerced it, so nothing threw — "boundary broken" and "no error occurred" were indistinguishable (see §15.1's inverse clause) |
| 8 | canary injecting a throw at `s.index("{", i)` | the first brace after a function name opens its body | it opened the destructured **parameter list**; the file never compiled and the run read as a boundary failure |

**The common property:** *the instrument assumed a guarantee the system does not
make.* Text may wrap. A file may still be being written. A page paints when it
paints. A command reports intent, not effect.

**Guard: do not trust a report of an action; observe its effect.**

Instance 5 shows the shape most cleanly, and its fix shows the discipline: the
writer was confirmed dead not by trusting `Stop-Process`, but by sampling
`count(*) from code_files` twice six seconds apart and seeing it unchanged. The
effect, not the report.

Adjacent to §15.1's canary rule but a distinct discipline. §15.1 asks *can this
check fail?* — a property of the check itself. This asks *is this check
observing the thing it claims to observe?* — a property of the check's
relationship to the system. A canary-verified test can still measure the wrong
quantity, and instances 1 and 2 were both perfectly capable of failing.

### 17.10 Name-versus-structure: a name enumeration is silently incomplete

> **Generalised by §17.15.** This entry states the rule for one case --
> names versus a structural marker -- and its guard and counter-case below
> stand unchanged. §17.15 widens it beyond names, and adds a second failure
> mode this entry does not describe: failing by MISCATEGORISATION rather
> than by omission, which removes the evidence of a defect instead of
> leaving it in place.

A repository with a committed virtualenv had **7,715 files discovered, 7,698 of
them third-party** — matplotlib, jupyterlab, IPython — ingested as the project's
own source. Real file count: **67**.

`DEFAULT_EXCLUDES` listed `venv/` and `.venv/`. The directory was named
`venv310`. The exclusion was name-based; the thing it was trying to exclude has
a structural marker.

| Approach | `venv/` | `venv310/` | `env/` | `virtualenv/` | Scripts, Include |
|---|---|---|---|---|---|
| Name enumeration | caught | **missed** | **missed** | **missed** | **missed** |
| `pyvenv.cfg` (PEP 405) | caught | caught | caught | caught | caught |

**Guard: where a structural marker exists, prefer it — a name enumeration is
always incomplete, and the incompleteness is silent.** Nothing failed. 7,698
files of pip packages were parsed, symbol-extracted and import-resolved without
one error.

#### The counter-case that makes the rule precise

The rule is not "replace names with more names". Three candidates were
deliberately **not** added, recorded in `discovery.AMBIGUOUS_NOT_EXCLUDED`:

- **`bin/`** — interpreter shims in a virtualenv, first-party scripts almost
  everywhere else. `bin/eslint.js` is a file this project validates its ranking
  against; a `bin/` pattern would have deleted it from the analysis. Caught
  instead by `pyvenv.cfg`, which is unambiguous about *which* `bin/` it means.
- **`Scripts/`** — same, Windows layout.
- **`packages/`** — NuGet dependencies in a .NET solution, first-party source in
  a JS monorepo. It is real code on both `apache/superset` and
  `palmerhq/monorepo-starter`.

So the rule is sharper than "prefer structure": **a name that means third-party
code in one ecosystem and first-party source in another cannot be a pattern at
all.** Only structure can separate those, and where no structural marker exists
the honest move is to exclude nothing and record why.

### 17.11 A signal must discriminate, and a warning that cries wolf is worse than none

A tripwire was specified: warn when more than 50% of discovered files sit under
one top-level directory that is not the source root. It was built, measured
against all six repositories in this project's database, and discarded.

| Repo | Top directory | Share | Verdict |
|---|---|---:|---|
| eslint | `lib/` | 393/398 = **98.7%** | correct — a library's source lives in `lib/` |
| Athena-OS | `backend/` | 144/224 = 64.3% | correct |
| superset | `superset-frontend/` | 3903/6516 = 59.9% | correct |
| AFDE | `frontend/` | 15/28 = 53.6% | correct |
| InsurIQ | `backend/venv310/` | ~7000/7715 ≈ 90% | **broken** |

**Four fires, zero true positives — and the broken case sits BELOW the most
correct one.** ESLint at 98.7% is exactly right; InsurIQ at 90% is exactly
wrong. No threshold separates them, because concentration was never the
discriminating property. The property was that InsurIQ's dominant directory
held third-party code — which is what the exclusion rules detect directly.

**Guard: before shipping a signal, measure it against known-healthy inputs. A
signal that does not separate healthy from broken is not a weak signal, it is
not a signal.**

And the reason it must be caught before shipping rather than tuned afterwards:
**a warning that fires on two-thirds of healthy inputs trains its reader to
ignore it**, which is strictly worse than no warning — it costs attention and
then spends the credibility that would have made a real alert land.

#### What shipped instead

A count of what discovery excluded:

```
7,698 source files were skipped as vendored or generated and are not
part of this analysis (largest: backend/ (7698)). Kept 67.
```

**It has no false-positive mode**, because it asserts a fact rather than
inferring a judgement. On the five healthy repos it is silent; on InsurIQ it
says the thing that mattered. A test asserts the wording contains none of
"suspicious", "probably", "may be wrong", "warning" — §15.1's mechanical-check
discipline applied to prose.

This was a correction to an explicit instruction, recorded as such rather than
substituted silently. The instruction named the right requirement — *7,000 of
7,719 files under one directory should have been one line* — and the wrong
signal for it.

### 17.12 Verified-a-different-thing — the check exercised a different code path than the fix

Split from §17.9 because the cost is different in kind. Check-shaped-wrong
costs time: the instrument misreports, you notice, you re-run. This produces a
**false finding** — a number that enters the record and is wrong.

**The instance.** The vendored-code exclusion (§17.10) was verified two ways
that were assumed to agree:

1. **Direct call** — `discover_files_with_stats(root, ...)` in a fresh Python
   process. Returned **67 kept, 7,698 skipped**. Correct.
2. **Through the job path** — `POST /api/repos/4/jobs` against the running
   server. Returned **7,715 files**, i.e. the fix appeared not to work.

Both were run after the edit. Both were believed to exercise the same code. The
direct call loaded the module from disk; the server was still holding the
pre-edit module, so the two differed by exactly the change under test.

**Why the server was stale, which is the part worth reading twice.** An earlier
"restart the backend" step did:

```
taskkill /F /PID <old>     -> exit 128, "process not found"
Start-Process run.py       -> new instance hits main.py's port guard, dies
Invoke-WebRequest /docs    -> 200
```

Every signal was consistent with success. `taskkill` "failing" looked like the
process was already gone; the `200` looked like the new server answering. It
was the **old** server, which had never stopped, answering on a port the new
instance had just been refused. The port guard in `app/main.py` exists to catch
exactly this and did its job — the message went to a redirected log nobody read.

Had the direct call not also been run, "the exclusion fix does not work" would
have gone into the record as a finding, with a plausible mechanism attached.

**Guard: when verifying a server-side fix, confirm the SERVING PROCESS is
running the new code — not that some process answers.**

Concretely, and this is now the routine:

```powershell
$proc = Start-Process ... -PassThru
$listener = (Get-NetTCPConnection -LocalPort 8000 -State Listen).OwningProcess
(Get-Process -Id $listener).StartTime   # must match the launch second
```

The serving PID's start time has to match when you launched. A `200` proves
*something* is listening; it proves nothing about *what*. With `reload=True` in
`run.py` the reloader's child differs from the launched parent, so comparing
PIDs directly does not work — the start time does.

**The general form**, beyond servers: any fix verified through a long-lived
process — a dev server, a worker, a REPL, a cached import, a warm container —
needs the process's identity confirmed, not its responsiveness. Two code paths
believed identical is the failure; the check is to make one of them prove which
code it holds.

### 17.13 Self-amplifying cost — when slowness causes more of the operation that caused it

A slow function is a slow function. This is a different animal: **a periodic
operation whose frequency is driven by elapsed time, and whose cost is charged
to the same elapsed time.** Slowness produces more occurrences, which produce
more slowness. It is a loop, not a rate.

**The instance.** `jobs.py`'s progress callback committed whenever
`_PROGRESS_WRITE_INTERVAL` (0.3s) had passed, so the SSE stream could see the
job row change. SQLAlchemy expires all loaded objects on commit by default, and
by the resolution stage that session held ~90k of them (6,522 files + 22,856
symbols + 60,865 imports). Every commit therefore invalidated the working set,
and the loop re-SELECTed each row the moment it next touched an attribute.

Resolution on apache/superset went from ~20s to ~90s. It was not read as a
regression for two ingests, because a plausible story was available: the
per-500-row progress reporting had been added deliberately, so of course
reporting costs something.

**The measurement that identified the loop.** Reducing the commit frequency —
the obvious fix — bought back far less than proportionally:

| commits | resolving | over silent | cost per commit |
|--------:|----------:|------------:|----------------:|
|     170 |    91.52s |      70.97s |           0.42s |
|      56 |    69.75s |      49.20s |           0.88s |
|      21 |    63.95s |      43.41s |           2.07s |
|       0 |    20.55s |           — |               — |

**8× fewer commits removed only 39% of the overhead, and the cost per commit
rose 5×.** That shape is the diagnostic. A per-call price is linear: halve the
calls, halve the cost. Here, rarer commits each expired a larger accumulated
set, so the total was roughly conserved while the per-call figure inflated to
match.

**The tell, stated generally: if halving the frequency does not roughly halve
the cost, you are not paying a per-call price — you are in a loop.** Any
throttled-commit, throttled-flush, time-based-checkpoint, periodic-GC or
autosave-on-a-timer pattern has this exposure.

**Why it also poisons the variance.** Two runs under *identical* conditions
measured 66.53s and 42.98s — a 1.5× spread that reads as machine noise and
would have been written off as such. It isn't noise. Commit count is
time-driven, so the slower run took more ticks, committed more, and was slower
for it. The loop amplifies any initial perturbation, so the spread is a
*symptom of the defect*, not a property of the machine. Writing it off as
variance is the wrong explanation for the right observation.

**Why the obvious fix was the wrong one.** Sampling harder — fewer callback
invocations — improves the number and leaves the loop intact, so the
improvement looks like a fix. The actual fix removes the coupling:
`expire_on_commit=False` on the job session, after which commit frequency stops
mattering and the interval is no longer load-bearing. Measured on the real job
path, warm: 183.5s → 94.3s, with resolution at 11.20s and output identical to
the digit (26,557 resolved, 254/241 clusters, agreement 0.8133015756687432).

**Two-layer diagnosis, and the layer that was nearly missed.** The first
hypothesis was that the callback ran per row. It does not — `ingest.py`'s
resolution loop calls `on_progress` once per 500 rows, so 60,865 rows produce
122 calls. That was checkable in the source before hypothesising, and checking
it is what moved the question from *how often is it called* to *what does each
call do*. Same shape as §17.12: a number was built on without first checking
what it measured.

**The scoping argument, which is what makes the flag correct rather than merely
faster.** `expire_on_commit=False` is applied to the job's session only, never
to `SessionLocal` globally — request sessions serving concurrent writers do want
the default, because staleness is a real risk when another writer exists. It is
safe for the job session specifically because ingest holds the repo advisory
lock (`repo_lock.py`) for its whole call, making that session the sole writer
for the duration: there is no concurrent mutation whose value it could go stale
against. A reader who finds the flag without that argument will reasonably
assume it is a shortcut, which is why the argument is written at the flag site
and not only here.

### 17.14 Cold ingest at scale — apache/superset, 6,522 files

The cold counterpart to §17.8's warm job 19, and the measurement §17.0b's fifth
clause was scored against. It existed to settle one design question: whether an
MCP server's first call can be synchronous.

**Method, because the number is only worth what the setup is worth.** Quiet
machine; one listener, no `--reload`, serving PID's start time matched to the
launch second (§17.12); parse cache invalidated by overwriting `content_sha256`
for repo 6 only, with the other six repos' hashes verified untouched; cold state
confirmed **in the job record** rather than assumed — `files_parsed: 6522`,
`files_skipped_unchanged: 0`.

**Result: 477.9 s (8.0 min).** Against the stated 5-minute threshold, that
settles it: **the first call cannot be synchronous; the interface needs an async
job handle from the start.**

| Stage | Cold | Warm | |
|---|---:|---:|---|
| parsing | 234.80s | 18.84s | **the only stage that scales** — 12.5× |
| resolving | 93.44s | 98.56s | flat, as predicted |
| health | 64.11s | *skipped* | not comparable |
| resyncing | 30.52s | 12.00s | cold fetched real commits |
| clustering | 16.23s | 16.39s | flat |
| ranking_graph | 14.72s | 14.61s | flat |
| ranking_history | 9.55s | 8.72s | flat |
| cleanup | 5.36s | 5.48s | flat, and not deletion work — see below |
| ranking_scoring | 4.33s | 3.80s | flat |
| discovering | 3.50s | 3.22s | flat |
| **total** | **477.9s** | **183.5s** | |

**The instrument had to be replaced before the measurement.** Every prior
per-stage figure came from the SSE stream, which polls a row written on a 0.3 s
throttle — so a stage's silence is charged to whichever stage last managed a
write. That is how 6.7 s once landed on `cleanup`, a stage independently
measured at 0.01 s. Stage times now come from marks taken in-process at the
transition itself, stored as `stage_seconds` in the job record. **Measuring with
a known-bad instrument produces a number nobody can use**, so replacing it first
was not scope creep.

**A property of every figure above, including the fixed ones: stage marks bound
labels, not work.** The 5.36 s `cleanup` interval contains **zero** deletions —
it is `ingest.py`'s flush of ~90k pending rows plus the load of all 60,865
import rows, both of which sit between the `cleanup` mark and the `resolving`
mark. The new instrument is honest about where labels change and silent about
what falls between them, which is one level down from the bug it fixed.

**The finding that outlived the headline.** Cold cost is a one-time price paid
knowingly. The warm floor is paid on every run, and at the time of measurement
**165 s of the 183.5 s reran regardless of what changed** — the parse cache
saved 45% and left a floor incrementality does not touch. That reclassified the
warm path from *pre-existing debt* to *blocks drift-detection-on-push*: a tool
that re-checks every push cannot cost three minutes.

That floor then turned out to be mostly artificial. Chasing why `resolving` had
gone from 20 s to 93 s found §17.13's feedback loop; removing it took the warm
job to **94.3 s**, with non-health non-resync work at **41.5 s** rather than
170 s. Drift-on-push is arguable at 40 s where it was not at three minutes —
though `health` (30.6 s) and `resync` (22.0 s) now dominate a full warm cycle
and neither has been looked at. The floor moved from *blocks Phase 8* to *Phase
8 needs its own look at health and resync*, which is progress, not resolution.

**The 477.9 s figure is pre-fix and now overstates cold cost.** It is
deliberately not re-measured: the decision it gates is unchanged either way, and
a fresh single run on a machine with ~1.5× between-run variance would trade an
honestly-labelled stale number for a falsely-precise new one.

### 17.15 Predicate-as-property versus predicate-as-list

**Supersedes §17.10**, which stated this rule for one case — name enumeration
versus a structural marker — and got the mechanism half right. §17.10's guard
("prefer a structural marker; a name enumeration is always incomplete") remains
correct and its counter-case (`bin/`, `Scripts/`, `packages/`) remains the
sharpest illustration. What follows generalises it beyond names, and adds a
second failure mode §17.10 does not describe.

**The general form:**

> **A predicate stated as a PROPERTY can be evaluated against a case nobody
> anticipated. A predicate stated as a LIST cannot, and its failure is silent.**

"Enumerations are incomplete" is the weaker version of this and it misses why
the incompleteness matters. A list does not merely omit — it cannot be
*consulted* about a new case. There is nothing to evaluate. The new case simply
does not appear, and no code path reports that it was not considered.

#### The three instances

| # | List-shaped predicate | Property-shaped predicate | What the list missed |
|---|---|---|---|
| 1 | `DEFAULT_EXCLUDES` naming `venv/`, `.venv/` | `pyvenv.cfg` exists in this directory (PEP 405) | `venv310` — 7,698 vendored files ingested as first-party source |
| 2 | Three separate `_IGNORED_DIR_NAMES` constants, 7 / 4 / 7 names, no two alike | one shared `discovery.iter_files_named` applying the same `pyvenv.cfg` rule | the same virtualenv, invisible from **three** code paths at once |
| 3 | "hide the filter bar on Overview and Findings" | "could a file filter meaningfully apply to what this view renders" | that **three other views** have the inverse defect |

Instance 2 is worth dwelling on because it shows the failure compounding. The
three lists were maintained independently and disagreed with each other; each
was individually plausible; none contained a virtualenv marker. Three chances to
catch the bug, three misses, and the divergence between the lists was itself
invisible until they were put side by side.

#### Two distinct failure modes, and the second is worse

**Failure by omission** — instance 1 and 2. The case is absent from the list, so
nothing happens. Nothing errors. 7,698 files of pip packages were parsed,
symbol-extracted and import-resolved without a single failure.

**Failure by miscategorisation** — instance 3. This one did not merely omit; it
would have produced a *confident wrong action*.

The instruction was list-shaped: hide the file filter bar on Overview and
Findings. Evaluating the property instead — *could a file filter meaningfully
apply to what this view renders* — separated two things the list conflated:

- **Filters inapplicable.** Overview is an aggregate landing page; Findings rows
  are (marker × directory). Nothing there is a file set. Correct fix: hide the
  bar.
- **Filters applicable and unimplemented.** Architecture and Matrix receive a
  server-built `dirGraph` plus the **unfiltered** `files`; `SubsystemsView`
  takes no filtered input at all. Their content *is* file-derived. Correct fix:
  honour the filters.

Same surface, same symptom — a bar that does nothing — **opposite fixes**. The
list version hides the bar on all five, which for three of them removes a
control that ought to work and buries a real defect under a cosmetic change. The
defect then becomes *harder* to find, because the visible symptom is gone.

**That is the sharper cost.** An omission leaves the bug where it was. A
miscategorisation removes the evidence of it.

#### How to tell which kind you are writing

A list answers *"is this one of these?"*. A property answers *"does this have
the quality I care about?"*. The test is whether a case that did not exist when
the predicate was written can be evaluated at all:

- `view !== "overview" && view !== "findings"` — a new view is silently included
- `keyedOnFiles: boolean` on each view definition — a new view **cannot be added
  without answering the question**

The second forces the author of the next case to categorise it. That is the
whole mechanism: not that properties are more complete, but that they make
omission impossible to express.

**Guard: state the condition, not the members. Where the members must be
enumerated anyway, attach the property to each member so a new one cannot be
added without evaluating it.**

Note the limit, inherited from §17.10's counter-case: this does not license
inventing a property where none exists. `packages/` means third-party in .NET
and first-party in a JS monorepo — no property of the *name* separates those,
and the honest move there was to exclude nothing and record why.

### 17.16 Report which instrument produced a number, not only its denominator

§17.5c requires the denominator to travel with a rate. This is the same rule for
**time**: when the instrument changes, a bare figure invites a comparison
against a figure the instrument could not have produced.

#### The instance

"2,733 findings" was quoted across three sessions, including in the instruction
that specified this work. The current figure is **6,649**. The corpus grew 13.7%
over the same period. A reader reconciling those two numbers concludes the
codebase got substantially worse.

It did not. Decomposed per marker, snapshot 6 against snapshot 13:

| Marker | Snap 6 | Snap 13 | Δ |
|---|---:|---:|---:|
| churn_volume | 0 | 2,745 | +2,745 |
| cycle_participation | 0 | 832 | +832 |
| complexity_under_churn | 0 | 175 | +175 |
| bidirectional_coupling_hub | 0 | 152 | +152 |
| the six maintainability markers | 2,733 | 2,745 | **+12** |
| **total** | **2,733** | **6,649** | **+3,916** |

Four markers went from producing **nothing** to producing 3,904 findings. Three
of them were the subjects of §17.1, §17.2 and §17.4 — `cycle_participation`
reversed, `bidirectional_coupling_hub` reversed, and churn dependent on the git
history pass that §17.4 rewrote. Snapshot 6 predates all three.

**So 2,733 was not a smaller measurement of the same thing. It was one working
axis out of three.** The six markers that worked in both snapshots moved by 12.

#### Why this needs a rule rather than a footnote

The contract now contains figures computed under different analyzer versions
sitting beside each other with nothing marking which is which. Every count
recorded before §17.1/§17.2/§17.4 describes a **different instrument**, and
nothing in the number says so.

The failure mode is not that someone recomputes and gets a surprise — that is
fine. It is that someone *compares two recorded numbers* and infers a trend from
an instrument change. That inference is unfalsifiable from the record alone: both
numbers are correct, both are labelled with their snapshot, and the conclusion
drawn from them is wrong.

**Guard: a recorded count carries its analyzer/thresholds version, or a note
naming what was broken when it was taken. A figure whose instrument has since
changed is not comparable and must say so where it is written, not in a section
someone might read.**

This is why `code_health_snapshots` stores `analyzer_version`,
`thresholds_version` and `weights_version` per row, and why `trend_delta`
refuses to compare across them — that mechanism was already correct for scores
and had no equivalent for prose. The rule above is the prose equivalent.

Same family as §17.5d: a caveat that exists somewhere and does not travel to
where the number is read is not a caveat.

**Extension, added after the fourth instance: this applies to INSTRUCTIONS
derived from the record, not only to numbers quoted from it.** Four times in one
session, work was specified against a stale reading of this repository's own
documents -- a §17 batch listing an entry that had already been written, a
"never run" validation that had run twice with the exact metrics being asked
for, a finding count from a superseded instrument, and a deferred item whose
recorded fix options no longer existed. Each instruction was internally
coherent and pointed at a state the record had already moved past.

A number carries its instrument. A plan carries the reading of the record it was
built from, and that reading has the same provenance problem -- with the
difference that nobody thinks to date a plan. **Before acting on a recorded
to-do, check the artifact it describes rather than the entry describing it.**

### 17.17 Count and size are inversely coupled in any fixed-depth grouping

> **At a fixed level of a hierarchy, group count and group size trade against
> each other, and no level satisfies both. This is a property of how the tree is
> shaped, not a tuning failure — so it cannot be fixed by choosing a better
> level.**

#### The measurement

The findings queue groups markers by directory. At the queue's default cut, on
apache/superset snapshot 13:

| Fixed level | Rows | Largest row |
|---|---:|---:|
| top 1 segment | 41 | 608 files |
| top 2 segments | 255 | 410 files |
| top 3 segments | 590 | 189 files |
| full parent dir | 1,335 | 122 files |

41 rows is scannable, and its top row is "every import cycle in the backend" —
true, and useless as a task. 1,335 rows have workable sizes and are no longer a
queue. The head and the tail move in opposite directions at every level, because
source trees are a few enormous directories and a long tail of small ones.

#### The resolution, twice

Roll up to a **budget**, not to a depth. Seed at the coarsest level and split
only what exceeds the budget:

| Cap | Rows | Largest row |
|---|---:|---:|
| 500 | 93 | 410 |
| **200** | **109** | **189** |
| 100 | 238 | 122 |
| 50 | 439 | 122 |

H1's directory rollup reached the same wall and answered it the same way, with a
cap of 24 groups. Two independent arrivals at the same answer is the evidence
that this is structural rather than a quirk of one view.

#### Irreducible groups, and why they must be marked

Below cap 100 the row count runs away while the largest row **stops shrinking**
at 122. That plateau is the diagnostic: `cycle_participation` across 122 files in
`superset-ui-core`, all in one directory. No cap divides them, because path depth
is the only axis the split has.

Such a group must be **marked, not silently left oversized** — otherwise the next
person tunes the cap trying to fix a row no cap fixes, and the plateau reads as a
bug in the algorithm rather than a fact about the corpus.

Marking it also forecloses the wrong fix. Splitting by a secondary key was
considered and rejected on two grounds:

- **Severity is degenerate here.** `cycle_participation`'s severity derives from
  cycle size, so every member of one SCC scores near-identically. The split would
  be on a variable that barely varies.
- **Cluster id inverts what clustering computed.** It is a genuinely different
  partition, but fragmenting one SCC across cluster boundaries presents a single
  architectural problem as several unrelated smaller ones — and clustering
  *condensed* that cycle. Using its output to divide the cycle back up undoes its
  own finding.

**So the honest output is one large row that says why it is large.** "122 files
in one cycle in one package" is a correct and useful statement; four severity
bands of the same cycle is a misleading one.

**Guard: when a grouping has a size budget, report groups the budget could not
reduce, and say why they are irreducible.**

### 17.18 Verified-reachable-but-not-on-current-data — a convention

Code whose correctness matters, whose trigger does not occur on the data in
front of you, is in a trap: it looks like dead code to a reader and like a
working feature to a reviewer. Both readings are wrong, and both are damaging —
one deletes a real guard, the other cites a behaviour that has never run.

> **Guard: such code carries a comment stating (a) that it does not fire on
> current data, (b) how reachability was verified, and (c) the condition under
> which it fires. It must not be read as a feature that fires today, and must
> not be deleted as dead.**

All three parts are load-bearing. (a) alone reads as an admission of dead code.
(b) is what separates this from a guess — "I believe this could happen" is not
verification. (c) is what lets a future reader recognise the case when it
arrives.

#### The three instances

| # | Code | Why it does not fire | How reachability was verified |
|---|---|---|---|
| 1 | `clusterList.ts::isSingleton` | the backend's `_sorted_clusters` already drops single-member groups before persisting | inspected persisted data: 255 clusters on superset, **zero** with `member_count <= 1`, smallest is 2 |
| 2 | `findings_queue` `irreducible` flag | the 122-file `superset-ui-core` group is under the 200 cap, so it is never split and never marked | **lowered the cap to 100 against real data** — produced exactly that row with `irreducible=True` |
| 3 | the boundary invariant behind instance 1 | same upstream filter | kept deliberately: it holds the invariant at the boundary rather than trusting a filter in another process, and it is three lines |

Instance 2 is the strongest verification of the three, and shows what (b)
should look like. "It would fire if a directory held more than the cap" is
reasoning. Lowering the cap until the case *must* occur, and observing the flag
set on a specific named row, is evidence. The difference matters: §15.1's inverse
clause says a negative result is only informative if the stimulus is first shown
to produce the condition, and this is that clause applied to reachability rather
than to a test.

#### Why not just delete it

Instances 1 and 3 are the same guard, and the argument for keeping it is not
"it might fire one day". It is that the invariant is enforced **at the boundary**
rather than assumed from a filter running in another process — three lines that
do not depend on a remote guarantee holding. Instance 2 is different: its
trigger is a **config value** (`MAX_FILES_PER_ROW`), so a repo shaped differently,
or an operator lowering the cap, reaches it without any code changing.

Neither is speculative, and neither fires today. That combination is exactly what
the comment has to convey.

### 17.19 What rests on measurement, what rests on inference

Added with the §17.15–§17.18 batch. §17 mixes two kinds of claim, and they carry
different weight and need different re-checking. A reader cannot tell them apart
from the prose alone, and treating an inference as a measurement is how §17.0's
original error happened — reading "did not occur in this corpus" as "does not
occur".

| § | Claim | Kind | Re-verification path |
|---|---|---|---|
| 17.1 | `cycle_participation` fires at 12.7% on superset | **measured** | re-run health on repo 6; compare `cycle_participation` fired count against 832 / 6,522 |
| 17.2 | `bidirectional_coupling_hub` fires at 2.3% | **measured** | same, marker count 152 |
| 17.4 | `--name-only --no-renames` took history from 427 s to 8.45 s | **measured** | time `_collect_git_history` on repo 6 |
| 17.8 | job 19 stage timings | **measured, superseded** | instrument replaced — see §17.14; those per-stage figures came from the SSE stream and misattribute boundaries |
| 17.13 | commit-in-callback cost, sublinear in frequency | **measured** | A/B `expire_on_commit` True/False on repo 6 at a fixed interval; expect ~4-6× on the resolution stage |
| 17.14 | cold ingest 477.9 s; only `parsing` scales | **measured, pre-fix** | invalidate `content_sha256` for one repo, run one job, read `stage_seconds` from the job record |
| 17.15 | property-shaped predicates catch cases list-shaped ones cannot | **inferred** from 3 instances | not re-runnable. Falsified by a case where a list-shaped predicate caught something a property-shaped one missed — none observed |
| 17.16 | counts predating §17.1/§17.2/§17.4 describe a different instrument | **measured** | per-marker decomposition of snapshot 6 versus 13; the six maintainability markers moved by 12 |
| 17.17 | count and size are inversely coupled at fixed depth | **measured on two independent cases** | re-run the level sweep on any repo's findings queue; expect the head and tail to move in opposite directions |
| 17.18 | the three verified-unreachable sites are reachable | **measured per site** | instance 2: set `MAX_FILES_PER_ROW=100` on repo 6, expect `irreducible=True` on `cycle_participation` / `superset-ui-core` |

**Two entries here are inferences and are marked as such.** §17.15 and §17.18's
*convention* (as distinct from its per-site reachability checks, which are
measured) are generalisations from a handful of instances. They are the most
useful entries in §17 and the least verifiable, which is precisely the
combination §17.0 warns about. Each says what would falsify it.

**The rule this table encodes:** a §17 entry states whether it rests on a
measurement or on a generalisation, and gives the path to re-check it. An entry
that can state neither has not established anything yet.

### 17.20 A change that alters nothing but reads as a fix

**Three instances, and the third is a different sub-shape from the first two.**
Distinct from §17.9 (the instrument misreports) and from cascade suppression (a
correct value discarded downstream): here the CODE was already right, or already
wrong in a way the change did not touch, and the change presents as a repair.

The damage is not the wasted edit. It is that a fix-shaped commit is believed:
it is written down, it is cited later, and the thing it claimed to fix is
crossed off.

| # | The change | What it actually did | How it was caught |
|---|---|---|---|
| 1 | Overrode uvicorn's access formatter to "add" the query string | Produced a **byte-identical** format string. uvicorn already logs the query via `get_path_with_query_string` | Printing the old and new `fmt` side by side and comparing them |
| 2 | `sys.stdout.reconfigure(line_buffering=True)` in `run.py` to fix empty logs | Fixed a real defect that was **not the cause**. Logs stayed empty | The logs were still empty afterwards |
| 3 | `PYTEST_CURRENT_TEST` guard on the port check | Correct variable, evaluated at the wrong moment — it is set per TEST, and the module is imported during COLLECTION | The tests failed identically to before |

**No-op versus partial fix, which is the distinction instance 2 forces.**
Instance 1 changed nothing at all. Instance 2 changed something real —
block-buffered stdout genuinely does lose output on kill, and that would have
bitten the moment the actual cause was fixed — but it was not why the logs were
empty. A partial fix is more dangerous than a no-op precisely because it is
defensible: every word written about it was true, and the conclusion drawn from
it was wrong.

Instance 2 was also **already relied upon**. It shipped in a commit describing
the log as "the record for the open Dependency Graph crash". The crash's
frontend instrumentation was verified by injected throw; the backend half was
verified by reading the configuration. One layer was tested and one was
asserted, and the untested one was the one that mattered.

**Guard: a fix is verified by observing the SYMPTOM disappear, not by observing
the change take effect.** "The formatter is now overridden", "stdout is now
line-buffered" and "the guard now skips under pytest" were all true, and the log
was still empty in the first two and the tests still failed in the third.

### 17.21 A null observation is compatible with several mechanisms

An empty file, a zero count, a silent log: absence of output is the observation
that most easily supports the first explanation offered, because it looks
identical under every cause.

**The instance.** Every server log in a session was empty. First diagnosis:
stdout buffering, which is real and demonstrable — a redirected process killed
three seconds after printing produces a zero-byte file. It was accepted, fixed,
committed, and the logs were still empty.

The actual cause was `alembic/env.py` calling
`fileConfig(config.config_file_name)` with `disable_existing_loggers` defaulting
to **True**, from a migration run at startup — which switched off
`uvicorn.access` and `uvicorn.error` for the life of every process.

**The discriminating evidence was present the whole time and was not looked at:
alembic's OWN log lines were in the file while uvicorn's were absent.** Logging
was working; specific loggers had been disabled. Buffering cannot produce that —
it loses everything or nothing. One line of the existing output separated the
two hypotheses and it was read past, because the first explanation already
accounted for "the file is empty".

**The rule: when the observation is an absence, enumerate what ELSE produces the
same absence before fixing the first candidate.** Then find the evidence that
separates them — and it is usually the thing that is present rather than the
thing that is missing, because an absence is uniform and a presence has
structure.

Related to §17.0b's third clause (check the mechanism against what the
instrument measured) but distinguishable: there, a number was divided by the
wrong denominator. Here there was no number at all, and the absence was treated
as a measurement of one cause.

### 17.22 A probe that cannot see the change reports "no change"

Eleven-plus instances of §17.9 across this project, and this is the sub-shape
worth naming separately, because its output is indistinguishable from a genuine
negative result and is therefore *acted on*.

**The instances, all from checking whether the Matrix honoured a filter:**

| Probe | Why it could not see the change |
|---|---|
| Cell COUNT | The grid is capped at 24 groups: its size is constant while its contents change entirely |
| `th`/`td` text containing `/` | Cells render `short_label` (the last path segment, no slash); the full path is in a `title` ATTRIBUTE |
| `/algorithm agreement/i` for a suppressed value | Also matches the SUPPRESSION NOTICE, so the feature working and explaining itself read as the feature failing |

The third is the sharpest: the probe could not distinguish the thing from the
notice of its absence, so success produced text that the check scored as
failure.

**The rule, in three parts:**

1. **Positive control first.** Before asserting a change, assert the probe can
   see the pre-change state. The corrected Matrix probe checks that frontend
   directories are present unfiltered; if they are not, it exits **2** and
   reports nothing about filtering.
2. **A distinct exit code for "blind".** Not a failure and not a pass. A probe
   that cannot measure has produced no evidence, and collapsing that into
   "pass" or "fail" is what makes it dangerous.
3. **Never report a comparison you could not make.** Two of these probes said
   "no change" about a view that was changing correctly underneath them.

A probe that can only return "no change" is worse than no probe. No probe leaves
a known gap; a blind probe fills it with a false negative carrying the same
confidence as a real one.

### 17.23 Data disappeared and the guarantee did not hold

Recorded for what it MEANS, not for what happened: **the property that data
cannot vanish without an identifiable cause does not currently hold in this
system.** The missing rows are the evidence, not the finding.

**What happened.** Repo 5 was present at the start of a session with 43 rows
across five tables, present after a cleanup that deliberately did not target it,
and absent afterwards — with **no orphaned rows**, meaning a complete removal
across all eight tables.

**What is ruled out.** LRU eviction targets `source_kind == "clone"` only (repo
5 was `local`), and at the time it deleted the `Repo` row alone, which would
have LEFT orphans — there were none. The cleanup script filtered
`name like 'athena-owned-%'`; repo 5 was named `repo`.

**What is left.** Either something invoked deletion in a way not identified, or
the reasoning about what can produce a complete removal is incomplete. No
evidence exists to distinguish those, because `delete_repo` had **no logging at
all** — the one code path capable of that outcome left no trace of having run,
so "was it called?" was unanswerable rather than merely unanswered. And the
server access log that would have shown the request was empty for the whole
session (§17.21).

**Three things changed as a result**, none of which explains this occurrence:

- `delete_repo` logs before and after every invocation, with a required
  `reason`. The BEFORE line is the load-bearing one: an after-only log records
  successes and says nothing about a run that died midway, which is precisely
  the case where rows are gone and nobody knows why.
- Logging works at all now (§17.21).
- Eviction calls `delete_repo_unconfirmed` instead of a hand-rolled
  `db.delete`, so the second destructive path is the same code as the first.

**The general form: after a destructive operation exists, "can this data
disappear without a trace?" is a question with a testable answer, and it should
be asked before the operation ships rather than after something vanishes.** A
43-row fixture is a cheap place to learn it. The same failure on a repository
someone cares about is not.

### 17.24 A check that silently detached from its subject

Distinct from §17.9's eleven instances, and the distinction is the point.

Those eleven were instruments that **could not perceive the variable** — a
grep that could not see wrapped text, a cell count that could not see a content
change, a probe that could not tell a value from the notice of its absence. The
instrument was pointed at the right thing and lacked the resolution to see it.

This one was pointed at the right thing and then **stopped being pointed at it**,
while continuing to run, pass, and report.

#### The instance

Three helpers in `test_ranking.py` identified the `git log` call by POSITION:

```python
if args and args[0] == "log":   # inject a timeout / an OSError / capture argv
```

The K8 fix prepended two elements to the command — `-c core.quotepath=false` —
so `args[0]` became `-c`. The helpers stopped matching. Nothing errored:

- the injected `TimeoutExpired` was never raised
- the injected `OSError` was never raised
- the argv capture recorded nothing, and the assertion died on `KeyError: 'args'`

Two of those three tests exist to prove that history collection **degrades
gracefully** — that a slow or failing `git log` returns `None` and costs the repo
its history signals rather than its entire ranking run. For the duration of the
detachment, both were exercising the happy path and asserting nothing about
degradation at all.

#### Why it announced itself, and how easily it might not have

It failed only because the happy path returned real history where `None` was
asserted, and `{...} is None` is false. **A looser assertion would have passed
green forever with those two guarantees unprotected.** `assert result is None or
result` would have done it. So would asserting on a count that happens to match.

That is the property that makes this worth its own entry: §17.9's instruments
produce a wrong ANSWER, which is at least an answer. This produces a test that
still passes while measuring nothing, and a passing test is not re-examined.

#### The guard

**Identify a subject by a PROPERTY of it, not by its position among its
neighbours.**

```python
if args and "log" in args:      # survives any prefix
```

This is §17.15 — predicate-as-property versus predicate-as-list — arriving in a
test helper rather than in product code. `args[0] == "log"` is a positional
claim about a list whose shape someone else controls; `"log" in args` is a claim
about the command itself. The list-shaped version was correct when written and
was invalidated by a change two modules away that had no reason to know it
existed.

#### Two layers, and the cheap one catches drift

The same fix produced the pattern worth keeping. K8 is now pinned twice:

| Layer | Test | Cost | Catches |
|---|---|---|---|
| Command shape | `core.quotepath=false` is in the argv | Microseconds, no fixture, every platform | **Argv drift** — the flag being dropped, reordered, or overwritten |
| Behaviour | CJK / accented / Cyrillic filenames come back matching `CodeFile.path` | A real git repo per run | The flag being present and not working |

The cheap one is the one that would have caught this class of failure, and it is
the one that would have been skipped as redundant. It is not redundant: it
asserts on the interface between two modules, which is exactly where a change
made elsewhere invalidates an assumption made here.
