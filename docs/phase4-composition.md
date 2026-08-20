# Phase 4 composition report: what the curated tables actually hold

> ## ⚠ Provenance, 2026-08-17: every subsystem-derived figure below is stale
>
> **Two separate instrument failures invalidate the derived numbers in this
> document. The curated-table figures (15 modules, 98 topics, 197 resources)
> are unaffected — those are counts of hand-written rows.**
>
> **1. `repo_id=3` was a 398-file stripped fixture, not `eslint/eslint`**
> (contract §17.26). Already noted at the correction block below, but it
> applies to every eslint figure in this file, not only the ones there.
>
> **2. `is_test_file` never matched a top-level `tests/` directory**
> (contract §17.28). 58.8% of eslint's graph edges and 9.8% of Superset's
> were weighted as production coupling instead of `test_edge`. Clustering is
> computed from those weights, so **every module count, module size, subsystem
> label, subsystem split and in-band percentage below was computed from a
> graph that no longer exists.** eslint went from 120 modularity clusters to
> 21 after the fix; Superset's counts moved too.
>
> Specifically stale, and NOT individually re-marked below: the `119 / 135`
> modules-produced figure for Superset, the `4/7` and `19/119` label-strategy
> in-band rates, the `149 / 1 / 1` largest-subsystem split, the eight-module
> eslint listing (`lib/rules · index` 151, `ast-utils` 139, `lib/shared` 56,
> …), the 932-resource Superset module, and every "largest module holds N"
> claim.
>
> **The catalogue thread is retired entirely** (contract §17.27): the
> classifier measured zero fires across 282 subsystems on three real repos and
> has been deleted, along with its constants, its `is_catalogue` field and its
> UI badge. Any reasoning in this document that branches on catalogue status
> is reasoning about an empty set.
>
> Current, re-measured figures live in `external-validation-eslint.md`
> Round 8 and contract §17.0/§17.27. The staging design that replaced this one
> is `module_mapping.stage_modules`.
>
> **CORRECTED 2026-08-20 (reconciliation pass): "No Phase 4 rows have been
> written" is NO LONGER TRUE and was left standing for three days after it
> stopped being true.** Phase 4 persistence shipped on 2026-08-17. Counted live
> against `athena.db` on 2026-08-20: **145 codebase modules, 3 codebase
> roadmaps, 661 comprehension cards** (Phase 5), 1 deletion-audit row. Written
> by `services/codebase/roadmap_persist.py` via `POST /repos/{id}/roadmap`,
> under migrations `f8a3c21d9b45` (repo provenance on modules/roadmaps),
> `a1c9e37f4b82` (orphan marker) and `c4b7e9d2f501` (comprehension cards).
> Rows are scoped to `source="codebase"` and never touch seed or generated
> content — pinned by `TestRepoRoadmapPersistence` in `tests/test_repos_api.py`.

Read from the live schema and real rows, not from reasoning about what these
tables probably contain. The findings-queue work established that a composition
report beats designing against assumptions, and the cost of being wrong is
higher here: curated and derived rows in one table is the hard-to-unwind case.

Counts are live as of 2026-08-14: 15 modules, 98 topics, 197 resources, 14
topic_progress rows, 2 review_items.

---

## a. The four tables, column by column

### `modules` (15 rows)

| column | type | notes |
|---|---|---|
| `id` | INTEGER | pk |
| `slug` | VARCHAR(120) | not null |
| `title` | VARCHAR(255) | not null |
| `kind` | VARCHAR(20) | not null — observed values: `tool`, `skill` |
| `summary` | TEXT | not null, but **empty string on all 4 generated rows** |
| `aliases` | JSON | not null — `[]` on generated rows |
| `source` | VARCHAR(20) | not null — **observed: `seed` (11), `generated` (4)** |
| `created_at` / `updated_at` | DATETIME | not null |

**The provenance column already exists.** `source` distinguishes hand-curated
(`seed`) from machine-made (`generated`) today, and every generated row was
produced by the existing roadmap flow. A codebase-derived module is a third
provenance, not a new concept — the table is already mixed, and the mixing is
already labelled.

### `topics` (98 rows)

| column | type | notes |
|---|---|---|
| `id` | INTEGER | pk |
| `module_id` | INTEGER | FK → `modules.id`, **ON DELETE NO ACTION** |
| `slug`, `title` | VARCHAR | not null |
| `blurb` | TEXT | not null — a sentence of prose |
| `order_index` | INTEGER | not null — reading order within the module |
| `estimated_minutes` | INTEGER | not null — 15/20/25 on real rows |
| `source` | VARCHAR(20) | not null — same vocabulary as modules |

