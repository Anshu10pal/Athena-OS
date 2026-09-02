"""Phase A acceptance measurement: run the extraction pipeline over the JD
fixtures and print the pre-registered acceptance table.

Usage:
    venv/bin/python scripts/arena_extraction_report.py            # all fixtures
    venv/bin/python scripts/arena_extraction_report.py short.txt  # one fixture
    venv/bin/python scripts/arena_extraction_report.py --smoke    # one tiny JD, live model

Mirrors scripts/validate_ranking.py: a script rather than a test, because the
output is a table for a human to judge and two of the eight criteria
("skills correctly extracted", "user edits needed") are explicitly the
reviewer's judgement and cannot be asserted in CODE at all.

WHAT THIS SCRIPT WILL NOT DO
============================
It will not tune anything. It prints what happened, including failures, marked
against the thresholds that were pre-registered BEFORE any JD was measured (see
config/arena_extraction.yaml and docs/arena-canonicalisation.md). A criterion
that fails is reported as FAIL with the number that failed it. Adjusting a
threshold until a column turns green and reporting only the final number is the
specific thing this script exists to make impossible to do quietly.

Two of the five fixtures are HELD OUT and are the reviewer's own job
descriptions. The reference pair-set that designed the canonicalisation cascade
has been used and is spent as a validation instrument -- it now lives in
tests/test_arena_canonicalise.py as a regression pin-set. These fixtures are the
validation.

COSTS REAL QUOTA. Each fixture is two live model calls against a free tier with
a low daily request ceiling. Nothing here runs automatically or in CI.
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.db.database import Base  # noqa: E402
from app.db.models import ArenaMergeSuggestion, ArenaSkillNode, User  # noqa: E402
from app.services.arena import graph_build  # noqa: E402
from app.services.arena.config import load_config  # noqa: E402

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "arena_jds"

# The pre-registered acceptance criteria. Target and hard-fail, as agreed at the
# Phase 0 checkpoint. Structural bounds are read from the node budget, because
# the whole point of that budget is that a short JD is allowed fewer parents.
# Pre-registered acceptance criteria. Pinned at the Phase 0 checkpoint and
# amended once, by measurement, for latency -- see LATENCY_TIERS.
CRITERIA = """
PRE-REGISTERED ACCEPTANCE CRITERIA

  skills correctly extracted     target >= 85%   hard fail < 70%      [YOUR JUDGEMENT]
  hallucinated skills            target 0        hard fail >= 2       span absent, OR span
                                                                      does not support the
                                                                      skill name
  parent nodes                   per node budget (a short JD may honestly yield 2-4)
  children per parent            target 2-5      hard fail > 8
  duplicate nodes surviving      target 0        hard fail >= 2       [YOUR JUDGEMENT]
  user edits needed              target <= 3     hard fail > 8        [YOUR JUDGEMENT]
  extraction latency             TIERED BY JD LENGTH -- see below
  LLM calls per JD               target <= 2     hard fail > 4

  paraphrase rate                no target. A SIGNAL, reported per JD.
  mean span words                no target. A SIGNAL: the prompt asks for <= 8;
                                 a mean drifting toward sentence length means the
                                 model has stopped honouring it.

  A vague JD producing few nodes with low confidence is a PASS.
  A vague JD producing 8 confident invented parents is a HARD FAIL, precisely
  because it clears the structural bar.

LATENCY, TIERED -- the original flat "< 15s" is SUPERSEDED BY MEASUREMENT

  JD words        target      hard fail
  < 500           < 15s       > 30s
  500 - 1500      < 25s       > 45s
  > 1500          < 45s       > 75s

  Why: the flat 15s was pre-registered before any numbers existed, and it does
  not survive them. Measured on a 3,487-word posting, extraction alone runs
  26.9-38.8s. The cost is Gemini 2.5 Flash's REASONING phase, which scales with
  input and task complexity -- not with output, which was tested directly and
  ruled out (-28% output bought -1% latency). Neither of the other two levers
  reaches 15s either: dropping the naming call saves 5-10s, running it async
  hides the same 5-10s. Chunking the JD and swapping the model are both out of
  Phase A scope. So the target is relaxed with the mechanism named rather than
  held to and failed against (contract section 17.16).

  Honest residual: if a real posting takes 75s the module is unusable at that
  length, and relaxing a number on paper does not fix that. That is a
  change-the-model or chunk-the-input conversation, not a Phase A one.

