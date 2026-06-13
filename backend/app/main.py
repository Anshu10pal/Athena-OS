from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import achievements, analytics, auth, briefing, chat, interview, missions, oratory, presentation, profile, review, roadmap, vault, voice
from app.db import models  # noqa: F401  (register models)
from app.db.database import Base, engine

Base.metadata.create_all(bind=engine)

# Lightweight migrations for columns added after first release (SQLite-safe)
from sqlalchemy import text as _text

with engine.connect() as _conn:
    for _stmt in (
        "ALTER TABLE interview_sessions ADD COLUMN mcq JSON",
        "ALTER TABLE interview_sessions ADD COLUMN mcq_score INTEGER DEFAULT -1",
        "ALTER TABLE roadmaps ADD COLUMN parent_roadmap_id INTEGER",
        "ALTER TABLE roadmaps ADD COLUMN parent_node_id VARCHAR(40)",
        "ALTER TABLE users ADD COLUMN voice VARCHAR(60) DEFAULT 'en-US-AriaNeural'",
        "ALTER TABLE interview_sessions ADD COLUMN jd TEXT DEFAULT ''",
        "ALTER TABLE roadmaps ADD COLUMN depth INTEGER DEFAULT 0",
        "ALTER TABLE node_content ADD COLUMN meaning TEXT DEFAULT ''",
        "ALTER TABLE node_content ADD COLUMN eli5 TEXT DEFAULT ''",
    ):
        try:
            _conn.execute(_text(_stmt))
            _conn.commit()
        except Exception:
            pass

app = FastAPI(title="ATHENA OS", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in (auth, profile, chat, roadmap, interview, presentation, vault, missions, analytics, voice, briefing, oratory, achievements, review):
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


# --- Serve the built React frontend (MUST be last — the catch-all swallows everything below it) ---
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path

_dist = Path(__file__).parent.parent.parent / "frontend" / "dist"
if _dist.exists():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        if full_path.startswith(("api", "docs")) or full_path == "openapi.json":
            return {"detail": "Not Found"}
        return FileResponse(_dist / "index.html")