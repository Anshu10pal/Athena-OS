"""Idempotent content-library seeder.

Loads content/modules/*.yaml and content/roadmaps/*.yaml into the DB. Safe to
re-run: every write is an upsert by slug, and a resource that's already been
saved over by the user (status == "saved") is never touched by a re-seed.

Content produced for these files is LLM-authored and frozen at build time —
that's not the same as curated. It becomes curated the moment a real link is
saved over a search-intent resource. Don't describe it as curated in comments
or UI copy; say "seeded" or "generated" instead.

Each seed topic may declare at most one resource per `kind` (one video, one
article, etc.) — the re-seed matcher keys on (topic, kind), so a second
resource of the same kind on the same topic would collide.
"""
import logging
from pathlib import Path

import yaml
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.db.models import ContentRoadmap, Module, Resource, RoadmapNode, RoadmapStage, Topic

logger = logging.getLogger("athena.seed")

CONTENT_DIR = Path(__file__).resolve().parents[3] / "content"
MODULES_DIR = CONTENT_DIR / "modules"
ROADMAPS_DIR = CONTENT_DIR / "roadmaps"


def seed_module(db: Session, data: dict) -> Module:
    module = db.query(Module).filter(Module.slug == data["slug"]).first()
    if not module:
        module = Module(slug=data["slug"])
        db.add(module)
    module.title = data["title"]
    module.kind = data.get("kind", "skill")
    module.summary = data.get("summary", "")
    module.aliases = data.get("aliases", [])
    module.source = "seed"
    db.flush()

    for i, t in enumerate(data.get("topics", [])):
        topic = db.query(Topic).filter(Topic.module_id == module.id, Topic.slug == t["slug"]).first()
        if not topic:
            topic = Topic(module_id=module.id, slug=t["slug"])
            db.add(topic)
        topic.title = t["title"]
        topic.blurb = t.get("blurb", "")
        topic.order_index = i
        topic.estimated_minutes = t.get("estimated_minutes", 15)
        topic.source = "seed"
        db.flush()

        existing = db.query(Resource).filter(Resource.topic_id == topic.id).all()
        for j, r in enumerate(t.get("resources", [])):
            match = next((res for res in existing if res.kind == r["kind"]), None)
            if match and match.status == "saved":
                continue  # curated over by the user -- a re-seed must never clobber this
            if not match:
                match = Resource(topic_id=topic.id)
                db.add(match)
            match.kind = r["kind"]
            match.status = "intent"
            match.title = r.get("title", "")
            match.search_query = r.get("search_query", t["title"])
            match.source_hint = "seed"
            match.order_index = j
    return module


def seed_roadmap(db: Session, data: dict) -> ContentRoadmap:
    roadmap = db.query(ContentRoadmap).filter(ContentRoadmap.slug == data["slug"]).first()
    if not roadmap:
        roadmap = ContentRoadmap(slug=data["slug"])
        db.add(roadmap)
    roadmap.title = data["title"]
    roadmap.target = data.get("target", data["title"])
    roadmap.aliases = data.get("aliases", [])
    roadmap.category = data.get("category", "role")
    roadmap.summary = data.get("summary", "")
    roadmap.kind = "seed"
    db.flush()

    # Stages/nodes carry no user-mutable state (progress lives on TopicProgress,
    # keyed to the module, not the node) so a full rebuild on every re-seed is safe
    # and keeps YAML the single source of truth for structure. Bulk .delete() skips
    # the ORM cascade and SQLite doesn't enforce FKs by default, so nodes are
    # deleted explicitly first -- leaving them would orphan and later duplicate.
    old_stage_ids = [sid for (sid,) in db.query(RoadmapStage.id).filter(RoadmapStage.roadmap_id == roadmap.id).all()]
    if old_stage_ids:
        db.query(RoadmapNode).filter(RoadmapNode.stage_id.in_(old_stage_ids)).delete(synchronize_session=False)
    db.query(RoadmapStage).filter(RoadmapStage.roadmap_id == roadmap.id).delete(synchronize_session=False)
    db.flush()

    for i, s in enumerate(data.get("stages", [])):
        stage = RoadmapStage(roadmap_id=roadmap.id, title=s["title"], order_index=i)
        db.add(stage)
        db.flush()
        for j, n in enumerate(s.get("nodes", [])):
            module_slug = n.get("module")
            module = db.query(Module).filter(Module.slug == module_slug).first() if module_slug else None
            db.add(
                RoadmapNode(
                    stage_id=stage.id,
                    module_id=module.id if module else None,
                    module_slug=module_slug,
                    title=n["title"],
                    blurb=n.get("blurb", ""),
                    order_index=j,
                    resolution="matched" if module else "unmatched",
                )
            )
    return roadmap


