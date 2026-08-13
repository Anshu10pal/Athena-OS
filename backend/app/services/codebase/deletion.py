"""Removing a repo: its rows, and -- only when Athena created it -- its clone.

Until this existed there was no way to remove a repo at all. Every registration
was permanent, including test ones, and clearing a repo meant hand-written SQL
across eight tables.

Why the directory guard has TWO conditions
------------------------------------------
A directory is deleted only when BOTH hold:

    1. repo.source_kind == "clone"                      -- a flag someone set
    2. the resolved local_path is inside the resolved
       clone cache root                                 -- a property of the path

Either alone would be enough on a good day. Both are required because the
failure mode is unrecoverable and the blast radius is real: repo 1 in this
project's own database is `source_kind="local"` pointing at
`D:\\Athena\\Athena\\athena-os` -- the working tree of Athena itself. A bug that
deleted a `local` repo's directory would destroy the codebase under
development, with no undo and nothing in git for uncommitted work.

Condition 1 is a claim recorded at registration time. Condition 2 is checked
against the filesystem now. They fail independently, which is the whole point:
if `source_kind` were ever wrong, containment still refuses. This is §17.15 --
a flag is list-shaped, containment is property-shaped -- applied where being
wrong costs the most.

Both paths are `.resolve()`d before comparison. A relative `local_path`, a
symlink, or a `..` segment would each defeat a naive string prefix test, and
`Path.resolve()` normalises all three.

Why the delete order is written out rather than left to the ORM
---------------------------------------------------------------
Nothing cascades. Every foreign key into `repos` is `ON DELETE NO ACTION`, so
deletion is entirely manual.

Worse, the schema contains a CYCLE:

    code_files.subsystem_{modularity,louvain,hdbscan}_id -> code_subsystems.id
    code_subsystems.top_fan_in_file_id                   -> code_files.id

No ordering of whole-table deletes satisfies both. Deleting files first violates
`top_fan_in_file_id`; deleting subsystems first violates `subsystem_*_id`. The
cycle is broken by nulling the file side before deleting subsystems.

This is load-bearing rather than theoretical: `requirements.txt` ships
`psycopg2-binary` and the README documents `DATABASE_URL` as "Point at Postgres
in production", where foreign keys ARE enforced. Locally SQLite runs with
`PRAGMA foreign_keys = 0`, so every wrong order passes here and fails only on a
database this machine cannot inspect -- the same environment trap as `text=True`
decoding cp1252 on Windows and UTF-8 on Render. The deletion tests therefore
turn foreign keys ON explicitly, or they would document intent without pinning
behaviour.
"""
from __future__ import annotations

import os
import shutil
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.models import Repo
from app.services.codebase import registry

# Executed in order, inside one transaction. Children before parents; see the
# module docstring for the cycle and why the UPDATE sits where it does.
#
# Each entry is (label, SQL). The label is what the caller reports, so the
# report and the work cannot drift apart -- there is one list, not a list of
# statements plus a separate list of names.
_DELETE_PLAN: list[tuple[str, str]] = [
    # Reaches the repo only through two parents, so it must go before both.
    ("code_file_health",
     "delete from code_file_health where snapshot_id in "
     "(select id from code_health_snapshots where repo_id = :rid)"),
    # Before code_symbols: code_imports.to_symbol_id references it.
    ("code_imports", "delete from code_imports where repo_id = :rid"),
    ("code_symbols",
     "delete from code_symbols where file_id in "
     "(select id from code_files where repo_id = :rid)"),
    ("code_file_ranks", "delete from code_file_ranks where repo_id = :rid"),
    ("code_health_snapshots", "delete from code_health_snapshots where repo_id = :rid"),
    # Breaks the code_files <-> code_subsystems cycle. Counted separately from
    # the deletes because it removes no rows -- reporting it as a deletion
    # count would overstate what was destroyed.
    ("code_files.subsystem_ids (nulled)",
     "update code_files set subsystem_modularity_id = null, "
     "subsystem_louvain_id = null, subsystem_hdbscan_id = null where repo_id = :rid"),
    ("code_subsystems", "delete from code_subsystems where repo_id = :rid"),
    ("code_files", "delete from code_files where repo_id = :rid"),
    ("repo_jobs", "delete from repo_jobs where repo_id = :rid"),
    ("repos", "delete from repos where id = :rid"),
]

# Counted BEFORE deleting, so the report describes what was actually there.
_COUNT_PLAN: list[tuple[str, str]] = [
    ("code_files", "select count(*) from code_files where repo_id = :rid"),
    ("code_symbols",
     "select count(*) from code_symbols where file_id in "
     "(select id from code_files where repo_id = :rid)"),
    ("code_imports", "select count(*) from code_imports where repo_id = :rid"),
    ("code_file_ranks", "select count(*) from code_file_ranks where repo_id = :rid"),
    ("code_subsystems", "select count(*) from code_subsystems where repo_id = :rid"),
    ("code_health_snapshots", "select count(*) from code_health_snapshots where repo_id = :rid"),
    ("code_file_health",
     "select count(*) from code_file_health where snapshot_id in "
     "(select id from code_health_snapshots where repo_id = :rid)"),
    ("repo_jobs", "select count(*) from repo_jobs where repo_id = :rid"),
]


class RepoDeletionRefused(RuntimeError):
    """The caller asked for something this function will not do."""