REPRODUCIBILITY PROTOCOL -- n = 3 RUNS PER JD, PINNED BEFORE THE RUN

  Three of four criteria were observed flipping between pass and hard fail on
  IDENTICAL input: latency 32.4-54.5s, invented 0-12 (hard fail is >= 2),
  parents 9-10 (hard fail > 9), coherence 20-40%. A single pass cannot decide
  pass/fail, so it is not asked to.

  Every criterion is reported as MEDIAN and (MIN, MAX) across three runs.

  PASS RULE, pinned before any number was seen:
      PASS       median meets target AND no run is in hard-fail
      HARD FAIL  any run is in hard-fail
      MISS       median misses target, but no run is in hard-fail

  Rationale: median, because a coin-flip criterion should not be decided by one
  toss; hard-fail-on-max, because a failure mode that fires even once is one
  users will hit.

  A run that fails with a rate-limit error is DISCARDED and re-run, not counted
  as a failure. This measures extraction, not rate-limit behaviour.
"""

# (max_words_inclusive, target_seconds, hard_fail_seconds)
LATENCY_TIERS = (
    (500, 15.0, 30.0),
    (1500, 25.0, 45.0),
    (10 ** 9, 45.0, 75.0),
)

RUNS_PER_JD = 3


def latency_tier(words: int) -> tuple[float, float]:
    for max_words, target, hard in LATENCY_TIERS:
        if words <= max_words:
            return target, hard
    return LATENCY_TIERS[-1][1], LATENCY_TIERS[-1][2]


SMOKE_JD = """Data Platform Engineer

Requirements
- 4+ years of strong Python in production.
- Advanced SQL and experience writing SQL queries against large warehouses.
- Hands-on Kubernetes operations, ideally K8s at scale.
- Building and maintaining ETL pipelines.

Preferred Qualifications
- Familiarity with Terraform.
- Exposure to Apache Spark.

Benefits
Competitive salary and generous leave.
"""


def _session():
    """In-memory database. This script measures the EXTRACTOR, not persistence,
    and it must never write into the developer's real database -- a measurement
    run is not a user action and its rows would pollute the job-target list."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _verdict(value, target_ok: bool, hard_fail: bool) -> str:
    if hard_fail:
        return f"{value}  HARD FAIL"
    if not target_ok:
        return f"{value}  MISS"
    return f"{value}  ok"


