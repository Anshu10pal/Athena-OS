"""Communication Gym — four modalities of general-communication practice.

Writing is implemented first: a generated prompt, a typed response, and a scorecard that
fuses locally-MEASURED metrics (vocabulary, clarity, precision) with LLM-EVALUATED ones
(grammar, structure, tone). Missed vocab/grammar items feed the spaced-repetition Review Queue.
"""
import base64
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.agents import prompts
from app.core.llm import chat_json
from app.core.security import get_current_user
from app.db.database import get_db
from app.db.models import CommunicationSession, ReviewItem, User
from app.services.text_metrics import analyze

router = APIRouter(prefix="/api/communication", tags=["communication"])

# weights to blend sub-scores into one modality score
WRITING_WEIGHTS = {"grammar": 0.2, "vocabulary": 0.18, "structure": 0.2, "precision": 0.16, "clarity": 0.13, "tone": 0.13}
READING_WEIGHTS = {"comprehension": 0.3, "inference": 0.3, "vocabulary": 0.2, "main_idea": 0.2}
LISTENING_WEIGHTS = {"reception": 0.55, "inference": 0.45}


def _now():
    return datetime.now(timezone.utc)


def _feed_review(db: Session, user_id: int, terms: list[dict]):
    """Missed vocab/grammar items become spaced-repetition cards (reuses ReviewItem)."""
    added = 0
    for t in terms[:4]:
        term = (t.get("term") or "").strip()
        if not term:
            continue
        node_id = f"comm:{term.lower()[:32]}"
        exists = (
            db.query(ReviewItem)
            .filter(ReviewItem.user_id == user_id, ReviewItem.node_id == node_id)
            .first()
        )
        if exists:
            continue
        db.add(
            ReviewItem(
                user_id=user_id,
                roadmap_id=0,
                node_id=node_id,
                node_title=term,
                kind=t.get("kind", "vocab") if t.get("kind") in ("vocab", "concept") else "vocab",
                detail=(t.get("detail") or "")[:500],
                interval_idx=0,
                due_at=_now() + timedelta(days=1),
            )
        )
        added += 1
    if added:
        db.commit()
    return added


def speaking_overall(scores: dict) -> int:
    """Oratory scores are 0-10 across dimensions; blend into a 0-100 speaking score."""
    vals = [v for v in (scores or {}).values() if isinstance(v, (int, float))]
    return round(sum(vals) / len(vals) * 10) if vals else 0


def backfill_speaking(db: Session) -> int:
    """One-time, idempotent: mirror existing SpeechSessions into CommunicationSession
    (modality='speaking') so the radar and gym history are coherent. Matches on
    (user_id, created_at) so reruns don't duplicate."""
    from app.db.models import SpeechSession
    existing = {
        (c.user_id, c.created_at)
        for c in db.query(CommunicationSession.user_id, CommunicationSession.created_at)
        .filter(CommunicationSession.modality == "speaking").all()
    }
    added = 0
    for sp in db.query(SpeechSession).all():
        if (sp.user_id, sp.created_at) in existing:
            continue
        db.add(CommunicationSession(
            user_id=sp.user_id, modality="speaking", difficulty=sp.mode or "classic",
            prompt=sp.topic or "", response=(sp.transcript or "")[:2000],
            metrics=sp.metrics or {},
            scores={k: v for k, v in (sp.scores or {}).items() if isinstance(v, (int, float))},
            overall=speaking_overall(sp.scores), created_at=sp.created_at,
        ))
        added += 1
    if added:
        db.commit()
    return added


@router.post("/writing/prompt")
def writing_prompt(payload: dict, user: User = Depends(get_current_user)):
    difficulty = payload.get("difficulty", "Intermediate")
    try:
        gen = chat_json(
            [
                {"role": "system", "content": prompts.WRITING_PROMPT_GEN.format(difficulty=difficulty)},
                {"role": "user", "content": "Generate one prompt."},
            ],
            fast=True,
        )
    except Exception:
        gen = {}
    target = {"Beginner": 80, "Intermediate": 150, "Advanced": 220}.get(difficulty, 150)
    return {
        "prompt": gen.get("prompt", "Describe a recent situation at work where clear communication made a difference."),
        "target_words": int(gen.get("target_words", target) or target),
        "register": gen.get("register", "professional"),
        "difficulty": difficulty,
    }


