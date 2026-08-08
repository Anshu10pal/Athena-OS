"""Phase E2.1: Python root discovery -- validation/report script, not a
served API endpoint (same one-off CLI precedent as validate_ranking.py /
compare_scorers.py).

Runs root discovery + verified scoring against a REAL registered repo's
current CodeFile/CodeImport rows, and prints: every candidate root
considered (marker vs structural nomination, or both), its score/percentage,
the specifiers it wins (not just the count), and the final promoted set.

This does NOT wire discovered roots into the real resolution pass --
ingest.py's resolve_python_import calls still use the pre-E2 default
["", "src"] roots. That integration, with nearest-ancestor-first ordering
and cross_root edge flagging, is Phase E2.3.

Usage (from backend/):
    python scripts/discover_roots.py <repo_id>
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.database import SessionLocal  # noqa: E402
from app.db.models import CodeFile, CodeImport, Repo  # noqa: E402
from app.services.codebase.ingest import _repo_root  # noqa: E402
from app.services.codebase.root_discovery import (  # noqa: E402
    find_marker_candidate_roots,
    find_structural_candidate_roots,
    partition_unresolved_specifiers,
    promote_roots,
    score_candidate_roots,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("repo_id", type=int)
    args = parser.parse_args()

    db = SessionLocal()
    try:
        repo = db.get(Repo, args.repo_id)
        if repo is None:
            print(f"Repo {args.repo_id} not found.", file=sys.stderr)
            sys.exit(2)

        files = db.query(CodeFile).filter(CodeFile.repo_id == repo.id).all()
        if not files:
            print(f"Repo {args.repo_id} has no ingested files -- run ingest first.", file=sys.stderr)
            sys.exit(2)

        all_paths = {f.path for f in files}
        python_files = {f.path for f in files if f.language == "python"}
        file_by_id = {f.id: f for f in files}

        unresolved_python_rows = (
            db.query(CodeImport)
            .join(CodeFile, CodeImport.from_file_id == CodeFile.id)
            .filter(
                CodeImport.repo_id == repo.id, CodeFile.repo_id == repo.id,
                CodeFile.language == "python", CodeImport.resolved == False,  # noqa: E712
            )
            .all()
        )
        unresolved_rows = [
            {
                "from_file": file_by_id[row.from_file_id].path,
                "raw_specifier": row.raw_specifier,
                "name": row.imported_names[0] if row.imported_names else None,
            }
            for row in unresolved_python_rows
            if row.from_file_id in file_by_id
        ]
        non_relative_rows = [r for r in unresolved_rows if not r["raw_specifier"].startswith(".")]
        partition = partition_unresolved_specifiers(non_relative_rows)
        not_yet_classified_rows = partition["not_yet_classified"]
        unresolved_specifiers = [r["raw_specifier"] for r in not_yet_classified_rows]

        repo_root = _repo_root(repo)
        marker_candidates = find_marker_candidate_roots(repo_root)
        structural_candidates = find_structural_candidate_roots(python_files, unresolved_specifiers)
        all_candidates = marker_candidates | structural_candidates

        print(f"Repo: {repo.host}/{repo.owner}/{repo.name} (id={repo.id})")
        print(f"Python files: {len(python_files)}")
        print(f"Unresolved Python import rows: {len(unresolved_rows)} total")
        print(f"  relative (root-independent, excluded): {len(unresolved_rows) - len(non_relative_rows)}")
        print(f"  non-relative: {len(non_relative_rows)}")
        print(f"    stdlib (cannot resolve internally by definition, excluded): {len(partition['stdlib'])}")
        print(f"    not_yet_classified (scored -- real internal misses + unclassified third-party): {len(not_yet_classified_rows)}")
        print()
        print(f"Marker-nominated candidates ({len(marker_candidates)}): {sorted(marker_candidates)}")
        print(f"Structurally-nominated candidates ({len(structural_candidates)}): {sorted(structural_candidates)}")
        print()

        scores = score_candidate_roots(all_candidates, not_yet_classified_rows, all_paths)
        promoted = promote_roots(scores)

        def _label(root: str) -> str:
            return root if root else "<repo root>"

        print("--- Scores (all candidates, sorted by score) ---")
        for root in sorted(all_candidates, key=lambda r: -scores[r]["score"]):
            info = scores[root]
            nomination = "+".join(
                x for x in (("marker" if root in marker_candidates else ""), ("structural" if root in structural_candidates else "")) if x
            ) or "?"
            promoted_flag = "  [PROMOTED]" if root in promoted else ""
            print(f"  {_label(root):<30} score={info['score']:<4} pct={info['percentage']*100:5.1f}%  ({nomination}){promoted_flag}")
        print()

        print(f"--- Promoted roots ({len(promoted)}) -- specifiers each one wins ---")
        explained = set()
        for root in sorted(promoted, key=lambda r: -scores[r]["score"]):
            info = scores[root]
            print(f"\n  {_label(root)}: {info['score']} of {len(not_yet_classified_rows)} not_yet_classified ({info['percentage']*100:.1f}%)")
            for raw_specifier, target, from_file in info["specifiers"]:
                print(f"      {raw_specifier}  ->  {target}   (from {from_file})")
                explained.add((raw_specifier, from_file))
        print()

        unexplained = [r for r in not_yet_classified_rows if (r["raw_specifier"], r["from_file"]) not in explained]
        print(f"Still unexplained by any promoted root (real gap OR unclassified third-party): {len(unexplained)} of {len(not_yet_classified_rows)}")
        for r in unexplained[:20]:
            print(f"    {r['raw_specifier']}   (from {r['from_file']})")
        if len(unexplained) > 20:
            print(f"    ... and {len(unexplained) - 20} more")
    finally:
        db.close()


if __name__ == "__main__":
    main()