def measure(db, user_id: int, title: str, jd_text: str, label: str) -> dict:
    cfg = load_config()
    started = time.perf_counter()
    target, cached = graph_build.build_graph(db, user_id, title, jd_text)
    wall = time.perf_counter() - started

    meta = target.extraction_metadata_json or {}
    extraction = meta.get("extraction", {})
    canon = meta.get("canonicalisation", {})
    clustering = meta.get("clustering", {})

    rows = db.query(ArenaSkillNode).filter(
        ArenaSkillNode.job_target_id == target.id).all()
    parents = [r for r in rows if r.parent_id is None]
    children_by_parent: dict = {}
    for row in rows:
        if row.parent_id:
            children_by_parent[row.parent_id] = children_by_parent.get(row.parent_id, 0) + 1
    child_counts = sorted(children_by_parent.values(), reverse=True)
    suggestions = db.query(ArenaMergeSuggestion).filter(
        ArenaMergeSuggestion.job_target_id == target.id).all()

    budget = clustering.get("budget_applied", {})
    n_parents = len(parents)
    min_p, max_p = budget.get("min_parents", 2), budget.get("max_parents", 9)
    max_children = int(cfg["max_children_per_parent"])
    rejected = extraction.get("rejected", 0)
    llm_calls = meta.get("llm_calls", 0)
    latency = meta.get("latency_seconds", wall)

    return {
        "label": label,
        "title": title,
        "words": len(jd_text.split()),
        "cached": cached,
        "mentions_raw": extraction.get("raw_count", 0),
        "mentions_accepted": extraction.get("accepted", 0),
        "rejected": rejected,
        "rejected_detail": extraction.get("rejected_detail", []),
        "filtered": extraction.get("filtered", 0),
        "filtered_detail": extraction.get("filtered_detail", []),
        "paraphrased": extraction.get("paraphrased", 0),
        "paraphrase_rate": extraction.get("paraphrase_rate", 0.0),
        "paraphrased_detail": extraction.get("paraphrased_detail", []),
        "extract_seconds": extraction.get("call_seconds", 0.0),
        "naming_seconds": clustering.get("naming_call_seconds", 0.0),
        "nodes": len(rows),
        # From the pipeline's own metadata, not re-derived from row counts --
        # `len(rows)` includes the synthetic parent rows and is a different
        # number. Reporting one under the other's label is exactly the
        # mislabelled-instrument problem contract section 17.16 is about.
        "nodes_after_canon": canon.get("nodes_after", 0),
        "parents": n_parents,
        "child_counts": child_counts,
        "max_children": max(child_counts) if child_counts else 0,
        "budget": budget,
        "parents_ok": min_p <= n_parents <= max_p,
        "children_ok": (max(child_counts) if child_counts else 0) <= max_children,
        "suggestions": len(suggestions),
        "merge_methods": canon.get("merge_methods", {}),
        "coherent_fraction": clustering.get("coherent_fraction"),
        "coherent_fraction_pct": (None if clustering.get("coherent_fraction") is None
                                  else clustering["coherent_fraction"] * 100),
        "mean_span_words": extraction.get("mean_span_words", 0.0),
        "escalation_required": clustering.get("escalation_required"),
        "latency": latency,
        "llm_calls": llm_calls,
        "sections": meta.get("sections_found", []),
        "parent_names": [p.canonical_name for p in parents],
        "skill_names": sorted(
            r.canonical_name for r in rows
            if r.extraction_source == graph_build.SOURCE_LLM),
    }


RATE_LIMIT_MARKERS = ("429", "rate limit", "rate_limit", "quota", "resource_exhausted")


def _is_rate_limited(exc: BaseException) -> bool:
    """A rate-limit failure is not a measurement.

    `app.core.llm` swaps provider on any exception and only raises once BOTH are
    exhausted, so reaching here means the whole lane is spent. Such a run is
    discarded and retried rather than counted, because the criteria measure
    extraction and this measures the free tier.
    """
    text = f"{type(exc).__name__} {exc}".lower()
    return any(marker in text for marker in RATE_LIMIT_MARKERS)


def measure_repeated(db, title: str, jd_text: str, label: str,
                     runs: int = RUNS_PER_JD, max_retries: int = 2) -> list[dict]:
    """`runs` independent measurements of the same JD.

    A FRESH USER PER RUN, deliberately. `graph_build` is idempotent on
    (user_id, jd_hash, extractor_version) -- which is correct behaviour and
    would silently make runs 2 and 3 cache hits, so the "three runs" would be
    one run reported three times. Found by reading the idempotency key rather
    than by seeing three identical numbers, which is what it would have looked
    like.
    """
    out: list[dict] = []
    for i in range(runs):
        attempts = 0
        while True:
            user = User(email=f"report-{label}-{i}-{attempts}@local",
                        name="Report", hashed_password="x")
            db.add(user)
            db.commit()
            try:
                out.append(measure(db, user.id, title, jd_text, f"{label} run{i + 1}"))
                break
            except Exception as exc:  # noqa: BLE001 -- classified below, not swallowed
                if _is_rate_limited(exc) and attempts < max_retries:
                    attempts += 1
                    print(f"    run{i + 1}: rate-limited, discarding and retrying "
                          f"({attempts}/{max_retries})")
                    time.sleep(20)
                    continue
                raise
    return out


def _median(values: list) -> float:
    ordered = sorted(values)
    n = len(ordered)
    if not n:
        return 0.0
    mid = n // 2
    return float(ordered[mid]) if n % 2 else (ordered[mid - 1] + ordered[mid]) / 2.0