### `resources` (197 rows)

| column | type | notes |
|---|---|---|
| `id` | INTEGER | pk |
| `topic_id` | INTEGER | FK → `topics.id`, ON DELETE NO ACTION |
| `kind` | VARCHAR(20) | not null — **observed: `article` (99), `video` (98). Nothing else.** |
| `status` | VARCHAR(20) | not null — observed: `intent` on every sampled row |
| `title` | VARCHAR(255) | not null |
| `url` | VARCHAR(1000) | **nullable, and null on every seeded row** |
| `search_query` | VARCHAR(255) | how the resource is to be FOUND, not where it is |
| `source_hint` | VARCHAR(255) | `seed` |
| `file_path`, `mime_type`, `size_bytes` | | for uploaded files |
| `order_index` | INTEGER | not null |

**The shape is "a thing to go and find", not "a thing at a location".** A seeded
resource is an *intent*: `status='intent'`, `url=null`, and a `search_query`
that a later step resolves. That is the opposite of a code reference, which is
exact and already resolved.

### `topic_progress` (14 rows)

| column | type |
|---|---|
| `id` | INTEGER pk |
| `user_id` | INTEGER |
| `topic_id` | INTEGER FK → `topics.id` |
| `completed_at` | DATETIME **not null** |

**Binary and terminal.** A row exists or it does not; there is no state, no
score, no partial. `completed_at` being NOT NULL means the row cannot represent
"started".

### `review_items` (2 rows) — how a card enters the queue

| column | type | notes |
|---|---|---|
| `user_id`, `roadmap_id` | INTEGER | `roadmap_id=0` on both real rows |
| `node_id` | **VARCHAR(40)** | observed: `comm:subjunctive mood` |
| `node_title` | VARCHAR(255) | |
| `interval_idx` | INTEGER | spaced-repetition step |
| `due_at`, `last_reviewed`, `last_score` | | |
| `kind` | VARCHAR(20) default `node` | observed: `concept`, `vocab` |
| `detail` | TEXT default `''` | |

Cards are addressed by a **`prefix:name` string in 40 characters**, and
`roadmap_id=0` is already used as "not from a roadmap". The `kind` + `detail`
columns were already added for non-roadmap cards, so the extension point exists.

---

## b–e. Where a codebase-derived row does not fit

---

## RESOLVED 2026-08-14, and one thing the data refuses

All five decisions below were answered. The mapping changed as a result, and
measuring the revised mapping produced a finding that outranks the decisions.

### The revised mapping

| Codebase concept | Library concept | Why |
|---|---|---|
| Subsystem | Module | "these files are entangled" |
| Architectural concept | Topic | a thing you study and are graded on |
| File | **Resource** | a thing you go and read — which is what a file is |

The first attempt mapped file → **topic** and produced **932 topics in one
module** on superset against a curated median of 7. That is not a granularity
choice; it is a module-shaped database view, operating two orders of magnitude
outside the range every module page, progress calculation and review interaction
was built for.

### What the revised mapping measures

| | eslint (repo 3) | superset (repo 6) | **curated** |
|---|---|---|---|
| modules produced / skipped | 7 / 2 | 119 / 135 | 15 |
| topics per module (min/med/max) | 1 / **3** / 12 | 1 / **2** / 189 | 5 / **7** / 8 |
| resources per topic | 1 / **3** / 149 | 1 / **3** / 117 | 2 / **2** / 3 |
| resources per module | 7 / **13** / 151 | 3 / **7** / 932 | 10 / **14** / 17 |

**At the median the mapping is right.** 13 resources per module against a
curated 14; 3 per topic against 2. Those are the same shape.

**The tail is the problem, and it is a known one.** eslint's largest module holds
151 resources, superset's holds 932. This is §17.17 — group count and group size
inversely coupled, no fixed level satisfying both — arriving in a third place
after the findings queue and H1's directory rollup. Both of those solved it by
rolling up to a **budget** rather than choosing a level, and the same answer
presumably applies here: a subsystem whose resource count exceeds a budget is
split rather than emitted whole. **Not implemented — that is a design decision.**

### A zero-topic module is not available, and that decides the topic question

Investigated because "a codebase module may not have topics at all" is the
better reading of the evidence. It is not reachable:

