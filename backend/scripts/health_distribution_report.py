"""Threshold sanity pass, stage 3: per-marker DEDUCTION report.

Consumes the real scoring engine (`health_scoring`) rather than reimplementing
the arithmetic -- a report that computes its own version of the score can
disagree with production and be believed anyway.

Answers what fire rate cannot: whether a marker that fires often is actually
moving the score, whether one marker dominates its category, and whether the
category caps are silently absorbing contributions.

    python -m scripts.health_distribution_report [repo_id ...]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# The engine's N/A reasons contain en-dashes (they are user-facing strings);
# the Windows console defaults to cp1252 and cannot encode them.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.db.database import SessionLocal            # noqa: E402
from app.db.models import CodeFile, Repo            # noqa: E402
from app.services.codebase.ast_metrics import metrics_for  # noqa: E402
from app.services.codebase.health_scoring import (  # noqa: E402
    ARCHITECTURE,
    CATEGORY_CAPS,
    CHANGE_HOTSPOT,
    MAINTAINABILITY,
    THRESHOLDS_VERSION,
    WEIGHTS_VERSION,
    FileInputs,
    build_repo_context,
    percentile,
    score_file,
)

AXES = (MAINTAINABILITY, ARCHITECTURE, CHANGE_HOTSPOT)


def stat(values):
    if not values:
        return "n=0"
    s = sorted(values)
    return (f"mean={sum(s)/len(s):5.2f} median={percentile(s,50):5.2f} "
            f"p90={percentile(s,90):5.2f} max={max(s):5.2f}")


def load_inputs(db, repo) -> list:
    """Builds FileInputs from the DB rows plus a live AST pass. Reachability
    and file-level SCCs are not persisted yet, so `cycle_size` is left None
    here -- the Architecture axis therefore reports only its coupling marker
    in this dry run, which is stated in the output rather than hidden."""
    root = Path(repo.local_path)
    if repo.source_root:
        root = root / repo.source_root

    inputs, na_language, unreadable = [], 0, 0
    for f in db.query(CodeFile).filter(CodeFile.repo_id == repo.id).all():
        try:
            data = (root / f.path).read_bytes()
        except OSError:
            unreadable += 1
            continue
        m = metrics_for(data, f.language)
        if m is None:
            na_language += 1
        inputs.append(FileInputs(
            file_id=f.id, path=f.path, language=f.language,
            nloc=m.nloc if m else f.line_count,
            ast_available=m is not None,
            function_count=m.function_count if m else 0,
            max_cyclomatic=m.max_cyclomatic if m else None,
            max_nesting=m.max_nesting if m else None,
            max_conditional_operands=m.max_conditional_operands if m else None,
            max_function_nloc=m.max_function_nloc if m else None,
            broad_handler_count=m.broad_handler_count if m else None,
            graph_available=f.fan_in is not None and f.fan_out is not None,
            fan_in=f.fan_in, fan_out=f.fan_out, cycle_size=None,
            commit_count=f.commit_count,
        ))
    return inputs, na_language, unreadable


def report_repo(db, repo):
    inputs, na_language, unreadable = load_inputs(db, repo)
    ctx = build_repo_context(inputs)
    scored = [(f, score_file(f, ctx)) for f in inputs]

    print(f"\n{'='*78}\n=== repo {repo.id}: {repo.owner}/{repo.name}  "
          f"({len(inputs)} files, unreadable={unreadable}, no-analyzer-rules={na_language})")
    print(f"    churn usable: {ctx.churn_usable}"
          + (f"  (P50={ctx.churn_p50:.0f} P95={ctx.churn_p95:.0f})" if ctx.churn_usable
             else f"  — {ctx.churn_na_reason}"))
    print(f"    fan_in P90/P99={ctx.fan_in_p90:.0f}/{ctx.fan_in_p99:.0f}   "
          f"fan_out P90/P99={ctx.fan_out_p90:.0f}/{ctx.fan_out_p99:.0f}")

    langs = {}
    for f in inputs:
        langs[f.language] = langs.get(f.language, 0) + 1
    print(f"    languages: {langs}")

    for axis in AXES:
        results = [getattr(s, axis) for _, s in scored]
        eligible = [r for r in results if r.available]
        na = [r for r in results if not r.available]
        print(f"\n  --- {axis} --- eligible={len(eligible)} N/A={len(na)}")

        reasons = {}
        for r in na:
            reasons[r.na_reason] = reasons.get(r.na_reason, 0) + 1
        for reason, n in sorted(reasons.items(), key=lambda kv: -kv[1]):
            print(f"      N/A {n:5} ({n/max(len(results),1):5.1%})  {reason}")
        if not eligible:
            continue

        # Per-marker: fire rate AND deduction distribution. Fire rate alone
        # cannot distinguish "fires often, contributes nothing" from
        # "fires often and dominates".
        print(f"      {'marker':26} {'elig':>5} {'fire%':>7} {'meanDed':>8} "
              f"{'medDed':>7} {'p90Ded':>7} {'maxDed':>7} {'share of cat':>13}")
        cat_totals = {}
        for r in eligible:
            for cat, v in r.category_deductions.items():
                cat_totals[cat] = cat_totals.get(cat, 0.0) + v

        keys = [m.key for m in eligible[0].markers]
        for key in keys:
            ms = [next(m for m in r.markers if m.key == key) for r in eligible]
            avail = [m for m in ms if m.available]
            if not avail:
                print(f"      {key:26} {'0':>5}   (all N/A)")
                continue
            ded = [m.deduction for m in avail]
            fired = sum(1 for m in avail if m.deduction > 0)
            cat = avail[0].category
            share = (sum(ded) / cat_totals[cat] * 100) if cat_totals.get(cat) else 0.0
            print(f"      {key:26} {len(avail):5} {fired/len(avail):7.1%} "
                  f"{sum(ded)/len(ded):8.2f} {percentile(sorted(ded),50):7.2f} "
                  f"{percentile(sorted(ded),90):7.2f} {max(ded):7.2f} {share:12.1f}%")

        # Cap bindings -- a capped category means a marker's contribution was
        # absorbed and the score understates what was measured.
        for cat, cap in CATEGORY_CAPS[axis].items():
            bound = sum(1 for r in eligible if cat in r.categories_capped)
            print(f"      cap[{cat}]={cap:.1f} bound on {bound:5} files ({bound/len(eligible):5.1%})")
        axis_bound = sum(1 for r in eligible if r.axis_capped)
        print(f"      axis cap bound on {axis_bound} files ({axis_bound/len(eligible):.1%})")

        values = [r.score if r.score is not None else r.points for r in eligible]
        print(f"      distribution: {stat(values)}")
        if axis == CHANGE_HOTSPOT:
            print(f"        points >0: {sum(1 for v in values if v>0)/len(values):5.1%}   "
                  f">2: {sum(1 for v in values if v>2)/len(values):5.1%}")
        else:
            print(f"        >=9.5: {sum(1 for v in values if v>=9.5)/len(values):5.1%}   "
                  f"<5.0: {sum(1 for v in values if v<5)/len(values):5.1%}")

    # Marker co-occurrence, focused on the question fire rate cannot answer:
    # are large_method and large_file the same files (Size double-counting) or
    # different ones?
    print("\n  --- marker overlap (Maintainability, eligible files) ---")
    elig = [(f, s.maintainability) for f, s in scored if s.maintainability.available]
    keys = ["complex_method", "large_method", "large_file", "complex_conditional",
            "deep_nesting", "broad_error_handling"]
    firing = {k: {f.file_id for f, r in elig
                  if any(m.key == k and m.deduction > 0 for m in r.markers)} for k in keys}
    print(f"      {'':26}" + "".join(f"{k[:11]:>12}" for k in keys))
    for a in keys:
        row = f"      {a:26}"
        for b in keys:
            inter = len(firing[a] & firing[b])
            row += f"{inter:12}" if a != b else f"{'['+str(len(firing[a]))+']':>12}"
        print(row)
    if firing["large_method"] and firing["large_file"]:
        both = firing["large_method"] & firing["large_file"]
        print(f"      large_method AND large_file = {len(both)}  "
              f"({len(both)/len(firing['large_method']):.1%} of large_method, "
              f"{len(both)/len(firing['large_file']):.1%} of large_file)")


def main():
    ids = [int(a) for a in sys.argv[1:]] or [1, 2, 3]
    print(f"thresholds_version={THRESHOLDS_VERSION} weights_version={WEIGHTS_VERSION}")
    print("NOTE: cycle_size is not persisted yet, so cycle_participation reads 0 "
          "for every file in this dry run.")
    db = SessionLocal()
    for rid in ids:
        repo = db.get(Repo, rid)
        if repo and repo.file_count:
            report_repo(db, repo)


if __name__ == "__main__":
    main()
