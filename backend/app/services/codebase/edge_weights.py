"""Phase F1: edge KIND classification -- a cheap proxy for import coupling
strength, using occurrence counts of the locally-bound name in the importing
file's own body, plus a few structural special cases occurrence counts alone
can't distinguish (class-base inheritance, call expressions, re-exports,
test-file provenance, unresolvable local bindings).

Deliberately not full usage analysis (that would need a real type-aware
symbol resolver) -- an occurrence-count proxy, as directed.

Kind is a fact about the code, computed once at parse time and stored on
the CodeImport row. The numeric WEIGHT per kind is a tunable parameter that
lives in config/edge_weights.yaml and is resolved at scoring time (Phase F3),
not here -- retuning a weight must never require re-parsing every file.

The one piece of "priority" needed here (which of several competing usage
signals wins) is a fixed structural ordering, not a tunable weight:
inherits is definitionally tighter coupling than a call, which is tighter
than heavy incidental use, and so on. That ordering doesn't change when
someone retunes the numbers in config, so it's a constant here, not a
config read.
"""
import re
from pathlib import Path
from typing import Optional

import yaml

# Provenance-based kinds (test_edge, reexport, unresolvable_binding) are
# checked first and short-circuit -- they describe a fundamentally different
# relationship, not a competing signal about the same one. Within the
# remaining usage-analysis group, this fixed order breaks ties when several
# apply (e.g. an imported name used in both a call and 6 other places is
# `calls`, not `heavy_use`) -- highest-coupling first.
USAGE_KIND_PRIORITY = ("inherits", "calls", "heavy_use", "light_use", "type_only")

ALL_KINDS = ("inherits", "calls", "heavy_use", "light_use", "type_only", "reexport", "test_edge", "unresolvable_binding")

# Directory names that make everything beneath them a test, checked as PATH
# SEGMENTS rather than as substrings. The substring version this replaced
# used "/tests/", which requires a leading slash and therefore matched a
# nested tests/ directory but never a TOP-LEVEL one -- so eslint/eslint's
# entire 963-file tests/ tree and 443 of Superset's test files were
# classified as ordinary source and their import edges weighted as real
# coupling instead of test_edge's 0.05. Segment matching has no such
# position dependency; it is also what stops "latest_version.py" and
# "contest.py" from matching, which a bare "test" substring would.
TEST_DIR_SEGMENTS = frozenset({"test", "tests", "__tests__", "__mocks__", "spec", "specs"})

# Filename conventions, applied to the BASENAME only. Anchored at a word
# boundary of "_", "." or "-" on at least one side in every branch, which is
# what keeps "testing_utils.py" (test infrastructure, not a test) and
# "latest_thing.py" out while admitting test_x.py, x_test.py, x_tests.py,
# x.test.ts, x.spec.ts and conftest.py. A `conftest.py`-sibling rule was
# considered and measured: on both Python repos here it flagged zero files
# the segment rule had not already caught, so it was not worth the
# directory-listing argument it would have required.
TEST_FILENAME_RE = re.compile(
    r"^test[_.\-]"
    r"|[_.\-]tests?[_.\-]"
    r"|[_.\-]tests?\."
    r"|\.spec\."
    r"|^conftest\.py$"
)

_HEAVY_USE_THRESHOLD = 5

DEFAULT_WEIGHTS = {
    "inherits": 1.0, "calls": 0.8, "heavy_use": 0.8, "light_use": 0.4,
    "type_only": 0.25, "reexport": 0.15, "test_edge": 0.05, "unresolvable_binding": 0.7,
}


def _weights_path() -> Path:
    from app.core.config import BACKEND_DIR, settings
    p = Path(settings.EDGE_WEIGHTS_PATH)
    return p if p.is_absolute() else BACKEND_DIR / p


