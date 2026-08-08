"""Per-repo advisory lock: ingest and rank must never run concurrently for
the same repo_id.

Phase E2.3's ingest re-resolves every import row in place across two
stages within one ingest_repo call. A rank read that lands in the same
window as a concurrent ingest for the same repo -- another request thread,
a background job (app/services/codebase/jobs.py), a leftover "Sync & Rank"
click -- risks observing an inconsistent view of that repo's graph. This
lock makes that window impossible to enter concurrently, rather than
trying to prove it can't be observed.

Scope, stated plainly: this is a single-process, in-memory lock. It
protects every caller running inside the same Python process -- the
FastAPI app's request threads and jobs.py's background daemon threads,
which is the real deployment shape (jobs.py opens its own SessionLocal in
a thread, not a separate process). It does NOT protect against two
separate OS processes (e.g. a live server plus a standalone script)
racing on the same SQLite file -- that would need a cross-process
advisory lock (a lock table, or SQLite's own file locking via BEGIN
IMMEDIATE), which is more than this phase's incident calls for.
"""
import threading
from contextlib import contextmanager

_locks: dict = {}
_locks_guard = threading.Lock()


class RepoBusyError(RuntimeError):
    pass


def _lock_for(repo_id: int) -> threading.Lock:
    with _locks_guard:
        lock = _locks.get(repo_id)
        if lock is None:
            lock = threading.Lock()
            _locks[repo_id] = lock
        return lock


@contextmanager
def repo_lock(repo_id: int, operation: str):
    """Raises RepoBusyError immediately (never blocks/waits) if this repo
    is already busy -- a caller silently queueing behind a lock it can't
    see would just move the race to "which one committed last" instead of
    removing it; refusing outright makes the conflict visible to whoever
    (or whatever job runner) tried to start the second operation."""
    lock = _lock_for(repo_id)
    if not lock.acquire(blocking=False):
        raise RepoBusyError(
            f"Repo {repo_id} is already busy with another ingest/rank operation -- "
            f"refusing to start {operation} concurrently."
        )
    try:
        yield
    finally:
        lock.release()
