"""Interview Arena API -- Phase A: JD in, confirmed skill graph out.

Namespaced /api/arena, not /api/interview. The legacy interview router is still
mounted and still feeds analytics, achievements and the activity streak; it also
stays useful as a side-by-side comparison against this pipeline.

Phase A endpoints only. There is no session, item or scoring endpoint here --
not even a stub returning an empty list, because an endpoint that answers
plausibly while nothing is implemented is worse than a 404: it looks like data.
"""
from datetime import timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.database import get_db
from app.db.models import (ArenaJobTarget, ArenaMergeSuggestion, ArenaSkillNode,
                           User, utcnow)
from app.db.schemas import ArenaGraphPatchIn, ArenaJobTargetIn, ArenaMergeDecisionIn
from app.services.arena import graph_build
from app.services.arena.canonicalise import METHOD_USER
from app.services.arena.config import load_config

router = APIRouter(prefix="/api/arena", tags=["arena"])

VALID_TIERS = ("expert", "proficient", "working", "awareness")


def _owned_target(db: Session, target_id: int, user: User) -> ArenaJobTarget:
    """Load a job target or 404. Ownership is checked here rather than in each
    endpoint so a new endpoint cannot forget it -- a graph is derived from a
    document the user pasted and is not shared."""
    target = db.get(ArenaJobTarget, target_id)
    if target is None or target.user_id != user.id:
        raise HTTPException(404, "Job target not found")
    return target


