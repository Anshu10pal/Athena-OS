# Decision log

> ## ⚠ Provenance, 2026-08-17: graph-derived numbers for repos 3 and 6 predate two instrument fixes
>
> Any figure in this log computed from the **import graph** — cluster and
> subsystem counts, cluster sizes and labels, algorithm agreement, unclustered
> rates, SCC/cycle counts, `fan_in`/`fan_out`, PageRank ranks, reachability
> and layer coverage — for `eslint` (repo 3) or `apache/superset` (repo 6) was
> measured before one or both of:
>
> - **§17.26** — `repo_id=3` was a 398-file stripped fixture, not
>   `eslint/eslint` (1,447 files). Affects eslint only.
> - **§17.28** — `is_test_file` never matched a top-level `tests/` directory,
>   so **58.8% of eslint's and 9.8% of Superset's resolved edges** carried
>   production weights instead of `test_edge`'s 0.05. Affects both, and
>   affects anything derived from edge weights: clustering, weighted PageRank,
>   RRF, and the Architecture map's directory `kind`.
>
> Individual rows below are marked where the number is load-bearing to the
> decision. Where a row's *reasoning* survives but its *example* does not,
> that is stated inline. Rows without an inline mark should still be read
> against this banner if they quote a graph-derived figure.
>
> **Not affected:** curated-table counts, timing measurements, row/column
> counts, and anything measured from the filesystem or git history rather than
> the resolved import graph.

Every non-obvious choice, why it was made, and what it cost or bought. A
decision belongs here when a reasonable person could have chosen otherwise,
when reversing it later would be expensive, or when the reasoning is not
recoverable from the code.

Entries are append-only. When a decision is amended or reversed, the original
stays and gains a **Superseded by** line — a log that quietly rewrites itself
cannot be used to check whether past reasoning held up.

**Status key:** `active` · `amended` · `superseded` · `at risk` (still in
force, but a known problem argues against it) · `deferred`.

---

## A. Scope and non-negotiables

### A1 — The codebase agent makes zero LLM calls
*2026-08-08 · active*

**Decision.** No part of the repo analysis pipeline — ingest, ranking,
clustering, health scoring — calls any language model, local or remote.

**Why.** The feature analyses source code the user has not agreed to send
anywhere. A guarantee that is enforced only by convention gets broken by the
next contributor who wants one summary.

**Impact.** Enforced by `test_jobs.py::test_zero_llm_calls_across_the_whole_pipeline`,
which patches `app.core.llm.chat/chat_json/chat_stream` to raise. Costs us
natural-language labelling of subsystems and any semantic grouping; bought a
guarantee that survives contributors. Embedding work (FastEmbed) had to be
local ONNX, CPU-only, no network egress, to stay inside this.

### A2 — Phase 1 ships without Phase 2 inputs
*2026-08-09 · active*

**Decision.** No co-change coupling, no test-coverage ingestion, no external
services in the first health release.

**Why.** Each is a data-acquisition problem as much as a scoring one, and
shipping them together would have meant none of them were verified properly.

**Impact.** Health measures only what tree-sitter and the import graph
already see. Co-change in particular is the strongest omission — it observes
something neither existing input structurally can.

---

## B. Metric design

### B1 — Three orthogonal axes, never blended
*2026-08-09 · **amended** by F3*

**Decision.** Maintainability, Architecture Health, and Change Hotspot are
reported separately. No combined number.

**Why.** The axes answer different questions and are not commensurable. A
single number would also let a weak axis hide behind a strong one.

**Impact.** More screen real estate, more for the reader to interpret. See F3
for the aggregate that was later added anyway and the constraints attached to
it.

### B2 — Direction is part of the metric's name
*2026-08-09 · active*

**Decision.** Axis 2 was renamed *Architecture Risk* → **Architecture
Health**. Axis 3 is **Change Hotspot — uncalibrated**, reported as *points*,
not a score.

**Why.** A metric called *Risk* scored so that 10 is good forces the reader to
mentally invert it. Naming the direction removes a whole class of misreading.

**Impact.** Made the F3 exclusion argument obvious later: Change Hotspot runs
the opposite direction, which is why it cannot be averaged with the others.

### B3 — "Defect Risk" and its synonyms are forbidden vocabulary
*2026-08-09 · active*

**Decision.** The terms *Defect Risk*, *Defect Exposure*, *bug risk* and
*predicted defects* may not appear in code, API payloads or UI.

**Why.** There is no defect data anywhere in this system — no issue-tracker
linkage, no bug-fix commit classification, no post-release failure history.
A number labelled as defect prediction would have nothing behind it.

**Impact.** Constrains naming permanently, including for future contributors
who may assume the label is available.

### B4 — Deduct from 10, with per-category caps and linear ramps
*2026-08-09 · active*

```
severity       = clamp((value − warn) / (saturate − warn), 0, 1)
axis_deduction = min(AXIS_CAP, Σ_categories min(CATEGORY_CAP, Σ_markers weight × severity))
```

**Why.** Step functions make a one-unit change flip a score; caps stop a
single dimension consuming the whole axis.

**Impact.** Every marker's contribution is separable and explainable, which is
what made the per-marker deduction report (D2) possible at all.

### B5 — `AXIS_CAP = 9.0` is documented as inert
*2026-08-09 · active*

**Decision.** Keep the axis cap even though it currently equals the sum of
each axis's category caps and therefore never binds.

**Why.** It is a forward guard: adding a category later must not silently
drive a file to 0.

**Impact.** Recorded as inert rather than presented as shaping the score —
describing a non-functioning guard as active would misrepresent the mechanism.

### B6 — Symbol → file aggregation takes the max, and keeps the evidence
*2026-08-09 · active*

**Decision.** Complexity markers use the **maximum** severity across a file's
functions, and additionally record how many functions breach the threshold
plus the worst symbol's name and line.

**Why.** `max` alone loses "3 functions over CC 10"; `mean` buries one
catastrophic function in a large clean file.

**Impact.** Explanations read *"3 functions over CC 10; worst `resolve_imports`
at CC 34, line 212"*. Costs extra fields per marker.

### B7 — Instability and distance-from-main-sequence excluded
*2026-08-09 · active*

**Why.** Both require **abstractness**, which needs an abstract/interface
distinction the parser does not record — verified: `CodeSymbol.kind` only ever
holds `class`/`function`/`method`. Instability without the axis it is meant to
be balanced against is a number with no interpretation.

**Impact.** Two well-known architecture metrics unavailable until the
extractor records abstractness.

### B8 — `hub_file` renamed `bidirectional_coupling_hub`
*2026-08-09 · active*

**Why.** The rule fires only when fan-in **and** fan-out both clear P90, so it
deliberately ignores a pure high-fan-in utility. It does not measure hubness
in general and must not claim to.

### B9 — Change recency and sole ownership demoted to context
*2026-08-09 · active*

**Decision.** Neither deducts. Both are displayed neutrally.

**Why.** Recency is genuinely bidirectional — recent change can mean actively
maintained or freshly destabilised, and we have nothing that distinguishes
them. Ownership concentration measures knowledge distribution, not defect
likelihood, and there is reason to think a dominant owner may be the
*healthier* configuration, which would make a deduction directionally wrong.

**Impact.** **The ownership literature claim is explicitly not relied upon.**
The factor is context-only regardless of how that literature resolves, so the
decision does not depend on a citation we have not verified.

### B10 — Reachability is evidence, never a deduction
*2026-08-09 · active*

**Decision.** `possibly_unreachable_by_static_imports` is persisted and shown,
and never subtracts from Architecture Health.

**Why.** Known false positives — framework discovery, plugins, generated code,
reflection, dynamic import — and it was **confirmed firing wrongly in our own
data**.

**Impact.** 66/173 files on repo 1 flagged; as a deduction that would have been
catastrophic. With no entry points at all the value is `None`
("could not be determined"), not `False` — asserting every file is possibly
dead would be an artifact of having nothing to search from.

---

## C. Missing data

### C1 — Exclude, don't zero
*2026-08-09 · active*

**Decision.** An unavailable marker, factor or axis is dropped from both the
numerator **and** the denominator. Never scored 0, never given full marks.

**Why.** Zero reads as "measured and terrible"; full marks reads as "measured
and fine". Both invent evidence.

**Impact.** Applied consistently at every level — markers, axes, the F3
aggregate, and the clustering agreement metrics. Requires N/A to be a
first-class state everywhere rather than a sentinel value.

### C2 — The substance floor is not applied uniformly
*2026-08-09 · active*

**Decision.** `SUBSTANCE_FLOOR_NLOC = 10` excludes trivial files from
Maintainability, but not from every axis.

**Why.** A 4-line file cannot be meaningfully graded for complexity, but it can
still sit inside an import cycle.

**Impact.** 33 of 596 files excluded in the threshold pass. Different axes
legitimately score different file populations, which every aggregate has to
account for.

### C3 — Degenerate churn gates the whole Change Hotspot axis
*2026-08-09 · active*

**Why.** On a shallow clone every file reports the same `commit_count`, so
churn carries zero information. Verified directly: all 398 files on the eslint
validation repo report `commit_count == 1`.

> **Note, 2026-08-17:** the "398 files"/`--depth 1` eslint repo referenced here
> was a stripped fixture, since replaced by a full, unscoped clone (1,447
> files) — see `docs/external-validation-eslint.md`'s Round 5. The gate this
> decision describes is unaffected (a real gate needed for any shallow clone,
> which is still a normal registration path), but the specific 398-file/
> `commit_count==1` observation is historical, not a property of the repo
> currently registered as repo id 3.

**Impact.** Ranking files by a constant would produce a confident-looking list
with nothing behind it. The axis reports N/A instead.

### C4 — The Architecture evidence gate is structural, not advisory
*2026-08-09 · active · **narrowed by K9***

**Decision.** When `cycle_participation` has no data the axis sets
`inputs_complete = False` and **withholds `score` entirely**; the provisional
number is parked in `provisional_value` for diagnostics.

**Why.** An inline caveat still leaves a prominent 9.98 on screen anchoring the
reader on a conclusion the evidence does not support. A UI cannot render a
value it was never given.

**Impact.** The strongest pattern in this codebase — structural impossibility
over documented convention. Reused for the coverage disclosure (F5) and the
staleness verdict (F7).

### C5 — Churn resolution is a badge, not a gate
*2026-08-09 · active*

**Decision.** `CHURN_RESOLUTION_MIN_SPAN = 5`: when P95 − P50 is narrower,
flag `resolution_limited` rather than withholding the score.

**Why.** Ranking *within* the repo stays usable even when the ramp is only two
commits wide — unlike the architecture case, where the missing marker was the
dominant one.

**Impact.** Repo 1 reaches maximum exposure at three commits. Deliberately a
**span** check, not a distinct-value check: §5.2 asks whether churn varies at
all, a weaker question than whether it varies enough to grade. Promoting spread
to first-class eligibility is an open candidate.

