from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
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


# ---------------- Codebase agent: repo registration and acquisition (Phase A) ----------------


class Repo(Base):
    """A registered repository -- either cloned into the local cache or an existing
    local checkout used in place. Never modified for `local` repos; `clone` repos
    are the codebase agent's own LRU-evicted cache, not a durable ledger."""

    __tablename__ = "repos"
    __table_args__ = (UniqueConstraint("host", "owner", "name", name="uq_repo_host_owner_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    host: Mapped[str] = mapped_column(String(255))
    owner: Mapped[str] = mapped_column(String(255), default="")
    name: Mapped[str] = mapped_column(String(255))
    url: Mapped[str] = mapped_column(String(1000), nullable=True, default=None)
    local_path: Mapped[str] = mapped_column(String(1000))
    source_kind: Mapped[str] = mapped_column(String(20))  # clone|local
    default_branch: Mapped[str] = mapped_column(String(255), default="")
    visibility: Mapped[str] = mapped_column(String(20), default="unknown")  # public|private|unknown
    source_root: Mapped[str] = mapped_column(String(500), nullable=True, default=None)
    allow_external_llm: Mapped[bool] = mapped_column(Boolean, default=False)
    last_ingested_sha: Mapped[str] = mapped_column(String(64), nullable=True, default=None)
    last_ingested_at: Mapped[datetime] = mapped_column(DateTime, nullable=True, default=None)
    file_count: Mapped[int] = mapped_column(Integer, nullable=True, default=None)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    # Phase E4 refinement: per-repo override for entry_detection's seed
    # tier -- prefix-matched (unlike config/entry_detection.yaml's
    # seed_ineligible_path_markers, which is substring-matched and
    # ecosystem-wide). Every repo has SOME auxiliary surface no generic
    # marker catches (a worker, a cron script, a dev harness); this is a
    # permanent category of exception, not a repo-1 quirk, so it lives on
    # the repo row rather than being folded into the global config.
    seed_exclude_paths: Mapped[list] = mapped_column(JSON, default=list)
    # Phase E2.3 incident tripwire (ranking.py's resolution-rate collapse
    # check): the HIGHEST Python resolution rate ever recorded for this repo
    # across rank runs that completed without tripping -- a true high-water
    # mark, not the last-observed value. Phase F7 correction: storing
    # "last observed" let a second consecutive bad run re-baseline against
    # an already-collapsed rate and pass silently (each individual step's
    # relative drop looks fine measured against its own already-degraded
    # predecessor, even though the cumulative drop from the real peak is
    # severe) -- comparing against the all-time high closes that gap. Null
    # until the first rank run for this repo. Updated by ranking.py, not
    # ingest.py -- the collapse this exists to catch was observed by a RANK
    # read, so that's where the comparison (and the refusal) belongs.
    python_resolution_high_water_mark: Mapped[float] = mapped_column(Float, nullable=True, default=None)
    # Phase F7 incident (2nd hypothesis): ingest.py's stage 2 Python root
    # promotion returning EMPTY (evidence pool empty, thresholds not
    # cleared, whatever the cause) silently collapses resolution to the
    # bare ["", "src"] fallback for every unresolved absolute import, with
    # no exception raised -- deterministic, but invisible under a rank-time
    # check alone since ranking never sees "promotion" as a concept. Null
    # until Python root promotion has run at least once for this repo
    # (distinct from "[]", which means promotion ran and legitimately
    # promoted nothing, e.g. every absolute import already resolved in
    # stage 1). Updated by ingest.py, not ranking.py -- this failure mode
    # is an ingest-time fact, unlike python_resolution_high_water_mark above.
    last_promoted_python_roots: Mapped[list] = mapped_column(JSON, nullable=True, default=None)
    # Phase G1: whether the LAST rank run that computed git history at all
    # (legacy_signal_snapshot -- weighted_pagerank never touches this) found
    # history unavailable. Repo-wide, not file-level or scorer-level: one
    # `git log` call per rank run determines this for every file
    # simultaneously, regardless of which scorer triggered the run. Used to
    # live on CodeFileRank, duplicated once per file per scorer (hundreds of
    # copies of the same single boolean, no mechanism forcing them to
    # agree). Nullable: None means no history-computing rank run has ever
    # completed for this repo.
    reduced_confidence: Mapped[bool] = mapped_column(Boolean, nullable=True, default=None)
    # Phase K1: a short human description of what this repo IS, extracted
    # at ingest time from the repo's own metadata (package.json
    # "description", pyproject/setup.cfg, or the README's first real
    # paragraph -- see repo_description.py), never written by hand and
    # never generated by an LLM. Stored rather than derived on read for the
    # same reason seed_eligible is: deriving it would mean a read endpoint
    # opening files on disk on every request, which is exactly the H1.5
    # mistake. Null means extraction found nothing quotable, which is a
    # real outcome for a repo with no README and no packaging metadata --
    # the UI says "no description found" rather than inventing one.
    description: Mapped[str] = mapped_column(Text, nullable=True, default=None)
    description_source: Mapped[str] = mapped_column(String(30), nullable=True, default=None)
    # Phase I1: repo-wide agreement between the two subsystem-clustering
    # algorithms (modularity vs. Louvain), computed over files in
    # multi-member clusters only -- see subsystems.py's compute_subsystems
    # for why singletons are excluded from the denominator. Repo-wide, not
    # per-file or per-cluster: it's one number describing whether the two
    # independent clusterings agree on this repo's structure at all, the
    # same "one scalar describing the whole run" shape as reduced_confidence
    # above. Null until subsystem clustering has run at least once.
    subsystem_algorithm_agreement: Mapped[float] = mapped_column(Float, nullable=True, default=None)
    # Phase I1: the last compute_subsystems run's cycle-cluster-coherence
    # findings (subsystems.cycle_cluster_coherence's return shape, JSON
    # list), persisted rather than recomputed on every GET. Doing this live
    # on a read endpoint is exactly the H1.5 mistake (entry_detection
    # re-scanning the filesystem on every /graph request) applied to a new
    # computation -- cycle_cluster_coherence rebuilds a directory-level
    # import graph from CodeImport rows, which is cheap at this repo's
    # scale but is still real work a read endpoint has no business redoing
    # on every request when POST /subsystems already computed it once.
    subsystem_cycle_coherence: Mapped[list] = mapped_column(JSON, nullable=True, default=None)
    # Phase I6: HDBSCAN (over FastEmbed embeddings of symbol signatures +
    # docstrings -- see embeddings.py/subsystems.py) is a THIRD, separately
    # triggered clustering algorithm, not a peer of the modularity/Louvain
    # pair above -- it answers a different question (what a file's code
    # SAYS it does, not who imports it) and is compared AGAINST modularity
    # rather than against Louvain. Kept as its own scalar/JSON pair rather
    # than reusing subsystem_algorithm_agreement/subsystem_cycle_coherence
    # above, since those two specifically mean "modularity vs Louvain" in
    # every place that already reads them (GET /subsystems for those two
    # algorithms) -- overloading their meaning per-algorithm would silently
    # break that existing contract. Null until POST /subsystems/hdbscan has
    # run at least once, or if no modularity clustering exists yet to
    # compare against (agreement has no defined value with nothing to
    # compare to).
    subsystem_hdbscan_agreement: Mapped[float] = mapped_column(Float, nullable=True, default=None)
    subsystem_hdbscan_cycle_coherence: Mapped[list] = mapped_column(JSON, nullable=True, default=None)


# ---------------- Codebase agent: parse + import graph (Phase B) ----------------


class CodeFile(Base):
    """One row per source file at last successful parse. `content_sha256` is the
    re-ingest cache key -- unchanged hash means the file is not re-parsed."""

    __tablename__ = "code_files"
    __table_args__ = (UniqueConstraint("repo_id", "path", name="uq_code_file_repo_path"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repos.id"), index=True)
    path: Mapped[str] = mapped_column(String(1000))  # relative to repo local_path, POSIX separators
    language: Mapped[str] = mapped_column(String(20))  # python|typescript|tsx|javascript
    content_sha256: Mapped[str] = mapped_column(String(64), index=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    line_count: Mapped[int] = mapped_column(Integer, default=0)
    last_parsed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    # Phase F2: a multiplicative scoring prior -- category is a fact about
    # the code (numeric prior values are tunable, resolved from
    # config/node_priors.yaml at scoring time, not stored here -- same
    # kind/weight split as CodeImport.kind). One of node_priors.ALL_CATEGORIES.
    prior_category: Mapped[str] = mapped_column(String(20), default="source")
    # How prior_category was determined:
    #   "pattern"    -- filename/path pattern (config, migration, generated)
    #   "structural" -- file-local structural fact (barrel; later, E4's
    #                   positive entry signals once that lands)
    #   "graph"      -- depends on current fan_in, recomputed at every rank
    #                   run (see ranking.py) since it can go stale without
    #                   this file itself changing. Only rows marked "graph"
    #                   are ever touched by that write-back -- this is the
    #                   guard against ranking clobbering E4's classification
    #                   once entry detection becomes structural.
    prior_source: Mapped[str] = mapped_column(String(20), default="graph")
    # Phase G1: ranking signals that are properties of the FILE, not of
    # whichever scorer last computed them -- fan_in/fan_out come from the
    # same resolved import graph regardless of scorer, is_entry_point from
    # the same entry_detection call, and commit_count/distinct_authors/
    # days_since_last_change from one repo-wide `git log` call independent
    # of which scorer triggered it. All five used to live on CodeFileRank,
    # duplicated once per (file, scorer) with no mechanism forcing
    # agreement -- exactly what let one scorer's row show real commit
    # history and another's show null for the same file. Written by
    # whichever rank_repo*/rank_repo_rrf/rank_repo_weighted_pagerank run
    # last computed them; every scorer that computes a given signal
    # computes the identical value, so it doesn't matter which one wins the
    # write in a given run -- only weighted_pagerank ever writes fan_in/
    # fan_out/is_entry_point without also writing the three history fields,
    # since its formula has no history term at all (see ranking.py).
    # Nullable throughout: None means no rank run has computed this yet,
    # not "confirmed zero/false".
    #
    # is_entry_point sits here rather than being derived from prior_category
    # above, deliberately: prior_category is a one-time classification that
    # freezes after a file's first migration (_migrate_entry_priors only
    # ever touches prior_source == "graph" rows -- see that function), while
    # is_entry_point here is recomputed fresh from entry_detection on every
    # single rank run, exactly matching what actually fed that run's score.
    # Deriving one from the other would silently report the stale value.
    fan_in: Mapped[int] = mapped_column(Integer, nullable=True, default=None)
    fan_out: Mapped[int] = mapped_column(Integer, nullable=True, default=None)
    is_entry_point: Mapped[bool] = mapped_column(Boolean, nullable=True, default=None)
    # Phase H1.5: True for a seed-eligible entry, False for a prior-only
    # entry (earns the entry prior via _migrate_entry_priors but shouldn't
    # seed PageRank -- see entry_detection._is_seed_eligible), None for a
    # non-entry file or one no rank run has touched yet -- same nullable
    # convention as the rest of this block, same "recomputed fresh on every
    # rank run" treatment as is_entry_point just above, for the same reason
    # (it comes from the exact same entry_detection call). Added because
    # GET /repos/{id}/graph's directory-level view (Phase H1) needed the
    # seed-eligible/prior-only split for its entry-vs-tooling distinction,
    # and was calling entry_detection live, on every read, to get it --
    # the same duplicated-computation shape Phase G1 already fixed once
    # for fan_in/fan_out/commit history (see the block comment above this
    # one), except this instance was also measurably slow: entry detection
    # walks the repo's filesystem, so a read endpoint was re-scanning disk
    # on every request instead of reading what ranking already persisted.
    seed_eligible: Mapped[bool] = mapped_column(Boolean, nullable=True, default=None)
    commit_count: Mapped[int] = mapped_column(Integer, nullable=True, default=None)
    distinct_authors: Mapped[int] = mapped_column(Integer, nullable=True, default=None)
    days_since_last_change: Mapped[int] = mapped_column(Integer, nullable=True, default=None)
    # Phase I1 (extended I6): which subsystem this file belongs to, one
    # column per algorithm rather than a generic scorer-style table --
    # there are exactly three fixed algorithms (modularity and Louvain,
    # both community-detected over the import graph; hdbscan, density-
    # clustered over FastEmbed embeddings of symbol text -- see
    # subsystems.py), not an open set that could grow, so the
    # CodeFileRank-style per-scorer join would be unjustified indirection
    # here. Null means either no clustering run has completed yet, or this
    # file landed in a singleton (unclustered) "cluster" that was never
    # persisted as a CodeSubsystem row -- see subsystems.py.
    subsystem_modularity_id: Mapped[int] = mapped_column(ForeignKey("code_subsystems.id"), nullable=True, default=None, index=True)
    subsystem_louvain_id: Mapped[int] = mapped_column(ForeignKey("code_subsystems.id"), nullable=True, default=None, index=True)
    # Phase I6: third algorithm, HDBSCAN over FastEmbed embeddings -- see
    # Repo.subsystem_hdbscan_agreement above for why it's not folded into
    # the two columns above despite the identical NULL-means-unclustered
    # convention.
    subsystem_hdbscan_id: Mapped[int] = mapped_column(ForeignKey("code_subsystems.id"), nullable=True, default=None, index=True)
    # Phase 1 code health: FILE-level strongly-connected component in the
    # resolved import graph. Distinct from the directory-level SCCs
    # subsystems.py computes -- those answer "which directories cycle", this
    # answers "is this specific file inside an import cycle, and how big".
    # scc_size == 1 means a trivial component, i.e. NOT in a cycle; the
    # `cycle_participation` marker reads size, not membership, for that
    # reason. Both null until a graph-structure pass has run.
    scc_id: Mapped[int] = mapped_column(Integer, nullable=True, default=None, index=True)
    scc_size: Mapped[int] = mapped_column(Integer, nullable=True, default=None)
    # Phase 1 code health: reachability from the seed-eligible entry set,
    # persisted rather than recomputed live in get_graph (the H1.5 rule).
    # EVIDENCE ONLY -- this feeds the neutral "possibly unreachable by static
    # imports" advisory and must never become a scored deduction without a
    # separate validation study. Our own ESLint run already showed it firing
    # wrongly on dynamically-imported plugin files. Null means no analysis
    # pass has run; False does NOT mean "dead code".
    reachable_from_entry: Mapped[bool] = mapped_column(Boolean, nullable=True, default=None)


class CodeSymbol(Base):
    __tablename__ = "code_symbols"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("code_files.id"), index=True)
    parent_symbol_id: Mapped[int] = mapped_column(ForeignKey("code_symbols.id"), nullable=True, default=None, index=True)
    name: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(20))  # function|class|method
    signature: Mapped[str] = mapped_column(Text, default="")
    docstring: Mapped[str] = mapped_column(Text, nullable=True, default=None)
    line_start: Mapped[int] = mapped_column(Integer)
    line_end: Mapped[int] = mapped_column(Integer)


class CodeImport(Base):
    """Unified file-level and symbol-level import edges. A file-only import (e.g.
    `import os`, `import * as ns from "lib"`) has `imported_names == []` and
    `to_symbol_id == None` even when resolved; a name-level import additionally
    resolves `to_symbol_id` when the target symbol can be found statically."""

    __tablename__ = "code_imports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repos.id"), index=True)
    from_file_id: Mapped[int] = mapped_column(ForeignKey("code_files.id"), index=True)
    raw_specifier: Mapped[str] = mapped_column(String(1000))
    imported_names: Mapped[list] = mapped_column(JSON, default=list)
    to_file_id: Mapped[int] = mapped_column(ForeignKey("code_files.id"), nullable=True, default=None, index=True)
    to_symbol_id: Mapped[int] = mapped_column(ForeignKey("code_symbols.id"), nullable=True, default=None)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    line_number: Mapped[int] = mapped_column(Integer, default=0)
    # Phase F1: a categorical fact about the code (occurrence-count proxy for
    # coupling strength -- see app/services/codebase/edge_weights.py),
    # computed once at parse time. Deliberately NOT a stored weight float --
    # the numeric weight per kind is a tunable parameter resolved from
    # config/edge_weights.yaml at scoring time, so retuning it never requires
    # re-parsing. One of edge_weights.ALL_KINDS.
    kind: Mapped[str] = mapped_column(String(30), default="light_use")
    # Phase E2.3: set only when resolved is True and something about HOW it
    # resolved is worth a second look -- null otherwise, never a separate
    # boolean, so the reason is always machine-readable without knowing
    # which language produced the edge. "root_fallback" (Python): the
    # winning root wasn't the importing file's own nearest promoted root --
    # a real fallback occurred, not the expected case. "workspace_boundary"
    # (TS/JS): the resolved target sits in a different declared
    # package.json workspace than the importer -- a direct cross-package
    # import bypassing whatever public entry point that package meant to
    # expose.
    cross_root_kind: Mapped[str] = mapped_column(String(30), nullable=True, default=None)


# ---------------- Codebase agent: ranking (Phase C) ----------------


class CodeFileRank(Base):
    """One row per (CodeFile, scorer), replaced wholesale for that scorer on
    every rank run for it -- ranking is decoupled from ingest so re-ranking
    with tuned weights never requires re-parsing.

    Phase G1: holds ONLY values that genuinely differ by scorer -- score,
    rank, and pagerank. Every field that's a property of the FILE rather
    than of whichever scorer computed it (fan_in, fan_out, is_entry_point,
    commit_count, distinct_authors, days_since_last_change) moved to
    CodeFile; reduced_confidence (repo-wide, not even file-level) moved to
    Repo. Storing them here, once per (file, scorer), was duplicated
    storage with no mechanism forcing the copies to agree -- diagnosed live
    on /repos/:id, which read this table without filtering by scorer and
    showed the same file's commit count as a real number under one scorer
    and null under another."""

    __tablename__ = "code_file_ranks"
    __table_args__ = (UniqueConstraint("file_id", "scorer", name="uq_code_file_rank_file_scorer"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repos.id"), index=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("code_files.id"), index=True)
    # Phase F3: which scorer produced this row -- "legacy" (the original
    # weighted-sum composite) or "weighted_pagerank" (Phase F3's seeded,
    # edge-weighted PageRank). Both can coexist per file; neither scorer's
    # rank_repo* function ever deletes the other's rows.
    scorer: Mapped[str] = mapped_column(String(30), default="legacy")
    score: Mapped[float] = mapped_column(Float, default=0.0)
    # Phase G1: 1-indexed position among ALL of this repo's files under
    # this scorer, assigned once at write time from the same sort order the
    # rank run itself produced -- never recomputed from a filtered or
    # re-sorted view. A file's rank is its position in the whole repo, not
    # among whatever subset happens to be currently displayed.
    rank: Mapped[int] = mapped_column(Integer, default=0)
    pagerank: Mapped[float] = mapped_column(Float, default=0.0)
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ---------------- Codebase agent: subsystem clustering (Phase I1) ----------------


class CodeSubsystem(Base):
    """One row per (repo, algorithm, cluster) from the last successful
    clustering run -- replaced wholesale per algorithm on every run, same
    "decoupled from ingest" shape as CodeFileRank, except clustering
    depends on the resolved import graph rather than the ranking scorers.
    Singleton clusters (a single file with no edges dense/weighted enough
    to join anything) are deliberately NOT given a row here -- they're
    reported in the UI as one aggregated "Unclustered" bucket, not as
    hundreds of one-file cards. A file in a singleton has NULL
    subsystem_modularity_id/subsystem_louvain_id on CodeFile, which is how
    "unclustered" is detected without a sentinel row."""

    __tablename__ = "code_subsystems"
    __table_args__ = (UniqueConstraint("repo_id", "algorithm", "cluster_index", name="uq_code_subsystem_repo_algo_index"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repos.id"), index=True)
    # "modularity" (networkx greedy_modularity_communities) or "louvain"
    # (networkx louvain_communities, seed=42) -- kept as two independent,
    # simultaneously-persisted clusterings per repo, not a single "current"
    # algorithm, so the agreement number on Repo can be recomputed/audited
    # and a future repo where they genuinely disagree has both available
    # without a re-run.
    algorithm: Mapped[str] = mapped_column(String(20))
    # Stable ordinal within one computation run, assigned by sorting
    # clusters (size descending, then minimum file id) before assigning
    # indices -- same "sort outputs, not just inputs" discipline as I0's
    # determinism check, since networkx's own community-list order is an
    # implementation detail, not a documented guarantee.
    cluster_index: Mapped[int] = mapped_column(Integer)
    member_count: Mapped[int] = mapped_column(Integer, default=0)
    # Label option 1: the most common immediate directory (dir_aggregation's
    # dirname_of) among members, plus how many members share it -- e.g.
    # "backend/app/api" with dominant_prefix_count=20 out of member_count=42.
    dominant_prefix_label: Mapped[str] = mapped_column(String(500), default="")
    dominant_prefix_count: Mapped[int] = mapped_column(Integer, default=0)
    # Label option 2: the basename (no extension) of whichever member has
    # the highest CodeFile.fan_in -- a plausible "centerpiece" name when a
    # cluster has a clear center, misleading when it doesn't (I0 confirmed
    # both cases occur on the same repo).
    top_fan_in_label: Mapped[str] = mapped_column(String(255), default="")
    top_fan_in_file_id: Mapped[int] = mapped_column(ForeignKey("code_files.id"), nullable=True, default=None)
    # Label option 3 (numeric) has no stored field -- it's just
    # f"Subsystem {cluster_index}", derivable, not worth persisting.
    # User override. Survives a re-cluster IF the new cluster overlaps the
    # old custom-labeled cluster by >=50% of the OLD cluster's members
    # (compute_subsystems' carry-over match) -- below that threshold the
    # label resets to the default dominant_prefix rule, since the "same"
    # subsystem can no longer be said to exist. Every reset is reported,
    # never silent -- same discipline as G1's category_flips.
    custom_label: Mapped[str] = mapped_column(String(255), nullable=True, default=None)
    # Which of the three rules the UI should currently display -- state
    # this explicitly rather than inferring it from which fields are
    # non-empty, same "state the source of truth" pattern as G3's glossary
    # tooltips. One of "dominant_prefix" | "top_fan_in" | "numeric" | "custom".
    active_label_rule: Mapped[str] = mapped_column(String(20), default="dominant_prefix")
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ---------------- Codebase agent: code health snapshots (Phase 1) ----------------


class CodeHealthSnapshot(Base):
    """One immutable code-health run. Append-only: a re-run at the same SHA
    writes a NEW row rather than mutating the old one, so a trend line can
    never be rewritten retroactively.

    Every field in the identity block exists because without it two results
    could be silently compared across different inputs:

    - `head_sha` + `branch` -- which revision was analysed.
    - `working_tree_dirty` -- **correctness, not bookkeeping.** For a `local`
      repo we analyse the user's live working directory, so HEAD may not
      describe the bytes that were actually measured at all. A snapshot
      claiming a SHA while the tree was dirty would be a false provenance
      claim.
    - `analyzer_version` -- the AST rules that produced the raw metrics.
    - `thresholds_version` / `weights_version` -- the scoring definition.
      A trend delta is only meaningful between snapshots whose scoring
      matches; comparing across a threshold change silently mixes two
      different measuring sticks.

    `inputs_complete` records whether every input the axes need was
    actually available (see CodeFileHealth.explanation and the Architecture
    Health gate) -- a snapshot taken before file-level SCCs existed is not
    the same kind of artifact as one taken after, and must not be presented
    as if it were.
    """

    __tablename__ = "code_health_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repos.id"), index=True)
    branch: Mapped[str] = mapped_column(String(255), default="")
    head_sha: Mapped[str] = mapped_column(String(64), nullable=True, default=None)
    working_tree_dirty: Mapped[bool] = mapped_column(Boolean, nullable=True, default=None)
    analyzer_version: Mapped[int] = mapped_column(Integer, default=0)
    thresholds_version: Mapped[int] = mapped_column(Integer, default=0)
    weights_version: Mapped[int] = mapped_column(Integer, default=0)
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    # Per-axis repo aggregates (mean/median/p10/counts) plus, per axis,
    # whether its evidence was complete. Stored as JSON rather than columns
    # because the axis set is a product decision that will change, and a
    # migration per axis tweak would be friction with no benefit.
    axis_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    files_scored: Mapped[int] = mapped_column(Integer, default=0)
    files_na: Mapped[int] = mapped_column(Integer, default=0)
    inputs_complete: Mapped[bool] = mapped_column(Boolean, default=False)


class CodeFileHealth(Base):
    """One file's scores within one snapshot, with the marker-level
    explanation that produced them.

    The explanation is stored, not recomputed on read: a historical score
    that cannot be explained by the markers of its own era is not auditable,
    and re-deriving it with today's thresholds would silently rewrite what
    the score meant.

    Null score/points means the axis was N/A for this file -- the reason is
    in `explanation`. Null is never coerced to a number on read.
    """

    __tablename__ = "code_file_health"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "file_id", name="uq_file_health_snapshot_file"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("code_health_snapshots.id"), index=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("code_files.id"), index=True)
    path: Mapped[str] = mapped_column(String(1000))
    nloc: Mapped[int] = mapped_column(Integer, default=0)

    maintainability: Mapped[float] = mapped_column(Float, nullable=True, default=None)
    architecture_health: Mapped[float] = mapped_column(Float, nullable=True, default=None)
    # Points, not a score -- higher means review sooner. Named to match the
    # direction so it cannot be read as a quality grade.
    change_hotspot_points: Mapped[float] = mapped_column(Float, nullable=True, default=None)
    adjusted_exposure: Mapped[float] = mapped_column(Float, nullable=True, default=None)
    explanation: Mapped[dict] = mapped_column(JSON, default=dict)


# ---------------- Codebase agent: background jobs (Phase D) ----------------


class RepoJob(Base):
    """A background resync+ingest+rank run for one repo. Runs in its own thread
    with its own DB session (see app/services/codebase/jobs.py) -- this row IS
    the state a reconnecting SSE client reads, not something held in memory,
    so the job survives a dropped connection and a page reload can reattach."""

    __tablename__ = "repo_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repos.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued|running|done|failed
    stage: Mapped[str] = mapped_column(String(40), default="queued")
    progress_current: Mapped[int] = mapped_column(Integer, default=0)
    progress_total: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str] = mapped_column(String(500), default="")
    result: Mapped[dict] = mapped_column(JSON, nullable=True, default=None)
    error: Mapped[str] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=True, default=None)
    finished_at: Mapped[datetime] = mapped_column(DateTime, nullable=True, default=None)
