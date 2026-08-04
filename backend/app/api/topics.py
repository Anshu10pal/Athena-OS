import json
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.resources import serialize_resource
from app.core.config import BACKEND_DIR
from app.core.security import get_current_user, require_write_access
from app.db.database import get_db
from app.db.models import Module, Resource, ResourceHistory, Topic, TopicProgress, User
from app.db.schemas import ResourceAddIn, ResourceReorderIn
from app.services.progress import module_progress
from app.services.uploads import MAX_UPLOAD_BYTES, MIME_BY_EXT, resolve_upload_extension

router = APIRouter(prefix="/api/topics", tags=["topics"])

DATA_DIR = BACKEND_DIR / "data" / "resources"


@router.patch("/{topic_id}/progress")
def set_topic_progress(topic_id: int, payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    topic = db.get(Topic, topic_id)
    if not topic:
        raise HTTPException(404, "Topic not found")
    done = bool(payload.get("done"))
    existing = (
        db.query(TopicProgress)
        .filter(TopicProgress.user_id == user.id, TopicProgress.topic_id == topic_id)
        .first()
    )
    if done and not existing:
        db.add(TopicProgress(user_id=user.id, topic_id=topic_id))
    elif not done and existing:
        db.delete(existing)
    db.commit()
    return module_progress(db, user.id, topic.module_id)


@router.post("/{topic_id}/resources")
def add_resource(topic_id: int, payload: ResourceAddIn, user=Depends(require_write_access), db: Session = Depends(get_db)):
    topic = db.get(Topic, topic_id)
    if not topic:
        raise HTTPException(404, "Topic not found")
    max_order = db.query(func.max(Resource.order_index)).filter(Resource.topic_id == topic_id).scalar()
    resource = Resource(
        topic_id=topic_id,
        kind=payload.kind,
        status="saved" if payload.url else "intent",
        title=payload.title or payload.search_query or "",
        url=payload.url,
        search_query=payload.search_query,
        source_hint="manual",
        order_index=(max_order if max_order is not None else -1) + 1,
    )
    db.add(resource)
    db.commit()
    db.refresh(resource)
    return serialize_resource(resource)


@router.post("/{topic_id}/resources/reorder")
def reorder_resources(topic_id: int, payload: ResourceReorderIn, user=Depends(require_write_access), db: Session = Depends(get_db)):
    topic = db.get(Topic, topic_id)
    if not topic:
        raise HTTPException(404, "Topic not found")
    resources = {r.id: r for r in db.query(Resource).filter(Resource.topic_id == topic_id).all()}
    for i, rid in enumerate(payload.resource_ids):
        if rid in resources:
            resources[rid].order_index = i
    db.commit()
    return {"ok": True}


@router.post("/{topic_id}/resources/upload")
async def upload_resource(
    topic_id: int, file: UploadFile = File(...), user=Depends(require_write_access), db: Session = Depends(get_db)
):
    topic = db.get(Topic, topic_id)
    if not topic:
        raise HTTPException(404, "Topic not found")
    module = db.get(Module, topic.module_id)

    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File exceeds the 25MB limit")
    try:
        ext = resolve_upload_extension(file.filename or "", data)
    except ValueError as e:
        raise HTTPException(400, str(e))

    dest_dir = DATA_DIR / module.slug
    dest_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4()}.{ext}"
    (dest_dir / stored_name).write_bytes(data)

    max_order = db.query(func.max(Resource.order_index)).filter(Resource.topic_id == topic_id).scalar()
    resource = Resource(
        topic_id=topic_id,
        kind="file",
        status="saved",
        title=file.filename or stored_name,
        file_path=str((dest_dir / stored_name).relative_to(BACKEND_DIR)),
        mime_type=MIME_BY_EXT[ext],
        size_bytes=len(data),
        source_hint="manual",
        order_index=(max_order if max_order is not None else -1) + 1,
    )
    db.add(resource)
    db.commit()
    db.refresh(resource)
    return serialize_resource(resource)


@router.post("/{topic_id}/undo")
def undo_last_change(topic_id: int, user=Depends(require_write_access), db: Session = Depends(get_db)):
    topic = db.get(Topic, topic_id)
    if not topic:
        raise HTTPException(404, "Topic not found")
    entry = (
        db.query(ResourceHistory)
        .filter(ResourceHistory.topic_id == topic_id)
        .order_by(ResourceHistory.changed_at.desc(), ResourceHistory.id.desc())
        .first()
    )
    if not entry:
        raise HTTPException(404, "Nothing to undo in this topic")

    if entry.field == "__deleted__":
        data = json.loads(entry.old_value)
        db.add(Resource(**data))
    else:
        resource = db.get(Resource, entry.resource_id)
        if resource:
            setattr(resource, entry.field, entry.old_value)

    db.delete(entry)
    db.commit()
    return {"ok": True}


@router.delete("/{topic_id}")
def delete_topic(topic_id: int, user=Depends(require_write_access), db: Session = Depends(get_db)):
    topic = db.get(Topic, topic_id)
    if not topic:
        raise HTTPException(404, "Topic not found")
    db.query(Resource).filter(Resource.topic_id == topic_id).delete(synchronize_session=False)
    db.query(TopicProgress).filter(TopicProgress.topic_id == topic_id).delete(synchronize_session=False)
    db.delete(topic)
    db.commit()
    return {"ok": True}
