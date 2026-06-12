from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.database import get_db
from app.db.models import User, VaultEntry
from app.db.schemas import NoteIn
from app.services.vector_store import add_memory, search_memory

router = APIRouter(prefix="/api/vault", tags=["vault"])


@router.post("/notes")
def save_note(payload: NoteIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    entry = VaultEntry(user_id=user.id, kind=payload.kind, title=payload.title, content=payload.content)
    db.add(entry)
    db.commit()
    add_memory(user.id, f"{payload.title}: {payload.content}", kind=payload.kind, title=payload.title)
    return {"id": entry.id}


@router.get("/entries")
def list_entries(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    entries = (
        db.query(VaultEntry).filter(VaultEntry.user_id == user.id).order_by(VaultEntry.id.desc()).limit(100).all()
    )
    return [
        {"id": e.id, "kind": e.kind, "title": e.title, "content": e.content[:500], "created_at": str(e.created_at)}
        for e in entries
    ]


@router.get("/search")
def semantic_search(q: str, user: User = Depends(get_current_user)):
    return search_memory(user.id, q, limit=8)
