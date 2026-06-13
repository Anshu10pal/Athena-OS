"""Achievements — badge unlocks driven by real events across the platform."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.database import get_db
from app.db.models import (
    Achievement,
    InterviewSession,
    Roadmap,
    SpeechSession,
    User,
)

router = APIRouter(prefix="/api/achievements", tags=["achievements"])

# code -> (title, description, icon-name, tier)
DEFS = {
    "first_steps": ("First Steps", "Complete your first node assessment", "footprints", "bronze"),
    "ten_nodes": ("Scholar", "Complete 10 nodes", "books", "silver"),
    "first_submap": ("Deep Diver", "Expand a node into a sub-map", "binoculars", "bronze"),
    "perfect_score": ("Flawless", "Score 100% on an assessment", "target-arrow", "gold"),
    "level_5": ("Ascendant", "Reach level 5", "stairs-up", "silver"),
    "level_10": ("Luminary", "Reach level 10", "crown", "gold"),
    "streak_7": ("Consistent", "Hold a 7-day streak", "flame", "silver"),
    "streak_30": ("Unstoppable", "Hold a 30-day streak", "flame", "gold"),
    "first_interview": ("In the Arena", "Finish your first interview", "microphone", "bronze"),
    "first_speech": ("Orator", "Complete your first speech", "speakerphone", "bronze"),
    "clean_speech": ("Silver Tongue", "Deliver a speech under 2 fillers/min", "feather", "gold"),
    "reviewer": ("Memory Keeper", "Clear 10 spaced-repetition reviews", "refresh", "silver"),
}


def check_and_award(db: Session, user: User) -> list[str]:
    """Idempotent: evaluates all achievement conditions, inserts any newly met. Returns new codes."""
    have = {a.code for a in db.query(Achievement).filter(Achievement.user_id == user.id).all()}
    newly: list[str] = []

    def award(code: str, condition: bool):
        if condition and code not in have:
            db.add(Achievement(user_id=user.id, code=code))
            have.add(code)
            newly.append(code)

    # Counts
    roadmaps = db.query(Roadmap).filter(Roadmap.user_id == user.id).all()
    completed_nodes = sum(
        1 for r in roadmaps for n in (r.nodes or []) if n.get("status") == "completed"
    )
    has_submap = any(r.parent_roadmap_id for r in roadmaps)
    level = user.xp // 500 + 1
    interviews = db.query(InterviewSession).filter(
        InterviewSession.user_id == user.id, InterviewSession.status == "finished"
    ).count()
    speeches = db.query(SpeechSession).filter(SpeechSession.user_id == user.id).all()
    best_filler = min((s.metrics.get("filler_rate_per_min", 99) for s in speeches if s.metrics), default=99)

    award("first_steps", completed_nodes >= 1)
    award("ten_nodes", completed_nodes >= 10)
    award("first_submap", has_submap)
    award("level_5", level >= 5)
    award("level_10", level >= 10)
    award("streak_7", (user.streak or 0) >= 7)
    award("streak_30", (user.streak or 0) >= 30)
    award("first_interview", interviews >= 1)
    award("first_speech", len(speeches) >= 1)
    award("clean_speech", best_filler < 2)

    if newly:
        db.commit()
    return newly


@router.get("")
def list_achievements(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    check_and_award(db, user)
    unlocked = {
        a.code: a.unlocked_at
        for a in db.query(Achievement).filter(Achievement.user_id == user.id).all()
    }
    out = []
    for code, (title, desc, icon, tier) in DEFS.items():
        out.append(
            {
                "code": code,
                "title": title,
                "description": desc,
                "icon": icon,
                "tier": tier,
                "unlocked": code in unlocked,
                "unlocked_at": str(unlocked[code])[:10] if code in unlocked else None,
            }
        )
    out.sort(key=lambda a: (not a["unlocked"], a["code"]))
    return {"achievements": out, "unlocked_count": len(unlocked), "total": len(DEFS)}
