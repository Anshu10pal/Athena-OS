from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.database import get_db
from app.db.models import ContentRoadmap, Module, RoadmapNode, User
from app.db.schemas import RoadmapSearchIn
from app.services.content_hub import slugify
from app.services.progress import roadmap_progress
from app.services.resolution import search_roadmap, serialize_roadmap

router = APIRouter(prefix="/api/roadmaps", tags=["roadmaps"])


@router.get("")
def list_roadmaps(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Every roadmap for browsing tiles -- seeded AND previously generated ones both
    become part of the shared, browsable library once they exist (same as modules) --
    with this user's derived percent on each."""
    roadmaps = db.query(ContentRoadmap).order_by(ContentRoadmap.title).all()
    return [
        {
            "slug": r.slug,
            "title": r.title,
            "summary": r.summary,
            "category": r.category,
            "kind": r.kind,
            "percent": roadmap_progress(db, user.id, r)["percent"],
        }
        for r in roadmaps
    ]


@router.get("/{slug}")
def get_roadmap(slug: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    roadmap = db.query(ContentRoadmap).filter(ContentRoadmap.slug == slug).first()
    if not roadmap:
        raise HTTPException(404, "Roadmap not found")
    if user.last_roadmap_id != roadmap.id:
        user.last_roadmap_id = roadmap.id
        db.commit()
    resolved_via = "seed" if roadmap.kind == "seed" else "cached"
    return serialize_roadmap(db, roadmap, resolved_via, user.id)


@router.post("/search")
def search(payload: RoadmapSearchIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    roadmap, resolved_via = search_roadmap(db, payload.query)
    if user.last_roadmap_id != roadmap.id:
        user.last_roadmap_id = roadmap.id
        db.commit()
    return serialize_roadmap(db, roadmap, resolved_via, user.id)


@router.post("/nodes/{node_id}/ensure-module")
def ensure_module(node_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Unmatched nodes route to a module created on the fly from the node title.

    Self-healing: if a module with that slug already exists (from a prior
    on-the-fly creation, or seeded since this roadmap was last resolved), reuse
    it and re-wire the node instead of creating a duplicate.
    """
    node = db.get(RoadmapNode, node_id)
    if not node:
        raise HTTPException(404, "Roadmap node not found")
    if node.module_id:
        module = db.get(Module, node.module_id)
        if module:
            return {"module_slug": module.slug}

    slug = slugify(node.title)
    module = db.query(Module).filter(Module.slug == slug).first()
    if not module:
        module = Module(slug=slug, title=node.title, kind="skill", source="generated")
        db.add(module)
        db.flush()

    node.module_id = module.id
    node.module_slug = module.slug
    node.resolution = "matched"
    db.commit()
    return {"module_slug": module.slug}