### C6 — `inputs_complete`, not `evidence_complete`
*2026-08-09 · active*

**Why.** The field asserts that every marker **in this contract** had its
input, and nothing more. 10.00 means "no file-level cycles and no
bidirectional coupling hub were found" — not "the architecture is healthy",
particularly not when the same product shows the user three directory-level
cycles elsewhere.

**Impact.** The rename shipped without a migration and caused a live 500 — see
I2.

### C7 — Per-marker N/A reasons are preserved, not collapsed
*2026-08-09 · active*

**Decision.** Three distinct states: `no_input` (coverage gap),
`input_available_zero_severity` (a result — evidence of absence),
`not_applicable` (permanent, e.g. no rule for this language).

**Why.** An undifferentiated "inactive" list conflates "we could not look" with
"we looked and found nothing" — opposite meanings for a reader deciding whether
to trust the score.

### C8 — Documentation coverage is Python-scoped
*2026-08-09 · active*

**Why.** `CodeSymbol.docstring` is populated only by the Python extractor —
verified 0 of 110 TS/TSX symbols and 0 of 1031 on eslint.

**Impact.** Excluding it rather than scoring JS/TS as undocumented raised
eslint's honest score from 0.57 to 0.67. Scoring it would have measured our
extractor, not their code.

---

## D. Thresholds and calibration

### D1 — Freeze thresholds before scores reach the UI; never tune against outcomes
*2026-08-09 · active*

**Decision.** A distribution report across all repos was required before
scores appeared anywhere, with any adjustment recorded with rationale.
Tuning against defect outcomes is **prohibited**.

**Why.** Tuning against outcomes is calibration; doing it while still labelling
the result "uncalibrated" would be the exact misrepresentation the contract
exists to prevent.

**Impact.** Caught the failure conditions early — the pass measured 563 scored
files across 596, and a wrong prediction (>80% pristine predicted, 63.9%
actual) exposed a ~9× reasoning gap between per-function and max-across-file
rates.

### D2 — Report mean deduction *beside* fire rate, not instead of it
*2026-08-09 · active*

**Why.** Fire rate alone cannot distinguish a marker that fires often and
contributes nothing from one that dominates its category.

**Impact.** This is what surfaced D3 and D4. Built as a pure scoring engine
rather than a throwaway script, so the same code produces the report and the
product scores.

### D3 / D4 — The warn-at-minimum defect class (found twice)
*2026-08-09 · active · `thresholds_version` 1 → 2 → 3*

**Decision.** `broad_error_handling` warn 1 → 0; `cycle_participation`
warn 2 → 1.

**Why.** A linear ramp whose `warn` sits **at** the minimum meaningful value
silently exempts the first real occurrence. The first bare `except:` was free;
a 2-file mutual import cycle was free.

**Impact.** Repo 1 went from 7 to 14 files flagged for broad handling, eslint
from 0 to 3. Notably the second instance was found by a **disclosure test**,
not by the distribution report — all repos have 0 cycles, so the report could
not have shown it. Two different verification methods were needed for the same
defect class.

### D5 — Calibration is out of scope, with preconditions predeclared
*2026-08-09 · deferred (blocked)*

**Decision.** Tier A may only be claimed with ≥200 labelled files and ≥50
defect-labelled commits, a time-ordered holdout, a result beating **both**
NLOC-only and churn-only ranking, and AUC/CI/n shown in the UI rather than
buried in a doc.

**Why.** Declaring the bar before attempting the work removes the temptation to
lower it afterwards.

**Impact.** Blocked here regardless: our repo has **0 conventional `fix:`
commits**, so this cannot engage without an external corpus.

---

## E. Snapshots and identity

### E1 — Source fingerprint added to snapshot identity
*2026-08-09 · active*

**Decision.** A SHA256 manifest digest over sorted `(path, content_sha256)`
pairs, alongside `head_sha` and `working_tree_dirty`.

**Why.** HEAD SHA + `dirty = true` cannot identify a local working tree — two
different sets of uncommitted edits share both values. An idempotency check on
those alone would treat different source states as identical.

**Impact.** Costs one indexed query, no re-hashing (ingest already computes
`content_sha256`). Path is included so a pure rename changes the fingerprint,
since it changes the import graph. Became the basis of the staleness check
(F7) months' worth of bugs earlier than expected.

### E2 — Snapshots are written atomically
*2026-08-09 · active*

**Decision.** Score entirely in memory, then one transaction for the snapshot
row and all per-file rows.

**Why.** A partially written trend snapshot is worse than none — it is
indistinguishable from a complete one on read.

### E3 — Trend comparability requires branch *and* all three version stamps
*2026-08-09 · active*

**Why.** Comparing scores across a `thresholds_version` bump measures our
threshold change, not the code's.

**Impact.** `trend_delta` returns an explicit reason when incomparable, never
`0.0` to mean "unknown".

### E4 — Explanations and marker parameters are stored, never back-filled
*2026-08-09 · active*

**Why.** Thresholds are versioned, so explaining a historical score with
today's numbers explains it wrongly.

**Impact.** Snapshots taken before a field existed simply omit it and render
nothing. Repos 2 and 3 currently show no parameter block until re-analysed —
accepted as the honest behaviour.

### E5 — Health is a conditional, non-fatal pipeline stage
*2026-08-09 · active*

**Decision.** Order is resync → ingest → rank → health. Health runs only after
successful ingest and rank, and only when source state or scoring versions
changed. A health failure is recorded as a retryable stage failure and must not
fail or roll back ingest/rank.

**Why.** Health is derived; the ingest it derives from is the expensive,
valuable part.

---

## F. API and presentation

### F1 — `GET /health` 404s when no snapshot exists
*2026-08-09 · active*

**Why.** An empty scorecard reads as "measured and fine".

### F2 — The Code Health tab was removed; tiles live on Overview
*2026-08-09 · active*

**Decision.** Aggregate tile plus three axis tiles on the Overview, each
opening an insights panel. Tab order: Overview, Layers, Reading List,
Architecture, Dependency Graph, Matrix, Dependency Clusters, Focus.

**Impact.** `HealthView.tsx` deleted as orphaned.

### F3 — A blended aggregate out of 100 ships, departing from B1
*2026-08-09 · **at risk***

**Decision.** The mean of the two health axes, each rescaled 1–10 → 10–100.

**Why.** A product decision, taken **before** the D5 evidence B1 said would be
required. Recorded as an amendment in the contract (§16) rather than left as a
silent divergence between doc and product.

**Compensating constraints — these are what make it acceptable:**
the tile face always states its own composition (`N of M axes`, `· partial`);
an unmeasurable axis is excluded, never zeroed or given full marks; no
aggregate at all when no health axis is measurable; bands stay coarse
(≥70 / ≥45 / below) because a finer gradient would imply precision the numbers
do not have; the panel states it is "a convenience summary, not a validated
measure".

**Why it is at risk.** `cycle_participation` fires on **0 of 599 files**, so
Architecture Health reads ~100 on every repo we have. The aggregate is
effectively `(Maintainability + 100) / 2`, which pins every repo into 95–100 —
and flatters it. Half the headline number currently cannot discriminate.
See G2.

### F4 — Change Hotspot is excluded from the aggregate as a *category* error
*2026-08-09 · active*

**Why.** Not a calibration issue. It is a review-priority ranking where higher
is worse, against two quality scores where higher is better. Averaging requires
silently inverting one, and the result answers no question — a repo could raise
its aggregate by becoming *more* urgent to review.

**Impact.** Keeps its own tile on its native 0–9 scale; its panel says why.

### F5 — The coverage disclosure is structured API data, not a rendering rule
*2026-08-09 · active*

**Decision.** `inputs_complete`, `file_level_cycle_count`,
`directory_cycle_count`, `active_markers`, `limitations` ship in the payload,
with a test that a non-null Architecture Health score renders them beside it.

**Why.** A documented convention lets a future UI receive a score and omit the
scope it applies to.

### F6 — `active_markers` means *fired*, not *had data*
*2026-08-09 · active*

**Why.** "Input available" and "affected this score" are different concepts.
Only the latter belongs in a score explanation.

**Impact.** Corrected after shipping — the original implementation listed
markers with data, and the commit message wrongly claimed it showed "what
actually carried the score".

### F7 — A stale score keeps its number and loses its verdict
*2026-08-09 · active*

**Decision.** `snapshot_staleness()` compares the stored fingerprint and
version stamps against current state and returns one of `no_files_ingested`,
`source_changed`, `scoring_changed`. Stale tiles grey out and lose their band
colour; the number stays.

**Why.** Found in production: the Contents panel read 0 files while the tiles
showed a green 97. The snapshot was not wrong when taken — presenting it as
current was. Withholding the number entirely would lose information the reader
may still want; withholding the *green* is the point.

**Impact.** The empty case is checked before the fingerprint comparison
deliberately — with no files the empty-manifest digest also differs, but "the
source changed" is the wrong thing to tell someone whose repo has nothing in
it.

---

## G. Graph and clustering

### G1 — No Neo4j; Cytoscape.js + ELK over the existing SQLite endpoint
*2026-08-09 · active*

**Decision.** Rebuild the file-level graph as a scoped, expandable explorer —
not a restored raw all-files force graph.

**Why.** The data already exists and is already correct. A graph database would
add an operational dependency to solve a rendering problem.

### G2 — A directory-cycle marker was deliberately *not* added
*2026-08-09 · **premise superseded by K3***

**Why at the time.** Adding a marker is a contract change with its own
before/after obligation, and the file-level marker is not *wrong* — a file
genuinely inside an import cycle is a real finding, it simply does not occur
here. Three repos is too small a corpus to conclude file-level cycles are rare
in general.

**The finding behind it.** Zero file-level import cycles across 599 files,
verified two independent ways (a synthetic 3-cycle is detected; networkx's
`find_cycle` agrees both real graphs are acyclic). Consistent with the 3
directory-level cycles that do exist — a directory cycle needs only `a1→b1`
and `b2→a2`, with no single file in a cycle.

**Why it is now at risk.** The judgement was made when the axis was one number
in a dedicated tab. F3 put it on the Overview carrying half the headline
number, where a constant is actively misleading. This is the leading candidate
for `thresholds_version` 4.

**Superseded 2026-08-12 (K3).** The premise — that file-level cycles are rare —
was drawn from 599 files across three small young repos. On apache/superset,
**828 of 6,516 files sit in import cycles**, the largest spanning 604. The
file-level marker was never inert; it was measuring something the corpus was
too small to contain. A directory-cycle marker may still be worth adding, but
no longer as a rescue for an axis that does not discriminate — it does. See
K2 for the sampling rule this should have been held to.

### G3 — HDBSCAN keeps the library default `min_samples`
*2026-08-08 · active*

