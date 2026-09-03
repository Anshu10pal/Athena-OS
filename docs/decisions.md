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
| — | **Architecture and Matrix — harder than recorded. Client-side post-aggregation filtering is NOT an available option.** The earlier entry offered it as one of two choices; it does not exist. `DirNodeT` carries no member list, so a surviving node would report aggregates computed over **all** its files while the filter selects a subset — "50 files" beside a filter matching 3, and edge weights unchanged. That is confidently wrong output, which is strictly worse than controls that do nothing, and it is the same defect as the client-side fix rejected for the filter bar itself. Re-aggregating client-side instead means a second copy of `aggregate_to_directories` in TypeScript — a drifting second implementation of a rule this project keeps server-side. **So the only correct fix is extending the endpoint's filter vocabulary**, and the machinery is already right: `GET /graph?level=directory` filters files BEFORE aggregating and caps directories after, reasoned in its own docstring. It accepts `language`, `path_prefix`, `min_score`; **no frontend caller sends any of them** (they appear only in `test_ranking.py:149` and `test_repos_api.py:219-221`). Not a missing capability — an unconnected one. Scope agreed: honour `segments[]`, `languages[]`, `query`; extend the endpoint to accept REPEATED values rather than have the client collapse a multi-select to one, which would silently under-filter *(**Scope addition, 2026-08-20, from checkpoint 2.6's surviving measurement.** After a rapid wide→narrow scope change the Dependency Graph takes **10.4–11.5s** to finish rendering on apache/superset, against **958ms** for an uninterrupted layout. Filter changes drive the SAME re-layout path (`DependencyGraph.tsx`'s effect on `[cy, elements, showFullGraph, focusIds]`), so a filter toggle on the largest repo will sit for ~10s with no signal — which gets reported as 'the filter is broken', not 'the filter is slow'. **This is :682 scope, not adjacent to it:** the frontend-send checkpoint needs debouncing on the filter inputs and/or a visible re-layout indicator, and the verify checkpoint must exercise both under filter toggling on superset specifically.)* *(**RE-SCOPED 2026-08-20 (reconciliation pass). The BACKEND HALF OF THIS ENTRY WAS ALREADY SHIPPED WHEN IT WAS WRITTEN — one day later.** `segments`/`languages` as repeated `Query(None)` params, plus `query` and `hide_noise`, landed in `9fb9bce3` on 2026-08-14 (`repos.py:363-372`, marked Phase L2) carrying the same 'do not collapse a multi-select' reasoning this entry argues for. Union-within-param / intersect-across-param semantics and post-filter counts are pinned by 15 tests in `TestGraphFilterVocabulary`, canaried 2026-08-20. **What actually remains of :682 is the FRONTEND half: no caller sends any of these params** — still true, verified this pass. A checkpoint-0 audit in this session read the entry and repeated its claim that :682 was 'genuinely unbuilt'; that audit checked the callers and not the endpoint, and was wrong.)* *(**CLOSED 2026-08-20.** Both halves are done and the entry was stale on both counts. BACKEND shipped in `9fb9bce` (2026-08-14), a day after this entry was written. FRONTEND also shipped in `9fb9bce`: `graphFilterParams` is wired at `RepoDetail.tsx:481` (level=file) and `:492` (level=directory), sending REPEATED values, with a 300ms debounce gated by `graphFiltersChanged` (`:748-756`). **My own checkpoint-0 audit claimed 'no frontend caller sends any of them' — that was wrong; I grepped `api.ts` instead of the call sites.** What genuinely remained, and was done this window: the Layers truncation notice (`c3f8018`), the Focus counter falling through to the capped array (`213ee95`), and a re-layout indicator for the measured 10-11.5s window (`4e1f42b`). **Verified end to end on apache/superset** (`b507189`): Architecture and Matrix both go 6,523 -> 2,547 files under a python filter and back, with DetailPanel — fed by both surfaces — still rendering. 2,547 is corroborated independently as superset's python count.)* | **closed** |
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
| — | **Six patterns found this session are written up nowhere and are pending §17.31+ at checkpoint 7.** Recorded here so they are not lost the way the earlier ones were: (1) **SQLite rowid reuse** invalidating id-keyed test assertions — bit twice, in the re-cluster fixture and the audit-survival test, fixed in tests only; (2) **`hash()` is per-process salted** in Python, so it cannot seed anything that must be reproducible across runs — caught before shipping in `_stable_offset`, recorded only as a code comment; (3) **distractor repetition and the odd-one-out** — two card-quality defects invisible to every test, found by reading generated output; (4) **an answer compared against itself** — the `filter_subject` bug, where a card's code-link was passed to the quality filter as if it were the question's subject. Items 1 and 4 are the likeliest to recur. **The browser-instrument pattern (§17.30 preview) is checkpoint 7's PRIMARY write-up**, and the `:683`/`:684` record-drift pattern is demoted to a closure line *(**WRITTEN UP 2026-08-20.** The four collapsed into two subsections rather than four, because two pairs share a mechanism: **§17.31** (SQLite rowid reuse + `hash()` per-process salting = an identifier that looks stable and is not) and **§17.32** (distractor repetition, odd-one-out, and answer-compared-against-itself = a question answerable without being answered). The browser-instrument pattern became **§17.30**, promoted from preview with a fifth instance: `str.replace` returning success without replacing anything.)* | **closed** |
| — | **Endpoint tests call route functions directly, which bypasses FastAPI entirely — audited.** The convention is fast and it proves logic while saying nothing about whether a client can reach the endpoint. Audited all route parameters whose direct-call value differs from the wire value: 2 marker defaults, 8 coerced scalars, 1 body list. **Only the 2 markers ever genuinely diverged** (`Query(None)` is truthy on a direct call, so every unfiltered request took the filtering branch and died on `in` against a non-iterable) and both are fixed. The other 9 were probed over HTTP and behave as the direct-call tests assume — including `hide_noise` accepting `true`/`1`/`false`/`0`, and `floor=abc` returning FastAPI's own 422 **before** the handler, a path no direct-call test can reach. Same shape as the reachability audit: tests verifying a capability nobody can reach | **closed** |
| — | **Phase 5's cards have NO USER SURFACE, and the record said Phase 5 was closed.** Found 2026-08-20 by a user asking where the cards were. `grep` over `frontend/src/` returns zero references to cards; the 661 rows are reachable only through `GET/POST /api/repos/{id}/cards` (`repos.py:1299`, `:1339`). **No UI was ever scoped, discussed or deferred** — unlike the topic budget or the SSL debt, there is no decision anywhere; it simply was not built and nobody said so. Phase 5's checkpoints were all backend (generation, quality filter, seam, grading, persistence) and none covered a surface. **The reporting failure is the sharper half:** the phase table read 'closed with one permanent gap' naming §17.29, which implied ONE gap when the larger one was that nothing could reach the feature. Every citation in that row was true and the aggregate claim was misleading — §17.30's shape with the record as the instrument. **A sweep for the same class found one other:** `POST /{id}/roadmap` also has no UI caller, but Phase 4's OUTPUT is visible (all 3 codebase roadmaps appear in `GET /api/roadmaps` beside seed tiles, with modules, topics and progress working), so only creation is unwired. `module-preview` and `roadmap-preview` are deliberately unwired and recorded as such; `ingest`/`resync` are used by the job path | **open — card UI unbuilt** |
| — | **PHASE 6 REGISTERED — Codebase Atlas Export: the graph as a queryable knowledge source.** **Goal:** let an external agent (Claude Code) answer structural questions by querying the existing codebase graph instead of reading source files, with a MEASURED token reduction on apache/superset as the headline deliverable. **Additive and reversible:** it reuses the codebase agent's existing tree-sitter parse, ranking and clustering output, modifies none of it, and ships as a separate tool — nothing already built changes shape. **Why it is differentiated rather than a clone:** the mechanism is comparable to Graphify (a 108k-star YC tool), but this has (a) a RANKING layer Graphify lacks, so a subgraph can be ordered by what matters rather than returned whole, (b) fully-local, zero-LLM operation, which is what makes it usable on private client code behind a corporate proxy, and (c) the §17 provenance discipline — every number carries its denominator and its instrument. **Checkpoints:** 0 = feasibility measurement (GATE), 1 = export artifact, 2 = query primitives, 3 = enforcement hook + measurement harness, 4 = MCP server (deliberately LAST, because it is the part that is worthless if 0–3 are not real). **CHECKPOINT 0 IS A GATE, STATED BEFORE MEASURING:** the phase proceeds only if the measured token delta on superset justifies the build. If it does not, the phase is REFRAMED — structural navigation rather than token savings — before any durable code is written. A weak number is not to be stretched into a showcase; that is what §17.0b exists to prevent *(**CHECKPOINT 0 RUN 2026-08-21 — GATE PASSED, HEADLINE CORRECTED.** **[MEASURED AT `e2bb33b1` — superset was re-ingested to `a05a0999` on 2026-08-21 (6,523→6,584 files, 60,873→61,559 imports), so every ABSOLUTE count below is snapshot-specific and now stale. Not re-measured here: checkpoint 3 supplies current figures at `a05a0999`. §17.16 — marked, not silently corrected.]** **The 34.3x is a RATIO and is roughly snapshot-stable** — grep and the graph both grew with the repo — but the per-question absolute token counts behind it are not. Median **34.3x** against a GREP baseline (n=5 questions grep can also answer), with **2 question classes grep cannot answer at all** — subsystem membership and import cycles, both computed graph properties invisible to text search. Threshold was fixed before measuring (median >=5x AND >=2 grep-impossible) and both halves pass. **A first pass measured against 'read every candidate file' and produced ratios up to 52,000x; that was a STRAWMAN and was discarded** — a competent agent greps, so grep is the real competitor. Spread on the honest baseline is 3.1x to 3,113x: local lookups ('what imports X') save only **3-5x**, and the value concentrates in whole-graph aggregates and the grep-impossible classes (§17.5c — the mean would have hidden this). **THE HEADLINE IS NOT 'we cut tokens': whole-graph-as-context is a token LOSS on superset.** Its compact serialisation is **962,330 tokens** against **560,768** for reading the top 100 files by rank — ~1.7x WORSE, and 4.8x a 200k window. The saving is real only for SCOPED QUERIES. Recorded here so the pitch cannot drift back into the strawman.)* | **checkpoint 0 PASSED — 1a next** |
| — | **A change that alters nothing but reads as a fix.** New category, **two instances now — this is a §17 entry the next time the batch runs.** Second instance: `run.py`'s access-logging comment, which correctly stated that logging was on and must not be suppressed, while every log it referred to was empty because stdout was buffered and the process was killed. The configuration was right and the outcome was nothing, which is the same failure as a redundant change presented as a fix — the claim reads as verified and was never checked end to end. First instance below | watching |
| — | **Phase 6 design decided by measurement: QUERIED-IN-PIECES, with whole-graph as a small-repo-only option.** Compact whole-graph serialisation measured 2026-08-21. **[MEASURED AT `e2bb33b1` — superset was re-ingested to `a05a0999` on 2026-08-21 (6,523→6,584 files, 60,873→61,559 imports), so every ABSOLUTE count below is snapshot-specific and now stale. Not re-measured here: checkpoint 3 supplies current figures at `a05a0999`. §17.16 — marked, not silently corrected.]** **The 'tokens track EDGES not files' scaling law and the ~1,500-2,000-file crossover are RATIOS and hold across snapshots; the token and file counts are absolutes and do not.** **Athena-OS 31,315 tok (280 files) / eslint 73,953 tok (1,447) / superset 962,330 tok (6,523)**; full-fidelity variants are 253k / 483k / 5,011,882. Tokens track EDGES, not files — eslint has 5x Athena-OS's files but 2.4x its tokens, while superset has 4.5x eslint's files and **13x** its tokens because edges grow 26x (2,304 -> 60,873). **So the crossover is roughly 1,500-2,000 files**, and the design is not a choice but a size-dependent switch: queried-in-pieces unconditionally for large repos, optional whole-graph mode below the threshold where it genuinely fits (eslint's entire graph costs less than superset's TOP-10 file read). **The artifact must state which mode produced it** — an export that is whole in one repo and scoped in another, without saying so, is a denominator that does not travel (§17.5c) | **decided** |
| — | **`ranking._build_graph` is pre-existing §17.28 coupling debt, and Phase 6 must not inherit it.** It is private by name, topology-only (an `nx.DiGraph` of integer file ids — no paths, ranks, clusters, symbols or provenance), and it DROPS unresolved edges (`to_file_id.isnot(None)`), so it cannot express 'this import exists but did not resolve' — real provenance an agent wants. Yet it is imported across module boundaries by `api/repos.py:32` and `graph_structure.py:33`, and called from `card_persist.py:150`, `roadmap_persist.py:140` and `ranking.py:709` — **five call sites for a name whose underscore says do not**. Every other whole-graph consumer reaches DIRECTLY into tables; the checkpoint-0 fact-finding had to write raw SQL across five tables because nothing else existed to call. **Checkpoint 1a introduces a proper typed boundary with the export as its only consumer. Migrating the five existing call sites onto it is DEFERRED to its own checkpoint** — doing it here would put a refactor of five live consumers inside a checkpoint whose job is defining one function | **open — migration deferred** |
| — | **CHECKPOINT 4b ACCEPTANCE CRITERIA, PINNED BEFORE IT IS BUILT — UTF-8 is a HARD GATE, not a header comment.** Recorded 2026-08-22 so it cannot be lost between deciding it and building it. **REQUIREMENT 1 — the real MCP server MUST call `sys.stdin.reconfigure(encoding="utf-8")` and the same for `stdout` BEFORE ANY OTHER I/O.** It currently exists only in the throwaway probe's header, and the probe is disposable. **REQUIREMENT 2 — it must be CANARIED, not asserted.** A test sends the harder payload — `U+2014` em dash, `U+00E9` accented Latin, `U+4E2D U+6587` CJK, `U+1F600` emoji (past the BMP) — through the real server and asserts an EXACT round trip **compared by codepoint, never by eye** (the terminal is cp1252 and will misreport what it received). **Observe it FAIL without the reconfigure** (payload returns mangled) **and pass with it**, per §15.1. An ASCII-only test cannot discriminate: ASCII survives cp1252 untouched. **WHY THIS IS LOAD-BEARING AND NOT HOUSEKEEPING.** 4b returns FILE PATHS and RAW IMPORT SPECIFIERS from arbitrary repos. Without the reconfigure, every non-ASCII path comes back silently wrong — well-formed, plausible, and corrupt — which is the §17.25 class exactly. **For a tool whose entire correctness bar is 'trust what it tells you', a path that returns subtly mangled is the same category of failure as a dropped dependent**, and it is the failure that sinks the pitch. The `echo` tool in 4a found this only because it exercised the variable that could be wrong; a connectivity check would have certified the wrong property (§17.35) | **SATISFIED — 4b closed 2026-09-01; see the closure row below. Requirement 2 was itself rewritten on Linux (§17.35 instance 4): the negative control borrowed its corrupting condition from the Windows platform default and could not fail under a UTF-8 locale, so it now forces cp1252 deterministically** |
| — | **CHECKPOINT 4a — MCP TRANSPORT GATE: stdio WORKS. Go for 4b, with one step only a session restart can close.** First-time MCP setup on this machine, probed 2026-08-22 with a THROWAWAY stdlib-only server (two tools: `ping`, `echo`; no graph, no boundary, nothing real). **REGISTRATION, recorded because it is first-time and non-obvious:** the `claude` CLI is **NOT installed** here — this is the VSCode extension, so `claude mcp add` does not exist and registration is config-file based. No `mcpServers` key existed anywhere (`~/.claude.json`, `~/.claude/settings.json`, no `.mcp.json`). Registered by creating **`d:\Athena\.mcp.json`** (workspace root, OUTSIDE the git repo) with `{mcpServers: {athena-transport-probe: {command: <python.exe>, args: [<server.py>]}}}`. **TRAP, cost a cycle:** writing that JSON via a bash heredoc **collapsed the escaped backslashes and produced invalid JSON**, which would have failed registration silently. Caught only because the file was re-read and parsed after writing. Write Windows paths in JSON with `json.dump`, never a heredoc. **ROUND TRIP PROVEN:** launched exactly as the config specifies — `initialize` -> `notifications/initialized` -> `tools/list` -> `tools/call`, returning `pong` and the echoed text, exit 0. **stdio is PROXY-IMMUNE and that is the reason to prefer it: it is a PIPE, not a network call**, so the SSL-intercepting proxy is not in the path at any layer. No proxy env vars reach spawned servers either. **CLOSED AT THE EXTENSION LAYER 2026-08-22.** MCP servers load at SESSION START, so the probe's tools were invisible to the session that registered them; after a VSCode window reload they appeared as `mcp__athena-transport-probe__{ping,echo}` and were called directly — **`ping` returned `pong`, `echo` returned its text**. Both layers now proven: protocol (hand-driven JSON-RPC) and extension (the client's own tool call). **AND THE `echo` CALL CAUGHT A REAL BUG THAT `ping` COULD NOT.** The echoed em-dash came back as three cp1252 characters: a process spawned on Windows defaults `stdin`/`stdout` to the ANSI codepage, but **MCP mandates UTF-8**, so every multi-byte character was mangled — and the round trip SUCCEEDED, returning a plausible-looking wrong string with nothing raised. Diagnosed (spawned python reports `cp1252 cp1252`), fixed with `sys.stdin/stdout.reconfigure(encoding="utf-8")`, and verified by codepoint against `U+2014 / U+00E9 / U+4E2D U+6587 / U+1F600` — exact round trip. **A `ping`-only gate would have passed clean and shipped this into 4b.** Full pattern: contract **§17.35**. **THE INCIDENT — `pip install mcp` POISONED THE PROJECT VENV.** The proxy permits pip, but installing the SDK upgraded **starlette 0.46.2 -> 1.6.0, which breaks fastapi 0.115.12**, inside `backend/venv`; the full suite was running against that venv at the time and its result was void. Reverted: suite killed, 13 packages uninstalled, `starlette==0.46.2` restored, verified `pip check` clean and `app.main` imports. **NEVER install the `mcp` SDK into the project venv — use an isolated venv or stay stdlib-only.** The probe was then rebuilt stdlib-only, which is the better gate anyway: zero dependency footprint, and a failure is unambiguously the TRANSPORT rather than a package install | **CLOSED 2026-08-22 — gate passed at BOTH layers; 4b may proceed** |
| — | **CHECKPOINT 4b — THE GRAPH MCP SERVER: CLOSED AT BOTH LAYERS.** `backend/mcp_graph_server.py`, stdlib-only for the protocol (no `mcp` SDK, per §17.34), exposing one tool: `neighborhood`. Committed `6ae89c8` with 9 tests. **PROTOCOL LAYER** proven on Windows and re-proven on the Linux VM 2026-09-01, spawned from the WORKSPACE ROOT rather than `backend/` — the cwd that broke the first extension attempt. **THE CWD BUG, and why the protocol test could not catch it:** settings carry RELATIVE paths (`sqlite:///./athena.db` and five config files) which resolve against the client's chosen cwd; the VSCode extension spawns from the workspace root, and **SQLite CREATES a missing database rather than refusing**, so the server started clean, left a 0-byte `athena.db` behind, and failed on the first query with `no such table: repos`. The protocol test spawned with `cwd=backend` and so FIXED THE VARIABLE UNDER TEST (§15.1). Fixed with `os.chdir(BACKEND_DIR)` before the app import, plus a regression test that spawns from a temp directory and asserts no stray database appears. **EXTENSION LAYER CLOSED 2026-09-01** on the Linux VM: `.mcp.json` recreated at the workspace root (`/home/hack-t36/Athena/.mcp.json`, Linux paths, written with `json.dump` and re-parsed), window reloaded, and `mcp__athena-graph__neighborhood` called for `superset/models/core.py` on `apache/superset`. **EVERY FIELD MATCHED THE PROTOCOL PROOF EXACTLY**: 258 importers, 22 imports, 51 unresolved, 25 enriched + 233 additional paths (= 258, no path dropped), `rank` 6, `in_cycle` true, snapshot `a05a0999`, `blast_radius` 244 same-subsystem / 14 crossing, budget 9,000 `applied: false` (server estimate 5,062). The server's own log reported `stdin=utf-8 stdout=utf-8` and `cached repo 6: 6,584 nodes, 61,559 edges` — the real graph, not an empty database. **Built on Windows, closed on Linux, and the two agree** | **CLOSED 2026-09-01 — both layers; checkpoint 5 is the last piece of Phase 6** |
| — | **CHECKPOINT 3 RESULTS — THE BENCHMARK. Measured at `a05a0999` on 2026-08-22, which is CURRENT: no staleness caveat applies.** Method: tiktoken `cl100k_base`, Graphify-shaped comparison — **NAIVE** = full text of the file plus every directly connected file (its imports and its importers), read in full; **GRAPH** = the checkpoint-2 neighbourhood query's output. Graph 6,584 nodes / 61,559 edges. **THE SPREAD** — leaf `scripts/__init__.py` (0 connected) naive 174 / graph 188 = **0.93x**; mid `superset/commands/annotation_layer/annotation/create.py` (6) 7,754 / 489 = **15.9x**; mid `superset/commands/chart/delete.py` (10) 30,206 / 561 = **53.8x**; hub `superset/__init__.py` (524) 1,651,458 / 8,452 = **195.4x**; hub `superset/utils/core.py` (355) 1,746,672 / 5,954 = **293.4x**. **Pooled 3,436,264 vs 15,644 = 219.7x (99.5% reduction).** **THE DISTRIBUTION IS THE DELIVERABLE, NOT THE POOLED NUMBER.** Floor **0.93x** on an isolated file — the graph costs **8% MORE than simply reading it** — then **94–98%** on the mid files where connected work actually happens, then **99.5%** on hubs. **The 0.93x floor is reported deliberately.** A benchmark that showed only the 293x hub would be less credible, not more: the pooled figure is dominated by two hubs, and anyone who checks will find the floor themselves. Stating it first is what makes the rest believable. **SELECTION CRITERIA, refined OPENLY mid-measurement.** Initial: mid = closest to median connectivity. That returned two near-identical `scripts/` files with **fan_in=0** — files nothing imports have no blast radius, so they would have measured the LEAF case twice under a 'mid' label. Refined to **median connectivity among files with fan_in>0 AND fan_out>0** (971 files, median 18). Recorded as a refinement rather than swapped silently, because a criterion changed after seeing results is post-hoc unless it is declared. **SUFFICIENCY: ZERO REAL MISSES** on every grep-adjudicable target (create.py 1/1, delete.py 2/2, `utils/core.py` **325 grep / 346 neighbourhood**), capped and uncapped alike; grep discrimination proven first (unescaped 10 hits vs escaped 8 on `config.py`, the broken pattern inventing `superset_config_docker_light.py`). **THE GREP SELF-CORRECTION — THIRD INSTANCE, NOW STRUCTURALLY PREVENTED.** The first sufficiency pass reported **6 misses, all of them the instrument's**: package `__init__.py` targets were grep-adjudicated, when checkpoint 2 had ALREADY established that `from superset import config` imports `superset/config.py` and no regex distinguishes it from the package. One 'miss' was inside a docstring. **The fix was encoded in the script (`NOT_GREP_ADJUDICABLE`, with the reason inline) rather than relied on from memory** — when the same instrument error appears a third time, the response is to build the constraint into the tool, not to remember harder. §17's own lesson applied to §17's checking process. **PREDICTION MISSES, named:** mid connectivity over-predicted (fan_in+fan_out counts EDGES; distinct connected FILES are fewer once duplicate edges collapse), and hub graph-cost over-predicted at ~12,500 against an actual 8,452 (798 importer edges resolve to 524 distinct files) | **done — the CEO number, with its floor** |
| — | **BUDGET CAP: default raised to 9,000, refuse-don't-cut kept underneath. Option (c) — cutting paths — REJECTED OUTRIGHT.** Graphify's default is 2,000. Measured at `a05a0999`, 2,000 **cannot hold a hub**: `superset/__init__.py` needs 8,452 tok for 524 importer paths and `utils/core.py` 5,954 for 346, and after shedding the second hop and every scrap of per-neighbour metadata both remain over — by **5,806** and **3,116** tokens respectively. **The only way to reach 2,000 is to drop ~500 dependents, and checkpoint 2 established that a dropped dependent is invisible to the consumer.** So the mechanism refuses: `_apply_budget` sheds the second hop, then metadata, then STOPS and reports `sufficiency_sacrificed: true` with an exact shortfall rather than hitting a pretty number by lying about completeness. **The cap cannot misrepresent completeness by construction** (§17.25 avoided structurally, not by discipline). **9,000 clears the worst measured hub with headroom**, so the cap is MET for every real file — **verified: `__init__.py` 8,452 and `utils/core.py` 5,954 both leave `applied=False`, nothing sacrificed, all 520 / 346 paths kept.** **Canary observed both ways:** held against budgets of 2,000 and 500 the same hub keeps **520 of 520 importer paths** and reports shortfalls of 5,806 and 7,305 — it never reaches its number by cutting. A mutation making the cap shed paths alongside metadata fails `test_LOADBEARING_the_cap_never_drops_a_path_to_hit_its_number`. **This is option (a)'s integrity with option (b)'s presentation:** the demo sentence is now **'flat, ≤9,000 tokens, sufficiency always preserved'** rather than 'variable up to 8,452', and the honest floor still fires for any future mega-hub that exceeds even 9,000. **OPT-IN:** `budget_tokens` still defaults to `None`, so no existing caller changes behaviour; 9,000 is what a caller passes when it wants the flat cost. `test_the_default_budget_clears_the_worst_measured_hub` pins the constant to the measurement so a later tidy-up cannot round it down | **decided — 9,000, never cut paths** |
| — | **PHASE 7 REGISTERED — multi-language expansion of the atlas. DEFERRED until the Phase 6 demo lands, deliberately.** **Goal:** extend tree-sitter extraction beyond Python and the JS family to Go, Rust, Java, C# and whatever else client work dictates, widening the tool's reach to more developers. **THE SEQUENCING IS THE DECISION: proven-then-expanded.** Checkpoint 3's benchmark demonstrates the token saving on superset, which is already Python + TypeScript and therefore already multi-language for demo purposes. Multi-language is the FUNDED NEXT STEP once that number lands, not a prerequisite for it — **leading with breadth before proving the saving would be building the wide part before the deep part**, and would put the effort into surface area while the core claim is still unmeasured. **The pattern is known and cheap per language**, mirroring the existing `extract_python.py` / `extract_js.py`: a tree-sitter grammar exists for roughly 40 languages, so adding one is *wire the grammar's node types to node/edge extraction*, not *write a parser*. Structured as **one language per checkpoint, each with a fixture repo and a canary** — the same discipline the existing extractors were held to, not a bulk drop. **LAYER DISTINCTION, so the two phases do not get conflated:** Phase 7 is an ATLAS-layer expansion (new extractors in the parse phase, changing what the atlas ingests). Phase 6's export/query layer is LANGUAGE-AGNOSTIC — it reads whatever the atlas produced, through `graph_read`. So Phase 7 widens the input; **the query mechanism already works over any language the atlas supports** and needs no change per language | **registered — deferred until checkpoint 3's number lands** |
| — | **CURATED GRAPHIFY-ADOPTION LIST — what to take, what to refuse, and the principle that decides.** Graphify (108k stars) shares this core mechanism, so the list exists to stop future phases drifting into cloning its breadth. **THE PRINCIPLE: take what serves the local / private / developer-workflow / token-saving pitch; skip what serves 'be everything to everyone'.** Cloning Graphify's breadth would dilute the focused advantage — ranking, validation rigor, private-infra local operation — that differentiates this from a standalone tool. **ADOPT.** (1) **Token-budget cap on queries** (their `--budget`, default 2000 tok) — makes per-query cost FLAT and predictable, a cleaner demo metric than the current variable-up-to-8,336; folds into Phase 6. (2) **Multi-language via tree-sitter** — Phase 7 above. (3) **The PreToolUse enforcement hook + MCP server** — already Phase 6 checkpoints 3/4; this is the *actually gets used* layer, and without it the saving is theoretical. (4) **`path` and `explain` as named query primitives** alongside the neighbourhood query — the traversal already exists internally (checkpoint 0 ran BFS over the edge set), so exposing them is cheap and matches what developers expect to be able to ask. **SKIP, deliberately rather than by oversight.** (1) **PDFs, images, video, docs-semantic-extraction** — LLM-cost sinks, off the developer-workflow target, and they **break the zero-LLM-local advantage**, which is the entire reason this can run on private client code. (2) **17-assistant integration breadth** — Claude Code done well beats many done shallowly; breadth here buys demos, not users. (3) **PR intelligence, git-hook auto-rebuild, obsidian/wiki export** — standalone-PRODUCT features, irrelevant to an embedded module | **decided — the adoption boundary** |
| — | **HONEST POSITIONING, recorded so it is not lost or inflated later.** **The token-saving MECHANISM is the same as Graphify's** — bounded-subgraph queries in place of file reads. That is proven at scale by a 108k-star tool and is **not novel**, and nothing in this record should be read as claiming otherwise. **The differentiators are three, and they are real:** (a) the **RANKING layer** — PageRank / RRF / weighted-pagerank, against their raw degree centrality, so a subgraph can be ordered by what matters rather than returned whole; (b) the **VALIDATION RIGOR** — §17's recorded failure modes, denominators that travel, canaries observed failing before green is trusted; **they do not publish anything equivalent**; (c) **fully-local, zero-LLM operation on private code inside our own infra**, which is what makes it usable on client repos behind a corporate proxy. **The claim is: we do the proven thing, on private client code, backed by analysis rigor standalone tools lack.** NOT *we invented it*, and NOT *we are broader or more mature than Graphify* — we are neither, and a pitch that says so loses the moment anyone checks | **decided — the claim, and its limits** |
| — | **CHECKPOINT 2 RESULTS — the neighbourhood query is BOUNDED and SUFFICIENT, with the evidence.** **[MEASURED AT `e2bb33b1`, recorded 2026-08-21. Superset has since been re-ingested to `a05a0999`, so the ABSOLUTE token counts here are snapshot-specific and stale; the BOUNDEDNESS and SUFFICIENCY properties, and the ratios, hold across snapshots. Not re-measured — checkpoint 3 supplies current figures. §17.16.]** **Cost across the range** (baseline for comparison: 560,768 tok to read superset's top-100 files): leaf `RELEASING/changelog.py` **261 tok** (300 with second hop, 0 importers); mid `superset/config.py` **1,466** (3,382; 10 importers, 22 imports, 33 unresolved); hub `superset/__init__.py` **8,336** (10,356; **515 importers**); hub `superset/utils/core.py` **5,835** (7,886; 340 importers); named `superset/models/core.py` **4,403** (6,642; 253 importers). **The recorded point is the shape, not the numbers: bounded across the entire range, worst hub at 1.5% of the baseline.** **THE HUB BOUND CORRECTS ITS OWN SPEC.** The bound was specified as rank-and-truncate the importers ('412 importers, top 20 by rank'). Measurement withdrew it: listing ALL 515 importer paths of the worst hub costs **7,458 tok**, 1.3% of the baseline. **Paths are cheap; per-neighbour METADATA is what scales** — so `MAX_ENRICHED = 25` bounds ENRICHMENT and a path is NEVER dropped. `enriched + additional_paths == total` on every hub (25+490=515, 25+315=340, 25+228=253), asserted by a canary rather than promised. Truncating paths would have traded blast-radius sufficiency for a saving that was not needed; the opt-in second hop is the one bounded part and reports its own `truncated` flag. **SUFFICIENCY CROSS-CHECK: ZERO REAL MISSES across five targets** — `models/core.py` grep 247 / nbhd 253, `utils/core.py` 319 / 340, `config.py` 8 / 10, `exceptions.py` 287 / 286, `sql_lab.py` 7 / 12; misses 0, 0, 0, 0, 0. **The neighbourhood is a strict SUPERSET of grep**, adding 2–21 importers per target that grep's patterns cannot express (relative, aliased and deferred imports). **INSTRUMENT-FAILURE CAVEAT, recorded because the result is only worth what the instrument is:** the FIRST cross-check reported five sufficiency failures and every one was the grep — an unescaped `.` in the interpolated module name matched the `_` in `from superset_config import *`, and a loose `import superset` attributed `import superset.utils.database` to `superset/__init__.py`. The corrected grep was then CANARIED against its own broken form before its zero-miss result was trusted (unescaped 10 hits vs escaped 8 on `config.py` — the instrument discriminates). A third apparent miss was a file never ingested, which is ingest scope, not a neighbourhood hole. **THE TARGETING VALUE, which is the whole pitch in one number:** `models/core.py`'s neighbourhood costs **4,403 tok** and points at **22 files worth 141,525 tok** to read — it does not save you the read, it tells you WHICH 141K to spend out of a 6,523-file repo. Four canaries observed failing on broken code and passing on fixed: completeness (importers half removed), unresolved imports, hub bound (made to drop paths), boundary-only read (both an indirection dodge and a direct table read) | **done — the evidentiary basis for checkpoint 3** |
| — | **Pre-Phase-6 superset counts are DELIBERATELY NOT STAMPED, and that is a finding rather than an omission.** The 2026-08-21 provenance pass stamped every Phase 6 figure `e2bb33b1`. Phase 4/5 rows also cite superset counts (6,523 files and others) and were LEFT ALONE: they date from 2026-08-12/13 and sit at snapshots nobody recorded, so they may predate `e2bb33b1` or sit at an intermediate ingest. **Stamping them `e2bb33b1` would have been inventing provenance** — a confident-looking marker for a snapshot never verified, which is worse than an unmarked number because it cannot be questioned. Marked here as unverified-snapshot instead. If any Phase 4/5 figure is ever load-bearing again, its snapshot has to be re-established, not assumed | **open — unverified snapshots, flagged not guessed** |
| — | **SCOPED-ARTIFACT MODE IS RETIRED for large repos — not re-budgeted, RETIRED.** At the end of 1b I proposed re-deriving the scoped budget on edges or tokens instead of files. **That fix targeted the wrong failure and is withdrawn.** The candidate comparison (2026-08-21, superset, baseline = 560,768 tok to read the top-100 files by `legacy` rank). **[MEASURED AT `e2bb33b1` — superset was re-ingested to `a05a0999` on 2026-08-21 (6,523→6,584 files, 60,873→61,559 imports), so every ABSOLUTE count below is snapshot-specific and now stale. Not re-measured here: checkpoint 3 supplies current figures at `a05a0999`. §17.16 — marked, not silently corrected.]** **The multiples (14.5x, 5.1x, 1.66x OVER, 27.0x, 10.8x, 15.4x) are RATIOS between two quantities measured on the SAME snapshot and are expected to hold; the 560,768 baseline, the six candidate token counts, and the sufficiency counts (24 of 253, 44 of 832, 54 vs 1,287) are absolutes and are stale.** It measured four export-layer representations, all read through the 1a boundary, none altering the atlas: **(a) top-100 all edges 38,757 tok (14.5x under baseline), top-250 109,833 (5.1x); (b) whole graph resolved-only 929,193 (1.66x OVER baseline); (c) top-100 resolved-only 20,798 (27.0x under), top-250 52,145 (10.8x); (d) five-question bundle 36,328 (15.4x under)**. **The bounded artifacts win on cost and lose on truth.** Asked the onboarding questions, top-100 returned **24 of 253** importers of `models/core.py`, **44 of 832** files in cycles, and named the largest subsystem `superset/migrations/versions` with **54 members when the true count is 1,287** — the RIGHT LABEL with the WRONG MAGNITUDE, and nothing in the artifact distinguishes 'this subsystem has 54 files' from 'this artifact contains 54 of its files' (§17.25). A budget change cannot fix that: **any** budget produces confidently-wrong answers, because the error is the boundedness itself, not its size. And (b), the one bounded-but-complete candidate, is more expensive than just reading the source. **Whole-graph mode stands UNCHANGED for small/mid repos** — Athena-OS 42,936 tok and eslint 79,027 tok are complete AND cheap, so below the threshold the artifact is genuinely the right product. The split is clean architecture, not a compromise | **decided — scoped artifact retired, whole-graph mode unchanged** |
| — | **DEFERRED, not cut: onboarding-question queries and structural subsystem summaries.** The five-question bundle (d) measured well. **[MEASURED AT `e2bb33b1` — superset was re-ingested to `a05a0999` on 2026-08-21 (6,523→6,584 files, 60,873→61,559 imports), so every ABSOLUTE count below is snapshot-specific and now stale. Not re-measured here: checkpoint 3 supplies current figures at `a05a0999`. §17.16 — marked, not silently corrected.]** **15.4x is a ratio; the per-question costs and the 128/~378-question crossover are absolutes derived from them and shift with the snapshot.** 36,328 tok, 15.4x under baseline, exact on all five — so this is parked because the goal narrowed, NOT because it failed. Two things are worth carrying forward when it is un-parked: the bundle's cost is dominated by **Q3 largest-subsystem members (17,722 tok) and Q5 files-in-cycles (15,911)**, both of which are simply long path lists (1,287 and 832 files), while Q1/Q2/Q4 cost 2,460 / 36 / 199 — so **a query interface that can only return everything hits the same wall the artifact did**, and summarisation or pagination is part of that work rather than a later refinement. Second: an artifact is paid once and queries are paid per question, so the whole resolved-only artifact becomes cheaper than querying at roughly **128 questions at the mean, ~378 at the median** (mean 7,266, median 2,460, range 36–17,722 — the distribution, not the mean, per §17.5c). Far beyond an onboarding session, so the verdict holds, but the crossover is real | **deferred — build only if a need appears** |
| — | **PHASE 6 GOAL REVISED AND NARROWED: the graph as a TARGETING MAP FOR READS, not a knowledge source to be exported.** The registered goal was 'let an external agent answer structural questions by querying the graph'. The measurement moved it. **The new goal:** when Claude Code works on a file in a repo, it queries the graph for that file's dependency neighbourhood and reads only the files that matter, instead of exploring the repo to find them. The saving is the difference between *grep around to find what is connected, then read it* and *the graph hands you the connected set directly*. This is narrower than 'export the atlas' and it is the part the measurement actually supports: a file's direct neighbourhood is inherently small, so it is bounded by construction rather than by a budget that has to be chosen | **decided — checkpoint 2 is the neighbourhood query** |
| — | **SUFFICIENCY, NOT CHEAPNESS, IS CHECKPOINT 2's CORRECTNESS BAR.** The neighbourhood query only delivers the pitch if its result is SUFFICIENT. If Claude Code still has to read files the neighbourhood did not point to, then query tokens **plus** the reads are net worse than just reading — the same arithmetic that sank the bounded artifacts, arriving by a different route. So the load-bearing property is not 'the neighbourhood is small', it is 'the neighbourhood contains what an agent needs to change the file'. **Checkpoint 2 must GUARANTEE it** (cross-check the neighbourhood against what grep finds as the file's real imports and importers; a miss is a §17.25 failure and stops the checkpoint) **and checkpoint 3 must MEASURE it** (against the read-anyway baseline, not against zero). A bound that hides a real dependency is the failure mode that sinks the whole pitch, so where a hub file's neighbourhood must be truncated the COUNT stays exact and stated — '412 importers, top 20 by rank' — never a silent cut | **decided — the bar checkpoint 2 is built against** |
| — | **Checkpoint 1b DONE — the atlas emitter, its threshold, and a threshold that does not do what it was chosen to do.** `atlas_export.py` serialises through `graph_read.read_repo_graph` and nothing else (canaried: stubbing the boundary must replace the ENTIRE artifact, plus a grep-level backstop against `db.execute`/`SELECT`/model imports). **Named constants, not magic numbers:** `WHOLE_GRAPH_MAX_FILES = 1500` (the checkpoint-0 crossover), `SCOPED_MAX_FILES`, `ARTIFACT_SCORER = 'legacy'`, `ARTIFACT_CLUSTERING = 'modularity'`, `ARTIFACT_SCHEMA_VERSION = 1`. The artifact STATES its mode and completeness (`mode`, `complete`, `files_included`/`files_total`) rather than leaving it inferable from size — §17.25. **[MEASURED AT `e2bb33b1` — superset was re-ingested to `a05a0999` on 2026-08-21 (6,523→6,584 files, 60,873→61,559 imports), so every ABSOLUTE count below is snapshot-specific and now stale. Not re-measured here: checkpoint 3 supplies current figures at `a05a0999`. §17.16 — marked, not silently corrected.]** **The byte-identity itself is a snapshot-independent PROPERTY of the two instruments and remains true; the token counts it reconciles are absolutes and are stale.** **Reconciliation against checkpoint 0 is BYTE-IDENTICAL on the like-for-like layer** for all three repos (Athena-OS/eslint/superset), and the published 31,315 / 73,953 / 962,330 re-derive exactly from raw SQL, so the emitter and the fact-finding measurement do not disagree. The artifact differs from those figures by exactly two REQUIRED changes, both accounted: **1a's one-member-SCC correction** (−1,370 / −1,985 / −33,142 tok — checkpoint 0 emitted `scc` for every file because every file is trivially its own SCC) and **the deliberate inclusion of unresolved edges** (+12,991 / +7,059 / **+687,307**). **THE FINDING: unresolved edges cost more than the resolved graph.** Superset's whole artifact is **1,616,495 tok**, 74% of it the 34,311 unresolved edges and their specifier strings. **AND THE THRESHOLD IS CALIBRATED ON THE WRONG QUANTITY.** Checkpoint 0's own conclusion was that *tokens track EDGES, not files* — yet `SCOPED_MAX_FILES` caps FILES. Scoping superset to its top 1,500 ranked files still emits **607,277 tok**, which is MORE than the 560,768 it costs to just read its top 100 ranked files. So scoped mode currently fails the very test that motivated Phase 6. A file cap cannot bound tokens in a repo whose density is the problem; **the fix is a budget expressed in edges or tokens, decided before checkpoint 2 rather than inside it** | **open — scoped budget must be re-derived on edges/tokens, not files** |
| — | **56% of superset's import edges are UNRESOLVED, and every `_build_graph` consumer works from the other 44% without knowing it.** Measured 2026-08-21 through the checkpoint-1a boundary, reconciled against raw SQL in the same process. **[MEASURED AT `e2bb33b1` — superset was re-ingested to `a05a0999` on 2026-08-21 (6,523→6,584 files, 60,873→61,559 imports), so every ABSOLUTE count below is snapshot-specific and now stale. Not re-measured here: checkpoint 3 supplies current figures at `a05a0999`. §17.16 — marked, not silently corrected.]** **The RATES (56.4% / 41.5% / 25.3%) are ratios and are expected to move only slowly; the edge COUNTS are absolutes and are stale — superset now has 61,559 import rows, not 60,873, and the unresolved share at `a05a0999` has not been re-measured.** **superset 34,311 of 60,873 edges unresolved (56.4%)**, **Athena-OS 939 of 2,265 (41.5%)**, **eslint 584 of 2,304 (25.3%)** — the denominator travels because the rate does not (§17.5c). `ranking._build_graph` filters `to_file_id.isnot(None)`, so PageRank, clustering, `graph_structure`, `card_persist` and `roadmap_persist` all see the resolved subset and have no signal that a majority of superset's import rows exist at all. **THE OPEN QUESTION IS NOT 'more edges is better'.** An unresolved edge has no target file, so it cannot carry a PageRank contribution or a clustering weight the way a resolved edge can — excluding them may be CORRECT for the ranking and clustering consumers. But an agent asking *what does this file import* wants to know about the import that did not resolve; that is real provenance. So: **the 1a boundary carries unresolved edges (right for the export), and whether each consumer uses them is the migration checkpoint's decision, made PER CONSUMER rather than as a blanket switch.** The migration checkpoint opens with that question, not with an assumed answer. **Candidate connection, NOT a mechanism claim:** superset's known validation problems — the 13.2% layer-reachability ceiling and ranking falling below its Overlap@20 bar — were diagnosed as Flask dynamic-blueprint registration producing no static edges. The 56% figure is CONSISTENT with that diagnosis and is a candidate contributor, but nothing here establishes cause. **Worth investigating whether the unresolved edges explain part of the reachability ceiling** — as an investigation to run, not a finding already made | **open — per-consumer decision deferred to the migration checkpoint** |
| — | **Phase 6 checkpoint structure, revised after checkpoint 0.** **1a** stable whole-graph read boundary (typed, uncapped, includes unresolved edges and cycles). **1b** emitter + mode switch. **2** query primitives — now MANDATORY rather than optional, because the measurement located the entire saving there and not in the whole-graph artifact. **3** measurement harness against a REALISTIC top-N file-read baseline (superset: 62k tok for top 10, 173k top 25, 229k top 50, 561k top 100 — real counts) using an onboarding-question bundle, not the read-everything strawman. **4** MCP server, deliberately last, because it is the part that is worthless if 1-3 are not real | **1a + 1b DONE 2026-08-21 (`graph_read.py` 11 tests, `atlas_export.py` 17 tests; counts reconciled to the raw-SQL baseline and the artifact byte-identical to checkpoint 0 like-for-like on all three repos). **2 must first re-derive the scoped budget on edges/tokens — the file cap does not bound tokens**** |
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
| 4 — module/roadmap persistence | **closed; output visible, creation unwired** | `f8a3c21d9b45`, `a1c9e37f4b82`; live: 145 modules, 3 roadmaps. Verified 2026-08-20 that all three appear in the roadmap library (`GET /api/roadmaps` returns them beside seed/generated tiles) with modules, topics and progress working. Only `POST /{id}/roadmap` has no UI caller — a roadmap can be used but not created from the interface |
| 5 — comprehension cards | **BACKEND COMPLETE, NO USER SURFACE** | `c4b7e9d2f501`; live: 661 cards (564 superset / 70 eslint / 27 Athena-OS). **Nothing in the UI renders them** — `grep` over `frontend/src/` finds zero references. Reachable only via `GET/POST /api/repos/{id}/cards`. Also carries the §17.29 gap |
| **6 — Codebase Atlas Export → GRAPH AS TARGETING MAP** | **GRAPH IS AT `a05a0999` (re-ingested 2026-08-21; 6,584 files / 61,559 imports). Every Phase 6 figure predating that was measured at `e2bb33b1` and is stamped as such in the rows below — checkpoint 3 supplies current numbers. Ratios carry across; absolute counts do not.**  **0/1a/1b DONE; scoped artifact RETIRED; checkpoint 2 = neighbourhood query** | gate cleared 2026-08-21: median **34.3x** vs grep, plus 2 question classes grep cannot answer (clusters, cycles). **Corrected headline: whole-graph-as-context is a token LOSS on superset** (962,330 tok vs 560,768 to read the top 100 ranked files) — the saving lives in SCOPED QUERIES. Design is queried-in-pieces, with whole-graph an option only below ~1,500 files. **GOAL REVISED after the candidate comparison: the graph is a TARGETING MAP FOR READS, not an export.** Claude Code queries a file's dependency neighbourhood and reads only what matters, instead of exploring to find it. **Scoped-artifact mode is RETIRED for large repos** — bounded artifacts were 14–27x cheaper than the 560,768-tok baseline but answered wrongly and confidently (top-100 gave the largest subsystem as 54 members against a true 1,287 — right label, wrong magnitude, undetectable by the consumer, §17.25); no budget fixes that, and the one complete candidate (929,193 tok) costs more than reading the source. **Whole-graph mode unchanged below the threshold** (Athena-OS 43K, eslint 79K — complete and cheap). Onboarding-question queries and subsystem summaries are **deferred, not cut**. Checkpoints: 1a boundary DONE, 1b emitter DONE, **2 neighbourhood query**, 3 measurement, 4 MCP. **The bar for 2 is SUFFICIENCY, not cheapness** — if CC still reads files the neighbourhood missed, query + reads is worse than reading. **1a also surfaced that 56% of superset's edges are unresolved and invisible to every `_build_graph` consumer** — the per-consumer decision is the migration checkpoint's opening question |
| **7 — multi-language expansion** | **REGISTERED, deliberately deferred** | no files, no migrations, no tests. Tree-sitter extractors for Go/Rust/Java/C# beyond the existing `extract_python.py` / `extract_js.py`; one language per checkpoint, each with a fixture repo and a canary. **Deferred until checkpoint 3's benchmark lands — proven-then-expanded.** Atlas-layer only; Phase 6's query layer is language-agnostic and needs no change per language |
| 8 | **NOT STARTED AND NOT DEFINED** | no files, no migrations, no tests — **and no scope has ever been written for it.** The number is a placeholder in this table, not a planned phase. A fresh session should treat 'Phase 8' as unallocated and ask what it is rather than inferring a scope from the numbering |

