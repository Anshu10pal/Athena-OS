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
    # --- vendored third-party code, added after a committed virtualenv was
    # --- ingested as a repo's own source (7,715 files of matplotlib,
    # --- jupyterlab and IPython attributed to a small full-stack app).
    #
    # The directory was called `venv310`, so the name-based `venv/` above
    # missed it -- as it also misses `env/`, `virtualenv/`, `venv312/`. That is
    # the general lesson: enumerating names is always incomplete, and where a
    # structural marker exists it should be preferred. `site-packages/` and
    # `dist-packages/` are structural -- every Python environment has one
    # whatever the directory above it is called. See also _venv_roots() below,
    # which catches the parts of a venv that are NOT under site-packages.
    "site-packages/",
    "dist-packages/",
    "*.egg-info/",
    ".tox/",
    "__pypackages__/",
    "bower_components/",
    ".yarn/cache/",
    ".pnpm-store/",
    ".gradle/",
    "Pods/",
]

# Deliberately NOT excluded, with reasons -- each is a name that means
# third-party code in one ecosystem and first-party source in another. A
# pattern cannot tell them apart; only structure can, and none of these is
# common enough here to justify the structural check yet.
#
#   packages/   NuGet dependencies in a .NET solution, but FIRST-PARTY SOURCE
#               in a JS monorepo -- it is real code on both apache/superset and
#               palmerhq/monorepo-starter. Would need anchoring to a sibling
#               .sln or packages.config.
#   bin/        Interpreter shims in a virtualenv, but real first-party scripts
#               in most repos -- eslint's own bin/eslint.js is a file this
#               project deliberately validates against. Caught instead by
#               _venv_roots(), which excludes bin/ ONLY under a detected venv.
#   Scripts/    Same as bin/, on Windows layouts.
AMBIGUOUS_NOT_EXCLUDED = ("packages/", "bin/", "Scripts/")

# PEP 405: every virtualenv has this file at its root, whatever the root is
# called. Detecting it excludes the WHOLE environment -- interpreter shims,
# Include/, Lib/ -- not just the library directory.
VENV_MARKER = "pyvenv.cfg"


class TooManyFilesError(RuntimeError):
    pass


# Directory names pruned by `iter_files_named`. One list, shared, rather than
# the three divergent `_IGNORED_DIR_NAMES` sets that previously lived in
# entry_detection, js_root_discovery and root_discovery -- they disagreed with
# each other and none contained a virtualenv marker, so all three walked into
# `venv310/Lib/site-packages` on a repo with a committed environment.
PRUNED_DIR_NAMES = {
    "node_modules", "dist", "build", ".git", "__pycache__",
    "venv", ".venv", "site-packages", "dist-packages",
    ".tox", "__pypackages__", "bower_components", ".gradle", "Pods",
}


def iter_files_named(search_root: Path, *names: str):
    """Yield paths to files with any of `names`, pruning as it walks.

    Phase H1.5 established the mechanism for `entry_detection`: `rglob(name)`
    filtered AFTER the fact still walks INTO the ignored directory before
    discarding what it found there, so the filter hides the cost without
    avoiding it. `os.walk`'s `dirnames` is mutable and read by the walk, so
    pruning it in place skips descending entirely.

    Two other callers never got that fix and were measured on a repo with a
    committed virtualenv: `root_discovery.find_marker_candidate_roots` at
    3.54 s and `js_root_discovery._iter_files_named` at 2.14 s, together 5.67 s
    of a 8.47 s ingest on a repo whose real source is 67 files. They were
    walking the 7,698 vendored files that `discover_files` already excludes.

    Also prunes any directory containing `pyvenv.cfg`, matching
    `discover_files` -- a name list cannot catch `venv310`, and this is the
    same structural marker for the same reason (§17.10).
    """
    names_set = set(names)
    for dirpath, dirnames, filenames in os.walk(search_root):
        if VENV_MARKER in filenames:
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames if d not in PRUNED_DIR_NAMES]
        for filename in filenames:
            if filename in names_set:
                yield Path(dirpath) / filename


# NOTE: an earlier version counted the parseable files inside each pruned
# subtree so the summary could say "7,698 files skipped". It cost 1.39s of a
# 3.72s ingest -- a second of wall clock for one log line -- because the count
# is unobtainable from the main walk BY CONSTRUCTION: pruning means never
# descending, so counting what was pruned requires a second traversal of
# exactly the tree the pruning existed to avoid.
#
# The directory names are free (known at the prune point) and carry the finding
# that mattered: that a virtualenv or a node_modules was excluded at all. The
# file count was the more quotable number and is not worth a second.


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
    found, _ = discover_files_with_stats(root, max_files, extra_excludes)
    return found


