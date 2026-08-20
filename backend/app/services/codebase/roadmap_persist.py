"""Phase 4: writing a repo's derived roadmap into the curated tables.

Everything before this phase was preview-only, and `writes_nothing: True` was
a literal field on the response. This is the first code that writes derived
rows into `modules`/`topics`/`resources`/`content_roadmaps` — tables that also
hold hand-written seed content and LLM-generated content. Three properties
make that safe, and each is enforced rather than intended:

1. **Scoped.** Every write and every delete is filtered to
   `source == "codebase"` AND `code_repo_id == this repo`. A seed or generated
   row cannot be reached by this module even in principle; there is no code
   path from here to a row that does not carry both markers.

2. **Progress-preserving.** `topic_progress` rows point at `topics.id`. A naive
   replace-wholesale would delete a topic a user had marked complete and take
   the progress with it. Topics are matched by `(module.slug, topic.slug)` and
   REUSED where they reappear, so ids survive a re-run. Where a topic really is
   gone, its progress is counted and reported, never silently dropped.

3. **Additive-first.** Resources under a surviving topic are replaced (they
   carry no user state); modules and topics are upserted. The only deletes are
   of codebase modules for this repo whose slug is absent from the new build,
   and those are reported with their progress cost.

**Module identity does not come from the slug.** A slug embeds its
`subsystem_id`, and `CodeSubsystem` rows are replaced wholesale on every
clustering run, so slug identity would break on precisely the operation
identity has to survive -- renaming every module and orphaning the whole
previous set, destroying each one's `topic_progress`. Modules are matched to
their predecessors by shared file PATHS instead (`match_modules_by_overlap`),
using the same rule and threshold as `subsystems.py`'s `custom_label`
carry-over: one notion of "the same cluster as before" for the codebase side,
not two that can disagree.

That a cluster boundary is not a stable identity is the contract's §17.0 third
row showing up in the data model. It cannot be designed away, only survived.
"""
from typing import Optional

from sqlalchemy.orm import Session

from app.db.models import (
    CodeFile, CodeImport, CodeSubsystem, ContentRoadmap, Module, Repo, Resource,
    RoadmapNode, RoadmapStage, Topic, TopicProgress, utcnow,
)
from app.services.codebase import module_mapping
from app.services.codebase.ordering import compute_layers
from app.services.codebase.roadmap_staging import load_roadmap_staging_config
from app.services.codebase.subsystems import subsystem_column_for

# `modules.source` / `content_roadmaps.kind` value marking a derived row.
SOURCE = module_mapping.SOURCE  # "codebase"


def build_candidate_modules(db: Session, repo_id: int, algorithm: str,
                            topic_strategy: str, subsystems: list) -> list:
    """The subsystem -> module build shared by /module-preview, /roadmap-preview
    and persistence. Split out here (it previously lived in api/repos.py) so
    that all THREE consumers cannot silently diverge on what a module is --
    the same reason it was extracted for the first two.
    """
    # One pass for every member file, then grouped in memory: a query per
    # subsystem would be 250+ round trips on apache/superset.
    from app.db.models import CodeFileRank
    rank_by_file = dict(
        db.query(CodeFileRank.file_id, CodeFileRank.rank)
        .filter(CodeFileRank.repo_id == repo_id, CodeFileRank.scorer == "legacy")
        .all()
    )
    column = subsystem_column_for(algorithm)
    members_by_subsystem: dict[int, list[dict]] = {}
    for file_id, path, category, sid in (
        db.query(CodeFile.id, CodeFile.path, CodeFile.prior_category, column)
        .filter(CodeFile.repo_id == repo_id, column.isnot(None))
        .all()
    ):
        members_by_subsystem.setdefault(sid, []).append(
            {"path": path, "file_id": file_id, "rank": rank_by_file.get(file_id),
             "prior_category": category}
        )

    modules = [
        module_mapping.map_subsystem_to_module(
            repo_id=repo_id,
            subsystem_id=s.id,
            subsystem_label=s.custom_label or s.dominant_prefix_label or s.top_fan_in_label,
            member_count=s.member_count,
            members=members_by_subsystem.get(s.id, []),
            topic_strategy=topic_strategy,
        )
        for s in subsystems
    ]

    # Files from below-floor subsystems, gathered rather than dropped.
    claimed = {m.subsystem_id for m in modules if m.skipped_reason is None}
    leftovers = [
        member
        for sid, member_list in members_by_subsystem.items()
        if sid not in claimed
        for member in member_list
    ]
    unclustered = module_mapping.unclustered_module(
        repo_id=repo_id, members=leftovers, topic_strategy=topic_strategy)
    if unclustered is not None:
        modules.append(unclustered)

    module_mapping.disambiguate_titles(modules)
    return modules


