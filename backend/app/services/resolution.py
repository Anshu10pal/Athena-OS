"""Roadmap search and module resolution (Phase 3).

Resolution order for a query against the roadmap library:
1. Exact/alias match against a seeded roadmap -- zero LLM calls.
2. A previously generated roadmap for the same (slugified) query -- zero LLM calls.
3. One LLM call for the stage/node skeleton only, then resolve each node against
   the module library independently.

Resolution order for a single node title against the module library:
1. Exact slug match.
2. Exact match against a module's title or one of its aliases.
3. Qdrant embedding similarity (candidate generation) + one cheap LLM confirmation
   call (precision gate) before accepting the match. Below either bar stays
   unmatched -- a wrong match is worse than no match.

Why a bare embedding threshold isn't enough (measured, not assumed): scored real
generated-roadmap nodes against the module library and found the true- and
false-match score distributions overlap substantially at this model size
(BAAI/bge-small-en-v1.5, title+blurb text). E.g. "Query Optimization" (genuinely
about SQL) scored 0.70 against `sql`, while "DAX Fundamentals" (a Power BI
topic, not core data engineering) scored 0.74 against `data-fundamentals` --
the wrong match outscored the right one. No single threshold or score margin
separates these cleanly; a semantic check does the job a numeric cutoff can't.
"""
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.agents import prompts
from app.core.llm import chat_json
from app.db.models import ContentRoadmap, Module, RoadmapNode, RoadmapStage
from app.services.content_hub import slugify
from app.services.vector_store import find_similar_module

# Candidate floor for the embedding search -- deliberately loose. Precision comes
# from the LLM confirmation step below, not from this number.
MATCH_THRESHOLD = 0.70


def _llm_confirms_module_fit(title: str, blurb: str, module: Module) -> bool:
    """Would someone studying `title` actually be served by `module`'s content?

    A verification failure (provider down, bad JSON) returns False, not True --
    staying unmatched is the safe default; silently passing an unconfirmed match
    through is exactly the failure mode this function exists to prevent.
    """
    try:
        result = chat_json(
            [
                {
                    "role": "system",
                    "content": (
                        'You verify whether a study module genuinely covers a topic. Respond ONLY JSON: '
                        '{"fits": true or false}. Say false if the module is a different subject that '
                        "merely shares surface vocabulary with the topic."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f'Module: "{module.title}" -- {module.summary}\n'
                        f'Topic: "{title}" -- {blurb}\n\n'
                        "Would someone studying this topic be well served by this module's content?"
                    ),
                },
            ],
            fast=True,
        )
        return bool(result.get("fits"))
    except Exception:
        return False


def normalize(s: str) -> str:
    return (s or "").strip().lower()


def find_seed_roadmap(db: Session, query: str) -> Optional[ContentRoadmap]:
    norm = normalize(query)
    for r in db.query(ContentRoadmap).filter(ContentRoadmap.kind == "seed").all():
        candidates = [r.slug, r.title, r.target, *(r.aliases or [])]
        if norm in (normalize(c) for c in candidates):
            return r
    return None


def find_cached_generated_roadmap(db: Session, query: str) -> Optional[ContentRoadmap]:
    slug = slugify(query)
    if not slug:
        return None
    return (
        db.query(ContentRoadmap)
        .filter(ContentRoadmap.kind == "generated", ContentRoadmap.slug == slug)
        .first()
    )


def resolve_module_for_title(db: Session, title: str, blurb: str = "") -> tuple[Optional[Module], str, Optional[float]]:
    slug_guess = slugify(title)
    module = db.query(Module).filter(Module.slug == slug_guess).first()
    if module:
        return module, "matched", 1.0

    norm_title = normalize(title)
    for m in db.query(Module).all():
        candidates = [m.title, *(m.aliases or [])]
        if norm_title in (normalize(c) for c in candidates):
            return m, "matched", 1.0

    hit = find_similar_module(f"{title}. {blurb}".strip(), threshold=MATCH_THRESHOLD)
    if hit and hit.get("module_id"):
        module = db.get(Module, hit["module_id"])
        if module and _llm_confirms_module_fit(title, blurb, module):
            return module, "matched", hit["score"]

    return None, "unmatched", None