## Suite state

- **Backend: 1,181 passed / 0 skipped / 0 failed** on the Linux VM, full run
  2026-08-26 (78.6s), against superset at SHA `a05a0999`. Green, with no test
  outstanding and no isolation-only verification pending. Includes checkpoint
  4b's 9 MCP server tests, **committed at `6ae89c8`**; the extension-level
  confirmation they were pending **completed 2026-09-01**.
  - **Superseded figure, kept per §17.16:** the Windows machine recorded
    **1,180 passed / 1 skipped / 0 failed** (2026-08-24, 18m27s). Both are
    correct for their platform and the totals reconcile exactly at 1,181
    collected. Two tests move in opposite directions: `test_git_credentials.py
    ::test_script_is_executable_on_posix` is `skipif(os.name == "nt")`, so it
    is skipped on Windows and genuinely runs and passes here; and the §17.35
    UTF-8 negative-control canary had to be rewritten to construct its
    corrupting condition deterministically (§17.35 instance 4) because its
    original Windows-only premise could not fail under a UTF-8 locale.
- **Frontend: 231 vitest tests across 18 files, all passing**, plus **8
  Playwright tests across 7 files** (`e2e/`; corrected 2026-08-26, §17.16 --
  the "6" was accurate when written 2026-08-20, but `card-practice.spec.ts`
  added a 2-test file the next day and the count was never re-verified after).
  `npx tsc --noEmit` clean.
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
| 4 | counter alignment | **done** — 4 of 6 surfaces were already correct; Layers notice `c3f8018`, Focus counter `213ee95` |
| 5 | frontend sends the params | **done — mostly already shipped** in `9fb9bce`; the genuine gap was the re-layout indicator, `4e1f42b` |
| 6 | verify under filter | **done** — `b507189`, superset 6,523 → 2,547 on Architecture and Matrix, DetailPanel intact |
| 7 | record: close `:682`, write §17.30 | **done** — §17.30 promoted, §17.31/§17.32 written |

