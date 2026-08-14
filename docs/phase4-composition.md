# Phase 4 composition report: what the curated tables actually hold

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
