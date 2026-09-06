from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.resources import serialize_resource
from app.core.security import get_current_user, require_write_access
from app.db.database import get_db
from app.db.models import Module, Resource, Topic, TopicProgress, User
from app.db.schemas import TopicAddIn
from app.services.content_hub import slugify
from app.services.progress import module_progress
from app.services.topics import ensure_topics

router = APIRouter(prefix="/api/modules", tags=["modules"])


@router.get("/{slug}")
def get_module(slug: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    module = db.query(Module).filter(Module.slug == slug).first()
    if not module:
        raise HTTPException(404, "Module not found")

    try:
        ensure_topics(db, module)
    except ValueError as e:
        # Generation ran but produced something unusable (e.g. a URL got through the scrub).
        raise HTTPException(502, str(e))
    except Exception:
        # Anything else -- no API keys, rate limited past fallback, network down -- is the
        # provider being unavailable, not a content problem. Fail loudly with a clear message
        # rather than a bare 500.
        raise HTTPException(503, "Athena's AI provider is unavailable right now -- try again shortly")

    topics = db.query(Topic).filter(Topic.module_id == module.id).order_by(Topic.order_index).all()
    topic_ids = [t.id for t in topics]
    done_ids = {
        tid
        for (tid,) in db.query(TopicProgress.topic_id)
        .filter(TopicProgress.user_id == user.id, TopicProgress.topic_id.in_(topic_ids))
        .all()
    }
    progress = module_progress(db, user.id, module.id)

    topics_out = []
    total_minutes = 0
    for t in topics:
        total_minutes += t.estimated_minutes or 0
        resources = db.query(Resource).filter(Resource.topic_id == t.id).order_by(Resource.order_index).all()
        topics_out.append(
            {
                "id": t.id,
                "title": t.title,
                "blurb": t.blurb,
                "estimated_minutes": t.estimated_minutes,
                "done": t.id in done_ids,
                "resources": [serialize_resource(r) for r in resources],
            }
        )

    return {
        "id": module.id,
        "slug": module.slug,
        "title": module.title,
        "summary": module.summary,
        "kind": module.kind,
        "percent": progress["percent"],
        "state": progress["state"],
        "topic_count": progress["topic_count"],
        # Which repo this module was derived from, for source="codebase" rows;
        # null for seed and generated modules. The module page needs it to fetch
        # comprehension cards, which are served repo-scoped
        # (GET /api/repos/{id}/cards?module_id=). Without it the page would have
        # to guess a repo or the cards would need a second, module-scoped route
        # returning the same rows -- two doors to one table.
        "code_repo_id": module.code_repo_id,
        "total_minutes": total_minutes,
        "topics": topics_out,
    }


@router.post("/{slug}/topics")
def add_topic(slug: str, payload: TopicAddIn, user=Depends(require_write_access), db: Session = Depends(get_db)):
    module = db.query(Module).filter(Module.slug == slug).first()
    if not module:
        raise HTTPException(404, "Module not found")
    max_order = db.query(func.max(Topic.order_index)).filter(Topic.module_id == module.id).scalar()
    topic = Topic(
        module_id=module.id,
        slug=slugify(payload.title),
        title=payload.title,
        blurb=payload.blurb,
        order_index=(max_order if max_order is not None else -1) + 1,
        estimated_minutes=15,
        source="manual",
    )
    db.add(topic)
    db.commit()
    db.refresh(topic)
    return {
        "id": topic.id,
        "title": topic.title,
        "blurb": topic.blurb,
        "estimated_minutes": topic.estimated_minutes,
        "done": False,
        "resources": [],
    }