**Why.** Lowering it made exact-minimum-size clusters appear, but caused
density chaining — a worse failure than the one it fixed. Investigated
empirically rather than assumed.

**Impact.** Tradeoff documented rather than silently tuned.

---

## H. Deployment and credentials

### H1 — A credential lookup that cannot be performed means *absence*, not failure
*2026-08-09 · active*

**Why.** A managed host has no keyring backend, so `keyring.get_password`
raises `NoKeyringError` — which subclasses `RuntimeError` and therefore
surfaced as "Could not acquire the repository" on a **public** clone that
needed no credential at all.

**Impact.** Public clones work with no configuration anywhere. Warned once, not
per call.

### H2 — Git tokens are per-host env vars; no generic fallback
*2026-08-09 · active*

**Decision.** `ATHENA_GIT_TOKEN_<HOST>` (host uppercased, non-alphanumerics →
`_`), checked ahead of keyring. There is deliberately **no** generic
`ATHENA_GIT_TOKEN`.

**Why.** A single variable would be offered to whatever host the submitted URL
names, so one mistyped or hostile URL becomes a credential disclosure to a
third party.

**Impact.** Slightly more configuration per host; a test asserts a token is
never offered to a different host. The token still lives only in the
environment — never in the URL, the argv, or the askpass script file.

### H3 — Ingest refuses to delete everything when discovery finds nothing
*2026-08-09 · active*

**Why.** Discovering nothing where there was previously something is a broken
checkout — an empty clone, a lost ephemeral disk, a bad `source_root` — far
more often than it is a repo whose every source file was deleted. The cleanup
pass deleted every unseen file, silently emptying the repo while snapshots and
ranks survived to keep rendering numbers for absent source.

**Impact.** Scoped narrowly: a legitimately empty *first* ingest is still
allowed, and ordinary partial deletions still clean up — otherwise the guard
would trade one stale-data bug for another. All three boundaries are tested.

---

## I. Process discipline

### I1 — Predict before measuring, and report the result either way
*2026-08-09 · active*

**Impact.** The threshold pass predicted >80% pristine files and measured
63.9%. The cause — reasoning from per-function rates (3.2%) when markers use
max-across-file (28.8%), a ~9× gap — was only visible because the prediction
was written down first.

### I2 — Migrations get a parity test, and it may never touch a live database
*2026-08-09 · active*

**Why.** Tests build schema via `create_all`, so migration drift is
**structurally invisible** to them. The `evidence_complete` → `inputs_complete`
rename shipped without a migration and caused a live 500 that no test could
have caught.

**Then the fix itself misfired:** `alembic/env.py` overwrites `sqlalchemy.url`
from `settings.DATABASE_URL`, so the new parity test migrated the **live
development database**. It was a no-op only by luck.

**Impact.** `assert_isolated()` now asserts the resolved URL is the generated
scratch path **and** explicitly rejects the configured development URL. The
guard was verified by injecting a canary column rather than assumed to work.

### I3 — Tests must be able to fail
*2026-08-09 · active*

**Impact.** Removed two stub tests that always passed and rewrote a third that
re-asserted a copy of the guard rather than calling it. A JavaScript golden
fixture was invalid source (`a && b || c ?? d` is a real SyntaxError) that
tree-sitter parsed anyway via error recovery — fixed, plus a test asserting no
fixture relies on error recovery. A marker test patched `scc_size`, which the
endpoint overwrites — rebuilt around a real mutual import.

### I4 — Verify claims about existing data rather than assuming
*2026-08-09 · active*

**Impact.** Required before the contract was written; caught that
`CodeSymbol.kind` never holds an abstractness distinction (B7) and that
docstrings are Python-only (C8). Both would have produced meaningless metrics.

---

## J. Open and deferred

*Revised 2026-08-12 after the superset run — see §K.*

