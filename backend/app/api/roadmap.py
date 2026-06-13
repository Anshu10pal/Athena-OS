from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.agents.roadmap_graph import generate_roadmap
from app.core.security import get_current_user
from app.db.database import get_db
from app.db.models import Roadmap, User
from app.db.schemas import NodeStatusIn, RoadmapIn

router = APIRouter(prefix="/api/roadmap", tags=["roadmap"])

XP_PER_NODE = 150


@router.post("/generate")
def generate(payload: RoadmapIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    result = generate_roadmap(payload.target_role, payload.current_skills or list((user.skills or {}).keys()))
    roadmap = Roadmap(
        user_id=user.id,
        title=result.get("title", f"{payload.target_role} Roadmap"),
        target_role=payload.target_role,
        nodes=result.get("nodes", []),
    )
    db.add(roadmap)
    db.commit()
    db.refresh(roadmap)
    return {"id": roadmap.id, "title": roadmap.title, "nodes": roadmap.nodes}


@router.get("")
def list_roadmaps(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    maps = (
        db.query(Roadmap)
        .filter(Roadmap.user_id == user.id, Roadmap.parent_roadmap_id.is_(None))
        .order_by(Roadmap.id.desc())
        .all()
    )
    return [{"id": m.id, "title": m.title, "target_role": m.target_role, "nodes": m.nodes, "depth": m.depth or 0} for m in maps]


@router.patch("/{roadmap_id}/node")
def update_node(roadmap_id: int, payload: NodeStatusIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    roadmap = db.get(Roadmap, roadmap_id)
    if not roadmap or roadmap.user_id != user.id:
        raise HTTPException(404, "Roadmap not found")
    nodes = roadmap.nodes or []
    by_id = {n["id"]: n for n in nodes}
    node = by_id.get(payload.node_id)
    if not node:
        raise HTTPException(404, "Node not found")
    if node["status"] == "locked":
        raise HTTPException(400, "Node is locked — complete its prerequisites first")
    if payload.status == "completed":
        raise HTTPException(400, "Nodes are completed by passing the assessment, not manually")

    leveled_up = False
    if payload.status == "skipped" and node["status"] not in ("completed", "skipped"):
        pass  # skip: unlocks dependents, no XP — "I already know this"
    node["status"] = payload.status

    # Unlock nodes whose dependencies are all complete
    for n in nodes:
        if n["status"] == "locked":
            deps = n.get("depends_on", [])
            if all(by_id.get(d, {}).get("status") in ("completed", "skipped") for d in deps):
                n["status"] = "available"

    roadmap.nodes = nodes
    flag_modified(roadmap, "nodes")
    db.commit()
    return {"nodes": nodes, "xp": user.xp, "xp_gained": XP_PER_NODE if leveled_up else 0}


# ---------------- Node dossier + gated assessment ----------------
from app.agents import prompts as _prompts
from app.core.llm import chat as _chat, chat_json as _chat_json
from app.db.models import Assessment, NodeContent
from app.services.content_hub import generated_links, get_community_resources, suggest_url


def _question_count(node: dict) -> int:
    n_skills = len(node.get("skills", []))
    return 15 if n_skills <= 3 else 20 if n_skills <= 6 else 25


def _find_node(db: Session, user: User, roadmap_id: int, node_id: str):
    roadmap = db.get(Roadmap, roadmap_id)
    if not roadmap or roadmap.user_id != user.id:
        raise HTTPException(404, "Roadmap not found")
    node = next((n for n in (roadmap.nodes or []) if n["id"] == node_id), None)
    if not node:
        raise HTTPException(404, "Node not found")
    return roadmap, node


@router.get("/{roadmap_id}/node/{node_id}/dossier")
def dossier(roadmap_id: int, node_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    import json as _json

    roadmap, node = _find_node(db, user, roadmap_id, node_id)
    content = (
        db.query(NodeContent)
        .filter(NodeContent.user_id == user.id, NodeContent.roadmap_id == roadmap_id, NodeContent.node_id == node_id)
        .first()
    )
    if not content or not (content.meaning or "").strip():
        profile = _json.dumps({"level": user.experience_level, "target_role": user.target_role, "skills": list((user.skills or {}).keys())})
        data = _chat_json(
            [
                {
                    "role": "system",
                    "content": _prompts.NODE_DOSSIER.format(
                        title=node["title"], description=node.get("description", ""), skills=", ".join(node.get("skills", [])), profile=profile
                    ),
                },
                {"role": "user", "content": "Write the dossier JSON."},
            ],
            fast=False,
        )
        if not content:
            content = NodeContent(user_id=user.id, roadmap_id=roadmap_id, node_id=node_id)
            db.add(content)
        content.meaning = data.get("meaning", "")
        content.eli5 = data.get("eli5", "")
        content.briefing = data.get("briefing", content.briefing or "")
        db.commit()
    child = (
        db.query(Roadmap)
        .filter(Roadmap.parent_roadmap_id == roadmap_id, Roadmap.parent_node_id == node_id, Roadmap.user_id == user.id)
        .first()
    )
    return {
        "node": node,
        "meaning": content.meaning,
        "eli5": content.eli5,
        "briefing": content.briefing,
        "child_roadmap_id": child.id if child else None,
        "depth": roadmap.depth or 0,
        "can_expand": (roadmap.depth or 0) < 2,
        "community_resources": get_community_resources(db, node["title"]),
        "generated_links": generated_links(node["title"], node.get("skills", [])),
        "suggest_url": suggest_url(node["title"]),
        "question_count": _question_count(node),
        "pass_threshold": 70,
    }


@router.post("/{roadmap_id}/node/{node_id}/assessment/start")
def start_assessment(roadmap_id: int, node_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _roadmap, node = _find_node(db, user, roadmap_id, node_id)
    if node["status"] in ("locked",):
        raise HTTPException(400, "Node is locked")
    total = _question_count(node)
    questions: list[dict] = []
    while len(questions) < total:
        batch = min(5, total - len(questions))
        result = _chat_json(
            [
                {"role": "system", "content": _prompts.MCQ_GENERATOR.format(n=batch, title=node["title"], skills=", ".join(node.get("skills", [])))},
                {"role": "user", "content": f"Generate {batch} questions. Avoid repeating: " + "; ".join(q["q"][:60] for q in questions[-5:])},
            ],
            fast=True,
        )
        for q in result.get("questions", []):
            if isinstance(q.get("options"), list) and len(q["options"]) == 4 and isinstance(q.get("answer"), int):
                questions.append({"q": q["q"], "options": q["options"], "answer": q["answer"], "topic": q.get("topic", node["title"])})
        if not result.get("questions"):
            break
    if len(questions) < 10:
        raise HTTPException(500, "Could not generate enough questions — try again")
    assessment = Assessment(user_id=user.id, roadmap_id=roadmap_id, node_id=node_id, questions=questions)
    db.add(assessment)
    db.commit()
    db.refresh(assessment)
    return {
        "assessment_id": assessment.id,
        "questions": [{"q": q["q"], "options": q["options"], "topic": q["topic"]} for q in questions],
        "pass_threshold": 70,
    }


@router.post("/assessment/{assessment_id}/submit")
def submit_assessment(assessment_id: int, payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    assessment = db.get(Assessment, assessment_id)
    if not assessment or assessment.user_id != user.id or assessment.status != "active":
        raise HTTPException(404, "Active assessment not found")
    answers = payload.get("answers", [])
    questions = assessment.questions or []
    results = []
    correct = 0
    for i, q in enumerate(questions):
        given = answers[i] if i < len(answers) else -1
        ok = given == q["answer"]
        correct += ok
        results.append({"q": q["q"], "given": given, "correct": q["answer"], "ok": ok, "topic": q["topic"]})
    score = round(100 * correct / max(1, len(questions)))
    assessment.score = score
    assessment.status = "graded"

    passed = score >= 70
    xp_gained = 0
    nodes_out = None
    if passed:
        roadmap = db.get(Roadmap, assessment.roadmap_id)
        nodes = roadmap.nodes or []
        by_id = {n["id"]: n for n in nodes}
        node = by_id.get(assessment.node_id)
        if node and node["status"] not in ("completed",):
            node["status"] = "completed"
            xp_gained = round(150 + 250 * (score - 70) / 100)
            user.xp += xp_gained
            skills = dict(user.skills or {})
            for s in node.get("skills", []):
                skills[s] = min(5, skills.get(s, 0) + 1)
            user.skills = skills
            for n in nodes:
                if n["status"] == "locked":
                    deps = n.get("depends_on", [])
                    if all(by_id.get(d, {}).get("status") in ("completed", "skipped") for d in deps):
                        n["status"] = "available"
            roadmap.nodes = nodes
            flag_modified(roadmap, "nodes")
            nodes_out = nodes
            from app.api.review import schedule_review
            schedule_review(db, user.id, assessment.roadmap_id, node["id"], node["title"])
    db.commit()
    parent_bonus = None
    if passed:
        child = db.get(Roadmap, assessment.roadmap_id)
        parent_bonus = _maybe_complete_parent(db, user, child)
        if parent_bonus:
            xp_gained += parent_bonus["bonus_xp"]
    weak = sorted({r["topic"] for r in results if not r["ok"]})
    new_badges = []
    try:
        from app.api.achievements import check_and_award, DEFS
        from app.db.models import Achievement
        if score == 100 and passed:
            if not db.query(Achievement).filter(Achievement.user_id == user.id, Achievement.code == "perfect_score").first():
                db.add(Achievement(user_id=user.id, code="perfect_score"))
                db.commit()
                new_badges.append("perfect_score")
        new_badges += check_and_award(db, user)
    except Exception:
        pass
    badges_meta = []
    try:
        from app.api.achievements import DEFS
        badges_meta = [{"code": c, "title": DEFS[c][0]} for c in new_badges if c in DEFS]
    except Exception:
        pass
    return {"score": score, "passed": passed, "xp": user.xp, "xp_gained": xp_gained, "results": results, "weak_topics": weak, "nodes": nodes_out, "parent_bonus": parent_bonus, "new_badges": badges_meta}


MAX_DEPTH = 2  # root(0) -> sub(1) -> sub-sub(2)


@router.get("/{roadmap_id}")
def get_roadmap(roadmap_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    m = db.get(Roadmap, roadmap_id)
    if not m or m.user_id != user.id:
        raise HTTPException(404, "Roadmap not found")
    parent = db.get(Roadmap, m.parent_roadmap_id) if m.parent_roadmap_id else None
    return {
        "id": m.id,
        "title": m.title,
        "target_role": m.target_role,
        "nodes": m.nodes,
        "depth": m.depth or 0,
        "parent_roadmap_id": m.parent_roadmap_id,
        "parent_title": parent.title if parent else None,
    }


@router.post("/{roadmap_id}/node/{node_id}/expand")
def expand_node(roadmap_id: int, node_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.agents.roadmap_graph import generate_sub_roadmap

    roadmap, node = _find_node(db, user, roadmap_id, node_id)
    if (roadmap.depth or 0) >= MAX_DEPTH:
        raise HTTPException(400, "Maximum drill-down depth reached")
    existing = (
        db.query(Roadmap)
        .filter(Roadmap.parent_roadmap_id == roadmap_id, Roadmap.parent_node_id == node_id, Roadmap.user_id == user.id)
        .first()
    )
    if existing:
        return {"id": existing.id, "title": existing.title, "nodes": existing.nodes, "depth": existing.depth or 0, "parent_roadmap_id": roadmap_id, "parent_title": roadmap.title}
    result = generate_sub_roadmap(roadmap.target_role, node)
    child = Roadmap(
        user_id=user.id,
        title=result.get("title", f"{node['title']} — deep dive"),
        target_role=roadmap.target_role,
        nodes=result.get("nodes", []),
        parent_roadmap_id=roadmap_id,
        parent_node_id=node_id,
        depth=(roadmap.depth or 0) + 1,
    )
    db.add(child)
    db.commit()
    db.refresh(child)
    return {"id": child.id, "title": child.title, "nodes": child.nodes, "depth": child.depth, "parent_roadmap_id": roadmap_id, "parent_title": roadmap.title}


def _maybe_complete_parent(db: Session, user: User, child: Roadmap) -> dict | None:
    """When every node in a sub-roadmap is completed/skipped, auto-complete its parent node."""
    if not child.parent_roadmap_id:
        return None
    nodes = child.nodes or []
    if not nodes or not all(n["status"] in ("completed", "skipped") for n in nodes):
        return None
    parent = db.get(Roadmap, child.parent_roadmap_id)
    if not parent:
        return None
    pnodes = parent.nodes or []
    by_id = {n["id"]: n for n in pnodes}
    pnode = by_id.get(child.parent_node_id)
    if not pnode or pnode["status"] == "completed":
        return None
    pnode["status"] = "completed"
    user.xp += 150
    for n in pnodes:
        if n["status"] == "locked":
            deps = n.get("depends_on", [])
            if all(by_id.get(d, {}).get("status") in ("completed", "skipped") for d in deps):
                n["status"] = "available"
    parent.nodes = pnodes
    flag_modified(parent, "nodes")
    db.commit()
    return {"parent_completed": pnode["title"], "bonus_xp": 150}



@router.post("/{roadmap_id}/node/{node_id}/expand")
def expand_node(roadmap_id: int, node_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Generate (or return) the granular sub-roadmap for one node — graph after graph."""
    import json as _json

    roadmap, node = _find_node(db, user, roadmap_id, node_id)
    existing = db.query(Roadmap).filter(
        Roadmap.parent_roadmap_id == roadmap_id, Roadmap.parent_node_id == node_id, Roadmap.user_id == user.id
    ).first()
    if existing:
        return {"id": existing.id, "title": existing.title, "nodes": existing.nodes, "existing": True}

    profile = _json.dumps({"level": user.experience_level, "target_role": user.target_role, "skills": list((user.skills or {}).keys())})
    result = _chat_json(
        [
            {
                "role": "system",
                "content": _prompts.SUBMAP_GENERATOR.format(
                    title=node["title"], description=node.get("description", ""), skills=", ".join(node.get("skills", [])), profile=profile
                ),
            },
            {"role": "user", "content": "Generate the sub-roadmap JSON now."},
        ],
        fast=False,
    )
    nodes = result.get("nodes", [])
    if not nodes:
        raise HTTPException(500, "Could not expand this topic — try again")
    for i, n in enumerate(nodes):
        n["status"] = "available" if i == 0 else "locked"
    # unlock any node with no dependencies
    for n in nodes:
        if not n.get("depends_on"):
            n["status"] = "available" if n["status"] == "locked" else n["status"]
    sub = Roadmap(
        user_id=user.id,
        title=result.get("title", f"{node['title']} — deep dive"),
        target_role=roadmap.target_role,
        nodes=nodes,
        parent_roadmap_id=roadmap_id,
        parent_node_id=node_id,
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return {"id": sub.id, "title": sub.title, "nodes": sub.nodes, "existing": False}


def _maybe_complete_parent(db: Session, user: User, child: Roadmap) -> dict | None:
    """When a sub-map is fully cleared, auto-complete its parent node (+100 bonus XP)."""
    if not child.parent_roadmap_id:
        return None
    if not all(n["status"] in ("completed", "skipped") for n in (child.nodes or [])):
        return None
    parent = db.get(Roadmap, child.parent_roadmap_id)
    if not parent:
        return None
    nodes = parent.nodes or []
    by_id = {n["id"]: n for n in nodes}
    pnode = by_id.get(child.parent_node_id)
    if not pnode or pnode["status"] == "completed":
        return None
    pnode["status"] = "completed"
    user.xp += 100
    for n in nodes:
        if n["status"] == "locked":
            deps = n.get("depends_on", [])
            if all(by_id.get(d, {}).get("status") in ("completed", "skipped") for d in deps):
                n["status"] = "available"
    parent.nodes = nodes
    flag_modified(parent, "nodes")
    db.commit()
    return {"parent_roadmap_id": parent.id, "parent_node": pnode["title"], "bonus_xp": 100}


from app.db.schemas import AddNodeIn


@router.post("/{roadmap_id}/node")
def add_node(roadmap_id: int, payload: AddNodeIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Add a custom topic to your journey — Athena fills in description and skills."""
    roadmap = db.get(Roadmap, roadmap_id)
    if not roadmap or roadmap.user_id != user.id:
        raise HTTPException(404, "Roadmap not found")
    nodes = list(roadmap.nodes or [])
    try:
        meta = _chat_json(
            [
                {"role": "system", "content": 'Return ONLY JSON: {"description": "1-2 sentence description of the topic", "skills": ["3-6 sub-skills"]}'},
                {"role": "user", "content": f"Topic: {payload.title} (context: learning path toward {roadmap.target_role})"},
            ],
            fast=True,
        )
    except Exception:
        meta = {"description": "", "skills": []}
    new_id = f"n{max((int(n['id'][1:]) for n in nodes if n['id'][1:].isdigit()), default=0) + 1}"
    nodes.append(
        {
            "id": new_id,
            "title": payload.title,
            "description": meta.get("description", ""),
            "skills": meta.get("skills", []),
            "depends_on": [],
            "status": "available",
            "custom": True,
        }
    )
    roadmap.nodes = nodes
    flag_modified(roadmap, "nodes")
    db.commit()
    return {"nodes": nodes}


@router.delete("/{roadmap_id}/node/{node_id}")
def remove_node(roadmap_id: int, node_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Remove a topic that isn't relevant to your journey. Dependents re-wire automatically."""
    roadmap = db.get(Roadmap, roadmap_id)
    if not roadmap or roadmap.user_id != user.id:
        raise HTTPException(404, "Roadmap not found")
    nodes = [n for n in (roadmap.nodes or []) if n["id"] != node_id]
    if len(nodes) == len(roadmap.nodes or []):
        raise HTTPException(404, "Node not found")
    by_id = {n["id"]: n for n in nodes}
    for n in nodes:
        n["depends_on"] = [d for d in n.get("depends_on", []) if d in by_id]
        if n["status"] == "locked" and all(by_id.get(d, {}).get("status") in ("completed", "skipped") for d in n["depends_on"]):
            n["status"] = "available"
    roadmap.nodes = nodes
    flag_modified(roadmap, "nodes")
    db.commit()
    return {"nodes": nodes}
