"""File discovery: walk a repo root, apply .gitignore + a default exclusion
list, keep only extensions we can parse, and refuse outright above a file cap
rather than silently truncating.
"""
import os
from pathlib import Path
from typing import Optional

import pathspec

from app.services.codebase.languages import EXTENSION_LANGUAGE

DEFAULT_EXCLUDES = [
    "node_modules/",
    "dist/",
    "build/",
    ".venv/",
    "venv/",
    "__pycache__/",
    "vendor/",
    ".git/",
    "*.min.js",
    "package-lock.json",
    "yarn.lock",
    "poetry.lock",
]


class TooManyFilesError(RuntimeError):
    pass


def _load_spec(root: Path, extra_excludes: Optional[list] = None) -> pathspec.PathSpec:
    lines = list(DEFAULT_EXCLUDES)
    if extra_excludes:
        lines.extend(extra_excludes)
    gitignore = root / ".gitignore"
    if gitignore.is_file():
        lines.extend(gitignore.read_text(encoding="utf-8", errors="ignore").splitlines())
    return pathspec.PathSpec.from_lines("gitignore", lines)


def discover_files(root: Path, max_files: int, extra_excludes: Optional[list] = None) -> list[Path]:
    """Relative (POSIX-separator) paths of every source file under root that
    survives .gitignore plus the default exclusion list, sorted for
    deterministic ingest order. Raises TooManyFilesError if the count would
    exceed max_files -- no silent truncation.

    extra_excludes: additional gitignore-style patterns applied regardless of
    root's own .gitignore (which may not exist at all). Used by the caller to
    hard-exclude the repo clone cache when it happens to live inside this
    ingest root -- that must never depend on the target having a .gitignore
    that happens to cover it."""
    spec = _load_spec(root, extra_excludes)
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root)
        kept = []
        for d in dirnames:
            rel = d if str(rel_dir) == "." else (rel_dir / d).as_posix()
            if not spec.match_file(rel + "/"):
                kept.append(d)
        dirnames[:] = kept

        for fname in filenames:
            if Path(fname).suffix.lower() not in EXTENSION_LANGUAGE:
                continue
            rel = fname if str(rel_dir) == "." else (rel_dir / fname).as_posix()
            if spec.match_file(rel):
                continue
            found.append(Path(rel))
            if len(found) > max_files:
                raise TooManyFilesError(
                    f"Repository has more than {max_files} matching source files -- "
                    "ingestion refuses rather than silently truncating. Raise "
                    "REPO_MAX_FILES or narrow the repo's source_root."
                )
    found.sort()
    return found
