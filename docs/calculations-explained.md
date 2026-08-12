# Every calculation in the codebase agent, explained

This document explains **all the maths** behind every number the tool shows
you — the Reading List, Code Health, Dependency Clusters, Layers, the
Architecture map, the Matrix, and the Overview counters.

It assumes **no prior knowledge**. Every formula is written out, every symbol
is defined, and every step is worked through on a small example you can follow
by hand. Where a number is a judgement call rather than a derivation, that is
said plainly.

**A note on trust.** Some of these numbers are well-founded and some are
explicitly uncalibrated. This document tells you which is which. If you only
read one thing, read §9 — *What these numbers are not*.

---

## Table of contents

1. [The raw material: what gets measured before any maths happens](#1-the-raw-material)
2. [Reading List — three different ways to rank files](#2-reading-list)
3. [Code Health — three separate scores](#3-code-health)
4. [The Code Health aggregate out of 100](#4-the-aggregate-out-of-100)
5. [Health by directory, and "the code in motion"](#5-health-by-directory)
6. [Dependency Clusters](#6-dependency-clusters)
7. [Layers, Architecture map and Matrix](#7-layers-architecture-and-matrix)
8. [Overview counters](#8-overview-counters)
9. [What these numbers are not](#9-what-these-numbers-are-not)

---

## 1. The raw material

Before any score exists, the tool builds three things from your code.

### 1.1 The file list

It walks the repository, keeps files it can parse (`.py`, `.ts`, `.tsx`,
`.js`, `.jsx`), and skips vendored code — `node_modules`, any directory
containing `pyvenv.cfg` (a Python virtual environment), `site-packages`, and
similar. Skipped directories are reported, not hidden.

### 1.2 The import graph

Every `import` statement is parsed and resolved to the file it points at. The
result is a **directed graph**:

- a **node** is a file
- an **edge** `A → B` means "file A imports file B"

Two numbers fall straight out of this and are used everywhere:

| Term | Meaning |
|---|---|
| **fan-in** of a file | how many files import it |
| **fan-out** of a file | how many files it imports |

> **Worked example.** Five files. `main.py` imports `utils.py` and `db.py`.
> `api.py` imports `utils.py`. `models.py` imports `db.py`.
>
> `utils.py` has **fan-in 2** (main, api) and **fan-out 0**.
> `main.py` has **fan-in 0** and **fan-out 2**.

### 1.3 Git history

For each file: how many commits touched it (`commit_count`), how many distinct
authors (`distinct_authors`), and how many days since the last change
(`days_since_last_change`).

If git history is unavailable — a shallow clone, no `.git` — these are
**absent**, not zero. That distinction drives a lot of what follows.

### 1.4 Edge weights: not all imports are equal

An import that makes one class inherit from another is stronger coupling than
an import used once for a type annotation. Each edge is classified at parse
time and given a weight at scoring time:

| Kind of import | Weight |
|---|---:|
| `inherits` — a class extends an imported class | 1.00 |
| `calls` — the imported thing is called | 0.80 |
| `heavy_use` — used many times | 0.80 |
| `unresolvable_binding` — wildcard import, untraceable | 0.70 |
| `light_use` — used once or twice | 0.40 |
| `type_only` — used only in a type annotation | 0.25 |
| `reexport` — imported purely to export again | 0.15 |
| `test_edge` — the importer is a test file | 0.05 |

**Why `test_edge` is nearly zero:** a utility imported by fifty test files is
not fifty-times more central to your architecture. Without this, test helpers
dominate every ranking.

### 1.5 Node priors: not all files are equal

Each file gets a category and a multiplier:

| Category | Multiplier | What it means |
|---|---:|---|
| `entry` | 1.40 | A real program start (detected from Dockerfile, `package.json` main, `if __name__ == "__main__"`, etc.) |
| `source` | 1.00 | Ordinary code — the default |
| `barrel` | 0.40 | A file that only re-exports other files |
| `config` | 0.20 | `*.config.*`, `setup.py`, `alembic.ini` |
| `migration` | 0.15 | Database migrations |
| `generated` | 0.05 | Machine-written (`@generated`, `DO NOT EDIT`) |

---

## 2. Reading List

**The question it answers:** *if I am new to this repository, in what order
should I read the files?*

There are **three different scorers**. They are not versions of each other —
they are three different opinions, kept side by side deliberately so they can
be compared. You choose one from a dropdown.

### 2.1 Scorer 1 — "Legacy" (a weighted sum)

Six signals are each squashed onto a 0-to-1 scale, then blended with fixed
weights.

**Step 1 — normalise each signal to 0–1 (min-max normalisation).**

```
normalised(x) = (x − minimum) / (maximum − minimum)
```

The smallest value in the repo becomes 0, the largest becomes 1, everything
else lands proportionally between.

> **Worked example.** Fan-in values across four files: 0, 2, 5, 10.
> Minimum 0, maximum 10.
> - file with fan-in 0 → (0−0)/(10−0) = **0.0**
> - file with fan-in 2 → (2−0)/(10−0) = **0.2**
> - file with fan-in 5 → **0.5**
> - file with fan-in 10 → **1.0**

*Edge case:* if every file has the same value, there is nothing to
distinguish, and every file gets **0.5** rather than 0 or a divide-by-zero.

**Step 2 — invert recency.** For days-since-last-change, *smaller is better*
(a file touched yesterday matters more than one untouched for a year). So
after normalising it, the tool flips it:

```
recency = 1 − normalised(days_since_last_change)
```

**Step 3 — multiply each normalised signal by its weight and add up.**

```
score(file) = Σ  weight(signal) × normalised_signal(file)
```

| Signal | Weight |
|---|---:|
| fan_in | 0.35 |
| pagerank | 0.30 |
| is_entry_point (1 or 0) | 0.15 |
| commit_count | 0.10 |
| distinct_authors | 0.05 |
| recency | 0.05 |
| **total** | **1.00** |

> **Worked example.** A file with normalised fan_in 0.8, pagerank 0.6, not an
> entry point (0), commits 0.4, authors 0.2, recency 0.9:
>
> ```
> 0.35×0.8 + 0.30×0.6 + 0.15×0 + 0.10×0.4 + 0.05×0.2 + 0.05×0.9
> = 0.28 + 0.18 + 0 + 0.04 + 0.01 + 0.045
> = 0.555
> ```

**Step 4 — what happens when git history is missing.** The three history
weights (0.10 + 0.05 + 0.05 = **0.20**) are **redistributed proportionally
across the three graph signals**, so the weights still total 1.0:

```
graph_weight_total = 0.35 + 0.30 + 0.15 = 0.80
new_weight(signal) = old_weight × (1 + 0.20 / 0.80) = old_weight × 1.25
```

So fan_in becomes 0.35 × 1.25 = **0.4375**, pagerank **0.375**,
is_entry_point **0.1875**.

**This is the "exclude, don't zero" rule**, and it appears throughout the
tool: a missing signal is removed from *both* the numerator and the
denominator. Scoring the missing history as 0 would push every file down
equally and pretend a measurement had been made.

### 2.2 PageRank — the idea behind it

PageRank asks: *if you wandered the import graph at random, how often would
you land on this file?* A file imported by many important files scores higher
than one imported by many unimportant files.

It works by repetition. Every file starts with an equal share of "rank". Then,
repeatedly:

```
new_rank(f) = (1 − d)/N  +  d × Σ  rank(u) / out_degree(u)
                              u imports f
```

- **N** — total number of files
- **d** — the *damping factor*, the probability of following an import rather
  than jumping somewhere random
- **out_degree(u)** — how many files `u` imports; `u` splits its rank evenly
  among them

Repeat until the numbers stop changing (they converge). The legacy scorer uses
**d = 0.85**, the web-search convention.

> **Intuition.** Rank flows along import edges. A file that many files point
> at accumulates it. A file pointed at by *one* very high-rank file can score
> higher than one pointed at by *ten* low-rank files.

### 2.3 Scorer 2 — Weighted, seeded PageRank

Same idea, three differences:

1. **Edges are weighted** by the coupling kinds in §1.4, so rank flows more
   through an `inherits` edge than a `test_edge`.
2. **The random jump is seeded**, not uniform. Instead of jumping to any file,
   the walker jumps back to a **detected entry point**. This measures "how
   close is this file to where the program actually starts", not "how
   important is it globally".
3. **Damping is 0.65**, not 0.85.

```
W(u)  = Σ  w(u,v)                       total outgoing weight of u
        u→v

PR(f) = (1−d)·s(f)  +  d ·[ Σ  PR(u)·w(u,f)/W(u)  +  D·s(f) ]
                            u→f
```

- **s(f)** — the seed vector; the share of jumps landing on `f`, non-zero
  only for entry points
- **D** — rank currently held by *dangling* files (files that import nothing);
  it has to go somewhere, and it goes back through the seed

**Why damping 0.65 matters.** Rank decays as `d^k` at `k` hops from the seed:

| Hops from an entry point | at d = 0.85 | at d = 0.65 |
|---:|---:|---:|
| 1 | 0.85 | 0.65 |
| 3 | 0.61 | 0.27 |
| 5 | 0.44 | 0.12 |

The lower value concentrates attention near entry points instead of spreading
it evenly across the whole repository.

**A deliberate consequence:** because *both* the random jump and the dangling
redistribution route through the seed, a file with no path from any entry
point converges to **exactly 0** — not a small non-zero number. Unreachable
means unreachable.

### 2.4 Scorer 3 — Reciprocal Rank Fusion (RRF)

This one has **no tunable weights at all**. Instead of blending magnitudes, it
blends **positions**.

**Step 1 — rank the files separately by each signal.** Best = rank 1.

**Step 2 — ties share the average position.** If two files tie for best, both
get rank 1.5 (the average of positions 1 and 2), not an arbitrary 1 and 2.

> **Why.** On a real repository dozens of files share `fan_in = 0`. Breaking
> that tie by, say, filename would invent an ordering the data does not
> contain.

**Step 3 — add up the reciprocals.**

```
score(f) = Σ  1 / (k + rank_signal(f))          with k = 60
        signals
```

> **Worked example.** A file ranked 1st on fan-in, 5th on pagerank and 40th on
> commits:
>
> ```
> 1/(60+1) + 1/(60+5) + 1/(60+40)
> = 0.01639 + 0.01538 + 0.01000
> = 0.04177
> ```

**What `k = 60` does.** It flattens the curve. Without it, being ranked 1st
instead of 2nd would be worth `1/1 − 1/2 = 0.5`, dwarfing everything else.
With `k = 60`, that same gap is worth `1/61 − 1/62 ≈ 0.00026`. A file must do
*consistently* well across signals, not spike on one.

**Missing signals contribute nothing** — no term is added, rather than a
fabricated worst-place rank.

### 2.5 Rank versus score

The **Rank** column is the file's position among *all* files at the moment the
ranking ran. It is stored, not recomputed. Filtering the table to one
directory and seeing ranks 1, 2, 3, 5, 11 is the useful signal — it does not
renumber to 1, 2, 3, 4, 5.

---

## 3. Code Health

**Three separate scores that are never blended into one** (except in the
Overview tile, §4, which is an explicit exception):

| Axis | Scale | Direction |
|---|---|---|
| **Maintainability** | 1–10 | higher is better |
| **Architecture Health** | 1–10 | higher is better |
| **Change Hotspot** | 0–9 points | **higher means review sooner** |

Direction is built into each name so you never have to mentally invert one.

### 3.1 The scoring mechanism — start at 10, subtract

Every axis starts at a perfect 10 and loses points for specific findings
("markers"). Each marker has a **threshold pair** and a **weight**.

**Step 1 — severity, a linear ramp from 0 to 1.**

```
              ⎧ 0                                   if value ≤ warn
severity =    ⎨ (value − warn) / (saturate − warn)   if between
              ⎩ 1                                   if value ≥ saturate
```

> **Worked example.** `complex_method` warns at 10 and saturates at 25.
> - complexity 8 → below warn → severity **0**
> - complexity 10 → at warn → severity **0**
> - complexity 17.5 → (17.5−10)/(25−10) = 7.5/15 = severity **0.5**
> - complexity 25 → severity **1**
> - complexity 60 → clamped → severity **1**

A *ramp*, not a step: one extra branch nudges the score, it does not flip it.

**Step 2 — deduction.**

```
deduction = weight × severity
```

**Step 3 — category caps.** Markers are grouped, and each group can only take
so much:

```
category_deduction = min(category_cap, Σ deductions in that category)
```

> **Why.** Without a cap, a file that is complex in three related ways could
> lose its entire score to one dimension, hiding everything else.

**Step 4 — the axis total, and the final score.**

```
axis_deduction = min(9.0, Σ category_deductions)

Maintainability     = 10 − axis_deduction
Architecture Health = 10 − axis_deduction
Change Hotspot      =      axis_deduction     ← not subtracted
```

The 9.0 axis cap means the worst possible score is **1**, never 0. It
currently equals the sum of the category caps, so it never actually binds — it
is a guard for future markers, documented as inert rather than presented as
doing work.

### 3.2 Maintainability markers

Measured from the parse tree of each file.

| Marker | What is measured | warn → saturate | Weight | Category |
|---|---|---|---:|---|
| `complex_method` | highest cyclomatic complexity of any function | 10 → 25 | 2.5 | complexity |
| `deep_nesting` | deepest block nesting in any function | 4 → 8 | 1.5 | complexity |
| `complex_conditional` | most operands in one boolean expression | 4 → 10 | 1.0 | complexity |
| `large_method` | longest function, in lines | 60 → 200 | 2.0 | size |
| `large_file` | file length in lines | 400 → 1500 | 1.5 | size |
| `broad_error_handling` | count of bare/empty catch blocks | 0 → 5 | 2.0 | error |

Category caps: **complexity 4.0**, **size 3.0**, **error 2.0**.

**Cyclomatic complexity** counts decision points: every `if`, `for`, `while`,
`case`, `catch`, ternary, and each `and`/`or`. One straight-line function
scores 1. A function with three `if`s scores 4. It approximates *how many
different paths run through this code*.

> **Full worked example.** A file whose worst function has complexity 17.5, a
> longest function of 130 lines, is 400 lines long, and has 1 bare `except:`.
>
> | Marker | Severity | Deduction |
> |---|---|---|
> | complex_method | (17.5−10)/15 = 0.5 | 2.5 × 0.5 = **1.25** |
> | large_method | (130−60)/140 = 0.5 | 2.0 × 0.5 = **1.00** |
> | large_file | (400−400)/1100 = 0 | **0.00** |
> | broad_error_handling | (1−0)/5 = 0.2 | 2.0 × 0.2 = **0.40** |
>
> complexity category = 1.25 (cap 4.0, not reached)
> size category = 1.00 (cap 3.0, not reached)
> error category = 0.40 (cap 2.0, not reached)
>
> **Maintainability = 10 − (1.25 + 1.00 + 0.40) = 7.35**

**Note the `broad_error_handling` warn of 0.** It was originally 1, which
meant the *first* bare `except:` deducted exactly nothing — the marker
silently required two before saying anything. A ramp whose `warn` sits at the
minimum meaningful value exempts the first real occurrence.

**Files under 10 non-blank lines are excluded** from Maintainability entirely
(reported as N/A). A 4-line file cannot be meaningfully graded for complexity.

### 3.3 Architecture Health markers

| Marker | What is measured | warn → saturate | Weight | Category |
|---|---|---|---:|---|
| `cycle_participation` | size of the import cycle the file is in | 1 → 12 | 4.0 | cycles |
| `bidirectional_coupling_hub` | `min(fan_in, fan_out)` | repo's P90 → P99 | 3.0 | coupling |

Category caps: **cycles 4.0**, **coupling 3.0**.

**An import cycle** is a group of files that all, directly or indirectly,
import each other — A imports B, B imports C, C imports A. Formally a
*strongly connected component*: a set where every file can reach every other
by following imports. A file not in a cycle has a cycle size of 1.

> Cycle of 4 files: severity = (4−1)/(12−1) = 3/11 = 0.27 → deduction 1.09
> Cycle of 12+: severity = 1 → deduction 4.0 → score **6.0**

**`bidirectional_coupling_hub`** fires only when a file is *both* heavily
imported **and** heavily importing — both above the repository's 90th
percentile. A pure utility that everything imports is deliberately **not** a
finding.

Note its thresholds are **relative to the repository**, not absolute — see
§9.3 for why that matters.

### 3.4 Change Hotspot markers

| Marker | What is measured | warn → saturate | Weight |
|---|---|---|---:|
| `churn_volume` | commit count | repo's P50 → P95 | 2.5 |
| `complexity_under_churn` | severity(complexity) × severity(churn) | 0.2 → 0.8 | 2.5 |

Category cap: **hotspot 5.0**.

**A percentile** is the value below which a given share of files fall. P50 (the
median) is the middle value; P95 is the value only 5% of files exceed.

**`complexity_under_churn`** multiplies two severities. It only fires when a
file is *both* complex *and* frequently changed — the classic "hotspot"
formulation. A complex file nobody touches is not urgent; a simple file
changed constantly is not either.

**The whole axis is N/A unless churn carries information.** If fewer than
three distinct commit counts exist across the repository — typical of a
shallow clone where every file reports 1 — the axis reports nothing. Ranking
files by a constant would produce a confident-looking list with nothing behind
it.

### 3.5 Effort-adjusted exposure

The Change Hotspot points tell you what to review; this tells you what to
review *first per unit of effort*.

```
review_cost_units = max(nloc, 30) / 100

adjusted_exposure = points / review_cost_units
```

> A file with 4.0 points and 200 lines: 4.0 / 2.0 = **2.0**
> A file with 3.0 points and 50 lines: 3.0 / 0.5 = **6.0**
>
> The smaller file ranks higher — same problem, a quarter of the reading.

**The floor of 30 lines** stops a 4-line file dominating purely by being tiny.
Both raw and adjusted numbers are always shown together.

### 3.6 Availability: N/A is not a low score

Every marker is in exactly one of these states:

| State | Meaning |
|---|---|
| **fired** | measured, and above the warning threshold |
| **input_available_zero_severity** | measured, and clean — *evidence of absence* |
| **no_input** | could not be measured — a coverage gap |
| **not_applicable** | permanently inapplicable (e.g. no rule for this language) |

The last two are **excluded from the calculation entirely** — removed from
both the sum and the count. Never scored 0 (which reads as "measured and
terrible") and never full marks (which reads as "measured and fine").

**One axis withholds its score entirely.** If Architecture Health cannot
measure cycles — its heaviest marker — the score is not shown at all, only a
reason. A caveat printed beside a large confident number still leaves the
number doing the persuading.

---

## 4. The aggregate out of 100

The Overview shows one **Code health** number. Here is exactly what it is.

**Step 1 — rescale each 1–10 axis onto 10–100.**

```
outOf100 = round(axis_score × 10)
```

**Step 2 — average the *health* axes that were measurable.**

```
aggregate = round( Σ outOf100(axis) / number_of_axes_used )
```

> **Worked example.** Maintainability 9.4 → 94. Architecture 10.0 → 100.
> Aggregate = (94 + 100) / 2 = **97**.

**Step 3 — Change Hotspot is excluded, and not because it is uncalibrated.**

It is excluded because it is a **different kind of quantity**: a
review-priority ranking where *higher is worse*, against two quality scores
where *higher is better*. Averaging them would require silently inverting one,
and the result would answer no question — a repository could raise its
aggregate by becoming *more* urgent to review.

**Step 4 — unmeasurable axes are dropped from the average**, never scored 0
and never given full marks. If no health axis is measurable, the tile reads
**N/A** with a reason rather than a number.

The tile always states its own composition — `N of M axes`, plus `partial`
when one is missing.

**Bands are deliberately coarse:** ≥70 good, ≥45 mixed, below that poor. The
underlying thresholds are reasoned defaults, not fitted to any outcome, so a
finer gradient would imply precision the numbers do not have.

---

## 5. Health by directory

### 5.1 Three numbers per directory, not one

A file belongs to **every directory above it**, so `backend/app/api/repos.py`
counts toward `backend`, `backend/app`, and `backend/app/api`.

**Size-weighted mean (the headline):**

```
weighted_mean = Σ (score(file) × lines(file)) / Σ lines(file)
```

This answers: *if I open a random line of code in this directory, how healthy
is the file I land in?*

**Plain mean:** every file counts equally.

**Worst file:** named explicitly.

> **Worked example.** A directory with twenty 5-line files scoring 10, and one
> 2,000-line file scoring 2.
>
> - plain mean = (20×10 + 2) / 21 = **9.6** — looks healthy
> - weighted = (20×5×10 + 2000×2) / (20×5 + 2000) = (1000 + 4000) / 2100 =
>   **2.4** — reflects where the code actually is
>
> The gap between the two is itself the signal: it says one large file
> dominates.

**Ranking requires at least 3 scored files.** A directory holding one unusual
file would otherwise top the "weakest" list on a sample size of one. Such
directories are still *shown*, marked unrankable — gated from ranking, not
hidden.

### 5.2 "The code in motion"

```
hot_files = files in the top 10% by commit count (minimum 5, ties kept together)
gap       = mean Maintainability(hot files) − mean Maintainability(all scored files)
```

> *"The files you change most score 8.38 on Maintainability — 1.04 below the
> codebase overall."*

**Why this is not circular:** Maintainability takes **no** change-history
input. `complexity_under_churn` lives on the Change Hotspot axis, not this
one. So this compares two genuinely independent measurements.

**It is N/A when churn is degenerate**, using the same test as §3.4. And on a
young repository it carries a caveat: *"changed most" overlaps with "written
most recently"* — the files you touched most are the ones you built last.

---

## 6. Dependency Clusters

**The question:** *which files form natural groups because they depend on each
other more than on the rest of the repository?*

### 6.1 The graph being clustered

Different from the ranking graph in two ways:

1. **Undirected** — for grouping, "A imports B" and "B imports A" both just
   mean "these two are connected".
2. **Weight = the maximum** among all import rows between that pair, not the
   sum. Splitting one import statement into five named imports should not
   quintuple the apparent coupling.

### 6.2 Modularity — the quality measure both algorithms optimise

**Modularity** asks: *are there more edges inside these groups than you would
expect by chance?*

```
Q = Σ  [ (edges inside group c) / (all edges)  −  ( (total degree of c) / (2 × all edges) )² ]
    c
```

- The **first term** is the share of edge weight that falls inside group `c`.
- The **second term** is the share you would expect if the same edges were
  rewired at random.
- **Q** near 0 means "no better than random". Higher means real structure.
  Typical real values are 0.3–0.7.

The subtraction is the whole idea. Putting every file in one giant group makes
the first term 1 — and the second term 1 as well, so `Q = 0`. Random density
is the baseline being beaten.

**Algorithm 1 — Greedy modularity.** Start with every file alone. Repeatedly
merge the two groups whose merger raises `Q` most. Stop when no merge helps.

**Algorithm 2 — Louvain.** Move individual files between neighbouring groups
while that raises `Q`; then collapse each group into a single node and repeat
on the smaller graph. Faster, and often finds different local optima. Seeded
with a fixed random seed (42) so results are reproducible.

**Algorithm 3 — HDBSCAN.** Completely different signal. It ignores imports
and groups files by what their **code text says** — function names, class
names, docstrings — converted to numeric vectors locally. Vectors are
L2-normalised first so that Euclidean distance becomes a monotonic function of
cosine similarity:

```
‖a − b‖ = √(2 − 2·cos_similarity(a,b))     for unit vectors
```

HDBSCAN labels genuinely isolated points as **noise** (label −1). Each noise
point becomes its own singleton rather than being forced into a group.

### 6.3 Algorithm agreement

```
agreement = Σ (largest overlap of cluster c with any cluster in B) / Σ |c|
          = over multi-member clusters c in A only
```

For each multi-member cluster found by algorithm A, find where most of its
files ended up in algorithm B's clustering, and count how many stayed
together.

**Singletons are excluded from both sides.** A lone file "landing with itself"
in both algorithms says nothing about whether the algorithms structurally
agree.

> **Worked example.** Cluster A₁ has 10 files: 8 land in B₃, 2 in B₇.
> Cluster A₂ has 5 files: all 5 land in B₁.
> agreement = (8 + 5) / (10 + 5) = 13/15 = **86.7%**

**Read agreement with care.** 100% agreement across 4 clusters is close to a
null result — there are not many ways to partition a tiny graph. 83% across
255 clusters is a real measurement about the methods.

### 6.4 Cycle-cluster coherence

For each directory-level import cycle, what share of its files landed in one
cluster?

```
coherence = (files in the single most common cluster) / (all files in the cycle)
```

Below **0.75** the cycle is flagged *weak* — and that is **not** a clustering
failure. It means the cycle is carried by a few specific edges rather than
pervasive coupling, so it may be fixable by inverting one or two imports
instead of restructuring both directories.

### 6.5 List shaping

- Clusters sorted **largest first**, ties broken by id so ordering is stable.
- **Top 20** shown, with "show all".
- **Single-member clusters aggregated** into one "Singletons (N)" row. A
  one-file cluster is a real result but not a grouping, and 200 of them as 200
  cards buries the ones that are.

---

## 7. Layers, Architecture and Matrix

### 7.1 Layers — distance from the entry points

**Breadth-first search** from every detected entry point at once:

- **Layer 0** — the entry points themselves
- **Layer 1** — everything they import directly
- **Layer 2** — everything those import
- …
- **Unreachable** — no path from any entry point

Cycles are collapsed first (a *condensation*), so a group of mutually-importing
files shares one layer rather than creating an infinite loop.

**Unreachable is a separate column, not the highest layer number.** "No path
exists" is a structurally different fact from "far away". And it is
**advisory** — never deducted from any score — because dynamic imports,
plugins, reflection and generated code are all invisible to static analysis.
It has been confirmed firing wrongly on this project's own code.

### 7.2 Architecture map — directory rollup

File-level edges are aggregated to directories:

```
edge weight (dir A → dir B) = number of file-level imports from a file in A to a file in B
```

A directory's fan-in and fan-out count **distinct connected directories**, not
the sum of its files' individual counts — otherwise a directory looks
important merely for being large.

### 7.3 Matrix

A grid with directories on both axes. Cell `(row, column)` = how many files in
`row` import files in `column`.

- The **diagonal** is imports *within* a directory.
- A pair with **both** `(A,B)` and `(B,A)` non-zero is a directory-level cycle.

---

## 8. Overview counters

| Counter | How it is computed |
|---|---|
| **Files** | count of parsed source files (vendored code excluded) |
| **Lines** | sum of line counts |
| **Modules** | count of distinct immediate parent directories — "module" is not a stored concept |
| **Symbols** | count of declared classes, functions and methods. *Not* "exports" — the parser does not record whether a symbol is exported, and calling them exports would overstate what was measured |
| **Imports** | count of import statements found |
| **% resolved** | `resolved imports / all imports` — the rest point outside the repo (third-party, standard library) or could not be traced |
| **Clusters** | multi-member clusters from the modularity algorithm |
| **Test files** | files whose path contains `test_`, `_test.`, `/tests/`, `.test.`, `.spec.`, `__tests__` |

---

## 9. What these numbers are not

This is the most important section.

### 9.1 Nothing here predicts defects

There is no defect data in this system: no issue-tracker linkage, no bug-fix
commit classification, no post-release failure history. The terms *defect
risk*, *bug risk* and *predicted defects* are forbidden in the code, the API
and the interface.

**Change Hotspot is labelled "uncalibrated" because it is.** It names the
signals it observes — change frequency × complexity — not an outcome it
predicts.

### 9.2 The thresholds are reasoned defaults, not fitted values

Every `warn` and `saturate` number in §3 was chosen by judgement and then
sanity-checked against real repositories. **None was fitted to any outcome.**
Doing so would be calibration, and calibrating while still labelling the
result "uncalibrated" would be exactly the misrepresentation this design
exists to prevent.

Proper calibration would require ≥50 defect-labelled commits, a time-ordered
holdout, and beating both lines-of-code-only and churn-only ranking. That
evidence does not exist yet.

### 9.3 Two markers are relative to your repository, not absolute

`churn_volume` and `bidirectional_coupling_hub` set their thresholds from your
repository's own distribution (P50/P90/P95/P99). Two consequences:

1. **They are not comparable across repositories.** "Repo A's hotspot score
   beats repo B's" is not a meaningful statement. Ranking *within* one
   repository is valid.
2. **Their fire rate is partly fixed by arithmetic.** A threshold at the
   median will always have about half the files above it; a threshold at P90
   can never flag more than 10%.

### 9.4 Scores are not comparable across versions

Thresholds are versioned. Comparing a score from one `thresholds_version` to
another measures the threshold change, not the code. The tool refuses such
comparisons and says why rather than showing a misleading trend.

### 9.5 Known blind spots

- Only Python, JavaScript, TypeScript and TSX are parsed. Anything else is
  N/A, never "clean".
- Dynamic imports, reflection, dependency injection and plugin registries
  create no static edge.
- Renames break history continuity: a renamed file carries only the commits
  made under its current name.
- A shallow clone has no usable history, so everything derived from churn is
  reported unavailable rather than computed from a constant.

### 9.6 What a 10 actually means

A perfect Maintainability score means **no marker in this contract fired**. It
does not mean the code is good. The markers measure specific, named, mostly
size-and-complexity properties — they say nothing about whether the design is
sensible, the names are clear, or the tests are meaningful.

Likewise Architecture Health 10.0 means *"no file-level import cycles and no
bidirectional coupling hub were found"* — not "the architecture is healthy".

**Every score in this tool is best read as a question to investigate, not a
verdict to act on.**