def build_module_dependencies(db: Session, repo_id: int, algorithm: str) -> dict:
    """subsystem_id -> set of subsystem_ids it imports from. Queried here so
    module_mapping's staging logic stays pure."""
    column = subsystem_column_for(algorithm)
    subsystem_of_file = dict(
        db.query(CodeFile.id, column)
        .filter(CodeFile.repo_id == repo_id, column.isnot(None)).all()
    )
    dependencies: dict[int, set] = {}
    for from_id, to_id in db.query(CodeImport.from_file_id, CodeImport.to_file_id).filter(
        CodeImport.repo_id == repo_id, CodeImport.to_file_id.isnot(None)
    ).all():
        a, b = subsystem_of_file.get(from_id), subsystem_of_file.get(to_id)
        if a is not None and b is not None and a != b:
            dependencies.setdefault(a, set()).add(b)
    return dependencies


def stage_repo_modules(db: Session, repo: Repo, algorithm: str, topic_strategy: str,
                       subsystems: list) -> tuple:
    """(modules, staging) for a repo -- the whole read-only half, shared by the
    preview endpoint and by persistence so the rows written are provably the
    rows previewed."""
    from app.api.repos import _build_graph  # local: api imports this module too

    modules = build_candidate_modules(db, repo.id, algorithm, topic_strategy, subsystems)
    file_by_id = {
        f.id: f for f in db.query(CodeFile).filter(CodeFile.repo_id == repo.id).all()
    }
    graph = _build_graph(db, repo, file_by_id)
    entry_ids = {fid for fid, f in file_by_id.items() if f.seed_eligible}
    layer_by_file_id = compute_layers(graph, entry_ids)

    staging = module_mapping.stage_modules(
        modules, layer_by_file_id,
        dependencies=build_module_dependencies(db, repo.id, algorithm),
        layer_coverage_threshold=load_roadmap_staging_config()["layer_coverage_threshold"],
    )
    return modules, staging


def _roadmap_slug(repo: Repo) -> str:
    return module_mapping.slugify(f"codebase-{repo.owner or 'local'}-{repo.name}")


def _existing_module_paths(db: Session, repo_id: int) -> dict:
    """Module row -> the set of file paths it currently holds.

    Recovered from `resources.code_path` rather than stored separately: those
    rows ARE the module's membership, so a second copy could disagree with
    them. Paths, not file ids -- ids are replaced on re-ingest, which is one of
    the operations module identity has to survive.
    """
    rows = (
        db.query(Module, Resource.code_path)
        .join(Topic, Topic.module_id == Module.id)
        .join(Resource, Resource.topic_id == Topic.id)
        .filter(Module.source == SOURCE, Module.code_repo_id == repo_id)
        .all()
    )
    paths_by_module: dict = {}
    module_by_id: dict = {}
    for module, path in rows:
        module_by_id[module.id] = module
        if path:
            paths_by_module.setdefault(module.id, set()).add(path)
    return {module_by_id[mid]: paths for mid, paths in paths_by_module.items()}