@dataclass
class DeletionReport:
    repo_id: int
    label: str
    source_kind: str
    rows_deleted: dict[str, int] = field(default_factory=dict)
    directory_deleted: bool = False
    directory_path: Optional[str] = None
    # Always populated, including on success -- "why this directory was or was
    # not removed" is the part a reader needs, and a bare boolean does not carry
    # it.
    directory_reason: str = ""

    @property
    def rows_total(self) -> int:
        return sum(self.rows_deleted.values())

    def to_dict(self) -> dict:
        return {
            "repo_id": self.repo_id,
            "label": self.label,
            "source_kind": self.source_kind,
            "rows_deleted": self.rows_deleted,
            "rows_total": self.rows_total,
            "directory_deleted": self.directory_deleted,
            "directory_path": self.directory_path,
            "directory_reason": self.directory_reason,
        }


def repo_label(repo: Repo) -> str:
    """What the caller must type back to confirm. Uses owner/name rather than
    the id: an id is easy to mistype into another repo that also exists, and a
    confirmation that can silently name a DIFFERENT valid target is not a
    confirmation."""
    return f"{repo.owner}/{repo.name}"


def _on_rm_error(func, path, _exc_info):
    """Git object files are read-only, and `shutil.rmtree` fails partway through
    a clone without this -- leaving a half-deleted directory that is neither a
    working repo nor gone.

    Observed on this project: clearing the clone cache with PowerShell's
    `Remove-Item` failed the same way and needed `rmdir /s /q`. `rmtree` needs
    the equivalent, which is to clear the read-only bit and retry the operation
    that failed."""
    os.chmod(path, stat.S_IWRITE)
    func(path)


def clone_directory_verdict(repo: Repo) -> tuple[bool, str]:
    """(may_delete, reason). Never raises -- the reason is reported either way.

    Both conditions are evaluated even when the first fails, so the reason names
    the actual disagreement rather than the first check to trip.

    DO NOT SIMPLIFY THE TWO CONDITIONS INTO ONE. They look redundant and are
    not. `source_kind` is a claim recorded at registration; containment is
    checked against the filesystem now, and they fail independently.

    The reason this is worth two checks rather than one: repo 1 in this
    project's own database is `source_kind="local"` with
    `local_path=D:\\Athena\\Athena\\athena-os` -- the working tree of Athena
    itself. If that flag were ever wrong, or a future registration path set it
    wrong, a single-condition guard would delete the codebase under development,
    including everything uncommitted. Containment refuses independently of what
    the flag says.
    """
    if not repo.local_path:
        return False, "No local path recorded for this repo; nothing on disk to remove."

    path = Path(repo.local_path)
    try:
        resolved = path.resolve()
        root = registry.clone_cache_root().resolve()
    except OSError as e:
        return False, f"Could not resolve the path to check it is inside the clone cache: {e}"

    is_clone = repo.source_kind == "clone"
    inside = resolved == root or root in resolved.parents

    if is_clone and inside:
        return True, f"Athena cloned this repo into its own cache ({resolved}), so the clone is removed."
    if not is_clone:
        return False, (
            f"source_kind is {repo.source_kind!r}, so {resolved} is a directory you registered rather "
            "than one Athena created. Database rows were removed; the directory was left untouched."
        )
    return False, (
        f"source_kind is 'clone' but {resolved} is not inside the clone cache ({root}). "
        "Refusing to delete a directory outside the cache even though the repo claims to be a clone."
    )


def delete_repo(db: Session, repo: Repo, confirm: str) -> DeletionReport:
    """Delete a repo's rows, and its clone directory when Athena created it.

    Irreversible. The caller must pass `confirm` equal to `repo_label(repo)`.

    The caller is responsible for holding the repo lock -- see the API layer.
    Doing it here would hide a busy repo behind a generic failure instead of a
    409 naming the job.
    """
    label = repo_label(repo)
    if confirm != label:
        raise RepoDeletionRefused(
            f"Confirmation did not match: expected {label!r}, got {confirm!r}. Nothing was deleted."
        )

    repo_id = repo.id
    source_kind = repo.source_kind
    may_delete_dir, reason = clone_directory_verdict(repo)
    directory_path = str(Path(repo.local_path).resolve()) if repo.local_path else None

    counts = {
        name: db.execute(text(sql), {"rid": repo_id}).scalar() or 0
        for name, sql in _COUNT_PLAN
    }

    # Rows first. If the directory removal fails afterwards the rows are still
    # gone and the repo is unregistered, which is recoverable -- a leftover
    # directory can be removed by hand. The reverse is not: a deleted clone with
    # rows still pointing at it leaves a repo that looks ingested and whose
    # files have vanished.
    for name, sql in _DELETE_PLAN:
        db.execute(text(sql), {"rid": repo_id})
    db.commit()

    report = DeletionReport(
        repo_id=repo_id,
        label=label,
        source_kind=source_kind,
        rows_deleted=counts,
        directory_path=directory_path,
        directory_reason=reason,
    )

    if may_delete_dir and directory_path and Path(directory_path).exists():
        shutil.rmtree(directory_path, onerror=_on_rm_error)
        report.directory_deleted = True
    elif may_delete_dir:
        report.directory_deleted = False
        report.directory_reason = (
            f"{reason} The directory was already absent, so nothing was removed."
        )

    return report
