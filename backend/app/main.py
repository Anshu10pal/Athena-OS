from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import achievements, analytics, auth, briefing, chat, communication, interview, missions, oratory, presentation, profile, review, roadmap, vault, voice
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
        "ALTER TABLE roadmaps ADD COLUMN parent_roadmap_id INTEGER",
        "ALTER TABLE roadmaps ADD COLUMN parent_node_id VARCHAR(40)",
        "ALTER TABLE users ADD COLUMN voice VARCHAR(60) DEFAULT 'en-US-AriaNeural'",
        "ALTER TABLE interview_sessions ADD COLUMN jd TEXT DEFAULT ''",
        "ALTER TABLE roadmaps ADD COLUMN depth INTEGER DEFAULT 0",
        "ALTER TABLE node_content ADD COLUMN meaning TEXT DEFAULT ''",
        "ALTER TABLE node_content ADD COLUMN eli5 TEXT DEFAULT ''",
        "ALTER TABLE review_items ADD COLUMN kind VARCHAR(20) NOT NULL DEFAULT 'node'",
        "ALTER TABLE review_items ADD COLUMN detail TEXT NOT NULL DEFAULT ''",
    ):
        try:
            _conn.execute(_text(_stmt))
            _conn.commit()
        except Exception:
            pass

# One-time data unification: mirror existing speeches into the Communication gym.
try:
    from app.db.database import SessionLocal as _SL
    from app.api.communication import backfill_speaking as _bf
    _bdb = _SL()
    _bf(_bdb)
    _bdb.close()
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

for module in (auth, profile, chat, roadmap, interview, presentation, vault, missions, analytics, voice, briefing, oratory, achievements, review, communication):
    app.include_router(module.router)


@app.get("/")
def root():
    return {"service": "athena-os", "status": "ok", "docs": "/docs", "health": "/api/health"}


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
