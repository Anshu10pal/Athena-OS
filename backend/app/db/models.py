from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    hashed_password: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    # Profile (kept flat for MVP)
    experience_level: Mapped[str] = mapped_column(String(50), default="beginner")
    current_role: Mapped[str] = mapped_column(String(120), default="")
    target_role: Mapped[str] = mapped_column(String(120), default="")
    learning_goals: Mapped[str] = mapped_column(Text, default="")
    skills: Mapped[dict] = mapped_column(JSON, default=dict)  # {"Python": 3, "RAG": 2} levels 0-5

    voice: Mapped[str] = mapped_column(String(60), default="en-US-AriaNeural")

    # Gamification
    xp: Mapped[int] = mapped_column(Integer, default=0)
    streak: Mapped[int] = mapped_column(Integer, default=0)
    last_active: Mapped[str] = mapped_column(String(10), default="")  # YYYY-MM-DD

    roadmaps: Mapped[list["Roadmap"]] = relationship(back_populates="user")
    missions: Mapped[list["Mission"]] = relationship(back_populates="user")


class Roadmap(Base):
    __tablename__ = "roadmaps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    target_role: Mapped[str] = mapped_column(String(120))
    parent_roadmap_id: Mapped[int] = mapped_column(Integer, nullable=True, default=None)
    parent_node_id: Mapped[str] = mapped_column(String(40), nullable=True, default=None)
    parent_roadmap_id: Mapped[int] = mapped_column(Integer, nullable=True, default=None, index=True)
    parent_node_id: Mapped[str] = mapped_column(String(40), nullable=True, default=None)
    depth: Mapped[int] = mapped_column(Integer, default=0)
    # nodes: [{id, title, description, skills, status: locked|available|in_progress|completed|skipped, depends_on: [id]}]
    nodes: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    user: Mapped["User"] = relationship(back_populates="roadmaps")


class Mission(Base):
    __tablename__ = "missions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    objective: Mapped[str] = mapped_column(Text)
    difficulty: Mapped[str] = mapped_column(String(20), default="easy")
    xp_reward: Mapped[int] = mapped_column(Integer, default=50)
    skills_gained: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active|completed
    date: Mapped[str] = mapped_column(String(10), default="")  # YYYY-MM-DD

    user: Mapped["User"] = relationship(back_populates="missions")


class VaultEntry(Base):
    __tablename__ = "vault_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    kind: Mapped[str] = mapped_column(String(30))  # note|chat|interview|presentation|research
    title: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)
    extra: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class InterviewSession(Base):
    __tablename__ = "interview_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    role: Mapped[str] = mapped_column(String(120))
    jd: Mapped[str] = mapped_column(Text, default="")
    # transcript: [{"q": "...", "a": "..."}]
    transcript: Mapped[list] = mapped_column(JSON, default=list)
    mcq: Mapped[list] = mapped_column(JSON, default=list)
    mcq_score: Mapped[int] = mapped_column(Integer, default=-1)
    scores: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active|finished
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class NodeContent(Base):
    __tablename__ = "node_content"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    roadmap_id: Mapped[int] = mapped_column(Integer, index=True)
    node_id: Mapped[str] = mapped_column(String(40), index=True)
    briefing: Mapped[str] = mapped_column(Text, default="")
    meaning: Mapped[str] = mapped_column(Text, default="")
    eli5: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Assessment(Base):
    __tablename__ = "assessments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    roadmap_id: Mapped[int] = mapped_column(Integer)
    node_id: Mapped[str] = mapped_column(String(40))
    questions: Mapped[list] = mapped_column(JSON, default=list)  # [{q, options, answer, topic}]
    status: Mapped[str] = mapped_column(String(20), default="active")  # active|graded
    score: Mapped[int] = mapped_column(Integer, default=0)  # percent
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ResourceCache(Base):
    __tablename__ = "resource_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SpeechSession(Base):
    __tablename__ = "speech_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    topic: Mapped[str] = mapped_column(Text)
    mode: Mapped[str] = mapped_column(String(20), default="classic")
    target_secs: Mapped[int] = mapped_column(Integer, default=60)
    transcript: Mapped[str] = mapped_column(Text, default="")
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    scores: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Achievement(Base):
    __tablename__ = "achievements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    code: Mapped[str] = mapped_column(String(50), index=True)
    unlocked_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ReviewItem(Base):
    __tablename__ = "review_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    roadmap_id: Mapped[int] = mapped_column(Integer)
    node_id: Mapped[str] = mapped_column(String(40))
    node_title: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(20), default="node")  # node|vocab|concept
    detail: Mapped[str] = mapped_column(Text, default="")           # definition/context for vocab & concept cards
    interval_idx: Mapped[int] = mapped_column(Integer, default=0)
    due_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    last_reviewed: Mapped[datetime] = mapped_column(DateTime, nullable=True, default=None)
    last_score: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class CommunicationSession(Base):
    __tablename__ = "communication_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    modality: Mapped[str] = mapped_column(String(20), index=True)  # writing|listening|reading|speaking
    difficulty: Mapped[str] = mapped_column(String(20), default="Intermediate")
    prompt: Mapped[str] = mapped_column(Text, default="")
    response: Mapped[str] = mapped_column(Text, default="")
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    scores: Mapped[dict] = mapped_column(JSON, default=dict)
    overall: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
