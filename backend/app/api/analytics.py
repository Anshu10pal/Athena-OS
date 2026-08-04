from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.database import get_db
from app.db.models import ContentRoadmap, InterviewSession, Mission, SpeechSession, User, VaultEntry
from app.services.activity import activity_calendar
from app.services.progress import roadmap_progress as _roadmap_progress

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/dashboard")
def dashboard(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # content_roadmaps aren't user-owned (shared library), so "the" roadmap the
    # dashboard shows is whichever one the user last searched -- see User.last_roadmap_id.
    roadmap = db.get(ContentRoadmap, user.last_roadmap_id) if user.last_roadmap_id else None
    if roadmap:
        rp = _roadmap_progress(db, user.id, roadmap)
        roadmap_progress = rp["percent"]
        roadmap_topic_count = rp["topic_count"]
        roadmap_completed_count = rp["completed_count"]
    else:
        roadmap_progress = 0
        roadmap_topic_count = 0
        roadmap_completed_count = 0

    interviews = (
        db.query(InterviewSession)
        .filter(InterviewSession.user_id == user.id, InterviewSession.status == "finished")
        .all()
    )
    if interviews:
        latest = interviews[-1].scores or {}
        dims = ["communication", "technical_accuracy", "confidence", "depth", "leadership"]
        vals = [latest.get(d, 0) for d in dims if isinstance(latest.get(d), (int, float))]
        interview_readiness = round(10 * sum(vals) / len(vals)) if vals else 0
    else:
        interview_readiness = 0

    presentations = db.query(VaultEntry).filter(VaultEntry.user_id == user.id, VaultEntry.kind == "presentation").count()
    missions_done = db.query(Mission).filter(Mission.user_id == user.id, Mission.status == "completed").count()

    today_str = date.today().isoformat()
    missions_today = db.query(Mission).filter(Mission.user_id == user.id, Mission.date == today_str).all()
    missions_today_completed = sum(1 for m in missions_today if m.status == "completed")

    # Digital Twin: simple derived capability metrics (0-100)
    skills = user.skills or {}
    avg_skill = (sum(skills.values()) / len(skills) / 5 * 100) if skills else 0
    twin = {
        "technical_depth": round(avg_skill),
        "communication": interview_readiness,
        "presentation_skill": min(100, presentations * 25),
        "ai_knowledge": round(
            sum(v for k, v in skills.items() if any(t in k.lower() for t in ("ai", "ml", "llm", "rag", "agent")))
            / max(1, len(skills)) * 20
        ),
        "consistency": min(100, user.streak * 10),
    }

    last_speech = db.query(SpeechSession).filter(SpeechSession.user_id == user.id).order_by(SpeechSession.id.desc()).first()
    vault_count = db.query(VaultEntry).filter(VaultEntry.user_id == user.id).count()

    _comm_score = None
    try:
        from app.db.models import CommunicationSession
        _cs = db.query(CommunicationSession).filter(CommunicationSession.user_id == user.id).order_by(CommunicationSession.id.desc()).limit(8).all()
        if _cs:
            _comm_score = round(sum(c.overall for c in _cs) / len(_cs))
    except Exception:
        pass
    review_info = {"reviews_due": 0, "memory_strength": 1.0}
    review_forecast = [{"date": today_str, "count": 0}]
    achievements_unlocked = 0
    try:
        from app.api.review import due_forecast as _due_forecast, summary as _review_summary
        review_info = _review_summary(db, user.id)
        review_forecast = _due_forecast(db, user.id)
    except Exception:
        pass
    try:
        from app.db.models import Achievement
        achievements_unlocked = db.query(Achievement).filter(Achievement.user_id == user.id).count()
    except Exception:
        pass

    return {
        "reviews_due": review_info.get("reviews_due", 0),
        "memory_strength": review_info.get("memory_strength", 1.0),
        "achievements_unlocked": achievements_unlocked,
        "communication_score": _comm_score,
        "oratory_filler_rate": (last_speech.metrics or {}).get("filler_rate_per_min") if last_speech else None,
        "speeches": db.query(SpeechSession).filter(SpeechSession.user_id == user.id).count(),
        "vault_entries": vault_count,
        "xp": user.xp,
        "level": user.xp // 500 + 1,
        "streak": user.streak,
        "roadmap_progress": roadmap_progress,
        "roadmap_title": roadmap.title if roadmap else None,
        "roadmap_slug": roadmap.slug if roadmap else None,
        "roadmap_topic_count": roadmap_topic_count,
        "roadmap_completed_count": roadmap_completed_count,
        "interview_readiness": interview_readiness,
        "interviews_completed": len(interviews),
        "presentations_analyzed": presentations,
        "missions_completed": missions_done,
        "missions_today": [
            {"id": m.id, "objective": m.objective, "status": m.status} for m in missions_today
        ],
        "missions_today_completed": missions_today_completed,
        "missions_today_total": len(missions_today),
        "review_forecast": review_forecast,
        "activity": activity_calendar(db, user.id),
        "skills": skills,
        "digital_twin": twin,
    }