def verdict(values: list, target_ok, hard_fail) -> tuple[str, str]:
    """Apply the PINNED pass rule to a criterion's three observations.

        PASS       median meets target AND no run is in hard-fail
        HARD FAIL  any run is in hard-fail
        MISS       median misses target, no run in hard-fail

    Returns (verdict, rendered) where `rendered` always shows median and the
    (min, max) spread -- never a point estimate. A criterion that passes at
    median but hard-fails at max is a different signal from one that passes at
    all three, and collapsing them to "passed" is the thing this protocol
    exists to prevent.
    """
    med = _median(values)
    lo, hi = min(values), max(values)
    spread = f"median {med:g}  (min {lo:g}, max {hi:g})"
    if any(hard_fail(v) for v in values):
        which = [i + 1 for i, v in enumerate(values) if hard_fail(v)]
        return "HARD FAIL", f"{spread}  HARD FAIL on run(s) {which}"
    if target_ok(med):
        return "PASS", f"{spread}  ok"
    return "MISS", f"{spread}  MISS (no run in hard-fail)"


def print_aggregate(rows: list[dict]) -> None:
    """The acceptance table for one JD across its runs."""
    r0 = rows[0]
    words = r0["words"]
    lat_target, lat_hard = latency_tier(words)
    budget = r0["budget"]
    min_p, max_p = budget.get("min_parents", 2), budget.get("max_parents", 9)
    max_children_cap = 8

    print(f"\n{'=' * 78}")
    print(f"  {r0['label']}  --  {r0['title']!r}  ({words} words, "
          f"{len(rows)} runs)")
    print(f"{'=' * 78}")
    print(f"\n  MEASURED AGAINST PRE-REGISTERED CRITERIA "
          f"(median + spread; pass rule: median meets target AND no run hard-fails)")

    checks = [
        ("hallucinated skills", [r["rejected"] for r in rows],
         lambda v: v == 0, lambda v: v >= 2),
        (f"latency (tier: <{lat_target:g}s / fail >{lat_hard:g}s)",
         [round(r["latency"], 1) for r in rows],
         lambda v: v < lat_target, lambda v: v > lat_hard),
        ("parent nodes", [r["parents"] for r in rows],
         lambda v: min_p <= v <= max_p, lambda v: not (min_p <= v <= max_p)),
        ("max children per parent", [r["max_children"] for r in rows],
         lambda v: v <= 5, lambda v: v > max_children_cap),
        ("LLM calls", [r["llm_calls"] for r in rows],
         lambda v: v <= 2, lambda v: v > 4),
    ]
    verdicts = {}
    for name, values, ok, hard in checks:
        v, rendered = verdict(values, ok, hard)
        verdicts[name] = v
        print(f"    {name:<44} {rendered}")

    print("\n  REQUIRES YOUR JUDGEMENT (this script cannot score these)")
    print("    skills correctly extracted   -- read the skill list below")
    print("    duplicate nodes surviving    -- read the skill list below")
    print("    user edits needed            -- open the graph screen")

    print("\n  SIGNALS (no target -- reported so a change in behaviour is visible)")
    for name, key, fmt in (("paraphrase rate", "paraphrase_rate", "{:.0%}"),
                           ("mean span words", "mean_span_words", "{:.1f}"),
                           ("fragments filtered", "filtered", "{:.0f}"),
                           ("review-band suggestions", "suggestions", "{:.0f}"),
                           ("cluster coherence", "coherent_fraction_pct", "{:.0f}%")):
        vals = [r.get(key) for r in rows]
        vals = [v for v in vals if v is not None]
        if not vals:
            print(f"    {name:<28} not applicable in any run")
            continue
        print(f"    {name:<28} median {fmt.format(_median(vals))}  "
              f"(min {fmt.format(min(vals))}, max {fmt.format(max(vals))})")

    esc = [i + 1 for i, r in enumerate(rows) if r["escalation_required"]]
    if esc:
        print(f"\n    *** COHERENCE GATE FAILED on run(s) {esc} -> LLM clustering "
              f"escalation is warranted. Reported, NOT silently switched. ***")

    worst = ("HARD FAIL" if "HARD FAIL" in verdicts.values()
             else "MISS" if "MISS" in verdicts.values() else "PASS")
    print(f"\n  OVERALL (machine-scorable criteria only): {worst}")

    print(f"\n  EXTRACTED SKILLS, run 1 of {len(rows)} ({len(r0['skill_names'])}) "
          f"-- read these; do not trust the counts above them")
    for name in r0["skill_names"]:
        print(f"    - {name}")
    if r0["rejected_detail"]:
        print(f"\n  INVENTED, run 1 ({r0['rejected']})")
        for item in r0["rejected_detail"]:
            print(f"    - {item.get('skill')!r}: {item.get('reason')}")
    if r0["filtered_detail"]:
        print(f"\n  FILTERED FRAGMENTS, run 1 ({r0['filtered']}) "
              f"-- real spans, not nameable skills")
        for item in r0["filtered_detail"]:
            print(f"    - {item.get('skill')!r}")
    if r0["paraphrased_detail"]:
        print(f"\n  PARAPHRASED (accepted), run 1 ({r0['paraphrased']})")
        for item in r0["paraphrased_detail"]:
            print(f"    - {item.get('skill')!r} <- {item.get('span')!r}")