def load_edge_weights() -> dict:
    """kind -> weight, read fresh from config/edge_weights.yaml every call --
    resolved at scoring time (Phase F3), never baked into a stored row, so
    retuning a number here never requires re-parsing anything. A missing or
    unreadable file falls back to DEFAULT_WEIGHTS rather than crashing."""
    path = _weights_path()
    if not path.is_file():
        return dict(DEFAULT_WEIGHTS)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    weights = data.get("weights") or {}
    return {**DEFAULT_WEIGHTS, **weights}


def resolve_weight(kind: str, weights: Optional[dict] = None) -> float:
    weights = weights if weights is not None else load_edge_weights()
    return weights.get(kind, DEFAULT_WEIGHTS.get(kind, 0.0))


def is_test_file(path: str) -> bool:
    """Structural, not marker-list-based: a path is a test if any DIRECTORY
    segment names a test directory, or if the basename follows a test-file
    naming convention. Backslashes are normalized first -- CodeFile.path is
    POSIX, but this is also called with raw paths during ingest on Windows."""
    segments = path.replace("\\", "/").lower().split("/")
    if any(segment in TEST_DIR_SEGMENTS for segment in segments[:-1]):
        return True
    return bool(TEST_FILENAME_RE.search(segments[-1]))


def _appears_in_bases_list(source_text: str, name: str) -> bool:
    """Heuristic (regex, not AST): `class X(name` or `class X(..., name`."""
    pattern = re.compile(r"class\s+\w+\s*\([^)]*\b" + re.escape(name) + r"\b")
    return bool(pattern.search(source_text))


def _appears_in_call_position(source_text: str, name: str) -> bool:
    """Heuristic: `name(` -- also matches `name.method(` type call chains
    via the same \\bname\\b token match used for occurrence counting."""
    pattern = re.compile(r"\b" + re.escape(name) + r"\s*\(")
    return bool(pattern.search(source_text))


def occurrence_count_after_line(source_text: str, name: str, boundary_line: int) -> int:
    """Counts \\bname\\b occurrences strictly after boundary_line (1-indexed).

    Excluding everything up to and including the file's own import block
    (not just this one import's declaration line) does two things: it never
    trivially counts an import's own declaration as a "use", and it reduces
    -- does not eliminate -- the risk of attributing the same body tokens to
    two different imports that happen to bind the same local name in one
    file (a shadowing re-import, or a local variable that happens to share
    the name). That residual ambiguity is accepted, not resolved further --
    plain occurrence counting has no way to tell which binding a given token
    refers to without a real scope-aware resolver.

    Caveat: a deferred/scattered import (e.g. one placed mid-function to
    dodge a circular import) pushes the whole file's boundary_line later
    than the "real" top-level import block, which can under-count body usage
    that occurs between the top-level imports and that later one.
    """
    if not name:
        return 0
    pattern = re.compile(r"\b" + re.escape(name) + r"\b")
    lines = source_text.splitlines()
    body = "\n".join(lines[boundary_line:])  # boundary_line is 1-indexed; this keeps only lines after it
    return len(pattern.findall(body))


def classify_edge(
    *,
    source_text: str,
    local_name: Optional[str],
    original_name: Optional[str],
    import_block_end_line: int,
    from_file_path: str,
    is_reexport: bool,
) -> str:
    """Returns one of ALL_KINDS. Never raises on missing/odd input -- a
    misclassified edge is far cheaper than a crashed ingest."""
    if is_test_file(from_file_path):
        return "test_edge"
    if is_reexport:
        return "reexport"
    if not local_name or original_name == "*":
        return "unresolvable_binding"

    matches = set()
    if _appears_in_bases_list(source_text, local_name):
        matches.add("inherits")
    if _appears_in_call_position(source_text, local_name):
        matches.add("calls")

    count = occurrence_count_after_line(source_text, local_name, import_block_end_line)
    if count >= _HEAVY_USE_THRESHOLD:
        matches.add("heavy_use")
    elif count >= 1:
        matches.add("light_use")
    else:
        matches.add("type_only")

    for kind in USAGE_KIND_PRIORITY:
        if kind in matches:
            return kind
    return "type_only"  # unreachable -- the loop above always finds one of the three usage-count kinds
