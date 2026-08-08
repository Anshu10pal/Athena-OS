"""Phase E2.1: Python root discovery.

Markers nominate; verified resolution evidence decides. This module only
identifies which directories deserve to be tried as sys.path roots, and how
confidently -- it does not resolve imports for real (see resolve_imports.py)
or wire discovered roots into ingest.py's actual resolution pass (Phase
E2.3's job, along with nearest-ancestor-first ordering and cross_root
edge flagging).

Two independent nomination paths, because markers alone miss real cases:
- Marker files (requirements.txt, pyproject.toml, setup.py, Pipfile) --
  conventional, but a flat app with no packaging file at all (Phase E2.4's
  repo 2 test case) would never nominate its own real root this way.
- Structural signals, independent of any marker: the parent of any directory
  that is itself a Python package (contains __init__.py), and any directory
  directly containing a module/package matching an unresolved bare
  specifier's first component. Cheap to compute, and it's what makes a
  marker-less flat layout's root reachable at all.

No DB access in this module (same pattern as entry_detection.py and
comparison.py) -- callers assemble repo-scoped inputs (a script or, once
E2.3 lands, ingest.py itself) and pass plain data in.

Scoring denominator, and why it's split into three named buckets rather
than one number: an unresolved specifier can fail to resolve for two
completely different reasons -- it's genuinely internal and no promoted
root explains it (a real gap), or it can never resolve to a file in ANY
repo because it names something external (stdlib or third-party). Only the
first kind is evidence against a candidate root; diluting the denominator
with the second kind understates every real root's score without telling
you anything about root discovery itself (verified on repo 1 and repo 2:
every non-stdlib unexplained specifier on both is a real third-party
package, zero genuine internal gaps -- see
tests/fixtures/known_external_python_specifiers.py).

partition_unresolved_specifiers splits out `stdlib` (sys.stdlib_module_names,
a zero-cost, zero-design-surface stdlib constant) from `not_yet_classified`
(everything else -- real internal misses AND third-party packages,
indistinguishable until Phase E3's requirements.txt/pyproject.toml parsing
lands). Only `not_yet_classified` rows are scored. When E3 lands, it adds a
THIRD bucket (`third_party`) carved out of `not_yet_classified` -- the
denominator narrows again, for a visible, explained reason, rather than the
"100% resolved" figure jumping between phases for reasons a reader can't see.
"""
import posixpath
import sys
from pathlib import Path
from typing import Optional

import yaml

PYTHON_ROOT_MARKER_FILENAMES = ("requirements.txt", "pyproject.toml", "setup.py", "Pipfile")
_IGNORED_DIR_NAMES = {"node_modules", "dist", "build", ".git", "__pycache__", "venv", ".venv"}

DEFAULT_RELATIVE_FLOOR = 0.05
DEFAULT_ABSOLUTE_FLOOR = 3
# NOT raised yet, on purpose: 5% of a denominator still diluted by
# unclassified third-party specifiers is a different test than 5% of a
# fully-narrowed one. Once Phase E3 adds its own exclusion bucket and the
# denominator is down to genuinely-could-be-internal specifiers only,
# revisit this -- repo 1 and repo 2 both cleared 100% once stdlib alone was
# excluded, so 15-20% would plausibly still pass a real root without
# weakening protection against a coincidentally-matching wrong one.


def find_marker_candidate_roots(repo_root: Path) -> set:
    """Directories (repo-root-relative, POSIX, "" for the repo root itself)
    containing a Python packaging marker file. Scanned directly off disk,
    not from the ingested CodeFile set: requirements.txt/Pipfile/
    pyproject.toml aren't parseable source languages, so they're never
    CodeFile rows at all (same reasoning as entry_detection's Dockerfile/
    Procfile scan). The repo root itself is always a candidate -- the
    guaranteed fallback if nothing else is ever promoted."""
    candidates = {""}
    for marker_name in PYTHON_ROOT_MARKER_FILENAMES:
        for p in repo_root.rglob(marker_name):
            if any(part in _IGNORED_DIR_NAMES for part in p.parts):
                continue
            rel_dir = p.parent.relative_to(repo_root).as_posix()
            candidates.add("" if rel_dir == "." else rel_dir)
    return candidates


