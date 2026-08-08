"""Validate the codebase agent's ranking against a hand-authored answer key.

Usage (from backend/):
    python scripts/validate_ranking.py <repo_id> <answer_key_path> [--scorer legacy|weighted_pagerank|rrf]

Answer key format: a markdown (or plain text) file, one file path per line,
most-important first. Leading list markers ("1.", "-", "*") and surrounding
backticks/whitespace are stripped; blank lines and lines starting with "#"
(headings/comments) are ignored. Paths must match code_files.path exactly --
POSIX-separated, relative to the repo's local_path/source_root. Example:

    # Reading list for pallets/click
    1. `src/click/core.py`
    2. `src/click/decorators.py`
    - src/click/types.py

This is a one-off comparison exercise, not a repeated feature -- there is no
API endpoint for it, by design (see the Phase C/D brief). If you tune
config/ranking_weights.yaml after seeing a comparison and re-run this,
report BOTH runs -- don't present only the tuned one as if it were the only
attempt.
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.database import SessionLocal  # noqa: E402
from app.db.models import CodeFile, CodeFileRank, Repo  # noqa: E402

LIST_MARKER_RE = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+")
GO_NO_GO_THRESHOLD = 12  # out of 20, per the brief


def parse_answer_key(path: Path) -> list:
    paths = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        cleaned = LIST_MARKER_RE.sub("", stripped).strip().strip("`").strip()
        if cleaned:
            paths.append(cleaned)
    return paths


def get_tool_ranking(db, repo_id: int, scorer: str = "legacy") -> list:
    # Both sides of the join filtered by repo_id, not just CodeFileRank's:
    # nothing in ingest/ranking today creates a CodeFileRank row whose
    # file_id points at a different repo's CodeFile, but that's an invariant
    # nothing enforces at the schema level -- a future bug there would
    # silently leak another repo's paths into this repo's reading list.
    #
    # scorer is REQUIRED, not incidental: CodeFileRank stores one row per
    # (file, scorer) -- legacy, weighted_pagerank, and rrf coexist for the
    # same repo (see CodeFileRank.scorer's docstring), on entirely different
    # scales (legacy tops out around 0.75 on a real repo, weighted_pagerank
    # around 0.3, rrf around 0.08). Ordering by score without filtering by
    # scorer silently interleaves three incompatible scales into one list --
    # whichever scorer happens to have the largest raw scores dominates the
    # "top" of the result, and the other two are pushed out entirely. This
    # was caught by actually running this script against a repo that had
    # more than one scorer's rows, not by inspection.
    rows = (
        db.query(CodeFileRank, CodeFile.path)
        .join(CodeFile, CodeFileRank.file_id == CodeFile.id)
        .filter(CodeFileRank.repo_id == repo_id, CodeFile.repo_id == repo_id, CodeFileRank.scorer == scorer)
        .order_by(CodeFileRank.score.desc())
        .all()
    )
    return [path for _rank, path in rows]


def overlap_at(tool_list: list, key_list: list, n: int) -> tuple:
    common = set(tool_list[:n]) & set(key_list[:n])
    return len(common), n


def spearman_on_intersection(tool_list: list, key_list: list) -> tuple:
    """Spearman rank correlation over the intersection of both top-20 lists --
    "for files both consider important, do we agree on their relative order?"
    A deliberate scope choice: it says nothing about files only one list
    considers important -- that's what overlap_at/mismatches are for. No
    scipy (same constraint as ranking.py's PageRank): computed by hand via
    rho = 1 - 6*sum(d^2) / (n*(n^2-1)). Returns (rho, n); rho is None when
    n < 2 (undefined -- not a crash).

    Ranks used in the formula are the common items' RELATIVE order within
    each top-20 (re-indexed 0..n-1), not their absolute position in the
    original top-20 list -- using absolute position was a real bug caught by
    testing against real data: a small common set scattered near opposite
    ends of two 20-item lists produced a rho far outside [-1, 1], since raw
    position gaps aren't bounded by n once most of the list isn't shared.
    """
    tool_top20 = tool_list[:20]
    key_top20 = key_list[:20]
    common = set(tool_top20) & set(key_top20)
    n = len(common)
    if n < 2:
        return None, n
    tool_order = [p for p in tool_top20 if p in common]
    key_order = [p for p in key_top20 if p in common]
    tool_rank = {p: i for i, p in enumerate(tool_order)}
    key_rank = {p: i for i, p in enumerate(key_order)}
    d_sq_sum = sum((tool_rank[p] - key_rank[p]) ** 2 for p in common)
    rho = 1 - (6 * d_sq_sum) / (n * (n**2 - 1))
    assert -1.0 - 1e-9 <= rho <= 1.0 + 1e-9, f"Spearman rho out of range: {rho} (n={n}) -- a bug in this function"
    return rho, n


def mismatches(tool_list: list, key_list: list, n: int = 20) -> dict:
    tool_top = set(tool_list[:n])
    key_top = set(key_list[:n])
    return {
        "in_key_not_tool": sorted(key_top - tool_top),
        "in_tool_not_key": sorted(tool_top - key_top),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("repo_id", type=int)
    parser.add_argument("answer_key_path", type=Path)
    parser.add_argument(
        "--scorer", default="legacy", choices=["legacy", "weighted_pagerank", "rrf"],
        help="Which scorer's CodeFileRank rows to validate against (default: legacy).",
    )
    args = parser.parse_args()

    key_list = parse_answer_key(args.answer_key_path)
    if not key_list:
        print(f"No paths parsed from {args.answer_key_path} -- check the format.", file=sys.stderr)
        sys.exit(2)

    db = SessionLocal()
    try:
        repo = db.get(Repo, args.repo_id)
        if repo is None:
            print(f"Repo {args.repo_id} not found.", file=sys.stderr)
            sys.exit(2)
        tool_list = get_tool_ranking(db, args.repo_id, scorer=args.scorer)
    finally:
        db.close()

    if not tool_list:
        print(f"Repo {args.repo_id} has no {args.scorer!r} ranking yet -- run rank_repo{'' if args.scorer=='legacy' else '_'+args.scorer} first.", file=sys.stderr)
        sys.exit(2)

    overlap20, _ = overlap_at(tool_list, key_list, 20)
    overlap10, _ = overlap_at(tool_list, key_list, 10)
    rho, n_common = spearman_on_intersection(tool_list, key_list)
    mm = mismatches(tool_list, key_list, 20)

    print(f"Repo: {repo.host}/{repo.owner}/{repo.name} (id={repo.id})")
    print(f"Scorer: {args.scorer}")
    print(f"Answer key: {args.answer_key_path} ({len(key_list)} entries)")
    print(f"Tool ranking: {len(tool_list)} files")
    print()
    print(f"Overlap@20: {overlap20}/20")
    print(f"Overlap@10: {overlap10}/10")
    if rho is None:
        print(f"Spearman (intersection): n/a (fewer than 2 files in common, n={n_common})")
    else:
        print(f"Spearman (intersection, n={n_common}): {rho:.3f}")
    print()
    verdict = "GO" if overlap20 >= GO_NO_GO_THRESHOLD else "NO-GO"
    print(f"Verdict: {verdict} (threshold: Overlap@20 >= {GO_NO_GO_THRESHOLD})")
    print()
    if mm["in_key_not_tool"]:
        print("In answer key's top 20 but missing from the tool's top 20:")
        for p in mm["in_key_not_tool"]:
            print(f"  - {p}")
    if mm["in_tool_not_key"]:
        print("In the tool's top 20 but not in the answer key's top 20:")
        for p in mm["in_tool_not_key"]:
            print(f"  - {p}")


if __name__ == "__main__":
    main()