| | Item | Status |
|---|---|---|
| K8 | Non-ASCII paths silently lose their history (`core.quotepath`) | **open, cascade suppression instance 7** |
| D5 | Calibration | **unblocked** — 10 of 25 fix-mentioning commits exist; the "0 conventional `fix:` commits" blocker measured the wrong thing |
| C5 | Promote churn spread to first-class eligibility | candidate — superset is the first repo with real resolution to test it against |
| A2 | Co-change coupling, coverage ingestion, ownership | deferred |
| G2 | Directory-cycle marker | **demoted** — the file-level marker discriminates (K3); this is now an addition, not a rescue |
| — | ESLint validation never re-run against subsystem output, which was HDBSCAN's justification | open |
| — | `codebase-agent-handoff.md` stops at K1; nothing covers health, deployment fixes, the Overview restructure, or §K | open |
| H3 | `REPO_CLONE_ROOT` still defaults to an ephemeral path while the database is persistent | needs a mounted disk |
| — | **§17 batch — DONE.** Written as §17.15 (predicate-as-property versus predicate-as-list, superseding §17.10), §17.16 (report the instrument, not only the denominator), §17.17 (count/size coupling at fixed depth), §17.18 (the verified-reachable convention) and §17.19 (a measurement-versus-inference table with re-verification paths, which did not previously exist). **Planned as five entries; four were written.** The `expire_on_commit` feedback loop was already §17.13, committed in `d377815` the session it was found — a whitespace-normalised probe confirmed it holds the sublinearity table, the 0.42/0.88/2.07 per-commit costs, the 66.53-vs-42.98 variance explanation and the rejected sampling lever. Re-writing it would have duplicated. **That the batch list was one item stale is itself the §17.16 failure in miniature:** a recorded to-do describing a state the record had already moved past | **closed** |
| — | **Cold ingest — DONE, contract §17.14.** 477.9 s for 6,522 files, which settles the MCP question it existed to gate: the first call cannot be synchronous and the interface needs an async job handle. Only `parsing` scales with a cold cache; nine other stages are flat within noise. The prediction scored 8-of-10 on structure and 2-of-10 on magnitude, every miss low — see §17.0b's fifth clause. The recorded figure is pre-`expire_on_commit`-fix and now overstates; deliberately not re-measured, since the decision is unchanged either way and a fresh single run on a machine with ~1.5× between-run variance would trade an honestly-labelled stale number for a falsely-precise new one | **closed** |
| — | The encoding test (K7) must force a non-UTF-8 decode or it passes on Linux CI for the wrong reason | **open** |
| — | **The warm floor gates Phase 8, and is not performance debt.** Recorded this way deliberately: it is a design constraint on unstarted work rather than a defect a user can see, so it does not compete with items that fix controls which visibly do nothing. Revisit when drift detection becomes live — at that point the question is whether it can run per-push at all, not whether it is slow | **open, gates Phase 8** |
| — | **The warm floor now needs `health` and `resync`, not caching.** Removing the `expire_on_commit` loop took a warm superset job from 183.5 s to 94.3 s, with non-health non-resync work at 41.5 s rather than 170 s. Drift-detection-on-push is arguable at 40 s where it was not at three minutes — so this moved from *blocks Phase 8* to *Phase 8 needs its own look at health (30.6 s) and resync (22.0 s)*, which now dominate a full warm cycle and have not been examined. Progress, not resolution | **open** |
| — | **Architecture, Matrix and Dependency Clusters render the file filter bar and ignore it.** Their content IS file-derived, so the fix is to honour the filters, not to hide the bar — the opposite of the Overview/Findings fix, which hides a bar that could never apply. The "Showing N of M files" counter moves while the view does not, the same shape as the recorded "Showing 0 of 173" bug. Found by auditing the predicate rather than the symptom — a condition stated as "views keyed on files" would have hidden the bar on all five. **CORRECTED 2026-08-13 after reading the endpoint rather than reasoning about it — the split recorded here was wrong in BOTH directions; see the two rows below** | **superseded** |
| — | **`/graph` filter vocabulary — DONE.** Architecture, Matrix and the Dependency Graph now honour the file filter bar they had been rendering and ignoring. Endpoint accepts `segments`, `languages`, `query`, `hide_noise`, mirroring `filterFiles` exactly; `hideZeroFanIn` and `subsystemId` excluded with the reasons recorded at the endpoint so they are not added later "for completeness". Repeated values (`?languages=a&languages=b`) rather than a client-side collapse — verified over HTTP as well as by direct call, since the endpoint tests bypass FastAPI's query parsing entirely and would have proved the filtering right while saying nothing about the wire format. Three values on superset returned their exact union (2,547 + 2,175 + 1,733 = 6,455). **The counter defect is closed**: filtering to python moves it 6,523 → 2,547 *and* the map redraws (97 → 79 nodes), the Matrix's axes lose every frontend directory and its cycle count goes 2 → 7. Truncation notice added, built against the post-filter denominator from the start. Server confirmed never to emit a dangling edge at either level — file level prunes to `kept_ids`, directory level prunes `dir_edges` to `kept_group_ids` after capping | **closed** |
| — | **Architecture and Matrix — harder than recorded. Client-side post-aggregation filtering is NOT an available option.** The earlier entry offered it as one of two choices; it does not exist. `DirNodeT` carries no member list, so a surviving node would report aggregates computed over **all** its files while the filter selects a subset — "50 files" beside a filter matching 3, and edge weights unchanged. That is confidently wrong output, which is strictly worse than controls that do nothing, and it is the same defect as the client-side fix rejected for the filter bar itself. Re-aggregating client-side instead means a second copy of `aggregate_to_directories` in TypeScript — a drifting second implementation of a rule this project keeps server-side. **So the only correct fix is extending the endpoint's filter vocabulary**, and the machinery is already right: `GET /graph?level=directory` filters files BEFORE aggregating and caps directories after, reasoned in its own docstring. It accepts `language`, `path_prefix`, `min_score`; **no frontend caller sends any of them** (they appear only in `test_ranking.py:149` and `test_repos_api.py:219-221`). Not a missing capability — an unconnected one. Scope agreed: honour `segments[]`, `languages[]`, `query`; extend the endpoint to accept REPEATED values rather than have the client collapse a multi-select to one, which would silently under-filter *(**Scope addition, 2026-08-20, from checkpoint 2.6's surviving measurement.** After a rapid wide→narrow scope change the Dependency Graph takes **10.4–11.5s** to finish rendering on apache/superset, against **958ms** for an uninterrupted layout. Filter changes drive the SAME re-layout path (`DependencyGraph.tsx`'s effect on `[cy, elements, showFullGraph, focusIds]`), so a filter toggle on the largest repo will sit for ~10s with no signal — which gets reported as 'the filter is broken', not 'the filter is slow'. **This is :682 scope, not adjacent to it:** the frontend-send checkpoint needs debouncing on the filter inputs and/or a visible re-layout indicator, and the verify checkpoint must exercise both under filter toggling on superset specifically.)* *(**RE-SCOPED 2026-08-20 (reconciliation pass). The BACKEND HALF OF THIS ENTRY WAS ALREADY SHIPPED WHEN IT WAS WRITTEN — one day later.** `segments`/`languages` as repeated `Query(None)` params, plus `query` and `hide_noise`, landed in `9fb9bce3` on 2026-08-14 (`repos.py:363-372`, marked Phase L2) carrying the same 'do not collapse a multi-select' reasoning this entry argues for. Union-within-param / intersect-across-param semantics and post-filter counts are pinned by 15 tests in `TestGraphFilterVocabulary`, canaried 2026-08-20. **What actually remains of :682 is the FRONTEND half: no caller sends any of these params** — still true, verified this pass. A checkpoint-0 audit in this session read the entry and repeated its claim that :682 was 'genuinely unbuilt'; that audit checked the callers and not the endpoint, and was wrong.)* | **open — FRONTEND half only** |
| — | **Dependency Clusters — easier than recorded; it needs no new endpoint.** The earlier entry said it "takes no filtered input at all and needs the wiring first". It takes no filtered input, but the data is already client-side: `RankedFileT` carries all three subsystem ids (`api.ts:92-94`), which is how the cluster filter chips are derived today. Per-cluster visible counts are computable from `visible` with no new endpoint and no re-implemented aggregation. One real complication: `agreement` and `cycle_coherence` are **repo-wide** and cannot be recomputed under a filter — suppressed with a note saying why, not caveated, since a caveated number still gets read. §17.5c territory: a statistic whose population differs from the one on screen *(**CLOSED 2026-08-20 (reconciliation pass) — this was never 'in progress'; it shipped in the same commit that wrote this entry.** `2695cac` (2026-08-13) is titled 'Make Dependency Clusters honour the file filter, and correct the deferred entry'. Verified: `lib/clusterList.ts` defines `VisibleCountsT`/`visibleCounts` and filters by visible count; `RepoDetail.tsx:1487` passes `visibleCounts={clusterVisibleCounts}`; the repo-wide `agreement`/`cycle_coherence` suppression is at `RepoDetail.tsx:353`; 16 tests in `clusterList.test.ts` pass. The label stood stale for 7 days. Pattern noted for checkpoint 7's closure line, NOT its own §17 subsection — superseded by §17.30.)* | **closed** |
| — | **DependencyGraph `Cannot read properties of undefined (reading 'index')` — reported once, boundary-caught, never reproduced.** Repo 6. Reported sequence: scrolling, clicked one CLUSTER chip, unclicked the same chip, then it failed; the user's own immediate repeat did not reproduce it either. **Not reproduced across three scripted attempts** — 8 filter permutations (invalid: the view renders a "Select a file…" placeholder until `hasFocus`, so Cytoscape never mounted and `canvas` stayed 0 throughout), a focus-then-filter sequence (invalid: every interaction timed out, so any result would have been a cascade), and a clean full-graph run on all 6,523 nodes (valid, rendered in ~3 s, no error). **Two facts established from the code, worth keeping whichever way this goes:** the update path is a FULL replacement (`cy.elements().remove(); cy.add(elements)`), so cytoscape's graph cannot diverge from what `buildGraphElements` emits — which refutes the "guard checks a different set" hypothesis; and **stale ELK layouts are NOT cancelled** — the effect starts `cy.layout(...).run()` on every `elements` change and returns no cleanup, so a layout still settling when the elements are replaced continues against removed nodes. That is consistent with `.index` on undefined, and explains why it needs a narrow→widen *transition* rather than a state and why a slower deliberate repeat misses it. **Invariant pinned but no fix claimed:** 5 dangling-edge tests assert every emitted edge names an emitted node, canaried by removing the guard (all 5 fail). **Instrumented:** the boundary now logs one structured object with filter state, element counts, and ELK layout phase / overlap count. Not closed, not being hunted *(**2026-08-20, third investigation.** The blocker that invalidated the prior scripted attempts is identified and is NOT a bug: the page-level file search calls `setView("focus")` (`RepoDetail.tsx:981-986`), so searching while ON Dependency Graph navigates away and unmounts cytoscape — which is why `canvas` stayed 0 both times. The working order is SELECT FIRST, then switch tabs: the seeding effect at `RepoDetail.tsx:815-820` copies `selectedFileId` into `graphFocusFileId`, making `hasFocus` true. Verified: 3 canvases mount, pixels readable and stable at idle. **Two corrections to this entry's own premises:** ELK no longer runs via `cy.layout(...).run()` — `6fe2e3f` moved it to a Web Worker and wired cancellation (`DependencyGraph.tsx`, now `return runElkLayout(...)`), so the mechanism described above no longer exists as written; and the graph is capped at **400 nodes by the backend** with the narrow scope at `DEFAULT_MAX_NODES = 60`, not the thousands assumed — a full-graph layout was MEASURED at **958ms**, not tens of seconds. **A browser-level cancellation test was attempted and abandoned**: it fails on correct code because after a rapid full-graph toggle (~300ms) the graph renders sparse and does not recover within 70s while the controls show correct state — a suspected real defect, unproven, and the next thing to look at here. Wiring is instead pinned by a source-level check (`src/lib/elkLayoutRun.wiring.test.ts`), canaried.)* *(**2026-08-20, checkpoint 2.6 — the suspected sparse-render defect DOES NOT EXIST, and the claim above that it 'does not recover within 70s' is RETRACTED.** Left in place rather than edited away, per §17.16. Reproduced 0/6 headed and 0/6 headless at the same 300ms toggle, so it is not a headless-compositor artifact either — the variable was never the browser, it was the SAMPLING. The abandoned test polled for '6s of unchanged pixels = at rest' and returned the moment it saw that; measured across 4 attempts it sampled at **6.73–6.82s** while the graph actually reaches full render at **10.35–11.52s**. Pixels do not change while ELK is still computing, so a mid-render canvas is indistinguishable from a settled one by that criterion — §17.22, a probe that cannot see the change reports no change. The '70s' figure was also a misreading of my own control flow: 70s was the poll BUDGET, never reached, because the poller returned early every time. **The one real observation that survives:** after a rapid wide→narrow toggle the graph takes ~10–11.5s to finish rendering on apache/superset, against 958ms for an uninterrupted wide layout — worth knowing before :682 makes filter changes trigger the same re-layout path, but it completes and is a latency fact, not a defect.)* *(**Checkpoint 7 planning, 2026-08-20:** the record-drift pattern this entry and :683 illustrate — an entry written describing a plan in the commit that implemented it, and an entry surviving the code it describes — is DEMOTED to a closure line rather than its own §17 subsection. It is displaced by the browser-instrument pattern (§17.30 preview, three instances this session), which is more general and lands in the area the next checkpoints touch. Do not reintroduce the drift pattern as a subsection.)* | **open, instrumented** |
| — | **Cancel the in-flight ELK layout on re-render.** Split from the row above because it is a real defect independent of whether it causes that crash: `DependencyGraph`'s elements effect calls `cy.layout(...).run()` and returns no cleanup, so nothing stops a previous layout when `elements` change. Ordinary React hygiene (an effect starting async work should cancel it) and cheap — a cleanup calling `layout.stop()`. Deliberately NOT bundled with the invariant test, because shipping it alongside would read as "fixed the crash" and the evidence does not support that claim *(**CLOSED 2026-08-20 (reconciliation pass) — fixed in `6fe2e3f` (2026-08-17), four days after this entry was written.** Verified at `DependencyGraph.tsx`: the effect now returns `runElkLayout(...)`, whose cleanup sets `cancelled = true`, and both the `.then` and `.catch` return early when it is set. Note the entry's own premise is also stale — ELK no longer runs via `cy.layout(...).run()` at all; it moved to a Web Worker in the same commit. **This entry is the §15.1 instance the record needed: the fix shipped with NO test, so a regression re-introducing the leak would have been silent for four days and nobody would have known.** Now covered in two layers, both canaried 2026-08-20: `lib/elkLayoutRun.test.ts` (8 tests) pins the cancellation MECHANISM — 4 fail with the `cancelled` guard removed — and `lib/elkLayoutRun.wiring.test.ts` (3 tests) is a source-level tripwire for the WIRING, failing if the `return` is dropped. The wiring layer is deliberately a text check, not a proof: a browser-level test was attempted and abandoned (see the entry above).)* | **closed** |
| — | **The filter bar's CLUSTER chip row was unbounded and filled the viewport — DONE.** 254 chips on apache/superset pushed every file-keyed view's content below the fold; the same symptom that made the Findings queue unusable, except there the fix was to hide a bar that could not apply, and here the bar *does* apply so hiding it would have been wrong. Now the treatment the cluster LIST already had: top 20 by member size (ties by id), a "show all 254 (234 more)" expander, expanded state in the URL as `clusterChips=all` so it survives a tab switch, and **the selected cluster always rendered even when outside the top N** — a selected filter scrolled out of view is worse than an uncapped list, since the view is narrowed and the control that narrowed it is invisible. Verified positionally rather than by chip count, because the symptom was positional: the reading table's top moved from below the fold to **y=750** in an 1100px viewport. PATH (12) and LANGUAGE (4) left alone — capping a list bounded by the repo's shape adds a control that never does anything | **closed** |
| — | ~~**The Dependency Graph renders a 400-node subset of a 6,523-file repo and says nothing about it.**~~ **DONE** with the `/graph` vocabulary batch, deliberately in the same pass: once filters are live the cap applies to the FILTERED set, so a notice built against the unfiltered total would have been right in one case and wrong in the other with nothing to distinguish them. Now reads "Graph shows the top 400 of 6,523 files by rank" and "of N matching files" when filtered. **A second defect surfaced while verifying it:** the "Showing N of M files" counter reported `visibleGraphNodes.length` for every graph-backed tab — the length of the CAPPED array — so on superset it read 400 both before and after a filter, and the cap masked the filter entirely. The counter now reports the server's post-filter total; the cap is stated separately by the notice. Two facts, stated separately, rather than one number trying to be both | **closed** |
| — | *(superseded)* **The Dependency Graph renders a 400-node subset of a 6,523-file repo and says nothing about it.** Observed while canarying the boundary instrumentation: `graphNodes: 400` against `apiEdges: 1794` on superset. `GRAPH_NODE_LIMIT_DEFAULT` caps nodes at file level and the frontend never passes `limit`, so the view shows a truncation the user is not told about — the endpoint *does* return `truncated` and `total_nodes_before_cap`, and nothing renders them. Belongs with the `/graph` filter-vocabulary work: both are about the endpoint's relationship to what actually gets drawn, and a filter that narrows to 400-of-6,523 means something different from one that narrows to 400-of-400 | **open** |
| — | **Phase 4 mapping: the median is right and the TAIL is §17.17 again.** Revised mapping is subsystem→module, architectural concept→topic, **file→resource** (the first attempt mapped file→topic and produced 932 topics in one module against a curated median of 7). Measured: resources per module median **13** (curated 14), resources per topic median **3** (curated 2) — the same shape. But eslint's largest module holds 151 resources and superset's holds 932. That is group count and group size inversely coupled with no fixed level satisfying both — **the third instance after the findings queue and H1's directory rollup**, both of which rolled up to a *budget* rather than choosing a level. The same answer presumably applies: split a subsystem whose resource count exceeds a budget. **Not implemented — design decision.** *(Note, 2026-08-17: the eslint "151" figure was measured against a stripped 398-file fixture, since replaced by a full clone — see `docs/external-validation-eslint.md` Round 5. The count/size coupling shape this row describes is unaffected — superset's 932-file module is independent evidence of the same shape — but the eslint number specifically should not be cited on its own.)* | **open, decide** |
| — | **The topic level does not exist in the data.** Three derivable groupings measured against a 3–8-per-subsystem target: parent directory 4/7 eslint and 19/119 superset in band; 2nd path segment 0% and 4%; `prior_category` 0% and 3%. And the failure is structural, not numerical — eslint's largest subsystem splits by parent directory into **149 / 1 / 1**, one directory with two strays. So `TOPIC_STRATEGIES` is named and selectable with the default being least-bad, and the preview reports the distribution. Inventing a concept level the data cannot support would be the same error as generating a module summary from filenames. *(**Re-measured 2026-08-17 against the corrected graphs.** The in-band rates broadly reproduce — parent directory 8/17 (47%) on eslint, 22/122 (18%) on superset, plus 4/4 on Athena-OS which is a fact about n=4, not the method (§17.5c). **But the structural argument does not survive and is withdrawn.** "149/1/1 — one directory with two strays" was a fixture artifact; on the real corpora the largest module splits 285/17/13/12/10/5… (eslint, top group 69%) and **94/75/56/41/36/34…** (superset, top group 8%). Superset's is genuinely even structure — a concept level DOES exist there. The real finding is that group count is uncorrelated with a 3–8 band because module size spans 3→1,138 files, which is **§17.17's count/size coupling one level down** — i.e. this row and the row above it are the same problem, and the answer is a size-aware budget, not a strategy choice. `single_topic` stays the default on the narrower basis. Full re-measurement in `module_mapping.py`'s docstring.)* | **open, decide — now merged with the §17.17 budget question above** |
| — | **`review_items.node_id` synthetic key is a workaround forced by a column width.** `repo:<id>:<file_id>` fits VARCHAR(40) and resolves through a lookup that already exists; a file path does not fit (`superset-frontend/src/components/ErrorMessage/index.tsx` is 52 chars). Recorded explicitly so that **if the column is ever widened for another reason, someone knows the natural key was the intent** — the synthetic form is not a preference | **open** |
| — | **Absolute reading rank is lost when files become resources.** `resources` has no rank column, so relative order survives (rank-sorted before grouping, `order_index` 0,1,2… per topic, topics ordered by best-ranked member) and "rank 3 of 398" does not. It rides along in the preview payload only. A genuine cost of the file→resource mapping, stated rather than absorbed | **open** |
| — | ~~**Two eslint subsystems produce the same module title (`lib/rules`).**~~ **FIXED — three of them, actually.** Where a title is shared, the module's best-**ranked** member's stem is promoted into it: `lib/rules · index`, `lib/rules · ast-utils`, `lib/rules · code-path-utils`. Unique titles are left untouched. **This is I3's labelling problem one level up** — dominant-prefix as the title with the top-fan-in stem as a subtitle, and the ambiguous-prefix case is precisely where the subtitle earns its keep. The centre file is guaranteed distinct because a file belongs to exactly one subsystem, and it says what the cluster is centred *on* rather than only where it lives. *(Note, 2026-08-17: these three specific titles were measured on the stripped 398-file eslint fixture; the real 1,447-file clone clusters differently — see `docs/external-validation-eslint.md` Round 5 — and does not currently produce three same-titled `lib/rules` modules. The disambiguation MECHANISM is unaffected and still tested; the specific example named here is stale.)* | **closed** |
| — | **Resource cap: 20, rank-ordered, with the total always travelling.** Cap and paginate rather than roll up, because §17.17's first two instances had a hierarchy to roll up *into* and files inside a module do not — inventing intermediate groups is the same objection as splitting a 122-file cycle by severity band. `resource_count`, `resources_shown` and `resources_truncated` are all in the payload; a truncated list whose total is not stated is the graph endpoint's old "400 of 6,523" problem. **This also settles the `order_index` question**: reading rank IS the resource ordering, so nothing is lost by moving files from topics to resources | **closed** |
| — | **A zero-topic module is not reachable, which settles the topic question.** `resources.topic_id` is `NOT NULL` with no `resources.module_id`, so a resource cannot exist without a topic and a zero-topic module returns no resources at all — the API's per-topic fetch is downstream of a schema constraint, not a design choice. Enabling module-level resources needs `topic_id` altered from NOT NULL to nullable, which fails the risk gate. So the choice was never "topics or no topics" but "invent a grouping or decline to": `single_topic` (one topic, `Files`, everything in rank order) is now the default, asserting that the analysis found no sub-structure — which is true — rather than three concepts that are one directory and two strays | **closed** |
| — | **Module identity survives re-clustering by file overlap, not by slug — measured at three thresholds.** A module's slug embeds its `subsystem_id`, and `CodeSubsystem` rows are replaced wholesale on every clustering run, so slug identity breaks on exactly the operation identity must survive. Demonstrated on eslint: a real re-cluster renamed **17 of 18** modules; with overlap matching all 18 were carried, 0 orphaned, and all 5 planted `topic_progress` rows survived — under slug identity that is 18 deletions and 5 destroyed study records. Matching is by **path**, not `file_id` (ids are replaced on re-ingest too), against the OLD module's size, one-to-one and greedy by overlap, reusing `subsystems.py`'s `custom_label` carry-over rule so there is one notion of "the same cluster" rather than two. **Threshold re-measured at this scale** rather than inherited, since here it decides whether study survives rather than whether a label is cosmetically right. Determinism first: identical input re-clusters to **100%** match at 0.50/0.70/0.90 on all three repos — the algorithm is deterministic, which had never been checked. Then perturbation, dropping every Nth file by sorted path to simulate an ingest delta: <br><br>`-2%` → eslint 95.2 / 90.5 / 76.2%, superset 95.7 / 94.9 / 93.3%<br>`-5%` → eslint 81.0 / 71.4 / 61.9%, superset 92.2 / 89.0 / 80.0%<br>`-10%` → eslint 71.4 / 66.7 / 38.1%, superset 84.7 / 79.2 / 56.9%<br><br>0.50 dominates at every delta and 0.90 collapses (38% on eslint at −10%). **Kept at 0.50, now measured rather than assumed.** Note the error asymmetry that makes this safe: because a dissolved module WITH progress is kept and marked rather than deleted, a *missed* match no longer destroys anything — it costs continuity, not data — which removes the pressure to lower the threshold further and accept false matches. Precision (wrongly merging two genuinely different modules) is **not** measured here and would need a labelled corpus | **closed** |
| — | **`health` is AST traversal, not parsing — profiled.** `collect_inputs` on repo 6: 78.6s under cProfile (30.6s unprofiled), 12.06 ms/file over 6,523 files. The hot spot is `ast_metrics._iter_subtree` at **35.8 million calls, 32.2s cumulative** — the tree is re-walked per metric rather than once with all metrics accumulated (65,653 calls each to `_cyclomatic_and_operands` and `_nesting_depth`, i.e. per function). tree-sitter parsing is only 6.8s and file I/O 14.0s. So the cost is not "parsing is slow"; it is walking the same tree repeatedly. Measurement only, no fix | **open, gates Phase 8** |
| — | **`resync` is git subprocess wall time — profiled.** 29.9s on repo 6, of which `checkout_branch` is 18.2s and `fetch` 11.8s; 23.97s is spent blocked on `_thread.lock.acquire` waiting for subprocess output, and `_winapi.CreateProcess` costs 5.2s for 5 spawns (~1s per process on Windows). Notable: **checkout is larger than the fetch** on an unchanged tree, which is the part worth understanding before optimising anything. Measurement only | **open, gates Phase 8** |
| — | **The 400-node `/graph` cap costs little to raise, measured.** limit=400 → 262kB payload; 800 → 503kB; 1200 → 719kB, with fetch times 1591 / 1019 / 1002 ms (the first is cold). All three still report `truncated=true` on superset's 6,523 files. **Default deliberately unchanged** — the measurement says the payload scales linearly and the server is not the bottleneck, so the question is client render cost, which this did not isolate | **open** |
| — | **Reading list on superset: 6,524 rows, 85,072 DOM elements, 7.6MB of innerHTML.** Time to first 50 rows 8,990 ms; a filter click to counter update 919 ms; scroll to bottom 1,726 ms; keypress round trip 81 ms. So typing stays responsive but every list-wide operation is ~1-2s. The 701,507-char figure recorded earlier is `innerText` (690,814 now); **`innerHTML` is 11× that**. Not virtualised, as instructed | **open** |
| — | **10 of 87 API routes are not referenced from any frontend source.** Same reachability question that found clustering off-path and `jobs/latest` uncalled. The one that matters: **`GET /api/repos/{repo_id}/health/files`** — a real feature endpoint with per-file health and stored explanations, which nothing in the UI requests. Also unreferenced: `POST /api/content/export`, `POST /api/roadmap/generate`, `POST /api/topics/{topic_id}/resources/reorder`, `GET /api/resources/{resource_id}/file`, `PUT /api/repos/{repo_id}/seed-exclude-paths`, `POST .../ingest`, `POST .../resync` (the last two are used internally by the job path), `GET /api/health` (liveness probe, expected), and `GET .../module-preview` (mine, deliberately unwired). Static analysis over template literals — a URL assembled at runtime would be missed, so each is a lead rather than a verdict | **open** |
| — | **Wire probes against mutating verbs must capture and restore, or use a throwaway repo.** Closing the direct-call audit meant exercising `PUT /seed-exclude-paths`, and the probe — written to look read-only, and mentally filed as read-only — overwrote repo 6's `seed_exclude_paths` from `[]`. Flagged rather than quietly reverted, because the general point is the one worth keeping: "this script only checks things" is a claim about intent, not about HTTP verbs. Any probe touching PUT/POST/DELETE either reads the prior value and restores it, or operates on a repo created for the purpose | **open** |
| — | **`evict_lru_if_needed` orphans every child row it should delete.** `registry.py`'s LRU cache eviction calls `db.delete(r)` on the `Repo` row alone. `Repo` declares no ORM relationships to `code_files`/`code_symbols`/`code_imports`/`code_file_ranks`/`code_subsystems`/`code_health_snapshots`/`code_file_health`/`repo_jobs`, and every foreign key is `ON DELETE NO ACTION`, so **nothing cascades** — an eviction leaves the whole analysis behind, pointing at a repo id that no longer exists, invisible to every query that starts from `repos`. Pre-existing and now trivially fixable: `deletion.delete_repo` does exactly this correctly, including the `code_files ↔ code_subsystems` cycle. Eviction should call it instead of hand-rolling a one-line delete. **Same class as the deletion work itself** — a destructive path that predates the correct implementation and was never pointed at it once one existed, which is how two ways to destroy the same data end up in one codebase with only one of them right. Found while running down an unexplained repo disappearance, which it turned out **not** to explain — eviction targets `source_kind == "clone"` only, and would have left orphans there were none of | **open** |
| — | **Every server log captured this session was EMPTY, including the ones meant to be the record for the open crash — and the first diagnosis was WRONG.** Two independent causes, and stopping at the first one would have shipped a fix that changed nothing. **(1) Diagnosed first, real but secondary:** Python block-buffers stdout when redirected to a file, and a dev server is ended by killing it, so the buffer never flushes. Measured — plain: nothing while alive, nothing after kill; `-u` or `line_buffering=True`: present in both. Fixed in `run.py`. **(2) The actual cause:** `alembic/env.py` called `fileConfig(config.config_file_name)`, whose `disable_existing_loggers` defaults to **True**, and `main.py` runs `command.upgrade(..., "head")` at startup — so importing the migration environment switched off every existing logger, `uvicorn.access` and `uvicorn.error` included. The server emitted no access log **and not even its own startup banner** for the entire life of every process. Fixed with `disable_existing_loggers=False`. **The tell, missed on the first pass:** alembic's own log lines were present while uvicorn's were absent — logging was working and specific loggers had been switched off, which is not what buffering looks like. An empty file looks identical either way, which is exactly why the first explanation was accepted too early. Verified after: `GET /api/repos/6/graph?level=file&limit=3&languages=python&languages=tsx&hide_noise=true 200 OK` — the first access line captured this session, carrying the query string and repeated params | **closed** |
| — | **Repo 5 disappeared, and the guarantee that data cannot vanish without an identifiable cause DOES NOT CURRENTLY HOLD.** That is what this entry is about; the missing repo is only the evidence. Present at session start with 43 rows across five tables, present in the listing after the throwaway-repo cleanup, absent now — with **no orphaned rows**, which means a complete removal across all eight tables. The only code that produces that is `deletion.delete_repo`, and no run of it targeted repo 5: the cleanup filtered `name like 'athena-owned-%'` and repo 5 was named `repo`. LRU eviction is ruled out twice (clones only, and it would have left orphans). So **either something invoked deletion in a way not yet identified, or the reasoning about what can produce a complete removal is incomplete** — and there is no evidence available to distinguish those, because no server log survived (see the row above). A 43-row fixture is a cheap place to learn this; the same failure on a repo someone cares about is not. Recorded as unexplained rather than given a plausible story. **Partially addressed:** `delete_repo` now logs before and after every invocation — it previously left no trace at all, which is why this is unexplained rather than diagnosed — and the log-buffering fix means those lines will now survive. A recurrence is diagnosable; this occurrence is not *(**UPDATED 2026-08-20 (reconciliation pass): the occurrence stays unexplained; a RECURRENCE is now traceable.** Verified repo 5 is absent from the `athena.backup-20260814` snapshot, so it predates all work in this session and cannot be attributed to it. The `print`-based logging this entry credits as a partial fix then proved inadequate on its own terms: it fired for exactly one real deletion and went to a stdout nobody captured, leaving the question as unanswerable as before — 'the code path fires' and 'the output can be read back' are different claims. Replaced by a durable append-only table, `repo_deletion_audits` (migration `d9f014c8a26b`): written in the SAME transaction as the deletes, carrying the before-counts per table, with no FK to `repos` so it outlives the row it describes, and never deleted by `delete_repo` itself. Canaried on a disposable repo and READ BACK FROM A SEPARATE PROCESS, which is the claim that failed last time. 4 tests in `TestDeletionAuditIsDurable`. **§17.29-shaped: this occurrence is unrecoverable, not unresolved** — the evidence needed no longer exists.)* | **open — occurrence permanently unexplained, recurrence traceable** |
| — | **`entry_detection` and `setup.py` `entry_points` — CLOSED 2026-08-20, and it was never recorded here in the first place.** Carried across sessions verbally as an open gap ('reads `pyproject.toml`'s `[project.scripts]` but not `setup.py`'). Verified implemented: `_scan_setup_py_console_scripts` at `entry_detection.py:129`, called from `:117`, text-scanned rather than imported because `setup.py` is arbitrary code. Covered by three tests — `test_setup_py_console_scripts` (`:66`), `test_setup_py_multiple_console_scripts` (`:87`), `test_setup_py_without_entry_points_yields_nothing` (`:98`) — using Apache Superset's real `superset=superset.cli.main:superset` declaration. **A checkpoint-0 audit in this session listed it as still-open from memory; that was wrong.** An item that lives only in conversation cannot be checked, which is the whole argument for this table | **closed** |
| — | **The 'ELK 400 → 250 cap' item does not exist in code and never did.** Carried verbally as a recommendation to lower the node cap. Verified: there is ONE value, `GRAPH_NODE_LIMIT_DEFAULT = 400` at `repos.py:310`, with no 250 anywhere in the frontend or backend. Measured 2026-08-20: the cap never binds at `level=directory` (22/24/24 nodes on Athena-OS/eslint/superset, `truncated=False`) and binds hard at `level=file` on both large repos (400 of 1,447 and 400 of 6,523, `truncated=True`). **Closed as a verbal artifact rather than carried further.** If lowering it is wanted, that needs a written proposal with a reason; nothing currently recommends 250 in writing | **closed — no such change exists** |
| — | **`/ranking` payload measured, and it is masked rather than felt.** Previously carried as an undocumented concern. Measured 2026-08-20 against the running backend: **0.104 MB / 0.31s** (Athena-OS, 257 files), **0.601 MB / 0.83s** (eslint, 1,447), **2.825 MB / 2.87s** (apache/superset, 6,523). A CDP walkthrough of the real page showed the landing tab is Overview, which renders from the health endpoints at ~0.9s while `/ranking` streams in parallel — so the 2.87s is **not user-perceived**, but ~4.1 MB is fetched on every repo page load (`/ranking` 2.89 MB + `/health/directories` 922 KB + `/graph` 263 KB) to render a page showing three score tiles. Requests appear twice in dev; that is React StrictMode's double-effect (`main.tsx:15`), not a double-fetch. **Not urgent, now quantified.** The two candidate fixes remain a lean fields-only endpoint or deferring each tab's fetch until it opens | **open — measured, not urgent** |
| — | **Counter alignment across the graph surfaces — FOUR OF SIX ARE ALREADY CORRECT, and the framing that said otherwise is RETRACTED.** ~~Earlier in this session I reported: 'Focus surfaces 400 of 6,523 correctly while Architecture / Dependency Graph / Matrix / Dependency Clusters / Layers all show 6,523 of 6,523 while drawing at most 400 — one consumer honours the cap, four don't, §17.28-shaped.'~~ **That is wrong on both halves** and is left here rather than deleted, per §17.16, because the way it was wrong is the record. Traced 2026-08-20: the counter is SHARED (`RepoDetail.tsx:1115`), sourced per view by `shownFileCount` (`:776-787`). Architecture and Matrix read `dirGraph.files_matched` (`:781`), Dependency Graph reads `graph.files_matched` (`:784`), Dependency Clusters reads `visible.length` (`:778`) — all post-filter, all correct, and `RepoDetail.tsx:764-775` documents the very bug ('it read *Showing 400 of 6,523* and stayed at 400 when a filter was applied') already fixed. **'6,523 of 6,523' beside '22 SHOWN' was never an inconsistency**: one counts files matching the filter, the other counts directory boxes drawn. **The two real defects are:** (1) **Layers** — counter correct, but the view renders from `visibleGraphNodes` (the 400-capped array, `:1441`) with NO truncation notice, so a user sees <=400 files under a counter saying 6,523; (2) **Focus** — `shownFileCount` falls through to `visibleGraphNodes.length` (`:786`), reporting the capped array, which is the residue of the bug fixed elsewhere. **How the wrong framing was produced (§17.30, fourth instance):** a CDP probe matched `[\d,]+\s+of\s+[\d,]+` and took the FIRST match per page; on Dependency Graph that is the filter counter, while the truncation notice 'Graph shows the top 400 of 6,523 files by rank' (`:1125`) sits further down the same DOM and was never examined. First-match-is-not-a-cap-notice was read as no-cap-notice-exists | **open — 2 surfaces, not 5** |
| — | **Six patterns found this session are written up nowhere and are pending §17.31+ at checkpoint 7.** Recorded here so they are not lost the way the earlier ones were: (1) **SQLite rowid reuse** invalidating id-keyed test assertions — bit twice, in the re-cluster fixture and the audit-survival test, fixed in tests only; (2) **`hash()` is per-process salted** in Python, so it cannot seed anything that must be reproducible across runs — caught before shipping in `_stable_offset`, recorded only as a code comment; (3) **distractor repetition and the odd-one-out** — two card-quality defects invisible to every test, found by reading generated output; (4) **an answer compared against itself** — the `filter_subject` bug, where a card's code-link was passed to the quality filter as if it were the question's subject. Items 1 and 4 are the likeliest to recur. **The browser-instrument pattern (§17.30 preview) is checkpoint 7's PRIMARY write-up**, and the `:683`/`:684` record-drift pattern is demoted to a closure line | **open — pending write-up** |
| — | **Endpoint tests call route functions directly, which bypasses FastAPI entirely — audited.** The convention is fast and it proves logic while saying nothing about whether a client can reach the endpoint. Audited all route parameters whose direct-call value differs from the wire value: 2 marker defaults, 8 coerced scalars, 1 body list. **Only the 2 markers ever genuinely diverged** (`Query(None)` is truthy on a direct call, so every unfiltered request took the filtering branch and died on `in` against a non-iterable) and both are fixed. The other 9 were probed over HTTP and behave as the direct-call tests assume — including `hide_noise` accepting `true`/`1`/`false`/`0`, and `floor=abc` returning FastAPI's own 422 **before** the handler, a path no direct-call test can reach. Same shape as the reachability audit: tests verifying a capability nobody can reach | **closed** |
| — | **A change that alters nothing but reads as a fix.** New category, **two instances now — this is a §17 entry the next time the batch runs.** Second instance: `run.py`'s access-logging comment, which correctly stated that logging was on and must not be suppressed, while every log it referred to was empty because stdout was buffered and the process was killed. The configuration was right and the outcome was nothing, which is the same failure as a redundant change presented as a fix — the claim reads as verified and was never checked end to end. First instance below | watching |
| — | *(first instance)* **A change that alters nothing but reads as a fix.** Recorded in case it recurs. Query-string access logging was "added" to `run.py` by overriding uvicorn's access formatter; checking showed the override produced a **byte-identical** format string, because uvicorn already logs the query via `get_path_with_query_string`. It would have shipped, appeared in a commit message as a fix, and been believed — the requirement was real and the change was redundant. Distinct from cascade suppression (a correct value discarded downstream) and from check-shaped-wrong (the instrument misreports): here the code was already correct and the *fix* was the redundant part. Closest relative is §17's reachability findings, inverted. A second instance makes it a §17 entry | watching |
| — | ~~**`hideNoise` on the directory graph — deferred with a reason, not an oversight.**~~ **DONE, and in the same batch precisely because of that reason.** Landing it separately would have invited a client-side version, which reintroduces the defect the whole batch exists to avoid. Applied server-side before aggregation, using `node_priors.NOISE_CATEGORIES` — a constant that must agree with the frontend's own `NOISE_CATEGORIES`, since the graph filters those files server-side while the reading list filters the same files client-side; a divergence would make the two views disagree about which files exist while both looked correct. Cross-language so it cannot be shared as code; the coupling is documented at both sites | **closed** |
| — | *(superseded)* **`hideNoise` on the directory graph — deferred with a reason, not an oversight.** Excluded from the filter-vocabulary work above. Applied client-side it has the same defect as the rejected client-side fix: a directory survives with some files hidden while still reporting aggregates over all of them. Applied server-side before aggregation it is correct — but then it belongs in the same batch as `segments`/`languages`/`query` rather than as an arguable extra, and that batch has not been scoped to include a `prior_category` filter. `hideZeroFanIn` stays out permanently: fan-in is a file-level property whose aggregation to a directory has three defensible answers (sum, max, distinct external importers) and picking one silently is worse than not offering the filter. `subsystemId` stays out — `DirNodeT` cannot carry subsystem membership, already recorded in `filters.ts:13-22` | **open** |
| — | **Flat text search against wrapped content — still 3 occurrences.** The §17.15–§17.19 append verified itself through `re.sub(r'\s+', ' ', text)` on both haystack and needle, across 12 probes on a file that wraps at ~80 columns, with no false result. First time the recorded fix was applied rather than re-derived — which is the whole point of the note below, and the reason the count did not become 4 | watching |
| — | **Flat text search against wrapped content — 3 occurrences; a fourth makes it a §17 entry.** The `open(` encoding audit returned 100% false positives because `encoding="utf-8"` sat on a continuation line; a doc-verification probe returned a false negative because `the fix was needed / for the reason given` spanned a wrap. Same root cause, opposite directions. Third: verifying §17.0b's own edit, probe `what population did this number get measured over` spanned a wrap. Fix is mechanical — normalise whitespace before searching, or search a short fragment that cannot wrap. **Note the third occurrence happened after the fix was written down here and not applied** — which is the point: a recorded fix that nobody runs is not a fix. Applying `re.sub(r'\s+', ' ', text)` before the probe resolved it immediately | watching |

---

## K. The first large-repo test — apache/superset, 2026-08-12

6,516 files, 22,119 commits. The first mature codebase to go through the
analyser. It reversed two published findings, exposed four nested defects in
one code path, and produced the first result the model could not have obtained
from small repos.

### K1 — Cascade suppression, named as a recurring defect shape
*2026-08-12 · active*

**Decision.** Give the pattern a name, document every instance in
`app/services/codebase/__init__.py`, and add the check to review discipline.

**The shape.** A value is computed correctly and then discarded downstream
because a *coarser* upstream check failed. The upstream failure is real; the
discard is not required by it. Because the discard is quiet, the surface above
reports "unavailable" rather than "partly available" — which a reader
interprets as "nothing here" instead of "some of this is missing".

**Why name it.** Eight instances across eight unrelated modules is a property
of the codebase, not a coincidence:

1. `_migrate_entry_priors` — a `continue` meant E4's own migration never
   corrected rows already migrated under the older heuristic.
2. G1 scorer scoping — rank rows correct at one level, discarded by a query at
   another. Motivated the entire Phase G rewrite.
3. History timeout — an uncaught `TimeoutExpired` walked past the function's own
   `return None` contract, costing the repo its whole ranking.
4. `--numstat` — computed line counts the next line discarded, at the cost of
   thousands of lazy blob fetches.
5. Architecture axis gate — the whole axis withheld for a missing 3.0-weight
   marker while the 4.0-weight marker had complete data.
6. UTF-8 decode — a `UnicodeDecodeError` in a subprocess reader thread became
   `stdout=None`, which the caller trusted.
7. **Non-ASCII paths** (K8, open) — `core.quotepath` escapes them, so they match
   no `CodeFile.path` and the file's history is dropped with no error.
8. **The calibration blocker** (D5) — §9 recorded "0 conventional `fix:`
   commits" and concluded calibration was impossible. Ten of twenty-five commits
   describe a fix in prose. The blocker was never "no defect data exists"; it
   was "our extractor recognises one format." A coarse detector's miss became a
   claim about the world, and it parked an entire workstream for weeks.

Instance 8 is worth dwelling on, because it is the most expensive so far and
the least like a bug. Nothing crashed, no value was silently dropped at a
boundary — a narrow input format produced a negative result, and that negative
result was written into a contract as a fact about the repository. It is the
same shape as the resolution-rate collapse counting stdlib imports as failures:
a detector's blind spot promoted to a finding.

**Impact.** The check is one question: *is this discard necessary, or merely
convenient?* In all six cases it was merely convenient. Every guard was
defensible in isolation — each was written to avoid reporting a number without
its inputs, the same instinct behind exclude-don't-zero. The failure is in
scope, not intent: a guard sized to the **coarsest** input rather than the
**required** one. That is why it survives review. It looks like caution.

### K2 — Small-repo calibration is provisional until a large repo has run
*2026-08-12 · active · **supersedes the reasoning behind G2***

**Decision.** Any claim of the form "this marker does not discriminate" now
requires a repository above roughly 2,000 files with several years of history
before it may be recorded as a finding rather than an observation.

**Why.** Two independent axes reversed on first contact with a real corpus, both
in the same direction. Small repos are biased in ways that specifically
suppress structural signals — fewer modules means fewer chances to form a
cycle, shorter history means degenerate churn, fewer contributors means
ownership carries no information. Every one is a **sampling** property, not a
property of software.

**Impact.** The measurements in §10.1 and §10.3 were never wrong; the inference
was. Reading "did not occur in this corpus" as "does not occur" led to calling
an axis decorative and deferring the work to fix it. See §17.0.

### K3 — `cycle_participation` reversed: 0% → 12.7%
*2026-08-12 · **supersedes G2's premise***

**The finding.** 828 of 6,516 files sit in import cycles; the largest SCC spans
**604 files**. Against zero across 599 files in three small repos.

**Phrasing adopted:** the earlier finding held for the corpus tested and does
not generalise. Correct about its sample, wrong about the world. A reversal,
not a refinement.

**Impact.** Architecture Health produced a distribution for the first time —
mean 9.499, **p10 = 6.00**. M1 is no longer "make the axis informative or drop
it"; the axis is informative and always was, on codebases large enough to
contain the thing it measures.

### K4 — `bidirectional_coupling_hub`: rare, not absent
*2026-08-12 · correction*

Called "looking for a shape that does not exist in practice" on the evidence
that eslint's most-imported file had `min(fan_in, fan_out) = 4`. On superset it
fires on **2.3%** of files (152 of 6,516). Same correction shape as K3, smaller
magnitude. "Does not exist in practice" was too strong and is withdrawn.

### K5 — `--name-only --no-renames` for history collection
*2026-08-12 · active*

**Why.** Rename detection compares file **contents**. On a `--filter=blob:none`
clone the blobs are not local, so every rename check became a lazy fetch from
the remote — thousands of network round trips disguised as CPU cost. Our own
clone optimisation was breaking our own history pass; the two decisions were
made in different modules and never met.

`git log --numstat` ~427 s (extrapolated) → `--name-only --no-renames`
**8.45 s**. The add/delete columns were parsed and discarded on the next line.

**Cost, accepted deliberately.** A renamed file carries only commits made under
its current name. Measured: history covers **24,835 paths against 6,516 files
in the tree** — ~18,000 paths that no longer exist. On a repo mid-refactor this
underweights exactly the files most recently reorganised. Accepted because the
alternative is that large repos cannot be ranked at all. Verified not to lose
data here: all 6,516 current files matched a history entry.

### K6 — A history timeout degrades; it does not fail the run
*2026-08-12 · active*

**Why this is the load-bearing fix, not K5.** `--no-renames` makes the *known*
large case fast. This makes every *other* large case survivable — a slow disk,
a bad shard, a larger history. The function's contract already said "None means
no history"; an uncaught exception walked straight past the graceful path that
existed.

**Impact.** Timeout raised to 600 s and made non-fatal. Ranking now produces
fan-in, fan-out and a reading list even when history is unavailable — none of
which depend on git history at all.

### K7 — Git output is decoded as UTF-8, not as the system codepage
*2026-08-12 · active · **the most important finding of the four***

**Why it matters more than K5.** Four defects were nested:

```
180-second timeout → UnicodeDecodeError → None stdout → AttributeError
```

The obvious response to a timeout is to raise the budget. Doing so would have
produced a **fast run returning no history, silently, via None** rather than
loudly via timeout — supporting the conclusion that superset has no usable git
history. The bug would have become permanent and invisible. **Fixing the
symptom would have destroyed the evidence.** That is the argument for root
causes over symptoms, with a concrete instance behind it.

**The defect.** `text=True` decodes with the system codepage — cp1252 here —
and git emits UTF-8 author names. Windows-specific: it would **not** reproduce
on Linux, where the default is UTF-8. Any test pinning it must force a
non-UTF-8 decode or feed bytes directly, or it passes on CI for the wrong
reason.

**`errors="replace"`, not strict.** One unmappable byte must not cost a
repository its entire history, and unlike `ignore` it leaves a visible marker.
Checked on superset: **0 of 24,835 paths contain U+FFFD** — because git escapes
non-ASCII paths (see K8), so replacement only ever lands in author names, where
a mangled name is strictly better than a dead pipeline.

### K8 — Known and unfixed: non-ASCII paths lose their history silently
*2026-08-12 · **open***

`core.quotepath` defaults to true, so git emits a non-ASCII path escaped and
quoted (`"src/\303\251t\303\251.py"`). That matches no `CodeFile.path`, so the
file's history is dropped with no error and no marker — cascade suppression in
miniature, instance seven.

Not observed on superset (zero non-ASCII paths, which is why all 6,516 matched).
Latent, not theoretical. The likely fix — `-c core.quotepath=false` — trades
escaping for raw UTF-8 and moves the burden to the decoder, where
`errors="replace"` could put U+FFFD in a path and fail the same way. Needs its
own pass.

### K9 — The Architecture gate requires the dominant marker, not every marker
*2026-08-12 · active · **narrows C4***

**Decision.** Two changes. The axis is N/A only when **both** cycle and coupling
inputs are missing. And `_assemble` withholds a score only when the axis's
**dominant** marker is missing (`DOMINANT_MARKERS`), rather than whenever any
input is absent.

**Why the asymmetry is principled.** C4's rationale was that with no cycle data
the axis reads 9.98, carried by a marker firing on ~1% of files — a caveat
beside a prominent 9.98 still anchors the reader on a conclusion the evidence
does not support. The inverse is **not** symmetric: with cycle data present and
coupling missing, the number derives from the heaviest marker and is a
conservative **floor** — adding the missing marker could only lower it.

**Impact.** Superset had complete cycle data for all 6,516 files and reported
Architecture Health as N/A because ranking had not run. Every one of those 828
cycle findings was computed and thrown away. Scores now report with
`inputs_complete = false` and the gap named, rather than not reporting at all.

### K10 — What superset validates
*2026-08-12*

**Superset ~95, Athena-OS 97.** The first time the large mature codebase scored
**below** the small young one, with the architecture axis doing it.

Every prior comparison had the model rewarding youth: a repo with too little
history for churn to resolve and too few modules to form a cycle scored well by
having nothing measurable held against it. No amount of further small-repo
testing could have produced this result.

Also worth recording: **seven predictions, seven correct**, including
Architecture mean at 95 against a 94–96 band. That was arithmetic, not
intuition — the SCC distribution was already persisted, so the marker's
severity ramp could be applied to it in advance. See §17.7 for the derivation.
When a marker's inputs are already stored, its distribution is computable
before the run, and prediction becomes calibration rather than a guess.

### K11 — D5 is unblocked but severely under-sampled, and the detector was measured not assumed
*2026-08-12 · finding*

**The correction to §9.** It recorded "0 conventional `fix:` commits" and
concluded calibration was impossible. That measured the wrong thing — the
blocker was never "no defect data exists", it was "our detector recognises one
format" (cascade suppression instance 8, K1).

**But the count was measured before being trusted.** All 25 commits were
hand-classified. A commit counts as a defect fix when its primary purpose was
correcting something that had already shipped.

| Detector | Matches | True fixes | Precision | Recall |
|---|---:|---:|---:|---:|
| Conventional `fix:` prefix | 2 | 2 | **100%** | **50%** |
| Subject-line keyword | 3 | 3 | **100%** | **75%** |
| Full-message keyword | 10 | 4 | **40%** | **100%** |

Ground truth: **4 defect-fix commits out of 25**.

**The full-message detector is 60% noise**, and predictably so. Commit messages
in this repo are long and narrative, so "fix" appears in prose describing what a
*feature* does — `Add code-health UI…`, `Add file-level SCCs…` and four others
all match on body text while being pure feature work. Using the raw count of 10
would have taken D5 from "no data, blocked" to "bad data, unblocked", which is
strictly worse.

**No keyword detector reaches usable recall here.** The highest-precision one
misses `003e2e6` — the most substantive fix in the entire history, correcting
two live production defects — because its subject reads *"Stop serving a stale
health score as current; stop ingest wiping a repo"*. No keyword, genuine fix.
That is not a tuning problem. It is a property of how commit messages are
written in this project, and it does not improve with a longer keyword list.

**File-level base rate:** the 4 fix commits touch **32 of 281 tracked files =
11.4%**. Not comparable to repowise's 7%, which was scoped to the last six
months; this repo's entire history is shorter than that window.

### K12 — D5's actual status: unblocked, not calibratable
*2026-08-12 · **deferred, with the reason now quantified***

Two different states, and only the second is true:

| §9 precondition | Required | Actual | |
|---|---|---:|---|
| Defect-labelled commits | ≥ 50 | **4** | 8% of the bar |
| Labelled files | ≥ 200 | **32** | 16% of the bar |
| Time-ordered holdout | fit before T, evaluate after T | impossible | ~3 months of history total |
| Beat NLOC-only **and** churn-only | required | untestable at n=4 | |

**Unblocked** — the data is not zero, and the earlier claim that it was is
withdrawn. **Not calibratable** — at n=4 any lift figure is noise, and a
time-ordered holdout needs history this repo does not have.

Stating both plainly because they are easy to conflate, and the optimistic
reading ("unblocked!") would licence exactly the unvalidated defect-risk number
B3 forbids. What changes is the *reason* D5 is deferred: not "no defect data
exists" but "far too little, and no way to hold out".

**What would move it:** an external corpus with real fix history — or, going
forward, conventional-commit prefixes on this repo, which would raise the
high-precision detector's recall for free.

---

# START HERE — session state as of 2026-08-20

**If you have lost the context window, read this section first.** It assumes you
have never seen this project. Everything below was verified against the code,
migrations, tests or database on 2026-08-20 unless labelled otherwise.

## What this is

A codebase-analysis agent inside ATHENA OS. It ingests a git repository, builds
its import graph, and produces a ranked reading list, an architecture map, a
dependency matrix, per-file focus views, subsystem clustering, structural health
metrics, and — since Phase 5 — study modules, roadmaps and comprehension cards
persisted into the content library. **Non-negotiable #5: zero LLM calls in the
codebase agent, ever.** Everything is deterministic local computation.

## Phase state

| phase | status | evidence |
|---|---|---|
| A–D — ingest, parse, import resolution, ranking | **closed clean** | migrations `c0a62258a8f6`…`2e4f4b743bea`; `test_ingest.py` (72), `test_ranking.py` (90), `test_resolve_imports.py` (18) |
| E — entry detection | **closed clean** | `entry_detection.py`; `test_entry_detection.py` (45), incl. `setup.py` `console_scripts` |
| F–H — architecture map, matrix, layers, focus | **partial** | UI ships and renders; `:682`'s frontend half is open — no caller sends the filter params |
| I (I1–I6) — subsystem clustering | **closed clean** | `8dc08ed8f03e`, `425611792c27`, `49b14fd05c27`, `d5e1a7c93f20`, `e6f2b8d41a37`; `test_subsystems.py` (42) |
| J1 / K1 — health, overview, description | **closed with documented gap** | thresholds not calibrated across ecosystems (§17.0); health 30.6s gates Phase 8 |
| 4 — module/roadmap persistence | **closed clean** | `f8a3c21d9b45`, `a1c9e37f4b82`; live: 145 modules, 3 roadmaps |
| 5 — comprehension cards | **closed with one permanent gap** | `c4b7e9d2f501`; live: 661 cards; gap is §17.29 |
| 6, 7, 8 | **not started** | no files, no migrations, no tests |

## Suite state

- **Backend: 1,114 tests collected.** Last full run 1,109 passed / 1 skipped /
  0 failed (2026-08-19 23:27). Since then checkpoint 3 added 4 tests, verified
  in isolation (15 passed in `TestGraphFilterVocabulary`; 110 passed across the
  legacy `/graph` callers). **A full run has not been done since those 4 landed.**
- **Frontend: 231 vitest tests across 18 files, all passing**, plus **2
  Playwright tests** (`e2e/`). `npx tsc --noEmit` clean.
- 37 migrations, chain intact, head `d9f014c8a26b`.
- Dev servers are started by hand: backend `:8000` (uvicorn `--reload`),
  frontend `:5173` (vite). Vite binds **IPv6 only** — `localhost:5173` works,
  `127.0.0.1:5173` is refused.

## The `:682` work — 7 checkpoints, 4 done

Goal: make the file-filter bar actually filter the Architecture, Matrix and
Dependency Graph views. Today those views render the filter controls and ignore
them.

| # | checkpoint | status |
|---|---|---|
| 1 | cancellation canary | **done** — `elkLayoutRun.ts` extracted, `elkLayoutRun.test.ts` (8), canaried |
| 2 | Playwright + Architecture render verification | **done** — Architecture renders correctly; the earlier "it doesn't" was an instrument failure |
| 2.5 | focus establishment + wiring test | **done** — select a file FIRST, then switch tabs; wiring pinned by a source-level tripwire |
| 2.6 | suspected sparse-render defect | **done — no defect existed**, retracted |
| 3 | backend repeated-value filter params | **done — already shipped 2026-08-14**; 4 combination tests added |
| 4 | counter alignment | **NOT STARTED — re-verify before scoping**, it may be partly built |
| 5 | frontend sends the params | not started; **must include debouncing and/or a re-layout indicator** |
| 6 | verify under filter | not started; must exercise superset specifically |
| 7 | record: close `:682`, write §17.30 | not started |

## Open items

| item | status |
|---|---|
| **repo 5 disappearance** | occurrence **permanently unexplained** (§17.29-shaped); recurrence now traceable via `repo_deletion_audits` |
| **size-aware topic budget** | **deferred by decision** — needs a real user hitting a too-coarse module, not a guessed number |
| **health 30.6s / resync 22.0s** | **gates Phase 8**, no work started, measurement only |
| **`verify=False` SSL** | real, but in `app/core/llm.py` and `services/content_hub.py` — **outside the codebase agent** |
| **six unwritten patterns** | pending §17.31+ at checkpoint 7 |
| **`/ranking` payload** | measured (2.825 MB on superset), masked by parallel fetches, not urgent |
| **`.index` crash** | never reproduced; instrumented; premises in its entry now corrected |

## The methodology contract

`docs/code-health-contract.md` holds **35 §17 subsections** — a running record of
instrument failures, each with the mechanism and the rule it produced. It is the
most useful thing to read before changing anything. The newest is **§17.30
(preview)**: browser-automation instruments reporting the absence of what they
cannot perceive, three instances in one session, all producing confident wrong
conclusions about product code that was fine.

## What to do next

1. **Re-verify checkpoint 4 against the code before scoping it.** Checkpoint 3
   was scoped as implementation work and turned out to be already built; the
   same is plausible here. **ANSWERED 2026-08-20 — see the checkpoint 4 row in
   the table above. Four of six surfaces are already correct**; the real defects
   are Layers (counter right, view capped, no truncation notice) and Focus
   (counter falls through to the capped array). "Showing 6,523 of 6,523 files"
   beside "22 SHOWN" was never an inconsistency: the first counts FILES matching
   the filter, the second counts DIRECTORY BOXES drawn. Both were right.
2. Then checkpoints 5, 6, 7 in order.
3. **Run a full backend suite** — the last one predates checkpoint 3's 4 tests.

## The habit that matters most here

Check the claim against the code before acting on it. This session found the
record wrong five times — a label that never changed after the work shipped, an
entry describing code that had been deleted, a fix recorded as open, a gap
recorded as open that was closed, and a backend feature recorded as unbuilt that
had shipped a day later. One of those wrong claims was produced by an audit
inside this same session. **A reported defect is not evidence a defect exists,
and a recorded gap is not evidence a gap exists.**