def find_structural_candidate_roots(python_files: set, unresolved_specifiers: list) -> set:
    """python_files: repo-relative POSIX paths of every ingested .py file.
    unresolved_specifiers: raw specifier strings from unresolved Python
    CodeImport rows (both dotted and bare -- a bare specifier's first
    "component" is the whole string).

    Two structural nominations, independent of marker files:
    1. The parent of any directory that is itself a Python package (directly
       contains __init__.py) -- that parent is what you'd need on sys.path
       to import the package by its own name.
    2. Any directory directly containing a module or package whose name
       matches an unresolved specifier's first dotted component -- this is
       what makes a flat, marker-less app's real root reachable: a bare
       `import crud` failing to resolve anywhere still nominates whichever
       directory actually holds crud.py, with no packaging file required."""
    candidates = set()
    modules_by_name: dict = {}

    for path in python_files:
        basename = posixpath.basename(path)
        if basename == "__init__.py":
            pkg_dir = posixpath.dirname(path)
            pkg_name = posixpath.basename(pkg_dir)
            container = posixpath.dirname(pkg_dir)
            candidates.add(container)
            modules_by_name.setdefault(pkg_name, set()).add(container)
        elif basename.endswith(".py"):
            module_name = basename[:-3]
            modules_by_name.setdefault(module_name, set()).add(posixpath.dirname(path))

    first_components = {
        spec.split(".")[0] for spec in unresolved_specifiers if spec and not spec.startswith(".")
    }
    for component in first_components:
        candidates.update(modules_by_name.get(component, ()))
    return candidates


def is_stdlib_specifier(raw_specifier: str) -> bool:
    """The specifier's first dotted component is a Python standard-library
    top-level module name -- cannot resolve to a file inside any repo, by
    definition, regardless of which root is chosen. sys.stdlib_module_names
    is a zero-cost, zero-design-surface stdlib constant; this is
    deliberately NOT third-party dependency detection (that needs parsing a
    repo's own requirements.txt/pyproject.toml/package.json -- a real
    system, Phase E3's job, not a free check)."""
    return raw_specifier.split(".")[0] in sys.stdlib_module_names


def partition_unresolved_specifiers(rows: list) -> dict:
    """Splits unresolved, non-relative Python import rows into `stdlib`
    (excluded from scoring's denominator -- cannot resolve internally by
    definition) and `not_yet_classified` (everything else: real internal
    misses AND third-party packages, indistinguishable until Phase E3's
    dependency-parsing lands). Only `not_yet_classified` should be passed to
    score_candidate_roots. See this module's docstring for why the
    denominator is reported as named buckets rather than one number."""
    stdlib_rows = [r for r in rows if is_stdlib_specifier(r["raw_specifier"])]
    not_yet_classified_rows = [r for r in rows if not is_stdlib_specifier(r["raw_specifier"])]
    return {"stdlib": stdlib_rows, "not_yet_classified": not_yet_classified_rows}


def root_depth(root: str) -> tuple:
    """Sort key for "deeper" -- more path segments first, longer string as
    a tiebreak (e.g. "backend/app" is deeper than "backend"). Public (no
    leading underscore): Phase E2.3's ingest.py wiring needs it too, to
    order a file's fallback roots deepest-first alongside its own nearest
    promoted root (see nearest_promoted_root below)."""
    if root == "":
        return (0, 0)
    return (root.count("/") + 1, len(root))


def nearest_promoted_root(from_file: str, promoted_roots: set) -> Optional[str]:
    """The DEEPEST promoted root that is an ancestor of (or equal to)
    from_file's own directory -- None if no promoted root governs this
    file at all (e.g. a standalone top-level script when the only promoted
    root is a nested package directory it doesn't live under). Mirrors
    js_root_discovery.config_for_file's ancestor-matching exactly, so both
    languages define "nearest" the same way even though what happens next
    differs: Python falls back to farther promoted roots (see ingest.py),
    TS/JS does not (E2.2's config_for_file is exclusive, no cascading)."""
    from_dir = posixpath.dirname(from_file)
    governing = None
    for root in promoted_roots:
        is_ancestor = root == "" or from_dir == root or from_dir.startswith(root + "/")
        if not is_ancestor:
            continue
        if governing is None or root_depth(root) > root_depth(governing):
            governing = root
    return governing


