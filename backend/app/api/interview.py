from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.agents import prompts
from app.core.llm import chat, chat_json
from app.core.security import get_current_user
from app.db.database import get_db
from app.db.models import InterviewSession, User, VaultEntry
from app.db.schemas import InterviewAnswerIn, InterviewStartIn
from app.services.vector_store import add_memory

router = APIRouter(prefix="/api/interview", tags=["interview"])

MCQ_COUNT = 10
DESCRIPTIVE_COUNT = 4
HARD_CAP = 10  # absolute max descriptive questions


def _system(session: InterviewSession) -> str:
    base = prompts.INTERVIEWER.format(role=session.role)
    if session.jd:
        base += f"\n\nThe interview is for this specific job. Tailor every question to it:\n{session.jd[:2500]}"
    return base


def _messages(session: InterviewSession) -> list[dict]:
    msgs = [{"role": "system", "content": _system(session)}]
    for turn in session.transcript:
        msgs.append({"role": "assistant", "content": turn["q"]})
        if turn.get("a"):
            msgs.append({"role": "user", "content": turn["a"]})
    return msgs


@router.post("/start")
def start(payload: InterviewStartIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Stage 1: rapid MCQ screen."""
    jd_note = f"\nTailor questions to this job description:\n{payload.job_description[:2000]}" if payload.job_description else ""
    questions: list[dict] = []
    while len(questions) < MCQ_COUNT:
        batch = min(5, MCQ_COUNT - len(questions))
        result = chat_json(
            [
                {"role": "system", "content": prompts.INTERVIEW_MCQ.format(n=batch, role=payload.role) + jd_note},
                {"role": "user", "content": f"Generate {batch} questions. Avoid: " + "; ".join(q["q"][:50] for q in questions)},
            ],
            fast=True,
        )
        for q in result.get("questions", []):
            if isinstance(q.get("options"), list) and len(q["options"]) == 4:
                questions.append(q)
        if not result.get("questions"):
            break
    if len(questions) < 5:
        raise HTTPException(500, "Could not generate screening questions — try again")
    session = InterviewSession(user_id=user.id, role=payload.role, jd=payload.job_description or "", transcript=[], mcq=questions, mcq_score=-1)
    db.add(session)
    db.commit()
    db.refresh(session)
    return {
        "session_id": session.id,
        "stage": "mcq",
        "questions": [{"q": q["q"], "options": q["options"]} for q in questions],
        "seconds_per_question": 30,
    }


@router.post("/mcq")
def submit_mcq(payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Grade stage 1, open stage 2 with the first descriptive question."""
    session = db.get(InterviewSession, payload.get("session_id"))
    if not session or session.user_id != user.id or session.status != "active":
        raise HTTPException(404, "Active session not found")
    answers = payload.get("answers", [])
    mcq = session.mcq or []
    for i, q in enumerate(mcq):
        q["given"] = answers[i] if i < len(answers) else -1
    flag_modified(session, "mcq")
    correct = sum(1 for q in mcq if q.get("given") == q.get("answer"))
    session.mcq_score = round(100 * correct / max(1, len(mcq)))

    question = chat(_messages(session) + [{"role": "user", "content": "MCQ screen done. Begin the descriptive round with your first question."}], fast=True)
    session.transcript = [{"q": question, "a": ""}]
    flag_modified(session, "transcript")
    db.commit()
    return {
        "session_id": session.id,
        "stage": "descriptive",
        "mcq_score": session.mcq_score,
        "question": question,
        "question_number": 1,
        "total": DESCRIPTIVE_COUNT,
    }


@router.post("/answer")
def answer(payload: InterviewAnswerIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    session = db.get(InterviewSession, payload.session_id)
    if not session or session.user_id != user.id or session.status != "active":
        raise HTTPException(404, "Active session not found")
    session.transcript[-1]["a"] = payload.answer
    flag_modified(session, "transcript")

    if payload.finish or len(session.transcript) >= HARD_CAP:
        return _finish(session, user, db)

    question = chat(_messages(session), fast=True)
    session.transcript.append({"q": question, "a": ""})
    flag_modified(session, "transcript")
    db.commit()
    return {
        "session_id": session.id,
        "stage": "descriptive",
        "question": question,
        "question_number": len(session.transcript),
        "total": DESCRIPTIVE_COUNT,
        "hard_cap": HARD_CAP,
        "finished": False,
    }


def _finish(session: InterviewSession, user: User, db: Session):
    transcript_text = "\n\n".join(f"Q: {t['q']}\nA: {t['a']}" for t in session.transcript)
    scores = chat_json(
        [
            {"role": "system", "content": prompts.INTERVIEW_SCORER.format(role=session.role)},
            {"role": "user", "content": transcript_text},
        ],
        fast=False,
    )
    # Blend measured MCQ accuracy into technical score
    mcq10 = round((session.mcq_score or 0) / 10)
    llm_tech = scores.get("technical_accuracy", 5)
    scores["technical_accuracy"] = round((llm_tech + mcq10) / 2)
    scores["mcq_score"] = session.mcq_score
    session.scores = scores
    session.status = "finished"
    flag_modified(session, "scores")
    user.xp += 200
    db.add(VaultEntry(user_id=user.id, kind="interview", title=f"{session.role} interview", content=transcript_text, extra=scores))
    db.commit()
    try:
        add_memory(user.id, f"Completed a {session.role} interview (MCQ {session.mcq_score}%). Feedback: {scores.get('feedback', '')}", kind="interview")
    except Exception:
        pass
    mcq_review = [
        {"q": q["q"], "options": q["options"], "given": q.get("given", -1), "correct": q.get("answer"), "ok": q.get("given") == q.get("answer")}
        for q in (session.mcq or [])
    ]
    return {
        "session_id": session.id,
        "finished": True,
        "scores": scores,
        "xp_gained": 200,
        "mcq_review": mcq_review,
        "transcript": session.transcript,
    }
