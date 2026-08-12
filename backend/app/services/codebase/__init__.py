"""Codebase agent: repository ingestion, import graph, ranking, clustering,
code health. Makes zero calls to any language model -- enforced by
tests/test_jobs.py::test_zero_llm_calls_across_the_whole_pipeline, not by
convention.

## Cascade suppression -- a recurring defect shape in this package

Named here because it has now appeared five times in five unrelated modules,
and naming it is what lets a reviewer catch the sixth.

**Shape:** a value is computed correctly and then discarded downstream because
a *coarser* upstream check failed. The upstream failure is real; the discard is
not required by it. Signal that exists, is correct, and is actionable gets
thrown away -- and because the discard happens quietly, the surface above it
reports "unavailable" rather than "partly available", which reads to a user as
"nothing here" instead of "some of this is missing".

**Instances, chronologically:**

1. `_migrate_entry_priors` -- a `continue` meant E4's own migration never got a
   chance to correct rows already migrated under the older heuristic. The
   corrected value existed; the guard skipped it.
2. **G1 scorer scoping** -- rank rows were correct at one level and discarded by
   a query at another, mixing incompatible scales into one sort. The motivating
   bug for the entire Phase G rewrite.
3. **History timeout** (`ranking._collect_git_history`) -- an uncaught
   `TimeoutExpired` walked past the function's own `return None` "no history
   available" contract, so one slow `git log` cost the repo its entire ranking:
   no fan-in, no fan-out, no reading list.
4. **Rename detection** (same function) -- `--numstat` computed added/deleted
   line counts that the very next line discarded, at the cost of thousands of
   lazy blob fetches on a `--filter=blob:none` clone.
5. **Architecture axis gate** (`health_scoring.score_architecture_health`) --
   gated the whole axis on fan-in/fan-out, so a repo with complete cycle data
   for all 6,516 files, 828 of them inside real import cycles, reported
   Architecture Health as N/A. The axis's heaviest marker (weight 4.0) was
   fully computed and suppressed by a missing 3.0-weight one.

**The check, every time:** when an upstream failure causes a downstream
discard, ask whether the discard is *necessary* or merely *convenient*. In all
five cases so far it was merely convenient, and the fix was to narrow the guard
to the input actually required -- then declare what is missing rather than
withholding everything.

**Why it keeps happening:** the guards are all defensible in isolation. Each was
written to avoid reporting a number without its inputs -- the same instinct that
produced this package's exclude-don't-zero and evidence-gate discipline. The
failure is in scope, not intent: a guard sized to the *coarsest* input rather
than the *required* one. That is why it survives review; it looks like caution.

See docs/decisions.md for the per-decision record.
"""
