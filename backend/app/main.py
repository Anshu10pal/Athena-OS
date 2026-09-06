import logging
import os
import sys
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

# THE PORT GUARD LIVES IN run.py NOW. Do not reintroduce it here.
#
# Moved 2026-09-04 (17.16 -- the reasoning is kept, because the reasoning is
# the record). The guard itself was never wrong; it was in the wrong PROCESS.
# `uvicorn.run(reload=True)` has the RELOADER PARENT bind the listening socket,
# and the worker inherits fd 3 -- so a connect_ex probe run at worker-import
# time is STRUCTURALLY GUARANTEED to find its own parent answering, and to kill
# the worker it was meant to protect. The parent keeps the port, so the result
# is a port that LISTENS and never replies: a server that reads as hung rather
# than dead, which is the hardest failure of the three to diagnose.
#
# The old comment here asserted the opposite in so many words -- "A normal
# `--reload` restart is unaffected -- that reloader kills the old worker and
# waits for it to exit before spawning a new one, so the port is genuinely free
# by the time this check runs again." False: the parent holds it. 22 "already
# answering" entries accumulated in .devlogs/backend.log before anyone noticed,
# because every one of them presented as a hanging request.
#
# It had also already been narrowed once, with `if "pytest" not in sys.modules`,
# because otherwise it failed every TestClient test whenever a dev server was
# running. That narrowing was a symptom of the same misplacement: a check that
# needs excluding from one caller after another is answering its question in the
# wrong place. In run.py it runs ONCE, in the parent, before anything binds --
# and needs no exclusions at all.

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
