# Decision log

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

**Impact.** Ranking files by a constant would produce a confident-looking list
with nothing behind it. The axis reports N/A instead.

### C4 — The Architecture evidence gate is structural, not advisory
*2026-08-09 · active*

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
*2026-08-09 · **at risk***

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

| | Item | Status |
|---|---|---|
| G2 | Directory-cycle marker — Architecture Health cannot discriminate without it | **leading next change** |
| C5 | Promote churn spread to first-class eligibility | candidate |
| A2 | Co-change coupling, coverage ingestion, ownership | deferred |
| D5 | Calibration | blocked — no defect-labelled corpus |
| — | ESLint validation never re-run against subsystem output, which was HDBSCAN's justification | open |
| — | `codebase-agent-handoff.md` stops at K1; nothing covers health, deployment fixes, or the Overview restructure | open |
| H3 | `REPO_CLONE_ROOT` still defaults to an ephemeral path while the database is persistent | needs a mounted disk |
