"""Daily briefing — Athena greets the user with a personalized status report."""
import json
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.llm import chat
from app.core.security import get_current_user
from app.db.database import get_db
from app.db.models import Mission, Roadmap, User

router = APIRouter(prefix="/api/briefing", tags=["briefing"])

BRIEFING_PROMPT = """You are ATHENA, an AI mentor giving a short spoken morning briefing.
Stats: {stats}
Write 3-4 short sentences, warm but crisp, Jarvis-style. Greet by first name,
mention the streak, what they're currently learning, and how many missions await.
No markdown, no emoji — this will be spoken aloud."""


@router.get("")
def briefing(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    roadmap = db.query(Roadmap).filter(Roadmap.user_id == user.id).order_by(Roadmap.id.desc()).first()
    current = next(
        (n for n in (roadmap.nodes if roadmap else []) if n["status"] in ("available", "in_progress")), None
    )
    missions_open = (
        db.query(Mission)
        .filter(Mission.user_id == user.id, Mission.date == date.today().isoformat(), Mission.status == "active")
        .count()
    )
    stats = json.dumps(
        {
            "name": user.name.split()[0],
            "streak_days": user.streak,
            "xp": user.xp,
            "level": user.xp // 500 + 1,
            "current_topic": (current or {}).get("title", "no active roadmap yet"),
            "open_missions": missions_open,
        }
    )
    try:
        text = chat(
            [
                {"role": "system", "content": BRIEFING_PROMPT.format(stats=stats)},
                {"role": "user", "content": "Give my briefing."},
            ],
            fast=True,
            max_tokens=200,
        )
    except Exception:
        text = f"Good morning, {user.name.split()[0]}. Day {user.streak} of your streak. {missions_open} missions are waiting."
    return {"text": text.strip()}
