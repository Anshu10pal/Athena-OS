from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.database import get_db
from app.db.models import User
from app.services.seed import export_content

router = APIRouter(prefix="/api/content", tags=["content"])


@router.post("/export")
def export(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return export_content(db)
