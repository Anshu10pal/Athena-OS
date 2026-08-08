"""Phase D: background execution for resync+ingest+rank, decoupled from any
HTTP request -- the job keeps running in its own thread with its own DB
session even if the client that started it disconnects. This is the real
background-job mechanism the Phase 0 audit found missing: the existing chat
SSE endpoint only streams while computing within one request; it isn't
something you can start, walk away from, and reattach to.

Progress state lives in the repo_jobs row, not in memory -- a reconnecting
SSE client or a page reload just reads current state; there is no in-process
pub/sub to lose.
"""
import threading
import time
from datetime import datetime, timezone

from app.db.database import SessionLocal
from app.db.models import Repo, RepoJob
from app.services.codebase import registry
from app.services.codebase.ingest import ingest_repo
from app.services.codebase.ranking import rank_repo

_PROGRESS_WRITE_INTERVAL = 0.3  # seconds -- avoid a DB write on every single file


def start_job(repo_id: int) -> int:
    """Returns the job id -- either a freshly created one, or an already
    in-flight job for this repo (never runs two ingests for the same repo
    concurrently; that could corrupt code_symbols/code_imports rows)."""
    db = SessionLocal()
    try:
        repo = db.get(Repo, repo_id)
        if repo is None:
            raise ValueError(f"Repo {repo_id} not found")
        existing = (
            db.query(RepoJob)
            .filter(RepoJob.repo_id == repo_id, RepoJob.status.in_(["queued", "running"]))
            .order_by(RepoJob.created_at.desc())
            .first()
        )
        if existing:
            return existing.id
        job = RepoJob(repo_id=repo_id, status="queued", stage="queued")
        db.add(job)
        db.commit()
        db.refresh(job)
        job_id = job.id
    finally:
        db.close()

    threading.Thread(target=_run_job, args=(job_id,), daemon=True).start()
    return job_id


def _run_job(job_id: int) -> None:
    db = SessionLocal()
    try:
        job = db.get(RepoJob, job_id)
        repo = db.get(Repo, job.repo_id)
        job.status = "running"
        job.started_at = datetime.now(timezone.utc)
        db.commit()

        last_write = 0.0

        def progress(stage: str, current: int, total: int, message: str) -> None:
            nonlocal last_write
            job.stage = stage
            job.progress_current = current
            job.progress_total = total
            job.message = message
            now = time.monotonic()
            if now - last_write >= _PROGRESS_WRITE_INTERVAL or current == total:
                db.commit()
                last_write = now

        if repo.source_kind == "clone":
            progress("resyncing", 0, 0, "Fetching latest changes")
            registry.resync(db, repo)

        report = ingest_repo(db, repo, on_progress=progress)
        rank_result = rank_repo(db, repo, on_progress=progress)

        job.status = "done"
        job.stage = "done"
        job.progress_current = job.progress_total
        job.result = {
            "files_total": report.files_total,
            "files_parsed": report.files_parsed,
            "files_skipped_unchanged": report.files_skipped_unchanged,
            "files_deleted": report.files_deleted,
            "symbols_total": report.symbols_total,
            "imports_total": report.imports_total,
            "imports_resolved": report.imports_resolved,
            "blind_spots": report.blind_spots,
            "reduced_confidence": rank_result["reduced_confidence"],
        }
        job.finished_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as e:
        db.rollback()
        job = db.get(RepoJob, job_id)
        job.status = "failed"
        job.error = str(e)
        job.finished_at = datetime.now(timezone.utc)
        db.commit()
    finally:
        db.close()