def print_result(r: dict) -> None:
    print(f"\n{'=' * 78}")
    print(f"  {r['label']}  --  {r['title']!r}  ({r['words']} words)")
    print(f"{'=' * 78}")

    print("\n  MEASURED AGAINST PRE-REGISTERED CRITERIA")
    print(f"    hallucinated skills      "
          f"{_verdict(r['rejected'], r['rejected'] == 0, r['rejected'] >= 2)}")
    b = r["budget"]
    print(f"    parent nodes             "
          f"{_verdict(r['parents'], r['parents_ok'], not r['parents_ok'])}"
          f"   (budget {b.get('min_parents')}-{b.get('max_parents')} "
          f"for <= {b.get('max_mentions')} mentions)")
    print(f"    max children per parent  "
          f"{_verdict(r['max_children'], r['max_children'] <= 5, not r['children_ok'])}")
    print(f"    extraction latency       "
          f"{_verdict(f'{r['latency']:.1f}s', r['latency'] < 15, r['latency'] > 45)}")
    print(f"    LLM calls                "
          f"{_verdict(r['llm_calls'], r['llm_calls'] <= 2, r['llm_calls'] > 4)}")

    print("\n  REQUIRES YOUR JUDGEMENT (this script cannot score these)")
    print(f"    skills correctly extracted   -- read the list below")
    print(f"    duplicate nodes surviving    -- read the list below")
    print(f"    user edits needed            -- open the graph screen")

    print(f"\n  PIPELINE DETAIL")
    print(f"    mentions returned by model   {r['mentions_raw']}")
    print(f"    paraphrased (accepted)       {r['paraphrased']}"
          f"  rate {r['paraphrase_rate']:.0%}"
          f"{'   <- watch this rate across JDs' if r['paraphrase_rate'] > 0.25 else ''}")
    print(f"    fragments filtered out       {r['filtered']}"
          f"{'   <- prompt quality, NOT hallucination' if r['filtered'] else ''}")
    print(f"    extraction call              {r['extract_seconds']:.1f}s")
    print(f"    naming call                  {r['naming_seconds']:.1f}s")
    print(f"    mentions accepted            {r['mentions_accepted']}")
    print(f"    nodes after canonicalisation {r['nodes_after_canon']}")
    print(f"    rows persisted (incl. groups) {r['nodes']}")
    print(f"    review-band suggestions      {r['suggestions']}")
    methods = {k: v for k, v in (r["merge_methods"] or {}).items() if v}
    print(f"    merge methods that fired     {methods or 'none'}")
    if (r["merge_methods"] or {}).get("enriched_cosine"):
        print("    *** enriched_cosine fired -- it is supposed to decide NOTHING ***")
    frac = r["coherent_fraction"]
    print(f"    cluster coherence            "
          f"{'not applicable (all singletons)' if frac is None else f'{frac:.0%} of parents'}")
    if r["escalation_required"]:
        print("    *** COHERENCE GATE FAILED -> LLM clustering escalation is warranted."
              " Report this number; do not silently switch. ***")
    print(f"    JD sections detected         {', '.join(r['sections']) or 'none'}")

    print(f"\n  PARENT GROUPS ({r['parents']})")
    for name in r["parent_names"]:
        print(f"    - {name}")

    print(f"\n  EXTRACTED SKILLS ({len(r['skill_names'])}) "
          f"-- read these, do not trust the counts above them")
    for name in r["skill_names"]:
        print(f"    - {name}")

    if r["filtered_detail"]:
        print(f"\n  FILTERED FRAGMENTS ({r['filtered']}) -- real spans, not nameable skills")
        for item in r["filtered_detail"]:
            print(f"    - {item.get('skill')!r}")

    if r["rejected_detail"]:
        print(f"\n  REJECTED MENTIONS ({r['rejected']}) -- spans not found in the JD")
        for item in r["rejected_detail"]:
            print(f"    - {item.get('skill')!r}: {item.get('reason')}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", nargs="?",
                        help="one fixture filename under tests/fixtures/arena_jds")
    parser.add_argument("--runs", type=int, default=RUNS_PER_JD,
                        help=f"measurements per JD (default {RUNS_PER_JD}; the "
                             "protocol is pinned at 3 and lowering it makes the "
                             "pass rule undecidable)")
    parser.add_argument("--smoke", action="store_true",
                        help="one small built-in JD, single run, live model -- "
                             "verifies wiring, NOT acceptance")
    args = parser.parse_args()

    print(CRITERIA)
    db = _session()

    if args.smoke:
        print("  SMOKE TEST -- built-in JD, ONE run. Integration check, not acceptance.\n")
        user = User(email="smoke@local", name="Report", hashed_password="x")
        db.add(user)
        db.commit()
        print_result(measure(db, user.id, "Data Platform Engineer", SMOKE_JD, "smoke"))
        return 0

    if args.runs < RUNS_PER_JD:
        # Not silently honoured. The pass rule is "median meets target AND no
        # run hard-fails"; with fewer than three observations the median is not
        # a median and the rule cannot be applied as pinned.
        print(f"  WARNING: --runs {args.runs} is below the pinned protocol of "
              f"{RUNS_PER_JD}. Results are NOT an acceptance measurement.\n")

    if not FIXTURE_DIR.exists():
        print(f"No fixture directory at {FIXTURE_DIR}.")
        return 1

    files = sorted(FIXTURE_DIR.glob("*.txt"))
    if args.fixture:
        files = [f for f in files if f.name == args.fixture]
    if not files:
        print(f"No .txt fixtures found in {FIXTURE_DIR}.")
        return 1

    all_rows: list[list[dict]] = []
    for path in files:
        raw = path.read_text(encoding="utf-8")
        # Fixtures carry a provenance header above a `---` separator (source URL,
        # retrieval date, why this posting represents its category) per contract
        # section 17.16 -- a measurement against a posting that has since
        # changed must stay reproducible against exactly what was tested. The
        # header is metadata and is NOT part of the JD.
        title = path.stem.replace("-", " ").title()
        body = raw
        if "\n---\n" in raw:
            header, body = raw.split("\n---\n", 1)
            for line in header.splitlines():
                if line.lower().startswith("title:"):
                    title = line.split(":", 1)[1].strip()
        print(f"\n  measuring {path.name} x{args.runs} ...")
        all_rows.append(measure_repeated(db, title, body.strip(), path.name,
                                         runs=args.runs))

    for rows in all_rows:
        print_aggregate(rows)

    print(f"\n{'=' * 78}")
    print("  SUMMARY -- median of runs, spread in brackets")
    print(f"{'=' * 78}")
    print(f"  {'fixture':<16} {'words':>6} {'skills':>14} {'parents':>12} "
          f"{'invented':>12} {'latency':>14}")
    for rows in all_rows:
        w = rows[0]["words"]
        def cell(key, fmt="{:g}"):
            vals = [r[key] for r in rows]
            return (f"{fmt.format(_median(vals))}"
                    f"[{fmt.format(min(vals))}-{fmt.format(max(vals))}]")
        skills = [len(r["skill_names"]) for r in rows]
        print(f"  {rows[0]['label']:<16} {w:>6} "
              f"{f'{_median(skills):g}[{min(skills)}-{max(skills)}]':>14} "
              f"{cell('parents'):>12} {cell('rejected'):>12} "
              f"{cell('latency', '{:.0f}s'):>14}")

    measured = len(all_rows)
    print(f"\n  {measured} of 5 fixtures measured, {args.runs} runs each.")
    if measured < 5:
        print("  NOT a complete acceptance run -- the reviewer's two held-out JDs")
        print("  and/or the public fixtures are missing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
