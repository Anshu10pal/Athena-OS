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
from app.services.codebase.graph_structure import persist_graph_structure
from app.services.codebase.health_snapshots import create_snapshot, should_create_snapshot
from app.services.codebase.ingest import ingest_repo
from app.services.codebase.ranking import rank_repo
from app.services.codebase.subsystems import compute_subsystems

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


def _run_clustering_stage(db, repo, progress) -> dict:
    """Subsystem clustering, in the pipeline rather than only on demand.

    It was previously reachable ONLY through POST /subsystems, which nothing in
    the normal path calls -- so every repo analysed the way a user actually
    analyses one had an empty Dependency Clusters tab. Found on
    apache/superset: 6,516 files, a complete import graph, and CLUSTERS reading
    0 on the Overview. A whole phase of work invisible to anyone who did not
    know to invoke it directly.

    Only modularity + Louvain run here. HDBSCAN stays on demand deliberately:
    it embeds every file's symbol text, which is real CPU work, where these two
    are near-instant graph maths over a graph that already exists.

    Same error boundary as the health stage below, for the same reason -- this
    is derived output, and losing a completed ingest because a clustering pass
    failed would be the expensive half thrown away for the cheap half. Runs
    AFTER rank_repo has released the per-repo lock, since compute_subsystems
    takes that lock itself.
    """
    try:
        progress("clustering", 0, 3, "Grouping files into subsystems")
        result = compute_subsystems(db, repo, on_progress=progress)
        algorithms = result.get("algorithms", {})
        return {
            "status": "computed",
            "modularity_clusters": algorithms.get("modularity", {}).get("cluster_count"),
            "louvain_clusters": algorithms.get("louvain", {}).get("cluster_count"),
            "agreement": result.get("agreement"),
            "retryable": False,
        }
    except Exception as e:
        db.rollback()
        print(f"[clustering] repo {repo.id}: stage failed, ingest/rank unaffected: {e}")
        return {"status": "failed", "error": str(e), "retryable": True}


def _run_health_stage(db, repo, progress) -> dict:
    """The health stage's own error boundary.

    Returns a stage record rather than raising, so a failure here can never
    fail the job or undo the ingest/rank work that already committed. Marked
    `retryable` because every failure mode this can hit (a file disappearing
    mid-run, a parser crash, a transient DB error) is fixed by running again,
    not by intervention.
    """
    try:
        progress("health", 0, 0, "Computing code health")
        persist_graph_structure(db, repo)
        decision = should_create_snapshot(db, repo)
        if not decision.should_create:
            return {"status": "skipped", "reason": decision.reason, "retryable": False}
        snapshot = create_snapshot(db, repo, on_progress=progress)
        return {
            "status": "created",
            "snapshot_id": snapshot.id,
            "reason": decision.reason,
            "retryable": False,
        }
    except Exception as e:
        # create_snapshot already rolled back its own transaction; this
        # rollback covers persist_graph_structure and leaves the session
        # usable for the job's own final commit.
        db.rollback()
        print(f"[health] repo {repo.id}: stage failed, ingest/rank unaffected: {e}")
        return {"status": "failed", "error": str(e), "retryable": True}


