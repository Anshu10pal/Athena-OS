import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.agents.commander import route
from app.core.llm import chat_stream
from app.core.security import get_current_user
from app.db.database import get_db
from app.db.models import User, VaultEntry
from app.db.schemas import ChatIn
from app.services.vector_store import add_memory

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("/stream")
def stream_chat(payload: ChatIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    decision = route(user, payload.message)
    messages = (
        [{"role": "system", "content": decision["system"]}]
        + payload.history[-10:]
        + [{"role": "user", "content": payload.message}]
    )

    def event_stream():
        yield f"data: {json.dumps({'type': 'meta', 'intent': decision['intent']})}\n\n"
        full = []
        try:
            for delta in chat_stream(messages):
                full.append(delta)
                yield f"data: {json.dumps({'type': 'token', 'text': delta})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            return
        answer = "".join(full)
        # Persist the exchange to long-term memory + vault
        try:
            summary = f"User asked: {payload.message}\nAthena ({decision['intent']}): {answer[:800]}"
            add_memory(user.id, summary, kind=decision["intent"])
            db.add(VaultEntry(user_id=user.id, kind="chat", title=payload.message[:80], content=answer))
            db.commit()
        except Exception:
            pass
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