@router.post("/job-target")
def create_job_target(
    payload: ArenaJobTargetIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Submit a title + JD; get back an unconfirmed skill graph.

    Idempotent on (user, normalised JD, extractor version): re-submitting the
    same JD returns the existing graph, edits and confirmation intact, rather
    than regenerating and silently discarding the user's corrections.
    """
    jd = (payload.jd_text or "").strip()
    if len(jd) < 40:
        # A floor, not a style preference: below roughly this length there is no
        # document to extract from, and the honest response is to refuse rather
        # than to return a graph invented from a phrase.
        raise HTTPException(422, "Job description is too short to extract a skill graph from")

    target, cached = graph_build.build_graph(
        db=db, user_id=user.id, title=(payload.title or "").strip(), jd_text=jd
    )
    graph = graph_build.serialise_graph(db, target)
    graph["cached"] = cached
    return graph


@router.get("/job-target/{target_id}")
def get_job_target(
    target_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    target = _owned_target(db, target_id, user)
    return graph_build.serialise_graph(db, target)


@router.get("/job-targets")
def list_job_targets(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """This user's job targets, newest first. Summary only -- the JD text and
    the full graph are large and neither is needed to render a list."""
    rows = list(db.execute(
        select(ArenaJobTarget)
        .where(ArenaJobTarget.user_id == user.id)
        .order_by(ArenaJobTarget.created_at.desc())
    ).scalars())
    counts = {
        row.id: db.query(ArenaSkillNode)
        .filter(ArenaSkillNode.job_target_id == row.id)
        .count()
        for row in rows
    }
    return [
        {
            "id": row.id,
            "title": row.title,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "graph_confirmed_at": (row.graph_confirmed_at.isoformat()
                                   if row.graph_confirmed_at else None),
            "extractor_version": row.extractor_version,
            "node_count": counts.get(row.id, 0),
        }
        for row in rows
    ]


@router.patch("/job-target/{target_id}/graph")
def patch_graph(
    target_id: int,
    payload: ArenaGraphPatchIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Persist user edits and optionally confirm the graph.

    Every edit sets `user_edited` on the touched node. That flag is free
    correction signal -- a labelled statement that the extractor got this node
    wrong -- and it is the only ground truth this component will ever have, so
    it is recorded rather than discarded.
    """
    target = _owned_target(db, target_id, user)
    cfg = load_config()
    max_children = int(cfg["max_children_per_parent"])
    touched = 0

    rows = {
        row.id: row
        for row in db.execute(
            select(ArenaSkillNode).where(ArenaSkillNode.job_target_id == target.id)
        ).scalars()
    }

    for edit in payload.deletes or []:
        row = rows.get(edit)
        if row is None:
            continue
        # Re-parent orphans to the deleted node's parent rather than cascading.
        # Deleting a parent must not silently delete the skills under it -- those
        # came from the JD and losing them is the one thing this pipeline must
        # never do.
        for candidate in rows.values():
            if candidate.parent_id == row.id:
                candidate.parent_id = row.parent_id
                candidate.user_edited = True
        db.delete(row)
        rows.pop(edit, None)
        touched += 1

    for update in payload.updates or []:
        row = rows.get(update.id)
        if row is None:
            continue
        if update.canonical_name is not None:
            name = update.canonical_name.strip()
            if not name:
                raise HTTPException(422, f"Node {update.id}: name cannot be empty")
            row.canonical_name = name[:200]
        if update.jd_weight is not None:
            if not 0.0 <= update.jd_weight <= 1.0:
                raise HTTPException(422, f"Node {update.id}: jd_weight must be 0.0-1.0")
            row.jd_weight = update.jd_weight
            # A user-set weight has no signal derivation. Recording that
            # explicitly, rather than leaving the model's stale breakdown in
            # place, so the UI never explains a hand-set number with arithmetic
            # that did not produce it.
            row.weight_signals_json = {
                "derivation": "set by user",
                "previous": row.weight_signals_json or {},
            }
        if update.target_tier is not None:
            if update.target_tier not in VALID_TIERS:
                raise HTTPException(422, f"Unknown target_tier {update.target_tier!r}")
            row.target_tier = update.target_tier
        if update.parent_id is not None:
            new_parent = None if update.parent_id == 0 else rows.get(update.parent_id)
            if update.parent_id != 0 and new_parent is None:
                raise HTTPException(422, f"Parent {update.parent_id} is not in this graph")
            if new_parent is not None:
                if new_parent.id == row.id:
                    raise HTTPException(422, "A node cannot be its own parent")
                if new_parent.parent_id is not None:
                    # Two levels only. A deeper tree is not something the
                    # confirmation UI or the coverage rule were designed for,
                    # and silently allowing it would let a user build a shape
                    # later phases cannot traverse.
                    raise HTTPException(422, "Graphs are two levels deep; that parent is a child")
                siblings = sum(1 for r in rows.values()
                               if r.parent_id == new_parent.id and r.id != row.id)
                if siblings + 1 > max_children:
                    raise HTTPException(
                        422, f"{new_parent.canonical_name} would exceed "
                             f"{max_children} children")
            row.parent_id = None if update.parent_id == 0 else update.parent_id
        row.user_edited = True
        touched += 1

    for addition in payload.additions or []:
        name = (addition.canonical_name or "").strip()
        if not name:
            raise HTTPException(422, "A new node needs a name")
        parent_id = addition.parent_id or None
        if parent_id and parent_id not in rows:
            raise HTTPException(422, f"Parent {parent_id} is not in this graph")
        row = ArenaSkillNode(
            job_target_id=target.id,
            parent_id=parent_id,
            canonical_name=name[:200],
            jd_weight=addition.jd_weight if addition.jd_weight is not None else 0.5,
            target_tier=addition.target_tier or "working",
            weight_signals_json={"derivation": "added by user"},
            surface_forms_json=[name],
            merge_evidence_json=[],
            source_spans_json=[],
            # A user-added node is NOT llm_extraction. Recording it correctly
            # keeps the hallucination count honest -- a skill the user added
            # must never later be counted as one the model invented, or as one
            # it found.
            extraction_source=graph_build.SOURCE_USER,
            user_edited=True,
            order_index=len(rows) + 1,
        )
        db.add(row)
        touched += 1

    if payload.confirm:
        nodes_left = db.query(ArenaSkillNode).filter(
            ArenaSkillNode.job_target_id == target.id).count()
        # Counting AFTER the edits above, including the additions still pending
        # in this session, so a user who deleted everything and added one node
        # can still confirm.
        if nodes_left + len(payload.additions or []) == 0:
            raise HTTPException(422, "Cannot confirm an empty graph")
        target.graph_confirmed_at = utcnow()

    db.commit()
    db.refresh(target)
    graph = graph_build.serialise_graph(db, target)
    graph["edits_applied"] = touched
    return graph


@router.post("/job-target/{target_id}/merge-suggestion/{suggestion_id}")
def decide_merge_suggestion(
    target_id: int,
    suggestion_id: int,
    payload: ArenaMergeDecisionIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Accept or reject one review-band merge suggestion.

    A REJECTION is the valuable outcome to record: it is hand-labelled negative
    data on exactly the band where the instrument is weakest, and it is what a
    future retune of `review_band_low` should be measured against. Both
    decisions are persisted with a timestamp; neither is inferred from the
    absence of the other.
    """
    target = _owned_target(db, target_id, user)
    suggestion = db.get(ArenaMergeSuggestion, suggestion_id)
    if suggestion is None or suggestion.job_target_id != target.id:
        raise HTTPException(404, "Merge suggestion not found")
    if payload.decision not in ("accepted", "rejected"):
        raise HTTPException(422, "decision must be 'accepted' or 'rejected'")

    suggestion.status = payload.decision
    suggestion.decided_at = utcnow()

    if payload.decision == "accepted":
        left = db.get(ArenaSkillNode, suggestion.left_node_id)
        right = db.get(ArenaSkillNode, suggestion.right_node_id)
        if left is None or right is None:
            raise HTTPException(409, "One of the suggested nodes no longer exists")
        # Keep the node with more evidence behind it; fold the other in.
        keeper, absorbed = (left, right)
        if len(right.source_spans_json or []) > len(left.source_spans_json or []):
            keeper, absorbed = (right, left)

        keeper.surface_forms_json = list(
            dict.fromkeys((keeper.surface_forms_json or []) + (absorbed.surface_forms_json or []))
        )
        keeper.source_spans_json = (keeper.source_spans_json or []) + (absorbed.source_spans_json or [])
        keeper.merge_evidence_json = (keeper.merge_evidence_json or []) + [{
            "surface": absorbed.canonical_name,
            # Recorded as METHOD_USER, never as an embedding branch. A
            # user-accepted merge must not be counted as one the cascade made,
            # or the branch-firing telemetry becomes unreadable.
            "method": METHOD_USER,
            "score": suggestion.enriched_cosine,
        }] + (absorbed.merge_evidence_json or [])
        keeper.jd_weight = max(keeper.jd_weight, absorbed.jd_weight)
        keeper.user_edited = True

        for candidate in db.execute(
            select(ArenaSkillNode).where(ArenaSkillNode.job_target_id == target.id)
        ).scalars():
            if candidate.parent_id == absorbed.id:
                candidate.parent_id = keeper.id
        db.delete(absorbed)

    db.commit()
    db.refresh(target)
    return graph_build.serialise_graph(db, target)


@router.get("/job-target/{target_id}/readiness")
def readiness(
    target_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Can a session start on this graph?

    Exists as its own endpoint so the frontend's Start-interview gate reads a
    server answer rather than re-deriving the rule client-side. Two copies of a
    gate is one copy too many, and the copy that drifts is always the one on the
    screen.
    """
    target = _owned_target(db, target_id, user)
    node_count = db.query(ArenaSkillNode).filter(
        ArenaSkillNode.job_target_id == target.id).count()
    pending = db.query(ArenaMergeSuggestion).filter(
        ArenaMergeSuggestion.job_target_id == target.id,
        ArenaMergeSuggestion.status == "pending",
    ).count()
    confirmed = target.graph_confirmed_at is not None
    return {
        "confirmed": confirmed,
        "confirmed_at": (target.graph_confirmed_at.replace(tzinfo=timezone.utc).isoformat()
                         if target.graph_confirmed_at else None),
        "node_count": node_count,
        "pending_merge_suggestions": pending,
        "can_start": confirmed and node_count > 0,
        # Pending suggestions do NOT block starting. They are genuinely
        # ambiguous pairs and forcing a decision on each would make the gate
        # a chore rather than a check; an undecided pair simply stays unmerged,
        # which is the safe default.
        "blocking_reason": (None if confirmed and node_count > 0
                            else "The skill graph has not been confirmed yet"
                            if not confirmed else "The skill graph is empty"),
    }