def discover_files_with_stats(root: Path, max_files: int,
                              extra_excludes: Optional[list] = None) -> tuple:
    """discover_files, plus a count of parseable files skipped as vendored,
    keyed by the top-level directory they were under.

    Split out rather than changing discover_files' signature: every existing
    caller and test wants just the paths, and only ingest needs the counts.
    """
    spec = _load_spec(root, extra_excludes)
    found: list[Path] = []
    skipped: dict = {}
    pruned_dirs: list = []

    def note_skipped(rel_posix: str) -> None:
        head = rel_posix.split("/", 1)[0]
        skipped[head] = skipped.get(head, 0) + 1

    def note_pruned(rel_posix: str) -> None:
        """Free: the path is known at the prune point. The file COUNT inside it
        is not -- see the note above, it needs a second traversal of exactly
        the tree pruning exists to avoid."""
        pruned_dirs.append(rel_posix)

    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root)

        # A virtualenv root: prune the entire subtree, whatever it is named.
        # Checked before the pattern pass because this is the rule that catches
        # `venv310/Scripts/` and `venv310/Include/` -- the parts of an
        # environment that are not under site-packages and that no safe name
        # pattern can reach (see AMBIGUOUS_NOT_EXCLUDED: a bare `bin/` rule
        # would swallow real first-party scripts).
        if VENV_MARKER in filenames:
            rel_here = "" if str(rel_dir) == "." else rel_dir.as_posix()
            note_pruned(rel_here or ".")
            dirnames[:] = []
            continue

        kept = []
        for d in dirnames:
            rel = d if str(rel_dir) == "." else (rel_dir / d).as_posix()
            if spec.match_file(rel + "/"):
                # Counted here because the walk will never descend into it.
                note_pruned(rel)
            else:
                kept.append(d)
        dirnames[:] = kept

        for fname in filenames:
            if Path(fname).suffix.lower() not in EXTENSION_LANGUAGE:
                continue
            rel = fname if str(rel_dir) == "." else (rel_dir / fname).as_posix()
            if spec.match_file(rel):
                note_skipped(rel)
                continue
            found.append(Path(rel))
            if len(found) > max_files:
                raise TooManyFilesError(
                    f"Repository has more than {max_files} matching source files -- "
                    "ingestion refuses rather than silently truncating. Raise "
                    "REPO_MAX_FILES or narrow the repo's source_root."
                )
    found.sort()
    return found, {"files": skipped, "dirs": pruned_dirs}


# How many vendored files must be skipped before it is worth a line in the
# report. Low, because the point is visibility, not alarm.
VENDORED_REPORT_THRESHOLD = 50


def vendored_summary(stats: dict, kept: int) -> Optional[str]:
    """Report what discovery THREW AWAY, not what dominates what it kept.

    ## Why not a concentration warning

    The obvious tripwire -- "warn when >50% of files sit under one top-level
    directory" -- was implemented, tested against the six repos in this
    database, and discarded. It fires on four of them:

        eslint                  lib/                 98.7%   legitimate
        Athena-OS               backend/             64.3%   legitimate
        superset                superset-frontend/   59.9%   legitimate
        AFDE                    frontend/            53.6%   legitimate
        InsurIQ (pre-fix)       backend/venv310/     ~90%    VENDORED

    ESLint is a library whose source lives in `lib/`; 98.7% concentration is
    exactly right. InsurIQ was ~90% and exactly wrong. **Concentration does not
    separate them**, so no threshold catches the bad case without crying wolf
    on the good ones -- and a warning that fires on two thirds of repos trains
    people to ignore it, which is worse than no warning.

    What distinguishes them is not how concentrated the files are, but that
    InsurIQ's dominant directory was third-party code. That is precisely what
    the exclusion rules now detect, so the honest report is the exclusion
    volume itself: "7,000 files skipped as vendored" would have been one line,
    with no false-positive mode at all, because it reports a fact rather than
    inferring a judgement.
    """
    # .git is pruned on every repo and is not a finding -- listing it as
    # "vendored" is noise that dilutes the line this exists to make.
    dirs = [d for d in (stats.get("dirs") or []) if Path(d).name != ".git"]
    loose = sum((stats.get("files") or {}).values())
    if not dirs and loose < VENDORED_REPORT_THRESHOLD:
        return None

    # Directory names, not a file count: the count needed a second traversal of
    # exactly the tree pruning avoids, and cost 1.39s of a 3.72s ingest. The
    # names are free and carry the finding -- that a virtualenv or a
    # node_modules was excluded at all.
    shown = ", ".join(sorted(dirs)[:4])
    more = f" and {len(dirs) - 4} more" if len(dirs) > 4 else ""
    parts = []
    if dirs:
        parts.append(f"{len(dirs)} vendored or generated directories were "
                     f"excluded from this analysis ({shown}{more})")
    if loose:
        parts.append(f"{loose} further files matched an exclusion pattern")
    return "; ".join(parts) + f". Kept {kept} files."
