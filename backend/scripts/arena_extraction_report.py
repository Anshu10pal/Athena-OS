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
CRITERIA = """
PRE-REGISTERED ACCEPTANCE CRITERIA (agreed before any JD was measured)

  skills correctly extracted     target >= 85%   hard fail < 70%      [YOUR JUDGEMENT]
  hallucinated skills            target 0        hard fail >= 2       span not in JD, OR
                                                                      span does not support
                                                                      the skill name
  paraphrase rate                no target -- a SIGNAL, reported per JD, not a criterion
  parent nodes                   per node budget (short JD may honestly yield 2-4)
  children per parent            target 2-5      hard fail > 8
  duplicate nodes surviving      target 0        hard fail >= 2       [YOUR JUDGEMENT]
  user edits needed              target <= 3     hard fail > 8        [YOUR JUDGEMENT]
  extraction latency             target < 15s    hard fail > 45s
  LLM calls per JD               target <= 2     hard fail > 4

  A vague JD producing few nodes with low confidence is a PASS.
  A vague JD producing 8 confident invented parents is a HARD FAIL, precisely
  because it clears the structural bar.
"""

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
        "escalation_required": clustering.get("escalation_required"),
        "latency": latency,
        "llm_calls": llm_calls,
        "sections": meta.get("sections_found", []),
        "parent_names": [p.canonical_name for p in parents],
        "skill_names": sorted(
            r.canonical_name for r in rows
            if r.extraction_source == graph_build.SOURCE_LLM),
    }


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
    parser.add_argument("fixture", nargs="?", help="one fixture filename under tests/fixtures/arena_jds")
    parser.add_argument("--smoke", action="store_true",
                        help="run one small built-in JD against the live model to verify wiring")
    args = parser.parse_args()

    print(CRITERIA)

    db = _session()
    user = User(email="report@local", name="Report", hashed_password="x")
    db.add(user)
    db.commit()

    if args.smoke:
        print("  SMOKE TEST -- built-in JD, live model. Verifies integration, NOT acceptance.\n")
        r = measure(db, user.id, "Data Platform Engineer", SMOKE_JD, "smoke")
        print_result(r)
        return 0

    if not FIXTURE_DIR.exists():
        print(f"No fixture directory at {FIXTURE_DIR}.")
        return 1

    files = sorted(FIXTURE_DIR.glob("*.txt"))
    if args.fixture:
        files = [f for f in files if f.name == args.fixture]
    if not files:
        print(f"No .txt fixtures found in {FIXTURE_DIR}.")
        print("Phase A's acceptance measurement needs five: two personal (held out,")
        print("supplied by the reviewer) and three public (committed with citation).")
        return 1

    results = []
    for path in files:
        raw = path.read_text(encoding="utf-8")
        # Fixtures carry a provenance header (source URL + retrieval date) above
        # a `---` separator, per contract section 17.16 -- a measurement against
        # a posting that has since changed must stay reproducible against
        # exactly what was tested. The header is metadata, not JD text.
        title = path.stem.replace("-", " ").title()
        body = raw
        if "\n---\n" in raw:
            header, body = raw.split("\n---\n", 1)
            for line in header.splitlines():
                if line.lower().startswith("title:"):
                    title = line.split(":", 1)[1].strip()
        results.append(measure(db, user.id, title, body.strip(), path.name))

    for r in results:
        print_result(r)

    print(f"\n{'=' * 78}")
    print("  SUMMARY")
    print(f"{'=' * 78}")
    print(f"  {'fixture':<22} {'words':>6} {'skills':>7} {'parents':>8} "
          f"{'halluc':>7} {'latency':>8} {'calls':>6}")
    for r in results:
        print(f"  {r['label']:<22} {r['words']:>6} {len(r['skill_names']):>7} "
              f"{r['parents']:>8} {r['rejected']:>7} {r['latency']:>7.1f}s {r['llm_calls']:>6}")
    print(f"\n  {len(results)} of 5 fixtures measured.")
    if len(results) < 5:
        print("  The remaining fixtures are the reviewer's two personal JDs (held out)")
        print("  and/or the public ones. This is NOT a complete acceptance run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