**`:682` is CLOSED.** All seven checkpoints complete.

## Open items

| item | status |
|---|---|
| **comprehension-cards UI** | **OPEN — a build, not a decision.** 661 live cards (564 superset / 70 eslint / 27 Athena-OS) have no frontend surface; `grep` over `frontend/src/` finds zero references, and they are reachable only through `GET/POST /api/repos/{id}/cards`. **Blocked on nothing** — every dependency exists: `card_grading.grade_card` is written and tested (and uncalled), `ComprehensionCard.module_id` points at modules already rendered at `/modules/:slug`, and `ModuleAssessment` has the right shape for attempts with zero code referencing it. **Blocks everything card-related**: the LLM-card tier would add generation capacity to a feature nobody can open, and card quality cannot be judged by anyone who cannot see a card. **Size: multi-checkpoint, comparable to `:682`** — a queue component, grading wiring, an attempt record, and browser verification |
| **codebase-roadmap creation has no UI** | **OPEN — small.** `POST /api/repos/{id}/roadmap` has no frontend caller; the three roadmaps that exist were made by script during this session, so a new user would never get one. Distinct from the card gap in severity: the OUTPUT is visible (all three appear in `GET /api/roadmaps` beside the seed tiles, with modules, topics and progress working) — only the creation action is missing. Roughly one button on the repo page plus its verification |
| **repo 5 disappearance** | occurrence **permanently unexplained** (§17.29-shaped); recurrence now traceable via `repo_deletion_audits` |
| **size-aware topic budget** | **deferred by decision** — needs a real user hitting a too-coarse module, not a guessed number |
| **health 30.6s / resync 22.0s** | **gates Phase 8**, no work started, measurement only |
| **`verify=False` SSL** | real, but in `app/core/llm.py` and `services/content_hub.py` — **outside the codebase agent** |
| **`verify=False` SSL is a machine-specific workaround, and this machine doesn't need it** | **found 2026-08-26, not acted on.** The Linux VM this project moved to has **no SSL-intercepting proxy** — direct internet, and a real (non-intercepted) cert chain confirmed on `pypi.org`. The `verify=False` calls above exist for the *old* Windows machine's corporate proxy, which is not a property of this codebase, it is a property of that machine. Leaving a blanket cert-verification bypass live on a box that does not need it is a loose end — not a fix to make now, but worth revisiting: either make it conditional on the constraint that motivated it, or confirm before any deploy off this VM that the target environment still needs it |
| **56% unresolved edges on superset — one-file partial data point** | **OPEN, shape refined 2026-09-01, blocking nothing.** Checkpoint 1a surfaced that 56% of superset's edges are unresolved and invisible to every `_build_graph` consumer. The 4b confirmation call gave a first data point: on `superset/models/core.py`, **all 51 unresolved imports are third-party or stdlib** (`sqlalchemy` x10, `typing` x5, `contextlib` x4, `flask` x3, numpy, pandas, sshtunnel, flask_appbuilder, marshmallow, ...) — **unresolved means EXTERNAL here**, and no first-party structure is being silently dropped. **This is ONE file of 6,584, and an atypical hub with a heavy third-party surface — it is NOT a repo-level answer and must not be quoted as one.** What it changes is the question worth asking: from 'how much real internal structure is invisible' to '**does unresolved-means-external hold repo-wide, or only on this file?**' The cheap version of that investigation is classifying unresolved specifiers repo-wide against a known-external list, not re-deriving reachability |
| **six unwritten patterns** | pending §17.31+ at checkpoint 7 |
| **`/ranking` payload** | measured (2.825 MB on superset), masked by parallel fetches, not urgent |
| **`.index` crash** | never reproduced; instrumented; premises in its entry now corrected |

