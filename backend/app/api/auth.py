from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.security import create_access_token, get_current_user, hash_password, verify_password
from app.db.database import get_db
from app.db.models import User
from app.db.schemas import ProfileOut, RegisterIn, TokenOut

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=TokenOut)
def register(payload: RegisterIn, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(400, "Email already registered")
    user = User(
        email=payload.email,
        name=payload.name,
        hashed_password=hash_password(payload.password),
        last_active=date.today().isoformat(),
        streak=1,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return TokenOut(access_token=create_access_token(user.id))


@router.post("/login", response_model=TokenOut)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == form.username).first()
    if not user or not verify_password(form.password, user.hashed_password):
        raise HTTPException(401, "Invalid email or password")
    # Streak logic
    today = date.today()
    if user.last_active:
        delta = (today - date.fromisoformat(user.last_active)).days
        if delta == 1:
            user.streak += 1
        elif delta > 1:
            user.streak = 1
    user.last_active = today.isoformat()
    db.commit()
    return TokenOut(access_token=create_access_token(user.id))


@router.get("/me", response_model=ProfileOut)
def me(user: User = Depends(get_current_user)):
    return user


from app.db.schemas import ChangePasswordIn


@router.post("/change-password")
def change_password(payload: ChangePasswordIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not verify_password(payload.current_password, user.hashed_password):
        raise HTTPException(401, "Current password is incorrect")
    if len(payload.new_password) < 6:
        raise HTTPException(400, "New password must be at least 6 characters")
    user.hashed_password = hash_password(payload.new_password)
    db.commit()
    return {"ok": True}
