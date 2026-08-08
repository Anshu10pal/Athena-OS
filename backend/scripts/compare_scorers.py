"""Phase F5: compare the legacy, weighted_pagerank, and RRF scorers against
EACH OTHER on the same repo -- not against a hand-authored answer key (that
is scripts/validate_ranking.py's job, a different question).

Runs all three scorers for real (each already deletes/rewrites only its own
scorer's CodeFileRank rows -- see CodeFileRank.scorer). Every number
reported below -- scores, ranks, signal values -- is exactly what that
scorer produced over the WHOLE ingested repo; --path-prefix never changes
how a scorer computes anything, it only restricts which files' (real,
globally-computed) numbers feed into each comparison. That matters
specifically for RRF: its score is rank-based, so "ablate a signal and
recompute" is done over the full corpus, same as production, and only the
comparison step is filtered -- a frontend-only RRF variant would not be the
same algorithm this repo would actually run.

On repo 1, restrict every comparison to --path-prefix frontend/: Python
import resolution is still ~0% (see the Phase E/F briefs), so anything
outside the frontend subgraph is an artefact of the broken graph, not a
real signal -- including it would let e.g. weighted_pagerank's forced-zero
backend scores dominate a Kendall tau that's supposed to measure real
disagreement between scorers.

Phase E4: --seed is now optional -- omit it to auto-derive weighted_pagerank's
seed from real entry detection (rank_repo_weighted_pagerank raises if
detection finds nothing and no explicit seed was given, rather than silently
producing an all-zero ranking). Pass --seed to override detection for
comparison, e.g. when isolating the effect of a seed change from a prior
change (see the E4 report for why those two must be tested one at a time).

Usage (from backend/):
    python scripts/compare_scorers.py <repo_id> [--seed <path> [--seed <path> ...]] \\
        [--top 30] [--path-prefix frontend/] [--damping 0.65] [--rrf-k 60]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.database import SessionLocal  # noqa: E402
from app.db.models import CodeFile, Repo  # noqa: E402
from app.services.codebase.comparison import (  # noqa: E402
    kendall_tau,
    signal_correlation_matrix,
    top_n_ablation_report,
)
from app.services.codebase.ordering import build_reading_order  # noqa: E402
from app.services.codebase.ranking import (  # noqa: E402
    _build_graph,
    composite_score,
    legacy_signal_snapshot,
    load_rrf_config,
    rank_repo,
    rank_repo_rrf,
    rank_repo_weighted_pagerank,
    reciprocal_rank_fusion,
)

ABLATION_NOTES = {
    # Phase E4 landed real entry detection (config/code-pattern, ~8 files on
    # repo 1) -- the old note here referenced the pre-E4 72-false-positive
    # heuristic, which no longer exists; is_entry_point is now a genuinely
    # small, accurate signal, worth re-reading this ablation on its own terms.
    "is_entry_point": "small, accurate signal post-Phase-E4 (~8 real entries, not the old 72-false-positive heuristic)",
    "distinct_authors": "near-zero variance on repo 1 (only values 1-2) -- RRF discards magnitude, unlike a weighted sum",
}


def _filtered(values: dict, in_scope) -> dict:
    return {fid: v for fid, v in values.items() if in_scope(fid)}


def _print_top_n(label: str, files: list, in_scope, top_n: int) -> None:
    shown = [f for f in files if in_scope(f["file_id"])][:top_n]
    print(f"--- {label}: top {top_n} (in-scope files) ---")
    for i, f in enumerate(shown, 1):
        print(f"  {i:>2}. {f['score']:.6f}  {f['path']}")
    print()


def _print_ablation_report(label: str, report: dict, path_by_id: dict) -> None:
    print(f"--- Leave-one-signal-out, {label} (top 20, in-scope files) ---")
    for key, info in report.items():
        left = [path_by_id[fid] for fid in info["left_top_n"]]
        entered = [path_by_id[fid] for fid in info["entered_top_n"]]
        spearman_str = f"{info['spearman']:.3f}" if info["spearman"] is not None else "n/a"
        note = f"  ({ABLATION_NOTES[key]})" if key in ABLATION_NOTES else ""
        print(f"  ablate {key:<22} left={len(left):<2} entered={len(entered):<2} spearman={spearman_str} (n={info['n_common']}){note}")
        for p in left:
            print(f"      - left:    {p}")
        for p in entered:
            print(f"      + entered: {p}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("repo_id", type=int)
    parser.add_argument(
        "--seed", action="append", default=None,
        help="Seed path for weighted_pagerank (repeatable). Omit to auto-derive from Phase E4 entry detection.",
    )
    parser.add_argument("--top", type=int, default=30)
    parser.add_argument("--path-prefix", default=None, help="Restrict every comparison to paths starting with this prefix")
    parser.add_argument("--damping", type=float, default=None)
    parser.add_argument("--rrf-k", type=float, default=None)
    args = parser.parse_args()

    db = SessionLocal()
    try:
        repo = db.get(Repo, args.repo_id)
        if repo is None:
            print(f"Repo {args.repo_id} not found.", file=sys.stderr)
            sys.exit(2)

        legacy_result = rank_repo(db, repo)
        wpr_result = rank_repo_weighted_pagerank(db, repo, seed_paths=args.seed, damping=args.damping)
        rrf_result = rank_repo_rrf(db, repo, k=args.rrf_k)

        path_by_id = {f["file_id"]: f["path"] for f in legacy_result["files"]}
        prefix = args.path_prefix
        in_scope = (lambda fid: path_by_id[fid].startswith(prefix)) if prefix else (lambda fid: True)
        n_in_scope = sum(1 for fid in path_by_id if in_scope(fid))

        seed_note = "auto-derived from entry detection" if wpr_result["seed_auto_derived"] else "explicit override"
        print(f"Repo: {repo.host}/{repo.owner}/{repo.name} (id={repo.id})")
        print(f"weighted_pagerank seed ({seed_note}): {wpr_result['seed_paths']}")
        if wpr_result.get("seed_excluded_structurally_inert"):
            print(
                "  excluded, seed-eligible but fan_out == 0 (would waste teleport mass on nothing): "
                f"{wpr_result['seed_excluded_structurally_inert']}"
            )
        if legacy_result["entry_detection"]:
            print(f"Entry detection ({len(legacy_result['entry_detection'])} files): {legacy_result['entry_detection']}")
        else:
            print("Entry detection: none found")
        if legacy_result["contradictions"]:
            print(f"Entry contradictions (detected entry with fan_in > threshold): {legacy_result['contradictions']}")
        print(f"  seed-eligible: {legacy_result['seed_eligible_entries']}")
        print(f"  prior-only (excluded from seeding, still get the entry prior): {legacy_result['prior_only_entries']}")
        print()
        print(f"Total files: {len(path_by_id)}; in scope (prefix={prefix!r}): {n_in_scope}")
        print()

        _print_top_n("legacy", legacy_result["files"], in_scope, args.top)
        _print_top_n("weighted_pagerank", wpr_result["files"], in_scope, args.top)
        _print_top_n("rrf", rrf_result["files"], in_scope, args.top)

        # Phase F7 seed-circularity fix: a zero-fan-in seed's weighted_pagerank
        # score is entirely s(f)*[(1-d)+d*D] -- its own seed weight and two
        # global constants, none of it earned from real graph structure (see
        # weighted_personalized_pagerank's docstring). Letting seeds also win a
        # selection slot on that score double-counts what ordering already
        # guarantees structurally (layer 0). This is the corrected view:
        # seeds are exempted from the score competition but still land first.
        wpr_file_by_id = {f.id: f for f in db.query(CodeFile).filter(CodeFile.repo_id == repo.id).all()}
        wpr_graph = _build_graph(db, repo, wpr_file_by_id)
        wpr_seed_ids = {fid for fid, p in path_by_id.items() if p in wpr_result["seed_paths"]}
        wpr_in_scope_files = [f for f in wpr_result["files"] if in_scope(f["file_id"])]
        reading_order = build_reading_order(
            wpr_in_scope_files, wpr_graph, wpr_seed_ids, args.top, score_exempt_ids=wpr_seed_ids
        )
        print(f"--- weighted_pagerank: reading order, top {args.top} (seeds exempt from score competition, forced to layer 0) ---")
        for i, f in enumerate(reading_order["ordered"], 1):
            layer_str = str(f["layer"]) if f["layer"] is not None else "unreachable"
            print(f"  {i:>2}. layer={layer_str:<11} {f['score']:.6f}  {f['path']}")
        if reading_order["unreachable_high_centrality"]:
            print(f"  unreachable_high_centrality: {[f['path'] for f in reading_order['unreachable_high_centrality']]}")
        print()

        legacy_scores = _filtered({f["file_id"]: f["score"] for f in legacy_result["files"]}, in_scope)
        wpr_scores = _filtered({f["file_id"]: f["score"] for f in wpr_result["files"]}, in_scope)
        rrf_scores = _filtered({f["file_id"]: f["score"] for f in rrf_result["files"]}, in_scope)

        print("--- Kendall tau (pairwise, in-scope files only) ---")
        for name_a, scores_a, name_b, scores_b in (
            ("legacy", legacy_scores, "weighted_pagerank", wpr_scores),
            ("legacy", legacy_scores, "rrf", rrf_scores),
            ("weighted_pagerank", wpr_scores, "rrf", rrf_scores),
        ):
            tau, n = kendall_tau(scores_a, scores_b)
            tau_str = f"{tau:.4f}" if tau is not None else "n/a"
            print(f"  {name_a} vs {name_b}: tau={tau_str}  (n={n})")
        print()

        # Global (whole-repo) signal snapshot and RRF signal values -- the
        # SAME inputs rank_repo/rank_repo_rrf themselves used, so scoping
        # below only ever filters WHICH files' real values feed a
        # comparison, never recomputes a value under a smaller population.
        snapshot = legacy_signal_snapshot(db, repo)
        signal_values_global = {
            "fan_in": snapshot["fan_in"],
            "pagerank": snapshot["pagerank"],
            "is_entry_point": {fid: (1.0 if v else 0.0) for fid, v in snapshot["is_entry"].items()},
        }
        if snapshot["have_history"]:
            signal_values_global["commit_count"] = {fid: v for fid, v in snapshot["commit_count"].items() if v is not None}
            signal_values_global["distinct_authors"] = {fid: v for fid, v in snapshot["distinct_authors"].items() if v is not None}
            signal_values_global["days_since_last_change"] = {fid: v for fid, v in snapshot["days_since_change"].items() if v is not None}

        print("--- Signal correlation matrix (in-scope files only; |r| > 0.8 flagged redundant) ---")
        signal_values_in_scope = {name: _filtered(values, in_scope) for name, values in signal_values_global.items()}
        matrix = signal_correlation_matrix(signal_values_in_scope)
        for (name_a, name_b), info in sorted(matrix["pairs"].items()):
            r_str = f"{info['r']:.3f}" if info["r"] is not None else "n/a (zero variance)"
            print(f"  {name_a:<22} {name_b:<22} r={r_str}  (n={info['n']})")
        if matrix["redundant"]:
            print("  REDUNDANT (|r| > 0.8):")
            for name_a, name_b, r in matrix["redundant"]:
                print(f"    {name_a} <-> {name_b}  r={r:.3f}")
        else:
            print("  No signal pairs above the redundancy threshold.")
        print()

        # Legacy leave-one-out: zero one weight (no renormalization -- see
        # comparison.py's top_n_ablation_report docstring for why that's
        # correct, not an oversight), recompute over the whole repo (same
        # population legacy_signal_snapshot's normalization already used),
        # THEN filter both baseline and ablated scores to in-scope files.
        legacy_baseline = _filtered(
            composite_score(snapshot["file_by_id"].keys(), snapshot["norm_by_key"], snapshot["active_weights"]), in_scope
        )
        legacy_ablated = {}
        for key in snapshot["active_weights"]:
            ablated_weights = dict(snapshot["active_weights"])
            ablated_weights[key] = 0.0
            legacy_ablated[key] = _filtered(
                composite_score(snapshot["file_by_id"].keys(), snapshot["norm_by_key"], ablated_weights), in_scope
            )
        _print_ablation_report("legacy scorer", top_n_ablation_report(legacy_baseline, legacy_ablated, top_n=20), path_by_id)

        # RRF leave-one-out: drop one signal from the fusion entirely (RRF
        # has no per-signal weight to zero), recompute over the whole repo's
        # signal_values_global, then filter to in-scope files -- same
        # global-then-filter treatment as legacy's ablation above.
        rrf_config = load_rrf_config()
        k = args.rrf_k if args.rrf_k is not None else rrf_config["k"]
        directions = rrf_config["directions"]
        rrf_baseline = _filtered(reciprocal_rank_fusion(signal_values_global, directions, k), in_scope)
        rrf_ablated = {}
        for key in signal_values_global:
            remaining = {name: values for name, values in signal_values_global.items() if name != key}
            rrf_ablated[key] = _filtered(reciprocal_rank_fusion(remaining, directions, k), in_scope)
        _print_ablation_report("RRF scorer", top_n_ablation_report(rrf_baseline, rrf_ablated, top_n=20), path_by_id)
    finally:
        db.close()


if __name__ == "__main__":
    main()
