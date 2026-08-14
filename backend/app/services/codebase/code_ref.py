"""Phase 4 groundwork: constructing and validating a reference to code.

PURE AND UNWIRED. Nothing writes a code_ref yet; these columns exist on
`resources` and no code path populates them. This is the constructor that will
be used when one does, written now so the validation rules are settled before
any row carries them.

Why a constructor rather than "just set the columns": a code reference has
invariants that a nullable column cannot express, and every one of them has a
failure mode that is silent rather than loud.

  * A line range with no SHA points at a MOVING TARGET. Line 340 of a file
    means nothing without the revision it was read from; re-ingest the repo a
    week later and the reference is wrong with no error anywhere. This is the
    invariant most likely to be skipped as pedantic and the one that decays
    fastest.
  * `line_end` before `line_start` is a silently empty range, not an error.
  * A path is repo-relative. An absolute path, or one containing `..`, is
    either a different machine's filesystem or an escape, and both look
    plausible in a VARCHAR.
  * A whole-file reference is legitimate and must be distinguishable from a
    range that failed to compute -- so both lines are null together, never one.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

# git object names: 40 hex for SHA-1, 64 for SHA-256. Both accepted; anything
# else is not a commit id, including a branch name or "HEAD", which are the two
# things most likely to be passed by mistake and are not fixed points.
_SHA = re.compile(r"^[0-9a-f]{40}$|^[0-9a-f]{64}$")


class InvalidCodeRef(ValueError):
    """Raised rather than returning a partly-valid reference. A code_ref that is
    almost right is worse than none: it renders, it looks authoritative, and it
    points somewhere wrong."""


@dataclass(frozen=True)
class CodeRef:
    repo_id: int
    path: str
    commit_sha: str
    line_start: Optional[int] = None
    line_end: Optional[int] = None

    @property
    def is_whole_file(self) -> bool:
        return self.line_start is None and self.line_end is None

    def to_columns(self) -> dict:
        """The `resources` column names, ready to splat into a row when
        something is eventually allowed to write one."""
        return {
            "code_repo_id": self.repo_id,
            "code_path": self.path,
            "code_line_start": self.line_start,
            "code_line_end": self.line_end,
            "code_commit_sha": self.commit_sha,
        }

    def describe(self) -> str:
        """Human-facing, and honest about the whole-file case."""
        if self.is_whole_file:
            return f"{self.path} @ {self.commit_sha[:7]}"
        if self.line_start == self.line_end:
            return f"{self.path}:{self.line_start} @ {self.commit_sha[:7]}"
        return f"{self.path}:{self.line_start}-{self.line_end} @ {self.commit_sha[:7]}"


def make_code_ref(
    *,
    repo_id: int,
    path: str,
    commit_sha: str,
    line_start: Optional[int] = None,
    line_end: Optional[int] = None,
) -> CodeRef:
    """Build a validated CodeRef, or raise InvalidCodeRef.

    Every rule here is a rule about something that would otherwise fail
    silently -- see the module docstring. Nothing is rejected merely for being
    unusual.
    """
    if not isinstance(repo_id, int) or repo_id <= 0:
        raise InvalidCodeRef(f"repo_id must be a positive integer, got {repo_id!r}")

    path = (path or "").strip()
    if not path:
        raise InvalidCodeRef("path is required")
    if path.startswith("/") or re.match(r"^[A-Za-z]:[\\/]", path):
        raise InvalidCodeRef(
            f"path must be repo-relative, got the absolute path {path!r} -- an absolute "
            "path is a location on one machine and means nothing on another"
        )
    if "\\" in path:
        raise InvalidCodeRef(
            f"path must use forward slashes to match CodeFile.path, got {path!r}"
        )
    if ".." in path.split("/"):
        raise InvalidCodeRef(f"path must not contain '..', got {path!r}")

    sha = (commit_sha or "").strip().lower()
    if not sha:
        raise InvalidCodeRef(
            "commit_sha is required: line numbers are only meaningful against the "
            "revision they were computed from, and a reference without one goes stale "
            "silently rather than visibly"
        )
    if not _SHA.match(sha):
        raise InvalidCodeRef(
            f"commit_sha must be a full 40- or 64-character git object name, got "
            f"{commit_sha!r} -- a branch name or 'HEAD' is not a fixed point"
        )

    if (line_start is None) != (line_end is None):
        raise InvalidCodeRef(
            "line_start and line_end must both be set or both be null: one alone cannot "
            "be told apart from a range that failed to compute"
        )
    if line_start is not None:
        if line_start < 1 or line_end < 1:
            raise InvalidCodeRef(
                f"line numbers are 1-based, got {line_start}-{line_end}"
            )
        if line_end < line_start:
            raise InvalidCodeRef(
                f"line_end {line_end} is before line_start {line_start}: a reversed range "
                "selects nothing and reads as a valid reference"
            )

    return CodeRef(repo_id=repo_id, path=path, commit_sha=sha,
                   line_start=line_start, line_end=line_end)


def is_stale(ref: CodeRef, current_commit_sha: Optional[str]) -> bool:
    """Whether this reference was computed against a different revision.

    Unknown current SHA is NOT stale: an unknown answer must not be reported as
    a positive finding. Same exclude-don't-zero reasoning used for missing
    health inputs.
    """
    if not current_commit_sha:
        return False
    return ref.commit_sha != current_commit_sha.strip().lower()