def run_seed() -> dict:
    """Load every content YAML file into the DB. Idempotent; call on every startup."""
    if not MODULES_DIR.exists() and not ROADMAPS_DIR.exists():
        return {"modules": 0, "roadmaps": 0}
    db = SessionLocal()
    modules_seeded = 0
    roadmaps_seeded = 0
    try:
        seeded_modules = []
        for path in sorted(MODULES_DIR.glob("*.yaml")) if MODULES_DIR.exists() else []:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            seeded_modules.append(seed_module(db, data))
            modules_seeded += 1
        db.commit()

        # Index for embedding-similarity resolution (Phase 3). Best-effort: an
        # indexing failure shouldn't block seeding the rest of the library.
        from app.services.vector_store import index_module

        for m in seeded_modules:
            try:
                index_module(m.id, m.slug, m.title, m.summary, m.aliases or [])
            except Exception:
                logger.exception("Failed to index module %r for similarity search", m.slug)

        # Roadmap nodes resolve against modules by slug, so modules must already be committed.
        for path in sorted(ROADMAPS_DIR.glob("*.yaml")) if ROADMAPS_DIR.exists() else []:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            seed_roadmap(db, data)
            roadmaps_seeded += 1
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    logger.info("Seeded %d module(s), %d roadmap(s)", modules_seeded, roadmaps_seeded)
    return {"modules": modules_seeded, "roadmaps": roadmaps_seeded}


def export_content(db: Session) -> dict:
    """Write current seed-sourced DB content back out to content/*.yaml for curation commits."""
    MODULES_DIR.mkdir(parents=True, exist_ok=True)
    ROADMAPS_DIR.mkdir(parents=True, exist_ok=True)

    modules = db.query(Module).filter(Module.source == "seed").order_by(Module.slug).all()
    for module in modules:
        topics = db.query(Topic).filter(Topic.module_id == module.id).order_by(Topic.order_index).all()
        data = {
            "slug": module.slug,
            "title": module.title,
            "kind": module.kind,
            "summary": module.summary,
            "aliases": module.aliases or [],
            "topics": [],
        }
        for topic in topics:
            resources = db.query(Resource).filter(Resource.topic_id == topic.id).order_by(Resource.order_index).all()
            t_data = {
                "slug": topic.slug,
                "title": topic.title,
                "blurb": topic.blurb,
                "estimated_minutes": topic.estimated_minutes,
                "resources": [],
            }
            for r in resources:
                if r.status == "saved":
                    r_data = {"kind": r.kind, "status": "saved", "title": r.title, "url": r.url}
                else:
                    r_data = {"kind": r.kind, "title": r.title, "search_query": r.search_query}
                t_data["resources"].append(r_data)
            data["topics"].append(t_data)
        (MODULES_DIR / f"{module.slug}.yaml").write_text(
            yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
        )

    roadmaps = db.query(ContentRoadmap).filter(ContentRoadmap.kind == "seed").order_by(ContentRoadmap.slug).all()
    for roadmap in roadmaps:
        stages = db.query(RoadmapStage).filter(RoadmapStage.roadmap_id == roadmap.id).order_by(RoadmapStage.order_index).all()
        data = {
            "slug": roadmap.slug,
            "title": roadmap.title,
            "target": roadmap.target,
            "aliases": roadmap.aliases or [],
            "category": roadmap.category,
            "summary": roadmap.summary,
            "stages": [],
        }
        for stage in stages:
            nodes = db.query(RoadmapNode).filter(RoadmapNode.stage_id == stage.id).order_by(RoadmapNode.order_index).all()
            s_data = {"title": stage.title, "nodes": []}
            for node in nodes:
                n_data = {"title": node.title, "blurb": node.blurb}
                if node.module_slug:
                    # From the hint, not the resolved module_id/Module join -- a node whose
                    # target module hasn't been seeded yet is still "unmatched" but the
                    # author's declared intent must round-trip, not silently vanish.
                    n_data["module"] = node.module_slug
                s_data["nodes"].append(n_data)
            data["stages"].append(s_data)
        (ROADMAPS_DIR / f"{roadmap.slug}.yaml").write_text(
            yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
        )

    return {"modules_exported": len(modules), "roadmaps_exported": len(roadmaps)}