| Question | Answer |
|---|---|
| Can a resource exist without a topic? | **No.** `resources.topic_id` is `NOT NULL` with an FK to `topics.id` |
| Is there a `resources.module_id`? | **No.** Resources reach a module only through a topic |
| Does `module_progress` divide by zero? | **No** — it guards `total == 0` and returns `percent=0, state="not_started"` |
| Can a review card attach to a resource? | **Yes** — `review_items.node_id` is free-text VARCHAR(40), so `repo:<id>:<file_id>` works and does not depend on topics |

So the API fetching resources per topic (`modules.py:34` then `:48`) is
downstream of a schema constraint, not a design choice. **A zero-topic module
returns no resources — it is an empty module, not a module of resources.**

Making module-level resources possible would need `resources.topic_id` changed
from `NOT NULL` to nullable, which alters an existing column and **fails the
risk gate**.

### Given a topic must exist: decline to invent one

`single_topic` is now the **default**. One topic per module, titled `Files`,
holding every file in reading-rank order.

The choice was never "topics or no topics" — it was **invent a grouping or
decline to**. All three path-derived strategies fail, and eslint's largest
subsystem splits 149/1/1 under the best of them. `single_topic` says "this
module has no sub-structure the analysis can see", which is true, instead of
asserting three concepts that are one directory and two strays.

### Cap and paginate, not roll up

§17.17's first two instances had a hierarchy to roll up *into* — a parent path
that was itself meaningful. Files inside a module do not. Inventing intermediate
groups is the same objection as splitting a 122-file cycle by severity band.

So: rank-order, show the top 20, state the total. On eslint's largest module
that is 151 files with the top 20 shown, led by `lib/rules/index.js` at rank 12.
`resource_count`, `resources_shown` and `resources_truncated` all travel in the
payload — a truncated list whose total is not stated is the graph endpoint's old
"400 of 6,523" problem.

**This also settles the `order_index` question.** Reading rank *is* the resource
ordering, so nothing is lost by moving files from topics to resources — the
earlier note about absolute rank stands only in the sense that the stored column
holds position rather than rank.

### Below-floor subsystems are gathered, not dropped

A `skipped_reason` keeps the counts honest; it does not keep the files. Files
from subsystems under the 3-file floor now land in a single **`Unclustered`**
module — the pattern the Dependency Clusters view already uses. On eslint that
is 4 files (`lib/shared/text-table.js`, `lib/config-api.js`, `eslint.config.js`,
`lib/cli-engine/formatters/stylish.js`) that would otherwise appear nowhere.

### The shipped default, on eslint

```
modules produced: 8 (7 subsystems + Unclustered)
resources per module: min 4 / median 11 / max 151     curated: 10 / 14 / 17

  lib/rules · index                         151 resources, showing 20  [capped]
  lib/rules · ast-utils                     139 resources, showing 20  [capped]
  lib/shared                                 56 resources, showing 20  [capped]
  lib/languages/js/source-code/token-store   13 resources, showing 13
  lib/rules/utils/unicode                    10 resources, showing 10
  lib/linter/code-path-analysis               8 resources, showing 8
  lib/rules · code-path-utils                 7 resources, showing 7
  Unclustered                                 4 resources, showing 4
```

> **Correction, 2026-08-17 — this run was against a stripped fixture, not
> `eslint/eslint`.** The repo registered as repo id 3 was a 398-file
> `bin/`+`lib/`-only slice (see `docs/external-validation-eslint.md`'s
> Caveat 1, which stated this correctly at the time). The catalogue
> classification work downstream of this report cited a 74.7% catalogue
> file share derived from this same 8-module shape without carrying that
> caveat forward — treating a number about the slice as a number about
> ESLint. Re-run against a freshly, fully re-cloned `eslint/eslint`
> (1,447 files, no scoping) produces a **different module set entirely**
> (18 produced modules, not 8) and **zero catalogue-flagged modules**, not
> two. `lib/rules · index` and `lib/rules · ast-utils` as named above are
> not the modularity clustering's output on the real repository — see
> `docs/external-validation-eslint.md`'s Round 5 for the corrected numbers
> and the mechanism (per §17.16: measured-provenance, not silently
> updated).

### Ambiguous titles are disambiguated by the centre file

Three of these were titled `lib/rules` — three clusters legitimately sharing a
dominant prefix, so the label carried less information than it appeared to.
Slugs differed, which prevents a collision and does nothing for a reader looking
at three modules with one name.

**This is I3's labelling problem one level up.** Dominant-prefix was chosen as
the title with the top-fan-in stem as a SUBTITLE, and the ambiguous-prefix case
is exactly where that subtitle earns its keep — so it is promoted into the
title, and **only where the prefix is not unique**. `lib/shared` above is
untouched.

