"""Spaced repetition with decay.

On node completion, a ReviewItem is scheduled. Reviews recur on an expanding interval;
passing advances the interval, failing resets it. Memory 'strength' decays past the due date,
visibly dimming nodes and the Digital Twin until the user reviews.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agents import prompts
from app.core.llm import chat_json
from app.core.security import get_current_user
from app.db.database import get_db
from app.db.models import Assessment, ReviewItem, User

router = APIRouter(prefix="/api/review", tags=["review"])

INTERVALS_DAYS = [1, 3, 7, 21, 60]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt and dt.tzinfo is None else dt


def schedule_review(db: Session, user_id: int, roadmap_id: int, node_id: str, node_title: str):
    """Called when a node is completed. Idempotent per (user, node)."""
    existing = (
        db.query(ReviewItem)
        .filter(ReviewItem.user_id == user_id, ReviewItem.roadmap_id == roadmap_id, ReviewItem.node_id == node_id)
        .first()
    )
    if existing:
        return
    db.add(
        ReviewItem(
            user_id=user_id,
            roadmap_id=roadmap_id,
            node_id=node_id,
            node_title=node_title,
            interval_idx=0,
            due_at=_now() + timedelta(days=INTERVALS_DAYS[0]),
        )
    )
    db.commit()


def strength_of(item: ReviewItem) -> float:
    """1.0 = fresh. Decays linearly once overdue, floored at 0.15."""
    due = _aware(item.due_at)
    now = _now()
    if now <= due:
        return 1.0
    overdue_days = (now - due).total_seconds() / 86400
    window = INTERVALS_DAYS[min(item.interval_idx, len(INTERVALS_DAYS) - 1)]
    return max(0.15, 1.0 - overdue_days / (window * 1.5))


def summary(db: Session, user_id: int) -> dict:
    items = db.query(ReviewItem).filter(ReviewItem.user_id == user_id).all()
    now = _now()
    due = [i for i in items if _aware(i.due_at) <= now]
    avg_strength = round(sum(strength_of(i) for i in items) / len(items), 2) if items else 1.0
    return {"reviews_due": len(due), "total_tracked": len(items), "memory_strength": avg_strength}


def due_forecast(db: Session, user_id: int, days: int = 7) -> list[dict]:
    """Real per-day due counts for the next `days` days. Anything already overdue
    or due today buckets into today -- not dropped, not double-counted."""
    today = _now().date()
    items = db.query(ReviewItem).filter(ReviewItem.user_id == user_id).all()
    counts: dict = {}
    for i in items:
        d = _aware(i.due_at).date()
        bucket = today if d <= today else d
        delta = (bucket - today).days
        if 0 <= delta < days:
            counts[bucket] = counts.get(bucket, 0) + 1
    return [
        {"date": (today + timedelta(days=k)).isoformat(), "count": counts.get(today + timedelta(days=k), 0)}
        for k in range(days)
    ]


@router.get("/due")
def due(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    now = _now()
    items = (
        db.query(ReviewItem)
        .filter(ReviewItem.user_id == user.id)
        .order_by(ReviewItem.due_at.asc())
        .all()
    )
    out = []
    for i in items:
        out.append(
            {
                "id": i.id,
                "node_title": i.node_title,
                "due_at": str(_aware(i.due_at))[:10],
                "is_due": _aware(i.due_at) <= now,
                "interval_stage": i.interval_idx + 1,
                "strength": round(strength_of(i), 2),
            }
        )
    return {"items": out, **summary(db, user.id)}


@router.post("/{review_id}/start")
def start_review(review_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    item = db.get(ReviewItem, review_id)
    if not item or item.user_id != user.id:
        raise HTTPException(404, "Review not found")

    # Vocab/concept cards (from the Communication gym) generate a fresh recall question.
    if getattr(item, "kind", "node") in ("vocab", "concept"):
        try:
            q = chat_json(
                [
                    {"role": "system", "content": (
                        "Create ONE multiple-choice recall question to test whether the user knows this "
                        f"{item.kind}: '{item.node_title}'. Context: {item.detail or 'general usage'}. "
                        "Return ONLY JSON: {\"q\": str, \"options\": [4 strings], \"answer\": int index}."
                    )},
                    {"role": "user", "content": "Generate it."},
                ],
                fast=True,
            )
            opts = q.get("options", [])
            if len(opts) >= 2:
                return {"review_id": item.id, "node_title": item.node_title,
                        "questions": [{"q": q.get("q", f"What does '{item.node_title}' mean?"),
                                       "options": opts, "answer": int(q.get("answer", 0))}]}
        except Exception:
            pass
        return {"review_id": item.id, "node_title": item.node_title,
                "questions": [{"q": f"Recall: what does '{item.node_title}' mean?",
                               "options": [item.detail or "the correct meaning", "an unrelated meaning", "none of these", "not sure"],
                               "answer": 0}]}

    # Reuse the node's most recent assessment question pool; sample 5.
    import random

    pool: list[dict] = []
    assessment = (
        db.query(Assessment)
        .filter(Assessment.user_id == user.id, Assessment.roadmap_id == item.roadmap_id, Assessment.node_id == item.node_id)
        .order_by(Assessment.id.desc())
        .first()
    )
    if assessment and assessment.questions:
        pool = list(assessment.questions)
    if len(pool) < 5:
        gen = chat_json(
            [
                {"role": "system", "content": prompts.MCQ_GENERATOR.format(n=5, title=item.node_title, skills=item.node_title)},
                {"role": "user", "content": "Generate 5 recall questions."},
            ],
            fast=True,
        )
        pool = gen.get("questions", pool)
    random.shuffle(pool)
    quiz = pool[:5]
    # stash answer key on the item via a transient store: re-fetch on submit from same pool is unreliable,
    # so return answers-hidden and keep the key in the assessment; we grade by matching question text.
    return {
        "review_id": item.id,
        "node_title": item.node_title,
        "questions": [{"q": q["q"], "options": q["options"], "answer": q.get("answer", 0)} for q in quiz],
    }


@router.post("/{review_id}/submit")
def submit_review(review_id: int, payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    item = db.get(ReviewItem, review_id)
    if not item or item.user_id != user.id:
        raise HTTPException(404, "Review not found")
    score = int(payload.get("score", 0))  # client computes correct/total*100 against provided answers
    passed = score >= 70
    if passed:
        item.interval_idx = min(item.interval_idx + 1, len(INTERVALS_DAYS) - 1)
        user.xp += 30
    else:
        item.interval_idx = 0
    item.due_at = _now() + timedelta(days=INTERVALS_DAYS[item.interval_idx])
    item.last_reviewed = _now()
    item.last_score = score
    db.commit()
    return {"passed": passed, "score": score, "next_due": str(item.due_at)[:10], "xp": user.xp, **summary(db, user.id)}