def match_modules_by_overlap(existing: dict, candidates: list, min_overlap: float) -> tuple:
    """Pair each new candidate module with the previous Module row it is a
    continuation of, by shared file paths.

    Overlap is measured against the OLD module's size -- `|old & new| / |old|`
    -- the same direction subsystems.py's custom_label carry-over measures it.
    That asks "is most of what this module used to be still here", which is the
    question that matters for whether a user's progress on it still refers to
    the same thing. Measuring against the new size instead would let a large
    new module claim a small old one it merely absorbed.

    Greedy, highest overlap first, one-to-one: two new modules cannot both
    inherit the same old module's identity (and its progress), and the tie is
    broken by overlap rather than by iteration order.

    Pure -- no DB, no writes. Returns (matched, orphans) where `matched` maps
    candidate slug -> (Module row, overlap).
    """
    scored = []
    for cand in candidates:
        cand_paths = {r.path for t in cand.topics for r in t.resources}
        if not cand_paths:
            continue
        for module, old_paths in existing.items():
            if not old_paths:
                continue
            overlap = len(old_paths & cand_paths) / len(old_paths)
            if overlap >= min_overlap:
                scored.append((overlap, cand.slug, module))

    scored.sort(key=lambda t: (-t[0], t[1]))
    matched: dict = {}
    claimed_modules = set()
    for overlap, slug, module in scored:
        if slug in matched or module.id in claimed_modules:
            continue
        matched[slug] = (module, overlap)
        claimed_modules.add(module.id)

    orphans = [m for m in existing if m.id not in claimed_modules]
    return matched, orphans


