import logging
import os
import sys
import socket
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import achievements, analytics, arena, auth, briefing, chat, communication, content, interview, missions, modules, oratory, presentation, profile, repos, resources, review, roadmap, roadmaps, topics, vault, voice
from app.core.config import BACKEND_DIR
from app.db import models  # noqa: F401  (register models)

# Schema is Alembic-owned. Safe to re-run: Alembic no-ops once the DB is at head.
# (Replaces the old create_all() + hand-written ALTER TABLE list.)
command.upgrade(AlembicConfig(str(BACKEND_DIR / "alembic.ini")), "head")

# Dev-environment tripwire, same fail-loudly-at-boot category as the clone-
# root-safety check below: this project's local dev backend always binds
# 127.0.0.1:8000. Found live during Phase H1.5 -- two independent
# `uvicorn --reload` processes had been left running from different points
# in one long session (a stray instance never killed, a new one started on
# top of it), which produced several minutes of requests that appeared to
# hang with no error anywhere, because they landed on whichever process's
# worker happened to still be alive and busy. A plain TCP connect attempt
# to the port BEFORE this process tries to bind it: if something already
# answers, refuse to start rather than silently create a second,
# conflicting listener. A normal `--reload` restart is unaffected -- that
# reloader kills the old worker and waits for it to exit before spawning a
# new one, so the port is genuinely free by the time this check runs again.
def _fail_loudly_if_port_already_bound(port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            raise RuntimeError(
                f"127.0.0.1:{port} is already answering -- another backend instance is "
                "still running (or never fully stopped). Kill it before starting a new "
                "one; two overlapping dev servers silently share the port and requests "
                "hang unpredictably instead of failing clearly."
            )


# Not under pytest. The guard answers "am I about to become a SECOND dev server
# on this port"; importing the app to drive it with TestClient binds nothing, so
# the question does not apply -- and answering it anyway made every
# TestClient-based test fail whenever a dev server happened to be running, which
# is most of the time on this machine.
#
# Narrowed rather than removed: the failure it catches is real (two overlapping
# `--reload` workers produced minutes of hanging requests with no error anywhere)
# and it still runs for every non-test start.
#
# `sys.modules`, not PYTEST_CURRENT_TEST: that variable is set per TEST, and this
# module is imported during COLLECTION, before any test runs. Using it failed
# exactly the same way as no guard change at all -- which is the sort of check
# that looks right and is evaluated at the wrong moment.
if "pytest" not in sys.modules:
    _fail_loudly_if_port_already_bound(int(os.environ.get("PORT", "8000")))

# Codebase agent: refuse to start rather than silently ingest the clone cache
# as part of a registered repo's own code. Must run after the migration above
# (the repos table must exist) and must NOT be swallowed like the try/except
# blocks below -- this is a fail-loudly-at-boot check, not best-effort startup work.
from app.db.database import SessionLocal as _SafetyCheckSL
from app.services.codebase.registry import check_clone_root_safety

_safety_db = _SafetyCheckSL()
try:
    check_clone_root_safety(_safety_db)
finally:
    _safety_db.close()

# One-time data unification: mirror existing speeches into the Communication gym.
try:
    from app.db.database import SessionLocal as _SL
    from app.api.communication import backfill_speaking as _bf
    _bdb = _SL()
    _bf(_bdb)
    _bdb.close()
except Exception:
    pass

# Content library: idempotent, re-run on every startup. A bad YAML file logs and
# skips rather than taking the API down.
try:
    from app.services.seed import run_seed as _run_seed

    _run_seed()
except Exception:
    logging.getLogger("athena.seed").exception("Content seeding failed at startup")

# Cheap, always-available staleness check -- same argument as ranking.py's
# resolution-rate tripwire: verifying a live server against its OWN code is
# free, and the alternative is silently drawing conclusions from a stale
# process. Found the hard way: a uvicorn run started hours before Phase G
# was still serving pre-Phase-G behavior with no error of any kind, because
# it wasn't started with --reload. Prefer --reload for local dev; this
# field is the check for when that habit lapses anyway.
_PROCESS_STARTED_AT = models.utcnow()

app = FastAPI(title="ATHENA OS", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in (auth, profile, chat, roadmap, roadmaps, modules, topics, resources, repos, interview, arena, presentation, vault, missions, analytics, voice, briefing, oratory, achievements, review, communication, content):
    app.include_router(module.router)


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "athena-os", "process_started_at": _PROCESS_STARTED_AT.isoformat()}


@app.on_event("startup")
def warmup():
    """Load the embedding model in the background so the first chat doesn't pay 2-4s."""
    import threading

    def _warm():
        try:
            from app.services.vector_store import client

            client()
        except Exception:
            pass

    threading.Thread(target=_warm, daemon=True).start()


frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if frontend_dist.exists():
    assets_dir = frontend_dist / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_frontend(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")

        requested_file = frontend_dist / full_path
        if requested_file.is_file():
            return FileResponse(requested_file)

        return FileResponse(frontend_dist / "index.html")
