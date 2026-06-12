from typing import Optional

from pydantic import BaseModel, EmailStr


class RegisterIn(BaseModel):
    name: str
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ProfileOut(BaseModel):
    id: int
    name: str
    email: str
    experience_level: str
    current_role: str
    target_role: str
    learning_goals: str
    skills: dict
    voice: str
    xp: int
    streak: int

    class Config:
        from_attributes = True


class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    experience_level: Optional[str] = None
    current_role: Optional[str] = None
    target_role: Optional[str] = None
    learning_goals: Optional[str] = None
    skills: Optional[dict] = None
    voice: Optional[str] = None


class ChatIn(BaseModel):
    message: str
    history: list[dict] = []
    speak: bool = False


class RoadmapIn(BaseModel):
    target_role: str
    current_skills: list[str] = []


class NodeStatusIn(BaseModel):
    node_id: str
    status: str  # available|in_progress|completed


class NoteIn(BaseModel):
    title: str
    content: str
    kind: str = "note"


class InterviewStartIn(BaseModel):
    role: str
    job_description: str = ""


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str


class AddNodeIn(BaseModel):
    title: str


class InterviewAnswerIn(BaseModel):
    session_id: int
    answer: str
    finish: bool = False
