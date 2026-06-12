"""Oratory Deck — Toastmasters-style impromptu speaking practice.

Topic draw -> 30s think -> 1-3 min speak -> verbatim transcription -> Ah-Counter analytics.
"""
import json
import re
import tempfile

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.agents import prompts
from app.core.llm import chat_json
from app.core.security import get_current_user
from app.db.database import get_db
from app.db.models import SpeechSession, User, VaultEntry
from app.services.vector_store import add_memory

router = APIRouter(prefix="/api/oratory", tags=["oratory"])

CORE_FILLERS = {"um", "uh", "erm", "ah", "hmm", "mmm", "uhm"}
CRUTCH_CANDIDATES = {"like", "basically", "actually", "literally", "so", "right", "okay", "just"}
HEDGES = ["i think", "i guess", "maybe", "sort of", "kind of", "probably", "i feel like", "not sure"]
WEAK_WORDS = {"very", "really", "thing", "things", "stuff", "good", "nice", "a lot"}
HEDGING = ["maybe", "probably", "perhaps", "kind of", "sort of", "i think", "i guess", "i feel like"]
_whisper = None


@router.post("/topic")
def topic(payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    mode = (payload or {}).get("mode", "classic")
    recent = [
        s.topic for s in db.query(SpeechSession).filter(SpeechSession.user_id == user.id).order_by(SpeechSession.id.desc()).limit(12).all()
    ]
    avoid = "; ".join(t[:70] for t in recent) or "none"
    result = chat_json(
        [
            {"role": "system", "content": prompts.ORATORY_TOPIC.format(mode=mode, role=user.target_role or "software engineer")},
            {"role": "user", "content": f"Draw a fresh, surprising topic. It must be clearly DIFFERENT from all of these recent ones: {avoid}"},
        ],
        fast=True,
    )
    return {"topic": result.get("topic", "Describe a lesson you learned the hard way."), "hint": result.get("hint", "")}


def _clean(word: str) -> str:
    return re.sub(r"[^\w']", "", word.lower())


@router.post("/analyze")
async def analyze(
    file: UploadFile = File(...),
    topic: str = Form(...),
    mode: str = Form("classic"),
    target_secs: int = Form(60),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    global _whisper
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise HTTPException(501, "Local STT not installed. Run: pip install faster-whisper")
    if _whisper is None:
        _whisper = WhisperModel("base", device="cpu", compute_type="int8")

    data = await file.read()
    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp:
        tmp.write(data)
        path = tmp.name

    # Verbatim mode: word timestamps on, prompt nudges Whisper to KEEP fillers it normally cleans out
    # suppress_tokens=[] disables Whisper's default token suppression — the main reason
    # fillers like "um"/"uh" silently vanish from transcripts.
    segments, _info = _whisper.transcribe(
        path,
        word_timestamps=True,
        initial_prompt="So um, uh, I think, you know, like, basically, um yeah...",
        suppress_tokens=[],
        vad_filter=False,
    )
    words = []
    for seg in segments:
        for w in seg.words or []:
            words.append({"w": w.word.strip(), "start": w.start, "end": w.end})
    transcript = " ".join(w["w"] for w in words)
    if not words:
        raise HTTPException(400, "No speech detected in the recording")

    # ---- Measured metrics (Ah-Counter + Timer roles) ----
    duration = words[-1]["end"] - words[0]["start"]
    n_words = len(words)
    wpm = round(n_words / max(duration, 1) * 60)

    filler_breakdown: dict = {}
    for w in words:
        c = _clean(w["w"])
        if c in CORE_FILLERS:
            filler_breakdown[c] = filler_breakdown.get(c, 0) + 1
    text_l = " ".join(_clean(w["w"]) for w in words)
    you_knows = len(re.findall(r"\byou know\b", text_l))
    if you_knows:
        filler_breakdown["you know"] = you_knows
    filler_count = sum(filler_breakdown.values())
    filler_rate = round(filler_count / max(duration / 60, 0.1), 1)

    counts: dict = {}
    for w in words:
        c = _clean(w["w"])
        if c in CRUTCH_CANDIDATES:
            counts[c] = counts.get(c, 0) + 1
    crutches = sorted(({"word": k, "count": v} for k, v in counts.items() if v >= 3), key=lambda x: -x["count"])[:5]

    pauses = []
    for i in range(len(words) - 1):
        gap = words[i + 1]["start"] - words[i]["end"]
        if gap > 0.6:
            rhetorical = bool(re.search(r"[.!?]$", words[i]["w"]))
            pauses.append({"after": words[i]["w"], "secs": round(gap, 1), "rhetorical": rhetorical})
    longest_pause = max((p["secs"] for p in pauses), default=0)
    stall_count = sum(1 for p in pauses if not p["rhetorical"])

    # Confidence hedges + weak/vague words
    hedge_breakdown = {h: len(re.findall(rf"\b{re.escape(h)}\b", text_l)) for h in HEDGES}
    hedge_breakdown = {k: v for k, v in hedge_breakdown.items() if v}
    weak_breakdown: dict = {}
    for w in words:
        c = _clean(w["w"])
        if c in WEAK_WORDS:
            weak_breakdown[c] = weak_breakdown.get(c, 0) + 1

    # Pace over time: WPM per 10-second bucket
    t0 = words[0]["start"]
    buckets: dict = {}
    for w in words:
        b = int((w["start"] - t0) // 10)
        buckets[b] = buckets.get(b, 0) + 1
    wpm_timeline = [{"t": b * 10, "wpm": count * 6} for b, count in sorted(buckets.items())]

    speech_time = sum(w["end"] - w["start"] for w in words)
    talk_ratio = round(min(1.0, speech_time / max(duration, 0.1)), 2)

    # Hedging language (undermines authority)
    hedges = {}
    for h in HEDGING:
        c = len(re.findall(r"\b" + re.escape(h) + r"\b", text_l))
        if c:
            hedges[h] = c

    # Pace timeline: WPM per 10-second bucket (for the sparkline)
    t0 = words[0]["start"]
    buckets: dict = {}
    for w in words:
        b = int((w["start"] - t0) // 10)
        buckets[b] = buckets.get(b, 0) + 1
    pace_timeline = [round(buckets.get(b, 0) * 6) for b in range(max(buckets.keys()) + 1)] if buckets else []

    # Longest clean streak: seconds spoken without a single filler
    filler_times = [w["start"] for w in words if _clean(w["w"]) in CORE_FILLERS]
    streak_points = [words[0]["start"]] + filler_times + [words[-1]["end"]]
    clean_streak = round(max((streak_points[i + 1] - streak_points[i]) for i in range(len(streak_points) - 1)), 1)

    metrics = {
        "hedging": sorted(({"phrase": k, "count": v} for k, v in hedges.items()), key=lambda x: -x["count"]),
        "pace_timeline": pace_timeline,
        "clean_streak_secs": clean_streak,
        "duration_secs": round(duration, 1),
        "target_secs": target_secs,
        "words": n_words,
        "wpm": wpm,
        "filler_count": filler_count,
        "filler_rate_per_min": filler_rate,
        "filler_breakdown": sorted(({"word": k, "count": v} for k, v in filler_breakdown.items()), key=lambda x: -x["count"]),
        "crutch_words": crutches,
        "pause_count": len(pauses),
        "stall_pauses": stall_count,
        "longest_pause_secs": longest_pause,
        "hedge_breakdown": sorted(({"word": k, "count": v} for k, v in hedge_breakdown.items()), key=lambda x: -x["count"]),
        "weak_words": sorted(({"word": k, "count": v} for k, v in weak_breakdown.items()), key=lambda x: -x["count"])[:6],
        "wpm_timeline": wpm_timeline,
        "talk_ratio": talk_ratio,
    }

    # ---- Evaluated scores (Grammarian + General Evaluator) ----
    try:
        scores = chat_json(
            [
                {"role": "system", "content": prompts.ORATORY_EVAL.format(topic=topic, transcript=transcript[:4000])},
                {"role": "user", "content": "Evaluate."},
            ],
            fast=True,
        )
    except Exception:
        scores = {}

    # XP: base + improvement bonus over your own last session
    last = db.query(SpeechSession).filter(SpeechSession.user_id == user.id).order_by(SpeechSession.id.desc()).first()
    xp_gained = 50
    improved = bool(last and filler_rate < (last.metrics or {}).get("filler_rate_per_min", 999))
    if improved:
        xp_gained += 25
    user.xp += xp_gained

    session = SpeechSession(user_id=user.id, topic=topic, mode=mode, target_secs=target_secs, transcript=transcript, metrics=metrics, scores=scores)
    db.add(session)
    db.add(VaultEntry(user_id=user.id, kind="speech", title=f"Speech: {topic[:60]}", content=transcript[:4000], extra={"metrics": metrics, "scores": scores}))
    db.commit()
    try:
        add_memory(user.id, f"Practiced impromptu speaking on '{topic}'. Filler rate {filler_rate}/min, WPM {wpm}. Tip: {scores.get('tip', '')}", kind="speech")
    except Exception:
        pass

    return {"transcript": transcript, "metrics": metrics, "scores": scores, "xp_gained": xp_gained, "improved": improved}


@router.get("/history")
def history(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    sessions = db.query(SpeechSession).filter(SpeechSession.user_id == user.id).order_by(SpeechSession.id.asc()).limit(50).all()
    return [
        {"id": s.id, "topic": s.topic[:60], "date": str(s.created_at)[:10], "filler_rate": (s.metrics or {}).get("filler_rate_per_min"), "wpm": (s.metrics or {}).get("wpm"), "duration": (s.metrics or {}).get("duration_secs")}
        for s in sessions
    ]
