"""Phase E2.2: TypeScript/JS root + alias discovery -- validation/report
script, not a served API endpoint (same one-off CLI precedent as
discover_roots.py / validate_ranking.py / compare_scorers.py).

Unlike discover_roots.py (Python), this reports config discovery only --
config presence is authoritative, not scored (see js_root_discovery.py's
module docstring for why a percentage-of-unresolved-specifiers metric
would be meaningless for TS/JS). It also reports, honestly, whether this
repo has ANY of the surface Phase E2.2 actually added logic for
(tsconfig/jsconfig paths, package.json workspaces) -- if it doesn't, this
script says so instead of implying validation where there was nothing to
validate. See tests/test_js_root_discovery.py's TestSyntheticFixtureEndToEnd
for the actual mechanism proof.

Usage (from backend/):
    python scripts/discover_js_roots.py <repo_id>
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.database import SessionLocal  # noqa: E402
from app.db.models import CodeFile, Repo  # noqa: E402
from app.services.codebase.ingest import _repo_root  # noqa: E402
from app.services.codebase.js_root_discovery import (  # noqa: E402
    find_package_json_workspace_dirs,
    find_ts_configs,
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

        js_files = db.query(CodeFile).filter(
            CodeFile.repo_id == repo.id, CodeFile.language.in_(("javascript", "typescript", "tsx"))
        ).count()

        repo_root = _repo_root(repo)
        configs = find_ts_configs(repo_root)
        workspaces = find_package_json_workspace_dirs(repo_root)

        print(f"Repo: {repo.host}/{repo.owner}/{repo.name} (id={repo.id})")
        print(f"JS/TS files: {js_files}")
        print()
        print(f"tsconfig.json/jsconfig.json found ({len(configs)}):")
        for c in configs:
            has_paths = bool(c["paths"])
            label = c["dir"] if c["dir"] else "<repo root>"
            print(f"  {label}: baseUrl={c['base_url']!r}, paths={'yes (' + str(len(c['paths'])) + ' aliases)' if has_paths else 'none'}")
        print()
        print(f"package.json workspace boundaries found ({len(workspaces)}): {sorted(workspaces)}")
        print()

        any_paths = any(c["paths"] for c in configs)
        if not any_paths and not workspaces:
            print(
                "HONEST NOTE: this repo has no tsconfig/jsconfig `paths` and no package.json "
                "workspaces field. Phase E2.2's alias/workspace-boundary logic has NOTHING to "
                "resolve here -- this repo cannot validate that logic, only confirm it correctly "
                "finds nothing to do. See tests/test_js_root_discovery.py's "
                "TestSyntheticFixtureEndToEnd for where that logic is actually exercised."
            )
    finally:
        db.close()


if __name__ == "__main__":
    main()
