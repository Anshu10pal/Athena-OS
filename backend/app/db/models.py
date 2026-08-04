from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
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

    # content_roadmaps rows are shared library content, not user-owned, so there's no
    # "this user's roadmaps" list under the new model. This is what the homepage
    # dashboard's roadmap card shows progress for -- set on every successful
    # /api/roadmaps/search call.
    last_roadmap_id: Mapped[int] = mapped_column(Integer, nullable=True, default=None)

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
    # nodes: [{id, title, description, skills, status: available|in_progress|completed|skipped, depends_on: [id]}]
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


# ---------------- Content library (modules are the atom, roadmaps compose references to them) ----------------


class Module(Base):
    __tablename__ = "modules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(20), default="skill")  # skill|tool
    summary: Mapped[str] = mapped_column(Text, default="")
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(String(20), default="generated")  # seed|generated
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    topics: Mapped[list["Topic"]] = relationship(back_populates="module", cascade="all, delete-orphan")


class Topic(Base):
    __tablename__ = "topics"
    __table_args__ = (UniqueConstraint("module_id", "slug", name="uq_topic_module_slug"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    module_id: Mapped[int] = mapped_column(ForeignKey("modules.id"), index=True)
    slug: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(255))
    blurb: Mapped[str] = mapped_column(Text, default="")
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    estimated_minutes: Mapped[int] = mapped_column(Integer, default=15)
    source: Mapped[str] = mapped_column(String(20), default="generated")  # seed|generated|manual
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    module: Mapped["Module"] = relationship(back_populates="topics")
    resources: Mapped[list["Resource"]] = relationship(back_populates="topic", cascade="all, delete-orphan")


class Resource(Base):
    __tablename__ = "resources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # video|article|doc|file
    status: Mapped[str] = mapped_column(String(20), default="intent")  # intent|saved
    title: Mapped[str] = mapped_column(String(255), default="")
    url: Mapped[str] = mapped_column(String(1000), nullable=True, default=None)
    search_query: Mapped[str] = mapped_column(String(255), nullable=True, default=None)
    source_hint: Mapped[str] = mapped_column(String(255), nullable=True, default=None)
    file_path: Mapped[str] = mapped_column(String(500), nullable=True, default=None)
    mime_type: Mapped[str] = mapped_column(String(120), nullable=True, default=None)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=True, default=None)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    topic: Mapped["Topic"] = relationship(back_populates="resources")


class ResourceHistory(Base):
    """Undo log for resource edits/deletes — not an audit trail."""

    __tablename__ = "resource_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    resource_id: Mapped[int] = mapped_column(Integer, index=True)
    # Denormalized from resource.topic_id at write time: undo is scoped by topic
    # ("POST /api/topics/{id}/undo"), and a delete's history row must stay
    # queryable that way even after the resource row it references is gone.
    topic_id: Mapped[int] = mapped_column(Integer, index=True)
    field: Mapped[str] = mapped_column(String(50))
    old_value: Mapped[str] = mapped_column(Text, nullable=True, default=None)
    new_value: Mapped[str] = mapped_column(Text, nullable=True, default=None)
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ContentRoadmap(Base):
    """An ordered composition of module references.

    Named ContentRoadmap (table content_roadmaps), not Roadmap, to avoid colliding
    with the existing per-user roadmaps table that still backs the older
    generate/dossier/assessment flow until that's cut over in a later phase.
    """

    __tablename__ = "content_roadmaps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    target: Mapped[str] = mapped_column(String(255), default="")
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    kind: Mapped[str] = mapped_column(String(20), default="generated")  # seed|generated
    category: Mapped[str] = mapped_column(String(20), default="role")  # role|tool -- browsing tiles on the roadmap page
    summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    stages: Mapped[list["RoadmapStage"]] = relationship(back_populates="roadmap", cascade="all, delete-orphan")


class RoadmapStage(Base):
    __tablename__ = "roadmap_stages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    roadmap_id: Mapped[int] = mapped_column(ForeignKey("content_roadmaps.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    order_index: Mapped[int] = mapped_column(Integer, default=0)

    roadmap: Mapped["ContentRoadmap"] = relationship(back_populates="stages")
    nodes: Mapped[list["RoadmapNode"]] = relationship(back_populates="stage", cascade="all, delete-orphan")


class RoadmapNode(Base):
    __tablename__ = "roadmap_nodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stage_id: Mapped[int] = mapped_column(ForeignKey("roadmap_stages.id"), index=True)
    module_id: Mapped[int] = mapped_column(ForeignKey("modules.id"), nullable=True, default=None, index=True)
    title: Mapped[str] = mapped_column(String(255))
    blurb: Mapped[str] = mapped_column(Text, default="")
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    resolution: Mapped[str] = mapped_column(String(20), default="unmatched")  # matched|unmatched
    match_score: Mapped[float] = mapped_column(Float, nullable=True, default=None)
    topics_generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=True, default=None)
    # For seed roadmaps: the module slug the YAML author declared, kept even when it
    # doesn't resolve yet (module not seeded so far) so export can round-trip the
    # author's intent instead of silently dropping it. Not used for generated roadmaps.
    module_slug: Mapped[str] = mapped_column(String(120), nullable=True, default=None)

    stage: Mapped["RoadmapStage"] = relationship(back_populates="nodes")
    module: Mapped["Module"] = relationship()


class TopicProgress(Base):
    __tablename__ = "topic_progress"
    __table_args__ = (UniqueConstraint("user_id", "topic_id", name="uq_topic_progress_user_topic"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id"), index=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ModuleAssessment(Base):
    """Quiz gating module XP — mirrors Assessment, scoped to a module instead of a roadmap node.

    Separate from TopicProgress: the checkbox tracks study, this tracks tested mastery + reward.
    """

    __tablename__ = "module_assessments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    module_id: Mapped[int] = mapped_column(ForeignKey("modules.id"), index=True)
    questions: Mapped[list] = mapped_column(JSON, default=list)  # [{q, options, answer, topic}]
    status: Mapped[str] = mapped_column(String(20), default="active")  # active|graded
    score: Mapped[int] = mapped_column(Integer, default=0)  # percent
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