def generate_roadmap_skeleton(query: str) -> dict:
    return chat_json(
        [
            {"role": "system", "content": prompts.ROADMAP_SKELETON_GENERATOR.format(query=query)},
            {"role": "user", "content": "Generate the roadmap skeleton JSON now."},
        ],
        fast=False,
    )


def create_generated_roadmap(db: Session, query: str) -> ContentRoadmap:
    try:
        skeleton = generate_roadmap_skeleton(query)
    except Exception as e:
        raise HTTPException(503, "Athena's AI provider is unavailable right now -- try again shortly") from e
    stages = skeleton.get("stages", [])
    if not stages:
        raise HTTPException(502, "Could not generate a roadmap for that -- try rephrasing it")

    slug = slugify(query)
    category = skeleton.get("category") if skeleton.get("category") in ("role", "tool") else "role"
    roadmap = ContentRoadmap(slug=slug, title=skeleton.get("title", query), target=query, kind="generated", category=category)
    db.add(roadmap)
    db.flush()

    for i, s in enumerate(stages):
        stage = RoadmapStage(roadmap_id=roadmap.id, title=s.get("title", f"Stage {i + 1}"), order_index=i)
        db.add(stage)
        db.flush()
        for j, n in enumerate(s.get("nodes", [])):
            title = n.get("title", "")
            blurb = n.get("blurb", "")
            module, resolution, score = resolve_module_for_title(db, title, blurb)
            db.add(
                RoadmapNode(
                    stage_id=stage.id,
                    module_id=module.id if module else None,
                    module_slug=module.slug if module else None,
                    title=title,
                    blurb=blurb,
                    order_index=j,
                    resolution=resolution,
                    match_score=score,
                )
            )
    db.commit()
    db.refresh(roadmap)
    return roadmap


def search_roadmap(db: Session, query: str) -> tuple[ContentRoadmap, str]:
    seed = find_seed_roadmap(db, query)
    if seed:
        return seed, "seed"
    cached = find_cached_generated_roadmap(db, query)
    if cached:
        return cached, "cached"
    return create_generated_roadmap(db, query), "generated"


def serialize_roadmap(db: Session, roadmap: ContentRoadmap, resolved_via: str, user_id: int) -> dict:
    from app.services.progress import module_progress, roadmap_progress  # local import: avoid a cycle

    overall = roadmap_progress(db, user_id, roadmap)
    percent_by_module: dict[int, int] = {}
    stages_out = []
    stages = db.query(RoadmapStage).filter(RoadmapStage.roadmap_id == roadmap.id).order_by(RoadmapStage.order_index).all()
    for stage in stages:
        nodes = db.query(RoadmapNode).filter(RoadmapNode.stage_id == stage.id).order_by(RoadmapNode.order_index).all()
        nodes_out = []
        for n in nodes:
            percent = None
            if n.module_id:
                if n.module_id not in percent_by_module:
                    percent_by_module[n.module_id] = module_progress(db, user_id, n.module_id)["percent"]
                percent = percent_by_module[n.module_id]
            nodes_out.append(
                {
                    "id": n.id,
                    "title": n.title,
                    "blurb": n.blurb,
                    "module_slug": n.module_slug,
                    "resolution": n.resolution,
                    "match_score": n.match_score,
                    "percent": percent,
                }
            )
        stages_out.append({"title": stage.title, "nodes": nodes_out})
    return {
        "id": roadmap.id,
        "slug": roadmap.slug,
        "title": roadmap.title,
        "target": roadmap.target,
        "kind": roadmap.kind,
        "summary": roadmap.summary,
        "resolved_via": resolved_via,  # seed | cached | generated -- only "generated" cost an LLM call
        # Whole-roadmap completion: completed topics across every DISTINCT module this
        # roadmap references, over total topics across those same modules. A module
        # referenced by more than one node is still only counted once.
        "percent": overall["percent"],
        "topic_count": overall["topic_count"],
        "completed_count": overall["completed_count"],
        "stages": stages_out,
    }