The centre file is the module's best-**ranked** member: already computed, and
guaranteed distinct because a file belongs to exactly one subsystem. The prefix
says *where* a cluster lives; the centre file says what it is centred *on* —
`lib/rules · index` and `lib/rules · ast-utils` are immediately different
things, which `lib/rules` twice was not.

### The topic level does not exist in the data

Three derivable candidates, measured for "groups per subsystem" against a 3–8
target:

| grouping | eslint in band | superset in band |
|---|---|---|
| parent directory | 4/7 (57%) | 19/119 (16%) |
| 2nd path segment | 0/7 (0%) | 5/119 (4%) |
| `prior_category` | 0/7 (0%) | 4/119 (3%) |

And the failure is not merely numerical. eslint's largest subsystem splits by
parent directory into **149 / 1 / 1** — one directory with two strays, not three
concepts.

So `TOPIC_STRATEGIES` is **named and selectable**, defaulting to the least-bad,
with the preview reporting the resulting distribution. Inventing a concept level
the data does not support would be the same error as generating a summary from
filenames.

### `order_index`: what survives and what is lost

Reading rank was a real argument for per-file topics. Under the revised mapping:

- **Relative order survives.** Files are rank-sorted before grouping, so each
  topic's `resources.order_index` is 0,1,2… in reading-rank order, and topics
  themselves are ordered by their best-ranked member.
- **Absolute rank is lost.** `resources` has no rank column, so "this is rank 3
  of 398" is not recoverable from `order_index`. It rides along in the preview
  payload only.

That is a genuine cost of the answer, stated rather than absorbed.

### One incidental finding

Two eslint subsystems both produce the title `lib/rules`. Slugs differ (the
subsystem id is appended) so there is no collision, but two modules with the same
displayed name is confusing and the label comes from the cluster's own
dominant-prefix rule — the same label two clusters can legitimately share.

---

### Decisions I am not making — options and tradeoffs

*(Answered 2026-08-14; kept for the reasoning. Resolutions: `understood_at`
nullable column added; `repo:<id>:<file_id>` synthetic key for `review_items`;
new resource `kind='code_ref'` rather than a new `status`; `modules.source =
'codebase'` rather than reusing `generated`.)*

**1. What is a topic, for a codebase module?**

| option | fits | costs |
|---|---|---|
| **per file** | `order_index` = reading-list rank, which already exists and is meaningful | 400 topics for one repo; `estimated_minutes` per file is a guess |
| **per symbol** | finest granularity, matches `code_symbols` | thousands of rows; most symbols are not worth a topic |
| **per concept/cluster** | ~20 per repo, matches a module's existing size (98 topics / 15 modules ≈ 6.5) | needs a name and a blurb per cluster, which is generated prose |

Existing modules average **6.5 topics**. Per-file on repo 3 would be 398. That
gap is the decision.

**2. Can `topic_progress` distinguish "read" from "understood"?**

**No.** One row, one `completed_at`, NOT NULL. Options: add a nullable
`understood_at` (additive, but two timestamps is a weak model of comprehension);
add a nullable `state` VARCHAR; or leave it binary and treat "read" as the only
claim the table makes. **This is a schema decision on a curated table and I have
not made it.**

**3. `review_items.node_id` is VARCHAR(40) — a file path does not fit.**

`superset-frontend/src/components/ErrorMessage/index.tsx` is 52 characters.
Options: a `repo:<id>:<file_id>` synthetic key (fits, opaque, needs a join to
render); widen the column (touches an existing column — **fails the risk gate**);
or a hash prefix (fits, collides in principle). The synthetic key is the only one
of the three that is additive.

**4. `resources.status='intent'` and `url=null` are the seeded shape.**

A code reference is exact and already resolved, so it would be the first resource
whose location is known at creation. Either a new `status` value (e.g. `resolved`)
or a new `kind` (`code_ref`) — both are additive since the columns are free-text
VARCHARs, but the vocabulary is a decision.

**5. `modules.source` — reuse `generated` or add `codebase`?**

`generated` already means "not hand-written". A third value distinguishes
codebase-derived from roadmap-derived, which matters for any later query that
wants one and not the other. Additive either way; naming is yours.

---

## What is NOT in the schema and would be needed

For a `code_ref` resource: **`repo_id`, `path`, `line_start`, `line_end`,
`commit_sha`**. None of the five exists. `file_path` is for uploads (a path on
this machine), not a path within a registered repo, and there is no SHA column
anywhere in `resources` — which matters because a code reference without a commit
is a reference to a moving target, and that is the single clearest way a
codebase-derived resource differs from a curated link.