def persist_repo_roadmap(db: Session, repo: Repo, *, algorithm: str = "modularity",
                         topic_strategy: str = module_mapping.DEFAULT_TOPIC_STRATEGY,
                         commit_sha: Optional[str] = None) -> dict:
    """Write (or re-write) this repo's derived roadmap. Returns a report of
    every row created, reused and deleted -- including the progress cost of any
    delete, which is the number a caller most needs and would otherwise have to
    infer from a total."""
    subsystems = (
        db.query(CodeSubsystem)
        .filter(CodeSubsystem.repo_id == repo.id, CodeSubsystem.algorithm == algorithm)
        .order_by(CodeSubsystem.member_count.desc(), CodeSubsystem.id.asc())
        .all()
    )
    if not subsystems:
        raise ValueError(
            f"no {algorithm} clustering for repo {repo.id} -- run clustering first. "
            "Writing an empty roadmap would read as 'this repo has no structure'."
        )

    modules, staging = stage_repo_modules(db, repo, algorithm, topic_strategy, subsystems)
    produced = [m for m in modules if m.skipped_reason is None]

    # ---- existing codebase rows for THIS repo, and only those -------------
    #
    # Matched by FILE OVERLAP, not by slug. A module's slug embeds its
    # subsystem_id and CodeSubsystem rows are replaced wholesale on every
    # clustering run, so slug identity would break on exactly the operation
    # this has to survive -- renaming every module and orphaning the whole
    # previous set, taking each one's topic_progress with it.
    min_overlap = float(load_roadmap_staging_config()["module_identity_min_overlap"])
    existing = _existing_module_paths(db, repo.id)
    matched, orphans = match_modules_by_overlap(existing, produced, min_overlap)

    created_modules = reused_modules = 0
    created_topics = reused_topics = 0
    resource_count = 0
    carried_over = []   # (old slug, new slug, overlap) -- nameable, not just counted
    renamed = 0
    stale_topics_kept, stale_topics_deleted = [], 0
    renamed_topics = 0
    progress_preserved = 0

    # Orphan slugs are freed BEFORE new rows claim them: `modules.slug` is
    # unique, and a kept orphan must not block the slug of the module that
    # replaced it.
    for module in orphans:
        module.slug = f"{module.slug}--orphaned-{repo.id}-{module.id}"
    db.flush()

    for order, cand in enumerate(produced):
        match = matched.get(cand.slug)
        if match is None:
            row = Module(slug=cand.slug, source=SOURCE, code_repo_id=repo.id)
            db.add(row)
            created_modules += 1
        else:
            row, overlap = match
            reused_modules += 1
            if row.slug != cand.slug:
                carried_over.append({
                    "previous_slug": row.slug, "slug": cand.slug,
                    "title": cand.title, "overlap": round(overlap, 4),
                })
                row.slug = cand.slug
                renamed += 1
            # A row that was orphaned by an earlier run and has now come back
            # is no longer an orphan.
            row.code_orphaned_at = None
        row.title = cand.title
        row.kind = cand.kind
        row.summary = cand.summary
        db.flush()

        existing_topics = {
            t.slug: t for t in db.query(Topic).filter(Topic.module_id == row.id).all()
        }
        for t_order, cand_topic in enumerate(cand.topics):
            topic = existing_topics.get(cand_topic.slug)
            if topic is None:
                # Slug missed -- but a topic's identity is no more its slug
                # than a module's is. Adopt a previous topic in this same
                # module holding the same TITLE at the same position: that is
                # the same topic under a different name, and reusing its row
                # carries its topic_progress across instead of stranding it
                # beside its own replacement.
                adopted = next(
                    (t for t in existing_topics.values()
                     if t.title == cand_topic.title and t.order_index == t_order),
                    None,
                )
                if adopted is not None:
                    topic = adopted
                    existing_topics.pop(adopted.slug, None)
                    topic.slug = cand_topic.slug
                    renamed_topics += 1
            if topic is None:
                topic = Topic(module_id=row.id, slug=cand_topic.slug, source=SOURCE)
                db.add(topic)
                created_topics += 1
            else:
                # REUSED, not replaced: topic_progress.topic_id points here.
                # Counts an adopted topic too -- it is the same row, reached by
                # title+position rather than by slug.
                reused_topics += 1
            topic.title = cand_topic.title
            topic.order_index = t_order
            db.flush()

            # Resources carry no user state, so they are replaced wholesale --
            # this is what keeps a re-run in step with a re-ranked repo.
            db.query(Resource).filter(Resource.topic_id == topic.id).delete(
                synchronize_session=False)
            for r in cand_topic.resources:
                db.add(Resource(
                    topic_id=topic.id, kind="doc", status="intent",
                    title=r.title, order_index=r.order_index,
                    code_repo_id=repo.id, code_path=r.path,
                    code_commit_sha=commit_sha,
                ))
                resource_count += 1

            existing_topics.pop(cand_topic.slug, None)

        # Topics under this module that the new build no longer produces. Same
        # rule as modules: one carrying progress is kept, one carrying none is
        # deleted. Leaving them in place was a real bug -- a topic stranded
        # beside its replacement keeps its resources and its progress while
        # showing nowhere, so a module reported completion for a topic it no
        # longer had. Discovered on eslint after a re-cluster, where every
        # module ended up with two identically-titled `Files` topics.
        for leftover in existing_topics.values():
            n_progress = db.query(TopicProgress).filter(
                TopicProgress.topic_id == leftover.id).count()
            if n_progress:
                stale_topics_kept.append({
                    "module_slug": cand.slug, "topic_slug": leftover.slug,
                    "topic_progress_rows": n_progress,
                })
                progress_preserved += n_progress
            else:
                db.query(Resource).filter(Resource.topic_id == leftover.id).delete(
                    synchronize_session=False)
                db.delete(leftover)
                stale_topics_deleted += 1

    # ---- modules the re-clustering dissolved ------------------------------
    #
    # An orphan with progress is KEPT and marked, never deleted: the user's
    # study is real and a re-cluster they did not ask for must not destroy it.
    # An orphan with no progress is deleted -- nothing is preserved by keeping
    # it, and it would accumulate on every re-cluster.
    orphaned_kept, orphaned_deleted = [], []
    for module in orphans:
        topic_ids = [tid for (tid,) in db.query(Topic.id).filter(
            Topic.module_id == module.id).all()]
        n_progress = (
            db.query(TopicProgress).filter(TopicProgress.topic_id.in_(topic_ids)).count()
            if topic_ids else 0
        )
        entry = {"slug": module.slug, "title": module.title,
                 "topic_progress_rows": n_progress}
        if n_progress:
            module.code_orphaned_at = utcnow()
            orphaned_kept.append(entry)
            progress_preserved += n_progress
        else:
            orphaned_deleted.append(entry)
            db.delete(module)  # cascades to its topics and their resources

    # ---- the roadmap itself ----------------------------------------------
    slug = _roadmap_slug(repo)
    roadmap = db.query(ContentRoadmap).filter(ContentRoadmap.slug == slug).first()
    if roadmap is None:
        roadmap = ContentRoadmap(slug=slug, kind=SOURCE, code_repo_id=repo.id)
        db.add(roadmap)
    roadmap.title = f"{repo.owner + '/' if repo.owner else ''}{repo.name}"
    roadmap.target = roadmap.title
    roadmap.category = "tool"
    roadmap.staging_basis = staging["basis"]
    roadmap.summary = staging["basis_reason"]
    db.flush()

    # Stages are rebuilt wholesale: they carry no user state, and their
    # identity IS their order, which changes whenever staging does.
    for s in db.query(RoadmapStage).filter(RoadmapStage.roadmap_id == roadmap.id).all():
        db.delete(s)  # cascades to nodes
    db.flush()

    # Orphans excluded: they are kept for their progress, not because they are
    # still part of this repo's reading order, and a stage node pointing at one
    # would put a dissolved module back on the roadmap.
    module_by_slug = {
        m.slug: m for m in db.query(Module).filter(
            Module.source == SOURCE, Module.code_repo_id == repo.id,
            Module.code_orphaned_at.is_(None),
        ).all()
    }
    stage_count = node_count = 0
    for s_order, stage in enumerate(staging["stages"]):
        stage_row = RoadmapStage(roadmap_id=roadmap.id, title=stage["title"],
                                 order_index=s_order)
        db.add(stage_row)
        db.flush()
        stage_count += 1
        for n_order, cand in enumerate(stage["modules"]):
            target = module_by_slug.get(cand.slug)
            db.add(RoadmapNode(
                stage_id=stage_row.id,
                module_id=target.id if target else None,
                module_slug=cand.slug,
                title=cand.title,
                blurb="",
                order_index=n_order,
                # "matched" means the node points at a real module row, which
                # is the same word the LLM path uses for the same condition.
                resolution="matched" if target else "unmatched",
            ))
            node_count += 1

    db.commit()
    return {
        "repo_id": repo.id,
        "roadmap_slug": slug,
        "roadmap_id": roadmap.id,
        "algorithm": algorithm,
        "topic_strategy": topic_strategy,
        "staging_basis": staging["basis"],
        "layer_coverage": staging["layer_coverage"],
        "module_identity_min_overlap": min_overlap,
        "modules_created": created_modules,
        "modules_reused": reused_modules,
        # Reused under a NEW slug -- i.e. the re-clustering renamed the module
        # and identity matching kept it anyway. This is the count that would
        # have been "deleted, progress lost" under slug identity.
        "modules_renamed": renamed,
        "modules_carried_over": carried_over,
        "modules_orphaned_kept": orphaned_kept,
        "modules_orphaned_deleted": orphaned_deleted,
        "topics_created": created_topics,
        "topics_reused": reused_topics,
        # Reused despite a changed slug, matched by title+position -- the
        # topic-level counterpart of modules_renamed.
        "topics_renamed": renamed_topics,
        "topics_stale_deleted": stale_topics_deleted,
        "topics_stale_kept": stale_topics_kept,
        "resources_written": resource_count,
        "stages": stage_count,
        "nodes": node_count,
        # Both stated even when zero: "no progress was lost" is a result, and a
        # caller should not have to infer it from the absence of a field.
        "topic_progress_rows_deleted": 0,
        "topic_progress_rows_preserved_on_orphans": progress_preserved,
    }
