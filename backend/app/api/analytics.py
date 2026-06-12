from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.database import get_db
from app.db.models import InterviewSession, Mission, Roadmap, SpeechSession, User, VaultEntry

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/dashboard")
def dashboard(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    roadmap = db.query(Roadmap).filter(Roadmap.user_id == user.id).order_by(Roadmap.id.desc()).first()
    nodes = roadmap.nodes if roadmap else []
    completed = sum(1 for n in nodes if n["status"] == "completed")
    roadmap_progress = round(100 * completed / len(nodes)) if nodes else 0

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

    return {
        "oratory_filler_rate": (last_speech.metrics or {}).get("filler_rate_per_min") if last_speech else None,
        "speeches": db.query(SpeechSession).filter(SpeechSession.user_id == user.id).count(),
        "vault_entries": vault_count,
        "xp": user.xp,
        "level": user.xp // 500 + 1,
        "streak": user.streak,
        "roadmap_progress": roadmap_progress,
        "roadmap_title": roadmap.title if roadmap else None,
        "interview_readiness": interview_readiness,
        "interviews_completed": len(interviews),
        "presentations_analyzed": presentations,
        "missions_completed": missions_done,
        "skills": skills,
        "digital_twin": twin,
    }
