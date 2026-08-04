import logging
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import achievements, analytics, auth, briefing, chat, communication, content, interview, missions, modules, oratory, presentation, profile, resources, review, roadmap, roadmaps, topics, vault, voice
from app.core.config import BACKEND_DIR
from app.db import models  # noqa: F401  (register models)

# Schema is Alembic-owned. Safe to re-run: Alembic no-ops once the DB is at head.
# (Replaces the old create_all() + hand-written ALTER TABLE list.)
command.upgrade(AlembicConfig(str(BACKEND_DIR / "alembic.ini")), "head")

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

app = FastAPI(title="ATHENA OS", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in (auth, profile, chat, roadmap, roadmaps, modules, topics, resources, interview, presentation, vault, missions, analytics, voice, briefing, oratory, achievements, review, communication, content):
    app.include_router(module.router)


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "athena-os"}


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
