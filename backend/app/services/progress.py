"""Module and roadmap progress derivation -- single source of truth.

No redundant "module state" column: state and percent are always computed from
topic_progress at read time. Reused by the module page (Phase 4), the roadmap
search results, and the homepage dashboard (Phase 6).
"""
from sqlalchemy.orm import Session

from app.db.models import ContentRoadmap, RoadmapNode, RoadmapStage, Topic, TopicProgress


def module_progress(db: Session, user_id: int, module_id: int) -> dict:
    topic_ids = [tid for (tid,) in db.query(Topic.id).filter(Topic.module_id == module_id).all()]
    total = len(topic_ids)
    if total == 0:
        return {"percent": 0, "state": "not_started", "topic_count": 0, "completed_count": 0}
    completed = (
        db.query(TopicProgress)
        .filter(TopicProgress.user_id == user_id, TopicProgress.topic_id.in_(topic_ids))
        .count()
    )
    percent = round(100 * completed / total)
    state = "not_started" if completed == 0 else "complete" if completed == total else "in_progress"
    return {"percent": percent, "state": state, "topic_count": total, "completed_count": completed}


def roadmap_progress(db: Session, user_id: int, roadmap: ContentRoadmap) -> dict:
    """Completed topics across every module the roadmap's matched nodes reference,
    over total topics across those same modules. A module referenced by more than
    one node (or stage) in the roadmap is only counted once -- it's one atom, not
    a copy per reference.
    """
    stage_ids = [sid for (sid,) in db.query(RoadmapStage.id).filter(RoadmapStage.roadmap_id == roadmap.id).all()]
    module_ids = set()
    if stage_ids:
        module_ids = {
            mid
            for (mid,) in db.query(RoadmapNode.module_id)
            .filter(RoadmapNode.stage_id.in_(stage_ids), RoadmapNode.module_id.isnot(None))
            .all()
        }
    if not module_ids:
        return {"percent": 0, "topic_count": 0, "completed_count": 0, "module_count": 0}

    topic_ids = [tid for (tid,) in db.query(Topic.id).filter(Topic.module_id.in_(module_ids)).all()]
    total = len(topic_ids)
    if total == 0:
        return {"percent": 0, "topic_count": 0, "completed_count": 0, "module_count": len(module_ids)}
    completed = (
        db.query(TopicProgress)
        .filter(TopicProgress.user_id == user_id, TopicProgress.topic_id.in_(topic_ids))
        .count()
    )
    return {
        "percent": round(100 * completed / total),
        "topic_count": total,
        "completed_count": completed,
        "module_count": len(module_ids),
    }