def score_candidate_roots(candidate_roots: set, unresolved_rows: list, all_paths: set) -> dict:
    """unresolved_rows: [{"from_file": path, "raw_specifier": str, "name": str|None}, ...]
    for every currently-unresolved, non-relative Python CodeImport row in
    this repo. Relative specifiers are excluded before this is called --
    root choice can't affect them (resolve_python_import ignores `roots`
    entirely for a relative specifier).

    Returns {root: {"score": int, "percentage": float, "specifiers": [(raw_specifier, target_path, from_file), ...]}}.

    Verification, not pattern-matching: reuses resolve_imports.resolve_python_import
    exactly as ingest.py's real resolution pass does, checking the
    candidate target against the REAL file set (all_paths) -- a root only
    gets credit for a specifier if the resulting file actually exists.

    Deduplication by resolved TARGET FILE, not by specifier: if the same
    target file is reachable via verified resolutions from more than one
    candidate root (e.g. both the bare repo root and a nested backend/ are
    promoted, and some specifier happens to verify under both), only the
    DEEPEST root keeps credit for that file -- an overlapping shallower
    root must not inflate its own score off a file that really belongs to
    a more specific, already-promoted root."""
    from app.services.codebase.resolve_imports import resolve_python_import  # local import: avoid a module-load-order assumption

    # Defensive, not just documented: a relative specifier resolves
    # identically regardless of `roots` (resolve_python_import ignores the
    # param for it), so every candidate would get the same credit/no-credit
    # for it -- it can never discriminate between roots, only dilute the
    # percentage denominator if a caller forgot to exclude it upstream.
    unresolved_rows = [row for row in unresolved_rows if not row["raw_specifier"].startswith(".")]

    total = len(unresolved_rows)
    hits = []
    for root in candidate_roots:
        for idx, row in enumerate(unresolved_rows):
            target, _is_submodule = resolve_python_import(
                row["raw_specifier"], row["name"], row["from_file"], all_paths, roots=[root]
            )
            if target:
                hits.append({"root": root, "idx": idx, "target": target})

    target_to_roots: dict = {}
    for h in hits:
        target_to_roots.setdefault(h["target"], set()).add(h["root"])
    deepest_root_for_target = {
        target: max(roots, key=root_depth) for target, roots in target_to_roots.items()
    }
    surviving_hits = [h for h in hits if h["root"] == deepest_root_for_target[h["target"]]]

    by_root = {root: {"score": 0, "percentage": 0.0, "specifiers": []} for root in candidate_roots}
    credited_idx_per_root: dict = {root: set() for root in candidate_roots}
    for h in surviving_hits:
        root, idx = h["root"], h["idx"]
        if idx in credited_idx_per_root[root]:
            continue  # same specifier verified under this root via more than one internal fallback -- count once
        credited_idx_per_root[root].add(idx)
        row = unresolved_rows[idx]
        by_root[root]["score"] += 1
        by_root[root]["specifiers"].append((row["raw_specifier"], h["target"], row["from_file"]))

    for info in by_root.values():
        info["percentage"] = info["score"] / total if total else 0.0
    return by_root


def promote_roots(scores: dict, relative_floor: Optional[float] = None, absolute_floor: Optional[int] = None) -> set:
    """A candidate is promoted only if it clears BOTH floors -- a decent
    percentage on a tiny unresolved pool could be 1-2 coincidental hits
    (absolute_floor guards this); a large absolute count on a huge repo
    could still be a small, non-primary slice (relative_floor guards
    this)."""
    config = load_root_discovery_config()
    relative_floor = relative_floor if relative_floor is not None else config["relative_floor"]
    absolute_floor = absolute_floor if absolute_floor is not None else config["absolute_floor"]
    return {
        root for root, info in scores.items()
        if info["percentage"] >= relative_floor and info["score"] >= absolute_floor
    }


def _config_path() -> Path:
    from app.core.config import BACKEND_DIR, settings
    p = Path(settings.ROOT_DISCOVERY_CONFIG_PATH)
    return p if p.is_absolute() else BACKEND_DIR / p


def load_root_discovery_config() -> dict:
    defaults = {"relative_floor": DEFAULT_RELATIVE_FLOOR, "absolute_floor": DEFAULT_ABSOLUTE_FLOOR}
    path = _config_path()
    if not path.is_file():
        return defaults
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {**defaults, **data}