def _run_job(job_id: int) -> None:
    # expire_on_commit=False, and this is a correctness-shaped perf fix rather
    # than a tuning knob.
    #
    # `progress` below commits so the SSE stream can see the row change. Under
    # SQLAlchemy's default, every one of those commits expires ALL loaded
    # objects -- and by the resolution stage this session holds ~90k of them
    # (6,522 files + 22,856 symbols + 60,865 imports). The loop then re-SELECTs
    # each row the moment it touches an attribute, so a UI progress tick was
    # silently paying to reload the working set.
    #
    # Measured on apache/superset, same repo, output identical
    # (imports_resolved=26,557 in every condition):
    #
    #     resolving, expire_on_commit=True     43-67s
    #     resolving, expire_on_commit=False       11s
    #
    # Raising _PROGRESS_WRITE_INTERVAL was the obvious alternative and is a bad
    # one: the saving is sharply sublinear (170 commits -> 0.42s each, 21
    # commits -> 2.07s each), because rarer commits expire more rows per storm.
    # Worse, commit count is time-driven, so a slow run takes more ticks and
    # commits more, which makes it slower -- duration and commit count feed each
    # other. Removing the expiry breaks that loop; lengthening the interval only
    # loosens it.
    #
    # Safe here specifically because this session is the sole writer for the
    # duration: ingest holds the repo advisory lock (repo_lock.py), so there is
    # no concurrent mutation whose value this session could go stale against.
    # This is deliberately NOT applied to SessionLocal globally -- request
    # sessions serving concurrent writers do want the default.
    db = SessionLocal(expire_on_commit=False)
    try:
        job = db.get(RepoJob, job_id)
        repo = db.get(Repo, job.repo_id)
        job.status = "running"
        job.started_at = datetime.now(timezone.utc)
        db.commit()

        last_write = 0.0

        # Per-stage wall time, measured where the stage actually changes.
        #
        # The SSE stream cannot be used for this. `progress` assigns job.stage
        # immediately but COMMITS only every _PROGRESS_WRITE_INTERVAL, and the
        # stream polls the committed row -- so an observer sees a transition up
        # to one interval late, and worse, a stage that emits nothing for a
        # while has that silence charged to whichever stage last managed a
        # write. Reading stage times off the stream once put 6.7s on `cleanup`,
        # a stage independently measured at 0.01s; the time belonged to
        # `resolving`, which had simply not written yet.
        #
        # These marks are taken in-process at the transition itself, so they do
        # not inherit the throttle. Ten-ish entries per job, appended on stage
        # change only -- not per file.
        stage_marks: list[tuple[str, float]] = []

        def progress(stage: str, current: int, total: int, message: str) -> None:
            nonlocal last_write
            if not stage_marks or stage_marks[-1][0] != stage:
                stage_marks.append((stage, time.monotonic()))
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

        # Health runs LAST and is deliberately isolated. ingest and rank have
        # already committed by this point, so nothing here can roll them back
        # -- a health failure is recorded as a retryable stage result and the
        # job still reports done, because the ingest/rank work is real and
        # useful on its own. It would be wrong to throw that away because a
        # scoring pass failed.
        #
        # Conditional, not unconditional: without the source-content check an
        # automatic pipeline manufactures a duplicate snapshot on every run
        # and fills the trend line with identical points. Note the check
        # compares a content fingerprint rather than HEAD -- two different
        # sets of uncommitted edits share a SHA and dirty=True, so those
        # cannot identify a working tree.
        #
        # Still zero outbound AI: this stage is AST parsing, git history and
        # graph maths only, same as every other stage here.
        clustering_stage = _run_clustering_stage(db, repo, progress)
        health_stage = _run_health_stage(db, repo, progress)

        job.status = "done"
        job.stage = "done"
        job.progress_current = job.progress_total
        stage_marks.append(("done", time.monotonic()))
        job.result = {
            # Seconds per stage, in execution order. A stage that runs more
            # than once (none currently do) would appear once per run.
            "stage_seconds": [
                {"stage": stage_marks[i][0], "seconds": round(stage_marks[i + 1][1] - stage_marks[i][1], 2)}
                for i in range(len(stage_marks) - 1)
            ],
            "files_total": report.files_total,
            "files_parsed": report.files_parsed,
            "files_skipped_unchanged": report.files_skipped_unchanged,
            "files_deleted": report.files_deleted,
            "symbols_total": report.symbols_total,
            "imports_total": report.imports_total,
            "imports_resolved": report.imports_resolved,
            "blind_spots": report.blind_spots,
            "reduced_confidence": rank_result["reduced_confidence"],
            "clustering": clustering_stage,
            "health": health_stage,
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
