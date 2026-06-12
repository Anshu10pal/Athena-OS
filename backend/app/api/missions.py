import json
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agents import prompts
from app.core.llm import chat_json
from app.core.security import get_current_user
from app.db.database import get_db
from app.db.models import Mission, Roadmap, User

router = APIRouter(prefix="/api/missions", tags=["missions"])


@router.get("/today")
def today(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    today_str = date.today().isoformat()
    missions = db.query(Mission).filter(Mission.user_id == user.id, Mission.date == today_str).all()
    active_count = sum(1 for m in missions if m.status == "active")
    need = 3 - active_count if missions else 3
    if (not missions) or (need > 0 and len(missions) < 10):
        roadmap = db.query(Roadmap).filter(Roadmap.user_id == user.id).order_by(Roadmap.id.desc()).first()
        current = next(
            (n for n in (roadmap.nodes if roadmap else []) if n["status"] in ("available", "in_progress")),
            None,
        )
        profile = json.dumps({"target_role": user.target_role, "skills": user.skills, "level": user.experience_level})
        try:
            generated = chat_json(
                [
                    {
                        "role": "system",
                        "content": prompts.MISSION_GENERATOR.format(
                            profile=profile, current_node=(current or {}).get("title", "none")
                        ),
                    },
                    {"role": "user", "content": "Generate today's missions."},
                ]
            )
            for m in generated.get("missions", [])[: (need if missions else 3)]:
                db.add(
                    Mission(
                        user_id=user.id,
                        objective=m.get("objective", ""),
                        difficulty=m.get("difficulty", "easy"),
                        xp_reward=int(m.get("xp_reward", 50)),
                        skills_gained=m.get("skills_gained", []),
                        date=today_str,
                    )
                )
            db.commit()
            missions = db.query(Mission).filter(Mission.user_id == user.id, Mission.date == today_str).all()
        except Exception:
            missions = []
    return [
        {
            "id": m.id,
            "objective": m.objective,
            "difficulty": m.difficulty,
            "xp_reward": m.xp_reward,
            "skills_gained": m.skills_gained,
            "status": m.status,
        }
        for m in missions
    ]


@router.post("/{mission_id}/complete")
def complete(mission_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    mission = db.get(Mission, mission_id)
    if not mission or mission.user_id != user.id:
        raise HTTPException(404, "Mission not found")
    if mission.status == "completed":
        return {"xp": user.xp, "xp_gained": 0}
    mission.status = "completed"
    user.xp += mission.xp_reward
    skills = dict(user.skills or {})
    for s in mission.skills_gained or []:
        skills[s] = min(5, skills.get(s, 0) + 1)
    user.skills = skills
    db.commit()

    # Rotation: immediately generate a replacement directive
    new_mission = None
    try:
        roadmap = db.query(Roadmap).filter(Roadmap.user_id == user.id).order_by(Roadmap.id.desc()).first()
        current = next((n for n in (roadmap.nodes if roadmap else []) if n["status"] in ("available", "in_progress")), None)
        profile = json.dumps({"target_role": user.target_role, "skills": user.skills, "level": user.experience_level})
        generated = chat_json(
            [
                {"role": "system", "content": prompts.MISSION_GENERATOR.format(profile=profile, current_node=(current or {}).get("title", "none"))},
                {"role": "user", "content": f"Generate 1 new mission, different from: {mission.objective[:100]}"},
            ],
            fast=True,
        )
        m = (generated.get("missions") or [None])[0]
        if m:
            new = Mission(
                user_id=user.id,
                objective=m.get("objective", ""),
                difficulty=m.get("difficulty", "easy"),
                xp_reward=int(m.get("xp_reward", 50)),
                skills_gained=m.get("skills_gained", []),
                date=date.today().isoformat(),
            )
            db.add(new)
            db.commit()
            db.refresh(new)
            new_mission = {"id": new.id, "objective": new.objective, "difficulty": new.difficulty, "xp_reward": new.xp_reward, "skills_gained": new.skills_gained, "status": new.status}
    except Exception:
        pass
    return {"xp": user.xp, "xp_gained": mission.xp_reward, "new_mission": new_mission}