## The methodology contract

`docs/code-health-contract.md` holds **37 §17 subsections** — a running record of
instrument failures, each with the mechanism and the rule it produced. It is the
most useful thing to read before changing anything. The newest are **§17.30** (instruments reporting the absence of what they cannot
perceive — five instances in one session, four browser probes and one
`str.replace` that returned success without replacing anything), **§17.31** (an
identifier that looks stable and is not: SQLite rowid reuse, `hash()` salting)
and **§17.32** (a question answerable without being answered: distractor
defects in generated cards).

## What to do next

**FIRST, a gap found on 2026-08-20 that outranks the three below:** Phase 5's
**661 comprehension cards have no user surface**. Nothing in `frontend/src/`
renders them. All three options below assume cards are usable — building the LLM
tier in particular would add generation capacity to a feature nobody can open.
Needs: a card queue, an attempt record (`ModuleAssessment` already has the right
shape and **zero code referencing it**), and a call to `card_grading.grade_card`
(written and tested, never called). Phase 4 is not in this position — its
roadmaps ARE visible in the library; only `POST /{id}/roadmap` is unwired.

**Then the three deferred items. None is started; the tradeoffs, not a
recommendation:**

1. **Size-aware topic budget** (`decisions.md`, "Phase 4 mapping" and "topic
   level" rows, now merged). Module size spans 3 → 1,138 files, so no fixed
   topic strategy produces a sensible count; `single_topic` is the honest
   default until a budget exists. *Deferred by decision*: it was judged to need
   a real person studying a too-coarse module rather than a guessed number, and
   that judgement still stands. Cheapest to start, least certain to be right.
2. **`health` 30.6s / `resync` 22.0s** — both profiled, both marked *gates
   Phase 8*, no work started. The hot spot is named (`ast_metrics._iter_subtree`
   at 35.8M calls, re-walking the tree per metric rather than once). Unblocks a
   phase; delivers nothing a user sees.
3. **The LLM card source** — Phase 5's seam exists and raises
   `NotImplementedError`; `card_source` is a column populated from row one. The
   argument for building it is measured: **24 of Superset's 122 modules produce
   no deterministic cards at all**, because the remaining templates need graph
   structure those modules lack. This is the only option that adds user-facing
   capability, and the only one that costs money per run and needs the zero-LLM
   non-negotiable explicitly lifted for that path.

**Done, was outstanding:** the full backend suite has since been run — 1,180
passed / 1 skipped, 2026-08-24, with nothing verified in isolation only.

## The habit that matters most here

Check the claim against the code before acting on it. This session found the
record wrong five times — a label that never changed after the work shipped, an
entry describing code that had been deleted, a fix recorded as open, a gap
recorded as open that was closed, and a backend feature recorded as unbuilt that
had shipped a day later. One of those wrong claims was produced by an audit
inside this same session. **A reported defect is not evidence a defect exists,
and a recorded gap is not evidence a gap exists.**
---

# Interview Arena — Phase A (2026-09-01)

New module, namespaced `arena_*` on branch `arena/phase-a`. JD in, confirmed
skill graph out. The legacy `/api/interview` flow stays mounted: it still feeds
analytics, achievements and the activity streak, and it is a useful side-by-side
against the new pipeline.

## The rule this phase earned

**Check code that operates on a PARTIAL view of its input has now failed three
times in one phase. Future check code must either operate on whole-name input,
or carry a test asserting the check fires on a case where the partial view
would have missed it.**

The three, all the same category and none of them a coincidence:

1. **`jd_sections._match_label`** tested `phrase in candidate` — a bare
   substring anywhere in the line. `"Competitive salary and free snacks."`
   became a boilerplate *header* via "salary", and `"We are an equal
   opportunity employer."` another. A false header silently relabels everything
   below it and shifts every downstream weight. This is the exact failure the
   module was written to prevent, and the matcher had the hole.
2. **`canonicalise.normalise`** singularised only the FINAL token, so
   `"Kubernetes"` became `kubernete` while `"Kubernetes operations"` became
   `kubernetes operation`. The same word compared unequal depending on its
   position; containment silently stopped firing and only a lucky bare-cosine
   hit merged the pair. Found by a live run, not by a unit test.
3. **`jd_extract.verify_spans`** required the skill name to be a literal
   substring of its span, and imposed a 12-character span floor. On the long
   fixture it reported **8 hallucinations of which zero were inventions** — four
   legitimate extractions out of coordinated compounds, four one-word
   competency lines — and dropped eight real skills while doing it.

**AND: an edit that describes a partial change must be staged and verified as
a partial change (`git add -p` or equivalent). Staging the whole file after a
partial edit re-introduces the same mismatch on the write side.**

That clause was added because the pattern immediately produced a **fourth
instance, in a different medium**. `docs/decisions.md` was edited with an
append (`cat >>`) and staged with `git add <file>`, which stages the whole
file — so two pre-existing hunks belonging to the Phase 6 work (checkpoint-5
table rows, a suite-state update) went into an Arena commit. The surgical
stage-HEAD-plus-append technique had already been applied to `models.py` and
`api.ts` because the problem was *predicted* there, and then was not applied to
a file where it had not been predicted. Caught on verification and amended; the
commit now carries one hunk. Partial edit, whole-file write, silent mismatch —
same category, different verb.

The shared shape across all four: **an operation reading or writing part of its
subject succeeds against the whole, and the code's own self-report describes
exactly what it is doing while the doing is wrong.** In case 3 the arithmetic
was honest and the conclusion was garbage.

A related instance in the same phase, different category but the same lesson
about honest self-reports: `weighting`'s `section_base.required` was set to
1.00, equal to `max_weight`, so every required skill clamped and four of five
signals could not move the output. The per-signal breakdown still reconciled to
the stored weight, so the explainability check passed while every explained
weight was identical. **Being able to explain a number is not the same as the
number being informative** — §17.0b's "a prediction is evidence only with a
named mechanism" has a corollary: the mechanism must also be live.
`test_arena_weighting.py::TestEachSignalCanMoveTheFinalWeight` now asserts, per
signal, that there is an input where changing only that signal moves the FINAL
weight by ≥ 0.02. Verified by reintroducing the defect: four assertions fire,
two of which no previous test caught.

## Pre-registered, before any JD was measured

- **Canonicalisation** is a four-stage cascade, not a threshold — measured, the
  SAME/SIBLING bands overlap and no single threshold delivers recall at zero
  false merges. Bare cosine ≥ 0.86 decides; [0.80, 0.86) is surfaced to the
  user as suggestions defaulting to NOT merged.
- **Context enrichment was WITHDRAWN** as a decision branch: under template
  phrasing (adjacent bullets sharing a sentence shape, i.e. how JD bullet lists
  are actually written) it reaches a 92% false-merge rate at 0.76, merging
  PostgreSQL with MySQL. Kept as a shadow metric that decides nothing.
- **Cluster coherence** ≥ 0.64 mean pairwise cosine per parent, ≥ 80% of
  parents. Escalation to LLM clustering happens only on failure, with the
  failing numbers reported. It has already failed on the long fixture (20% and
  40% across two runs) and has NOT been silently switched.
- **Node budget** keyed on post-canonicalisation mention count, not word count:
  a short JD honestly yielding 2–4 parents is a PASS. A vague JD producing 8
  confident invented parents is a HARD FAIL, precisely because it clears the
  structural bar.

## Retraction

An earlier report in this phase claimed "1,641 postings scanned, zero meet
either threshold." **Withdrawn.** A helper script had been named `select.py`,
which shadowed Python's stdlib `select` and broke `subprocess`; the run measured
nothing. Re-run clean over 1,983 postings on 13 boards: minimum 506 words,
nothing under 400, minimum specificity 0.41. Recorded here with the mechanism
named rather than the number quietly updated (§17.16).

## Latency target: the flat 15s is SUPERSEDED BY MEASUREMENT

The original prompt pre-registered `extraction latency < 15s, hard fail > 45s`.
That was the right number to pre-register and the wrong number to hold to after
measurement, so it is marked superseded rather than quietly missed (§17.16).

| JD words | target | hard fail |
|---|---|---|
| < 500 | < 15s | > 30s |
| 500 – 1500 | < 25s | > 45s |
| > 1500 | < 45s | > 75s |

**Mechanism, named:** extraction on a 3,487-word posting runs 26.9–38.8s. The
cost is **Gemini 2.5 Flash's reasoning phase, which scales with input and task
complexity — not with output.** Output was tested directly and ruled out: capping
the span quote cut response volume 28% and bought 1% latency. Neither remaining
lever reaches 15s either — dropping the cluster-naming call saves 5–10s, running
it async hides the same 5–10s.

**Rejected, with reasons:** *chunking the JD* reintroduces the whole class of
lost-context-across-a-boundary defects for a module that does not need them;
*changing the model* forks the LLM story — `gemini-2.5-flash` is pinned across
this codebase and an Arena-only fork has no owner for keeping it current. Both
are out of Phase A scope.

**Honest residual:** if a real posting takes 75s the module is unusable at that
length, and relaxing a number on paper does not fix that. At ~60s across three
runs this is accepted; at ~90s it is back to change-the-model or chunk, neither
of which is Phase A work.

## Acceptance protocol: n = 3 runs per JD, pass rule pinned before the run

Three of four machine-scorable criteria were observed flipping between pass and
hard fail on **identical input**: latency 32.4–54.5s, invented 0–12 (hard fail
is ≥ 2), parent nodes 9–10 (hard fail > 9), cluster coherence 20–40%. A single
pass cannot decide pass/fail, so it is no longer asked to.

Every criterion is reported as **median and (min, max)** — never a point
estimate. A criterion that passes at median while hard-failing at max is a
different signal from one that passes on all three runs, and collapsing them
into "passed" is what this protocol exists to prevent.

**Pass rule, pinned before any number was seen:**

| verdict | condition |
|---|---|
| PASS | median meets target **and** no run is in hard-fail |
| HARD FAIL | any run is in hard-fail |
| MISS | median misses target, no run in hard-fail |

Median because a coin-flip criterion should not be decided by one toss;
hard-fail-on-max because a failure mode that fires even once is one users will
hit. A run that fails with a rate-limit error is **discarded and re-run**, not
counted as a failure — the criteria measure extraction, not the free tier.

Implemented in `scripts/arena_extraction_report.py` (`LATENCY_TIERS`,
`RUNS_PER_JD`, `verdict`, `measure_repeated`). One trap found by reading the
idempotency key rather than by seeing three identical numbers: `graph_build` is
idempotent on `(user_id, jd_hash, extractor_version)`, so repeated runs would
have been cache hits — one run reported three times, which is exactly what three
identical numbers would have looked like. `measure_repeated` uses a fresh user
per run.

## Extraction: short verbatim quote, not a whole sentence

Shipped as an **extraction-quality** change; the latency hypothesis that
motivated trying it is recorded as dead. Measured over two runs per variant on
the long fixture: accepted mentions 33 → 49, inventions on the long JD 12,0 →
3,2, inventions on the vague JD 0 → 0 (the guard did **not** weaken), mean span
17.1w → 4.2w. `SPAN_MAX_WORDS = 8`, fixed at the value the comparison was run
at and deliberately not swept against the acceptance fixtures. No toggle: the
whole-sentence variant is deleted, because a flag leaves two extractors alive
and one of them is worse.

## Free-tier rate limits: MEASURED, superseding the Phase 0 estimates

Both Phase 0 figures came from secondary sources because **both providers'
official rate-limit pages are account-gated** — Google's publishes no per-model
table and points at AI Studio; Groq's points at `/settings/limits`. The
estimates were reported with their confidence stated. One of them was wrong by
**10x**, and it was wrong in the direction that made the module look feasible.

Mechanism, stated so the lesson transfers: **secondary-source averaging is
unreliable at 10x scale, and the response headers are the authoritative signal
for the numbers that actually matter.** When sources disagreed on Gemini's RPD
(250 vs 500 vs 1,500, with one claiming a December-2025 cut to "20-50 in some
configurations"), the low outlier was the true one and averaging discarded it.
Read the headers. They cost one unit of the thing being measured and they are
not opinions.

### Groq — measured 2026-09-03T13:45:30Z, response headers verbatim

Measured against **`openai/gpt-oss-20b`**, not `llama-3.3-70b-versatile`.
The latter is decommissioned (KI-4) and a `404 model_not_found` **short-circuits
before rate-limit accounting**, so it returns no rate-limit headers at all — the
originally specified probe produced a null, not a measurement. Groq's limits are
per-model, so this measures a candidate replacement, which is the figure a
replacement decision would need anyway.

```
HTTP/2 200
x-ratelimit-limit-requests:      1000
x-ratelimit-limit-tokens:        8000
x-ratelimit-remaining-requests:  999
x-ratelimit-remaining-tokens:    7923
x-ratelimit-reset-requests:      1m26.4s
x-ratelimit-reset-tokens:        577ms
```

**Which axis each limit is on, derived rather than assumed** — the header names
say `requests` and `tokens` but not the window, and guessing the window is how a
10x error happens twice:

| header | used | reset | implied refill | window |
|---|---|---|---|---|
| `limit-requests` 1000 | 1 | 86.4s | 86400 / 86.4 = **1000/day** | **RPD** |
| `limit-tokens` 8000 | 77 | 0.577s | 77 / 0.577 x 60 = **8007/min** | **TPM** |

Both derivations reproduce the round number in the header, which is the check on
the interpretation. So: **1,000 requests/day, 8,000 tokens/minute.**

Two properties worth keeping:

- **It is a leaky bucket, not a midnight cliff.** Requests refill continuously
  at one per 86.4s. That is a materially different failure shape from Gemini's
  hard daily cap: a Groq-backed caller degrades to a rate rather than stopping.
- **8,000 TPM is genuinely tight**, and it confirms the Phase 0 reasoning that
  put Gemini on extraction. The long fixture's extraction call is ~3,000+ tokens
  in one request; two such calls inside a minute exceed the bucket. This is an
  independent, measured reason to keep the large-context call on Gemini that has
  nothing to do with provider preference.

### Gemini 2.5 Flash — measured by observed exhaustion, ~20-25 requests/day

No header equivalent was captured; the figure is bounded by two independent
429s:

| date | successful calls before 429 | evidence |
|---|---|---|
| 2026-09-02 | ~24 | 4 fixtures x 3 runs x 2 calls = 24, then fixture 5 raised |
| 2026-09-03 | 20 | 3 fixtures x 3 runs x 2 = 18, plus 2 isolated probes |

Consistent at **~20-25 requests/day**. Reported as a bounded observation rather
than a figure, because exhaustion establishes a ceiling, not the ceiling's exact
value, and no header stated it.

### Superseded, originals kept (§17.16)

| figure | Phase 0 estimate | measured | error |
|---|---|---|---|
| Gemini RPD | 250 (medium confidence, sources disagreed) | **~20-25** | **10x optimistic** |
| Gemini TPM | 250,000 | not measured | — |
| Groq RPD | 1,000 (low confidence) | **1,000** | correct |
| Groq TPM | 6,000 (low confidence, 6k vs 12k in sources) | **8,000** | ~33% pessimistic |
| Groq TPD | ~100,000 (unconfirmed) | **no such header exists** | not a real axis |

The Phase 0 estimates are NOT overwritten above; they stand in the left column
with the measured values beside them. Notably the *low-confidence* Groq figures
were nearly right and the *medium-confidence* Gemini figure was the one that was
badly wrong — the stated confidence did not track the actual error.

### One rationale this falsifies, for a decision that nonetheless stands

The two-day acceptance protocol was chosen over "use Groq as a second budget"
for three reasons. **Reason 1 is now dead:** it argued that Groq's ceiling was
known only from the same class of secondary sources that got Gemini wrong by
10x, so betting the protocol on it would repeat the failure. That objection is
answered — the ceiling is now measured from authoritative headers, not
estimated.

**The decision stands on reasons 2 and 3, either of which is sufficient:**
swapping providers mid-protocol means two Gemini runs and one Groq run, which is
not n=3 of one instrument; and two-day execution preserves the instrument while
spending nothing new. Recorded because a decision surviving on fewer reasons
than it was made with is worth knowing, and because the dead reason should not
be re-cited later as if it still held.

Provider ordering, bank-fill economics and cold-session viability remain **filed
for Phase B and deliberately unchanged here**, regardless of what these numbers
imply about them.

### Corollary to §17.16 — a confidence label on an UNMEASURED figure does not discriminate

Filed as an instance, not as a rule change.

The Phase 0 rate-limit estimates carried explicit confidence labels. When the
measurements landed, **the labels did not track the error**:

| figure | label | error |
|---|---|---|
| Gemini RPD 250 | *medium* confidence | **wrong by 10x** |
| Groq RPD 1,000 | *low* confidence | exact |
| Groq TPM 6,000 | *low* confidence | 33% pessimistic |
| Groq TPD ~100,000 | *low* confidence, "unconfirmed" | not a real axis at all |

The medium-confidence figure was the catastrophically wrong one and the three
low-confidence figures were nearly right. The label was assigned from *how many
secondary sources agreed*, which turned out to measure source-copying rather
than truth — the 250 RPD figure appeared in several places because those places
were copying each other, and the lone dissenting source ("20-50 in some
configurations") was the accurate one.

**The lesson is not "be more pessimistic on medium confidence."** It is that a
confidence label attached to secondary-source aggregation carries little
information and must not be treated as a substitute for measurement. Where the
number matters, read it from the system. Recorded here so that the next time a
confidence label is reached for on an unmeasured figure, this instance is on
file rather than the habit being repeated with more careful adjectives.

### Phase 0 provider ordering: upgraded from ESTIMATION-BASED to MEASUREMENT-CONFIRMED

Phase 0 put Gemini on the large-context extraction call and Groq on the small
naming call, reasoning that Groq's TPM ceiling could not hold a long JD plus a
structured response. That reasoning rested on an **estimated** 6,000 TPM from
secondary sources.

It is now **measured at 8,000 TPM** (2026-09-03, response headers). The
long-fixture extraction call is ~3,000+ tokens in a single request, so two such
calls inside one minute exceed the bucket. The conclusion is unchanged and the
basis is stronger: this is a rare upgrade from "we chose correctly" to "we can
show why the alternative fails", and it holds independently of any preference
between providers.

Recorded because the ordering decision will be re-opened in Phase B (see the
backlog note below) and whoever re-opens it should know which parts rest on
measurement and which do not.

### Phase B backlog — quota exhaustion is a categorically different PRODUCT on each provider

Not a Phase A item. Filed because it is a design input, not an observation.

The two providers do not merely have different ceilings; they **fail in
different shapes**, and from a user's seat those are different products:

| | Gemini 2.5 Flash | Groq (`openai/gpt-oss-20b`) |
|---|---|---|
| ceiling | ~20-25 requests/day (measured by exhaustion) | 1,000 requests/day (header) |
| shape | **cliff** — a hard daily cap | **leaky bucket** — refills 1 request / 86.4s |
| user experience at the limit | the session is *stuck until the cap resets*; nothing the user does helps | the session *slows to a rate* and keeps making progress |

A mid-interview quota exhaustion on Gemini ends the interview. On Groq it makes
the next question take 86 seconds. Phase B needs a real answer for that state,
and "surface the 429" is not one — it is the difference between "come back
tomorrow" and "this is slow right now".

Two further Phase B inputs from the same measurements, filed and deliberately
NOT acted on in Phase A:

- **Bank-fill economics.** Phase 0 concluded "warm bank ~3 calls, ~80 sessions
  per day." At the measured ceiling a warm-bank session is 12-15% of the daily
  budget, not 1.2%. The design survives, but the bank must reach steady-state
  hit rate far sooner than the original arithmetic assumed.
- **The ordering question has changed shape.** With a 40x request-ceiling
  asymmetry, Phase B's question is not "which provider is primary" but "do the
  bank-fill economics move to a Groq-first model given that asymmetry" —
  bounded by the 8,000 TPM finding above, which still rules Groq out for the
  long-context call. That is a different question from the one Phase 0 answered.
- **"A 20-question mixed session fits."** True at 250 RPD, false at 25. A
  cold-bank session consumes an entire user-day of budget.

## Latency: length tiering RETIRED, superseded by its own first measurement (§17.16)

Two superseded targets now, both kept rather than overwritten:

| generation | target | fate |
|---|---|---|
| original, Phase 0 | flat `< 15s`, fail `> 45s` | superseded 2026-09-02 — extrapolated from no data |
| tiered, 2026-09-02 | `<500w: <15s` / `500-1500w: <25s` / `>1500w: <45s` | **superseded 2026-09-03 — falsified by measurement** |
| **current** | **flat `< 30s`, hard fail `> 60s`, all lengths** | derived from 9 observations |

**What falsified the tiers.** Measured medians across 3 runs each:

| fixture | words | latency | against its own tier |
|---|---:|---:|---|
| short | 80 | 17.4s | MISS (`<15s`) |
| foundry-fde | 452 | **45.6s** | **HARD FAIL** (`>30s`) |
| long | 3487 | 37.2s | ok (`<45s`) |

**A 452-word posting is slower than a 3,487-word one.** Length does not predict
cost, so a schedule keyed on length measures the wrong variable — and the
`<500w` band had itself been extrapolated from a single 54-word smoke test,
which is one data point stretched across an order of magnitude. Both errors
were mine and both are marked rather than quietly replaced.

**Hypothesis for the real driver, named and NOT measured** — so it stays a
hypothesis (§17.0b): Gemini 2.5 Flash's reasoning phase scales with task
AMBIGUITY rather than input size. The 452-word posting is prose-heavy with
implicit, judgement-requiring skills ("Confidence in troubleshooting complex
systems issues independently"); the 3,487-word one is a structured federal
announcement, mostly boilerplate, with explicit skill mentions. Testing this
needs thinking-token counts, which the OpenAI-compatible endpoint does not
return. Recorded as the next thing to measure, not as a finding.

**Residual, stated:** 9 observations across 3 fixtures is a thin basis for any
band, and §17.0 is explicit that a threshold set from a small sample is
provisional. `< 30s / > 60s` discriminates (a regression to 70s hard-fails) and
reports the module honestly as slower than wanted rather than broken. It should
be re-derived when there are more fixtures — and NOT by sweeping against the
held-out set.

## Aggregation defect found on real data: run 1's node budget applied to all runs

`print_aggregate` judged every run's parent count against **run 1's** node
budget. The budget is keyed on that run's own post-canonicalisation mention
count, so a run which legitimately extracted more mentions earns a wider parent
band — and was being judged against a band that was never its own.

It changed a verdict: `short.txt` run 3 produced 6 parents and was reported
**HARD FAIL** against run 1's 2-4 band. That may have been a false failure.
`long.txt` run 3 (10 parents) fails regardless, since 10 exceeds the widest band.

Fixed before the re-run, because measuring against a broken aggregator makes it
impossible to tell whether a new hard-fail is real. The criterion is now
evaluated per run against that run's own band, and the table prints the bands
when they differ across runs rather than silently picking one.

### Gemini RPD is EXACTLY 20 — upgraded from a bounded observation to the authoritative figure

2026-09-03. The earlier entry recorded "~20-25 requests/day, bounded by two
observed 429s" and said plainly that exhaustion establishes a ceiling rather
than its value. The value is now stated by the API itself:

```
Quota exceeded for metric:
  generativelanguage.googleapis.com/generate_content_free_tier_requests
limit: 20
model: gemini-2.5-flash
quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier
```

**20 requests per day, per project, per model.** The Phase 0 estimate was 250 —
wrong by 12.5x, not 10x.

Two details worth keeping:

- **The 429 advertises a misleading `retryDelay` of 19-57 seconds** for what is
  a DAILY cap. A naive backoff-and-retry loop would spin against it all day.
  The protocol's discard-and-retry (2 attempts) honoured the delay, failed, and
  correctly reported the fixture as NOT MEASURED.
- **The provider pin proved itself immediately.** With Groq now working, an
  unpinned run would have fallen through silently and produced a
  mixed-provider "n=3". Pinned, the raised error was Gemini's own and therefore
  the informative one — KI-1's misattribution did not occur, because there was
  no second provider to mis-blame.

**What 20 RPD means for the measurement.** One fixture at n=3 is 6 calls; five
fixtures is 30. So a complete acceptance run is a **minimum of two days** with
zero development calls in between. The two-day plan is confirmed, now on an
authoritative number rather than an estimate.

**What it means for the product, filed for Phase B.** At 20 RPD a single
cold-bank interview session consumes an entire user-day of budget on Gemini.
Groq's measured 1,000 RPD is 50x that. The Phase B ordering question is no
longer "which provider is primary" but "is Gemini viable as a primary at all",
bounded by the 8,000 TPM finding that keeps it on the long-context call.

## Phase A acceptance measurement — COMPLETE, 5 fixtures x 3 runs, 2026-09-03

Pinned to **Groq (`openai/gpt-oss-120b`)**, not the shipped Gemini-first path.
Gemini's measured 20 requests/day cannot carry a 30-call protocol; Groq's 1,000
can. **Caveat, load-bearing: extraction QUALITY is the model-dependent part, so
criterion 1 here is Groq's accuracy, not the shipped path's.** Structural
criteria are provider-independent and do transfer.

| fixture | words | skills | parents | invented | latency | verdict |
|---|---:|---:|---:|---:|---:|---|
| short | 80 | 14 `(11-16)` | 5 `(4-6)` | **0** | 12.9s | **PASS** |
| foundry-fde | 452 | 17 `(15-18)` | 6 | **0** | 7.8s | MISS |
| vague | 254 | 19 `(15-21)` | 6 | **0** | 29.7s | MISS |
| target-role | 324 | 22 `(19-24)` | 7 `(7-8)` | **0** | 31.8s | **HARD FAIL** |
| long | 3487 | 19 `(18-23)` | 7 | **0** | 58.7s | **HARD FAIL** |

### What the fixes bought

- **`invented` is 0 on every fixture and every run.** It was 0-12 on
  foundry-fde before. The taxonomy fix (nominalisations reclassified as
  `unverified` rather than hallucinations, with a stem anchor keeping unrelated
  names out) closed criterion 2 completely. `unverified` and `paraphrase` rates
  both came back at 0% on Groq, which is itself informative: this model quotes
  literally rather than nominalising, so the class the fix was built for did not
  even arise here. It will on Gemini.
- **The `short.txt` parent-count HARD FAIL was indeed a false failure.** With
  per-run bands it now reads `median 5 (min 4, max 6) ok`, bands
  `[(3,5),(5,7),(3,5)]` — run 2 legitimately earned a wider band.
- **Latency improved sharply** where it was worst: foundry-fde 45.6s -> 7.8s.
- **The fragment filter now fires**, and skill lists are materially cleaner
  (foundry-fde 36 skills of which ~16 were junk, now 17).

### The two failures are BOTH clustering, not extraction

1. **`max children per parent` MISSes on four of five fixtures** — median 7-8
   against a 2-5 target, hard fail >8. Every fixture sits at or just under the
   cap, which is the shape of a clusterer producing one oversized group rather
   than several balanced ones.
2. **The coherence gate failed on ALL FIVE fixtures** (medians 33-75% against
   an 80% bar). Per the pre-registration this means escalation to LLM
   clustering is warranted — reported, not silently switched.

`target-role` hard-failed on parent count (8 on run 1, band max 7) and `long`
on latency (65.2s on run 2, bar 60s). Neither is an extraction defect.

**So the honest diagnosis: extraction is now in reasonable shape and CLUSTERING
is the weak component.** That is a different conclusion from the one the first
run supported, and it points at exactly one pre-registered next action rather
than at another extractor iteration.

### Held out no longer

`target-role.txt` has now been measured and is spent. Its 24-skill list is
dominated by genuine ML vocabulary (PyTorch, TensorFlow, recommendation
systems, ML pipelines, model training, feature development, hypothesis testing,
regression analysis) with four degree fields (Computer Science, Data Science,
Mathematics, Statistics) that the filter deliberately does not remove — see the
`is_fragment` comment for why that trade is the right direction.

### Read the output, not the counts (§17.32)

The vague fixture returned `crypto`, `betting`, `gaming`, `fintech` — which
looked like invented domain inference against a 0-invented count. Checked
against the fixture: all four are in its final requirements line, *"Experience
in crypto, betting, gaming, trading, fintech, or similar fast-paced platforms
is a strong plus."* The suspicion was wrong and the guard was right. **The vague
JD degraded HONESTLY**: 19 skills all traceable to the document, 6 parents, zero
inventions — which is the PASS condition that case was written to test.

## LLM clustering escalation — RUN, and Phase A CLOSES ON THE RECORDED FAILURE

The pre-registered escalation (§7.3 / `min_coherent_parent_fraction`) fired on
its trigger, once, and was measured under the same protocol: 5 fixtures x 3
runs, Groq-pinned, same table, same PASS/MISS/HARD FAIL rule, prompt pinned by
hash before any fixture ran under it.

### The table

| fixture | words | skills | parents | max children | coherence | latency | verdict |
|---|---:|---:|---:|---:|---:|---:|---|
| foundry-fde | 452 | 21 | 6 `(5-6)` ok | **5** ok | 67% | 19.3s ok | **PASS** |
| short | 80 | 10 | 4 `(3-4)` ok | **3** ok | 0% | 18.2s ok | **PASS** |
| target-role | 324 | 19 | 5 `(4-6)` ok | **5** ok | 75% | 30.9s MISS | MISS |
| vague | 254 | 26 | 5 ok | 7 MISS | 40% | 20.4s ok | MISS |
| long | 3487 | — | — | — | — | — | **NOT MEASURED** |

`hallucinated skills` 0 and `LLM calls` 2 on every measured fixture and run.
`clustering: invented` and `clustering: unassigned` were **0 everywhere** — the
model respected the skill set completely, inventing nothing and omitting
nothing across 12 runs.

### What moved, against the deterministic baseline

| | deterministic | LLM clustering |
|---|---|---|
| HARD FAILs | **2** (target-role parents, long latency) | **0** among measured |
| `max children` MISS | **4 of 5** | **1 of 4** |
| target-role parents | 7 `(7-8)` **HARD FAIL** | 5 `(4-6)` ok |
| verdicts | 1 PASS / 2 MISS / 2 HARD FAIL | 2 PASS / 2 MISS / 1 NOT MEASURED |

Per-fixture `max children`: foundry-fde 7 -> 5, short 4 -> 3, target-role 8 ->
5, vague 7 -> 7. That was the criterion the escalation most directly targeted
and it moved on three of four.

Coherence moved in **both** directions and is the honest disappointment:
foundry-fde 50% -> 67%, target-role 50% -> 75%, vague 50% -> 40%, short 50% ->
**0%**. The short fixture is the interesting one: 10 mostly non-technical
marketing skills split into 4 groups of 2-3, and NOT ONE parent cleared the
0.64 cosine bar. That is a plausible sign the coherence threshold — derived
from a reference set of *technical* skill-name pairs — does not transfer to
non-technical vocabularies. It is a bar question, and it is filed rather than
adjusted.

### Why `long.txt` could not be measured

Groq returned `400 json_validate_failed` with **`'failed_generation': ''`** —
the model generated **nothing**, on the largest skill list of the five. Not a
JSON syntax defect: an empty generation that then failed JSON validation. Same
class as the empty-content risk that disqualified `gpt-oss-20b` for streaming
and that requirement 4 of the KI-4 qualification was written to catch, now
appearing on a reasoning model under JSON mode with a large input.

**Not fixed here.** The stop condition for this session says a prompt-shape
defect is repaired by a NEW PINNED PROMPT, not by an in-flight retry with
looser parsing, and the prompt must not be swept against fixture output. It
occurred on exactly 1 fixture of 5, which is *at* the stop threshold ("more
than 1") and not over it, so the run continued and the fixture is reported
NOT MEASURED — which is a true statement where a salvaged number would not be.

The rate-limit classifier behaved correctly: it did not mistake a 400 for a 429
and did not retry into it.

### VERDICT: FAIL at the pre-registered bar. Phase A closes here.

Two MISSes and one unmeasurable fixture is not a pass, and a fixture that could
not be run is not a fixture that passed. The pre-registered response has fired
once; per the rules agreed before this session, there is no second escalation
and the bar is not adjusted because numbers came in close.

Stated plainly because it would be easy to spin: the escalation **worked on
what it targeted** — both hard fails cleared, the max-children criterion moved
on three of four fixtures, and the model never invented or dropped a skill. It
did not clear the bar, and the remaining gaps are one empty-generation defect
and two marginal misses (target-role latency 30.9s against a 30s bar; vague
max-children 7 against a 2-5 target).

### Held-out limitation of THIS measurement, recorded as a limitation

All five fixtures were visible when this clustering prompt was written. The
prompt was deliberately not swept against their output — it was pinned by hash
before any fixture ran under it, and the hash test is hardcoded so an edit
cannot pass silently. But "not tuned" is a statement about process, not a
property the numbers can demonstrate. **A clustering design authored after its
evaluation set became visible cannot claim general validity from that set**, and
this table should be read as evidence about these five graphs rather than about
JD clustering in general. A sixth, unseen fixture is the only thing that would
settle it, and adding one is a Phase B decision, not this session's.

### PHASE A CLOSE-OUT — read this first

**Phase A closed on measurement, not on judgement.** The pre-registered
acceptance bar was set before any job description was processed, the
pre-registered escalation fired once on its own trigger, and the result was a
recorded FAIL: two MISSes and one fixture that could not be measured, against a
bar that was not moved to accommodate them. The escalation did work on what it
targeted — both HARD FAILs cleared, `max children per parent` moved on three of
four fixtures, and across twelve runs the clusterer invented no skill and
dropped none — and it still did not clear the bar. Both statements are true and
neither cancels the other. Two temptations are named in the record rather than
left implicit, because naming where the pull was is the only way the next person
knows where to look: **adjusting the latency bar**, which `target-role` missed
by 0.9 seconds against a threshold I had myself set from nine observations and
marked provisional (reading "provisional" as "adjustable" would have converted a
MISS into a PASS by editing the ruler after seeing the measurement), and
**patching the `long.txt` prompt**, which looks like a one-line `max_tokens` fix
precisely because the fixture it would rescue is already known. One defect in
the session's own work was caught in flight and is recorded: the prompt pin
originally computed its expected digest from the constant at module load, so it
compared the prompt's hash to its own hash and **could never fail** — the same
class of defect as a check that certifies the wrong property. The digest is now
a literal and the pin was demonstrated failing against a mutated prompt before
being trusted. Seven items are filed forward, below. Phase A ships nothing that
claims to have passed.

### Phase B inherits seven open items

1. **Extractor-on-Gemini criterion-1 quality.** Both acceptance runs measured
   Groq's extraction accuracy, not the shipped Gemini-first path's. 20 RPD
   makes a Gemini run a two-day exercise.
2. **Bar re-examination**, with this run's numbers as its evidence: `2-5`
   children with `5-9` parents implies 10-45 leaves while the extractor
   honestly produces 10-26 skills; and the 0.64 coherence threshold was derived
   from technical skill-name pairs and returned 0% on a non-technical fixture.
3. **Quota exhaustion is a different product per provider** — Gemini cliffs at
   20 RPD, Groq throttles at 1 request/86.4s. "Surface the 429" is not an answer.
4. **Bank-fill economics** at the real ceiling: a warm-bank session is 12-15% of
   a Gemini day, not 1.2%.
5. **Provider ordering under measured numbers**: 1,000 RPD vs 20 is a 40x
   asymmetry, bounded by the 8,000 TPM finding that keeps the long-context call
   on Gemini.
6. **`long.txt` empty-generation on Groq — a known Groq failure mode on large
   inputs, not a novel discovery.** The clustering call on the largest skill set
   returned `400 json_validate_failed` with `failed_generation: ''`: the model
   produced nothing, so there was no JSON to validate. **The same class already
   disqualified `openai/gpt-oss-20b`** during the KI-4 replacement
   qualification, where it yielded zero content deltas when streaming, and it is
   why requirement 4 of that qualification (non-empty content at
   `max_tokens=200`) exists at all. So this is a third sighting of one behaviour
   — reasoning models under output pressure returning empty content — not a new
   problem.
   **Fixed in Phase B by a NEW PINNED PROMPT, never by a retry loop.** A retry
   with looser parsing would report a number for a grouping the model did not
   produce, and the fixture is currently reported NOT MEASURED precisely because
   that is the true statement. Whatever prompt replaces it gets pinned by a
   hardcoded digest before any fixture runs under it, exactly as this one was.
7. **The 0.64 coherence threshold does not transfer to non-technical skill
   sets — a threshold-domain-generality question, filed and NOT adjusted.**
   Evidence: the `short` fixture returned **0% coherence** — not one parent of
   four cleared the bar — on 10 mostly non-technical marketing skills grouped
   2-3 per parent. The threshold was derived in Phase 0 from a hand-labelled
   reference set of **technical** skill-name pairs, where 0.64 was the measured
   SIBLING/UNRELATED separation point (SIBLING min 0.639, UNRELATED max 0.636).
   Nothing in that derivation claimed it generalised to marketing, operations or
   commercial vocabularies, and this run is the first evidence that it does not.
   The honest reading is that the *instrument* is domain-scoped, not that these
   graphs were incoherent. Adjusting it now would be tuning a threshold against
   the fixture that exposed it (§17.27); it needs its own reference set per
   domain, or an explicit statement that the metric applies only to technical
   graphs.

---

# Voice migration — Phase 2 closed, and a phase reordering (§17.16)

## The wired-gate test moves from Phase 3 to Phase 4, deliberately

The plan put the "installed and wired" gate in Phase 3, with STT. That
ordering cannot work as specified, and the reason is worth recording so the
next reader does not wonder why the gate is not with the phase that introduced
the thing it gates.

**A real wired-gate test needs real speech audio, and the repository has none.**
The only audio file in the tree was a 0-byte `backend/test.mp3` referenced
nowhere (deleted in Phase 2). Speech cannot be synthesised without a working
TTS, and working TTS is Phase 4. So the fixture the test needs is produced by
the phase *after* the one the test was assigned to.

Resolved by splitting the assertion in two, because "installed and wired" and
"transcribes real speech" were always two different claims sharing one test:

- **Phase 3** ships a tone-based gate: a 1-second 16 kHz sine WAV, generated
  with stdlib `wave`. It asserts imports resolve, the endpoint is reachable, and
  the response is **not 501**. That is all Phase 3 was ever supposed to prove.
  A tone correctly produces an empty transcript, and `oratory.analyze` correctly
  returns 400 "No speech detected" — both are the right answers for a tone, and
  neither is evidence about transcription quality.
- **Phase 4** commits a real-speech WAV, generated by the newly-working Kokoro
  TTS, to `tests/fixtures/voice/` with a provenance line naming the engine and
  version. The real gate lands here and asserts a **round trip**: Kokoro audio
  through the shared STT service yields a non-empty transcript whose word count
  is within ±1 of the spoken phrase. **Not string equality** — Whisper on
  Kokoro on CPU is not deterministic, and an exact-match assertion would be a
  flaky test pretending to be a strict one.

The bootstrap is the point: Phase 4's output becomes Phase 3's test input, so
the gate has to follow the generator.

## Phase 2 outcome

Merged the four voice packages from the optional `requirements-voice.txt` into
`requirements.txt` and deleted the extras file. **16 packages added, 0 existing
pins changed** (`starlette`, `fastapi`, `pydantic`, `numpy`, `onnxruntime`,
`protobuf`, `SQLAlchemy`, `tokenizers` all verified byte-identical before and
after) and `pip check` clean — the §17.34 `pip install mcp` incident did not
recur, and it was checked rather than assumed.

All five previously-broken voice paths now respond. See
`docs/voice-known-issues.md` for the before/after table, plus four filed
defects: two Communication Gym issues found by the baseline and deliberately
not fixed here (silent TTS degradation, and a listening test that leaks its
passage through the fallback), one resolved (`piper-tts==1.2.0` was never
installable on Python 3.12), and one carried to Phase 5 (the STT model still
downloads 142 MB at runtime — KI-2's defect class, now confirmed for a second
model).

## "No new dependencies" — what the rule means, resolved on evidence

Written down because the next ambiguity should be resolved from a record rather
than by asking.

The constraint reads **no new libraries entering the dependency graph.** It
exists to prevent "let me also add Vosk for flexibility" — breadth acquired
speculatively. It does **not** govern version changes to libraries already
pinned.

Phase 2 hit the ambiguity: `piper-tts==1.2.0` was unresolvable on Python 3.12
and the merge failed outright. Bumping to `1.7.0` is within scope, because the
same library at a version that exists for this runtime is not a new entrant —
and this particular bump *removed* a transitive dependency
(`piper-phonemize`), so the graph got smaller. Version bumps are governed by
the ordinary change discipline instead: pinned in one place, tested, and called
out in the commit message.

The alternative reading — drop Piper entirely — would have made Phase 4
Kokoro-only with no fallback. That is a **product** decision about what happens
when the primary TTS engine fails, not a scope decision, and it would need its
own case made. The bump is the boring correct answer.

## VKI-4 is the substantial finding of Phase 2, not a footnote

Phase 2's probe caused faster-whisper to fetch **142 MB** of weights at runtime.
That matters more than its filing suggests, for three reasons:

1. **It is a second instance of a defect class already filed.**
   `docs/arena-known-issues.md` KI-2 records exactly this for
   `bge-small-en-v1.5`. Two models, two modules, one mechanism.
2. **It was found the same way both times** — by a probe reaching the network in
   a design that says it should not need to. Not by reading the code, in either
   case.
3. **It means voice currently "works" only because a cache is warm.** Which is
   precisely the condition that hid KI-2 for as long as it did, now reproduced
   in a second module.

So **Phase 5 is not a small Dockerfile edit.** It closes two separately-filed
defects under one bake-at-build change, and when it lands its audit trail
should say so rather than treating the change as a formality. Recorded here
because the phase most likely to be rushed is the one that looks like plumbing.

## Phase 3 outcome, and a coverage gap it exposed

The verbatim STT configuration now lives in `app/services/voice/stt.py` and
both API call sites route through it; the 501 message constants moved to
`app/services/voice/` from `app/api/voice.py`, which was the wrong home for a
contract two API modules share.

**The gap worth naming: filler preservation had ZERO test coverage before this
phase.** `tests/` contained no test referencing Oratory, voice, or the filler
logic at all — the hard requirement rested entirely on four keyword arguments in
one endpoint, which is how the *other* endpoint came to be missing all four
without anything noticing. `tests/test_voice_stt.py` is the first test in this
repository that guards it, and the pin was verified to fail against a mutation
of each of the four settings individually before being trusted.