@router.post("/writing/analyze")
def writing_analyze(payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    prompt = payload.get("prompt", "")
    response = (payload.get("response") or "").strip()
    register = payload.get("register", "professional")
    difficulty = payload.get("difficulty", "Intermediate")

    measured = analyze(response)
    if measured.get("empty") or measured.get("word_count", 0) < 5:
        return {"error": "Write at least a sentence or two so Athena can score it."}

    # LLM-evaluated dimensions
    try:
        ev = chat_json(
            [
                {"role": "system", "content": prompts.WRITING_EVAL.format(prompt=prompt, register=register, response=response[:4000])},
                {"role": "user", "content": "Evaluate."},
            ],
            fast=True,
        )
    except Exception:
        ev = {}

    m = measured["scores"]
    scores = {
        "grammar": {"value": int(ev.get("grammar_score", 70)), "source": "evaluated"},
        "vocabulary": {"value": m["vocabulary"], "source": "measured"},
        "structure": {"value": int(ev.get("structure_score", 70)), "source": "evaluated"},
        "precision": {"value": m["precision"], "source": "measured"},
        "clarity": {"value": m["clarity"], "source": "measured"},
        "tone": {"value": int(ev.get("tone_score", 70)), "source": "evaluated"},
    }
    overall = round(sum(scores[k]["value"] * WRITING_WEIGHTS[k] for k in WRITING_WEIGHTS))

    review_added = _feed_review(db, user.id, ev.get("review_terms", []))

    # XP: base + improvement-agnostic small reward
    user.xp += 20 + (10 if overall >= 75 else 0)

    session = CommunicationSession(
        user_id=user.id, modality="writing", difficulty=difficulty,
        prompt=prompt, response=response,
        metrics=measured, scores={k: v["value"] for k, v in scores.items()}, overall=overall,
    )
    db.add(session)
    db.commit()

    new_badges = []
    try:
        from app.api.achievements import check_and_award, DEFS
        new_badges = [{"code": c, "title": DEFS[c][0]} for c in check_and_award(db, user) if c in DEFS]
    except Exception:
        pass

    return {
        "overall": overall,
        "scores": scores,
        "measured": measured,
        "feedback": ev.get("feedback", ""),
        "tip": ev.get("tip", ""),
        "grammar_fixes": ev.get("grammar_fixes", [])[:4],
        "vocab_upgrades": ev.get("vocab_upgrades", [])[:4],
        "review_added": review_added,
        "xp": user.xp,
        "new_badges": new_badges,
    }


@router.post("/reading/passage")
def reading_passage(payload: dict, user: User = Depends(get_current_user)):
    difficulty = payload.get("difficulty", "Intermediate")
    try:
        gen = chat_json(
            [
                {"role": "system", "content": prompts.READING_GEN.format(difficulty=difficulty)},
                {"role": "user", "content": "Write the passage and quiz."},
            ],
            fast=True,
        )
    except Exception:
        gen = {}
    passage = gen.get("passage", "")
    questions = [q for q in gen.get("questions", []) if q.get("options") and len(q["options"]) >= 2]
    word_count = len(passage.split())
    return {
        "passage": passage,
        "word_count": word_count,
        "target_seconds": max(20, round(word_count / 200 * 60)),
        "questions": questions,
        "difficulty": difficulty,
    }


@router.post("/reading/submit")
def reading_submit(payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    difficulty = payload.get("difficulty", "Intermediate")
    wpm = int(payload.get("wpm", 0))
    questions = payload.get("questions", [])
    picks = payload.get("picks", [])

    by_type: dict[str, list[bool]] = {}
    missed_terms: list[dict] = []
    results = []
    for i, q in enumerate(questions):
        pick = picks[i] if i < len(picks) else -1
        correct = pick == q.get("answer", 0)
        t = q.get("type", "comprehension")
        by_type.setdefault(t, []).append(correct)
        results.append({"q": q.get("q", ""), "correct": correct, "your": pick, "answer": q.get("answer", 0), "type": t})
        if not correct and t == "vocabulary" and q.get("term"):
            missed_terms.append({"term": q["term"], "detail": q.get("detail", ""), "kind": "vocab"})

    dims = {}
    for t in ("comprehension", "inference", "vocabulary", "main_idea"):
        hits = by_type.get(t, [])
        dims[t] = round(100 * sum(hits) / len(hits)) if hits else None
    present = {k: v for k, v in dims.items() if v is not None}
    overall = round(sum(present[k] * READING_WEIGHTS[k] for k in present) / sum(READING_WEIGHTS[k] for k in present)) if present else 0

    review_added = _feed_review(db, user.id, missed_terms)
    user.xp += 20 + (10 if overall >= 75 else 0)

    metrics = {"wpm": wpm, "word_count": payload.get("word_count", 0), "dimensions": dims}
    db.add(CommunicationSession(
        user_id=user.id, modality="reading", difficulty=difficulty,
        prompt="(reading passage)", response="",
        metrics=metrics, scores={k: v for k, v in dims.items() if v is not None}, overall=overall,
    ))
    db.commit()

    new_badges = []
    try:
        from app.api.achievements import check_and_award, DEFS
        new_badges = [{"code": c, "title": DEFS[c][0]} for c in check_and_award(db, user) if c in DEFS]
    except Exception:
        pass

    return {"overall": overall, "wpm": wpm, "dimensions": dims, "results": results,
            "review_added": review_added, "xp": user.xp, "new_badges": new_badges}


async def _synthesize(text: str, voice_name: str) -> bytes:
    import io
    try:
        import edge_tts
        communicate = edge_tts.Communicate(text[:1500], voice=voice_name or "en-US-AriaNeural")
        buf = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                buf.write(chunk["data"])
        return buf.getvalue()
    except Exception:
        return b""


@router.post("/listening/passage")
async def listening_passage(payload: dict, user: User = Depends(get_current_user)):
    difficulty = payload.get("difficulty", "Intermediate")
    try:
        gen = chat_json(
            [
                {"role": "system", "content": prompts.LISTENING_GEN.format(difficulty=difficulty)},
                {"role": "user", "content": "Write the passage and quiz."},
            ],
            fast=True,
        )
    except Exception:
        gen = {}
    passage = gen.get("passage", "")
    questions = [q for q in gen.get("questions", []) if q.get("options") and len(q["options"]) >= 2]

    audio = await _synthesize(passage, getattr(user, "voice", None))
    if audio:
        # text withheld so it's a genuine listening test
        return {
            "audio_b64": base64.b64encode(audio).decode(),
            "questions": questions,
            "difficulty": difficulty,
            "tts_unavailable": False,
        }
    # Fallback: TTS blocked/unavailable -> hand the text to the client to read aloud via
    # the browser speech synthesizer (the client must NOT render it on screen).
    return {"audio_b64": None, "passage": passage, "questions": questions, "difficulty": difficulty, "tts_unavailable": True}


@router.post("/listening/submit")
def listening_submit(payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    difficulty = payload.get("difficulty", "Intermediate")
    questions = payload.get("questions", [])
    picks = payload.get("picks", [])

    by_type: dict[str, list[bool]] = {}
    missed_terms: list[dict] = []
    for i, q in enumerate(questions):
        pick = picks[i] if i < len(picks) else -1
        correct = pick == q.get("answer", 0)
        by_type.setdefault(q.get("type", "reception"), []).append(correct)
        if not correct and q.get("term"):
            missed_terms.append({"term": q["term"], "detail": q.get("detail", ""), "kind": "concept"})

    # reception groups recall + detail; inference separate
    recep_hits = by_type.get("reception", []) + by_type.get("detail", [])
    inf_hits = by_type.get("inference", [])
    dims = {
        "reception": round(100 * sum(recep_hits) / len(recep_hits)) if recep_hits else None,
        "inference": round(100 * sum(inf_hits) / len(inf_hits)) if inf_hits else None,
    }
    present = {k: v for k, v in dims.items() if v is not None}
    overall = round(sum(present[k] * LISTENING_WEIGHTS[k] for k in present) / sum(LISTENING_WEIGHTS[k] for k in present)) if present else 0

    review_added = _feed_review(db, user.id, missed_terms)
    user.xp += 20 + (10 if overall >= 75 else 0)

    db.add(CommunicationSession(
        user_id=user.id, modality="listening", difficulty=difficulty,
        prompt="(listening passage)", response="",
        metrics={"dimensions": dims}, scores={k: v for k, v in dims.items() if v is not None}, overall=overall,
    ))
    db.commit()

    new_badges = []
    try:
        from app.api.achievements import check_and_award, DEFS
        new_badges = [{"code": c, "title": DEFS[c][0]} for c in check_and_award(db, user) if c in DEFS]
    except Exception:
        pass

    return {"overall": overall, "dimensions": dims, "review_added": review_added, "xp": user.xp, "new_badges": new_badges}


@router.get("/radar")
def radar(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Latest score per modality + blended Communication metric for the Digital Twin."""
    out = {}
    for modality in ("writing", "listening", "reading", "speaking"):
        last = (
            db.query(CommunicationSession)
            .filter(CommunicationSession.user_id == user.id, CommunicationSession.modality == modality)
            .order_by(CommunicationSession.id.desc())
            .first()
        )
        out[modality] = last.overall if last else None
    # speaking can fall back to oratory history if not yet migrated
    if out["speaking"] is None:
        try:
            from app.db.models import SpeechSession
            sp = db.query(SpeechSession).filter(SpeechSession.user_id == user.id).order_by(SpeechSession.id.desc()).first()
            if sp and sp.scores:
                vals = [v for v in sp.scores.values() if isinstance(v, (int, float))]
                if vals:
                    out["speaking"] = round(sum(vals) / len(vals) * 10)  # oratory scores are 0-10
        except Exception:
            pass
    present = [v for v in out.values() if v is not None]
    out["communication"] = round(sum(present) / len(present)) if present else None
    return out
