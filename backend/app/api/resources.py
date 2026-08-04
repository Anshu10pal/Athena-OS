from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.config import BACKEND_DIR
from app.core.security import get_current_user, require_write_access
from app.db.database import get_db
from app.db.models import Resource, ResourceHistory
from app.db.schemas import ResourcePatchIn

router = APIRouter(prefix="/api/resources", tags=["resources"])


def serialize_resource(r: Resource) -> dict:
    return {
        "id": r.id,
        "topic_id": r.topic_id,
        "kind": r.kind,
        "status": r.status,
        "title": r.title,
        "url": r.url,
        "search_query": r.search_query,
        "mime_type": r.mime_type,
        "size_bytes": r.size_bytes,
        "order_index": r.order_index,
    }


def record_history(db: Session, resource: Resource, field: str, old_value, new_value) -> None:
    db.add(
        ResourceHistory(
            resource_id=resource.id,
            topic_id=resource.topic_id,
            field=field,
            old_value=None if old_value is None else str(old_value),
            new_value=None if new_value is None else str(new_value),
        )
    )


@router.patch("/{resource_id}")
def update_resource(
    resource_id: int, payload: ResourcePatchIn, user=Depends(require_write_access), db: Session = Depends(get_db)
):
    resource = db.get(Resource, resource_id)
    if not resource:
        raise HTTPException(404, "Resource not found")
    url = payload.url.strip()
    if not url:
        raise HTTPException(400, "A URL is required to save a resource")
    title = payload.title.strip() if payload.title else resource.title

    if resource.url != url:
        record_history(db, resource, "url", resource.url, url)
    if resource.title != title:
        record_history(db, resource, "title", resource.title, title)
    if resource.status != "saved":
        record_history(db, resource, "status", resource.status, "saved")

    resource.url = url
    resource.title = title
    resource.status = "saved"
    db.commit()
    db.refresh(resource)
    return serialize_resource(resource)


@router.delete("/{resource_id}")
def delete_resource(resource_id: int, user=Depends(require_write_access), db: Session = Depends(get_db)):
    resource = db.get(Resource, resource_id)
    if not resource:
        raise HTTPException(404, "Resource not found")

    import json

    snapshot = json.dumps(
        {
            "topic_id": resource.topic_id,
            "kind": resource.kind,
            "status": resource.status,
            "title": resource.title,
            "url": resource.url,
            "search_query": resource.search_query,
            "source_hint": resource.source_hint,
            "file_path": resource.file_path,
            "mime_type": resource.mime_type,
            "size_bytes": resource.size_bytes,
            "order_index": resource.order_index,
        }
    )
    record_history(db, resource, "__deleted__", snapshot, None)
    db.commit()  # history committed before the delete, per spec

    db.delete(resource)
    db.commit()
    return {"ok": True}


@router.get("/{resource_id}/file")
def download_resource(resource_id: int, user=Depends(get_current_user), db: Session = Depends(get_db)):
    resource = db.get(Resource, resource_id)
    if not resource or resource.kind != "file" or not resource.file_path:
        raise HTTPException(404, "File not found")
    full_path = BACKEND_DIR / resource.file_path
    if not full_path.is_file():
        raise HTTPException(404, "File not found on disk")
    return FileResponse(full_path, media_type=resource.mime_type or "application/octet-stream", filename=resource.title)
