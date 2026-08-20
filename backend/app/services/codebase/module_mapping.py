"""Phase 4 groundwork: what a codebase subsystem would look like in the library.

PURE AND UNWIRED. Nothing calls this from a write path; the only caller is a
read-only preview endpoint that computes and returns without inserting.

## The mapping, and why the first attempt was wrong

The first version mapped subsystem -> module and FILE -> TOPIC. On
apache/superset that produced a module with **932 topics**, against a curated
median of 7. A module with 932 topics is not a module; it is a database view
wearing a module's schema, and every existing module page, progress calculation
and review interaction would be operating two orders of magnitude outside its
tested range.

The revised mapping uses each library concept for what it was built for:

    subsystem              ->  module      "these files are entangled"
    architectural concept  ->  topic       a thing you study
    file                   ->  resource    a thing you go and read

A resource is a thing you go and read, which is exactly what a file is. A topic
is a thing you study and get graded on, and a file path is not that.

## The measured shapes -- and the level that is NOT available

Curated side, observed live:

    topics per module        5 / 7 / 8          (min / median / max)
    resources per TOPIC      2 / 2 / 3          97 of 98 topics have exactly 2
    resources per MODULE    10 / 14 / 17

Codebase side, repo 3 (eslint, the validated repo):

    subsystems with members  9                  NOT ~20
    files per subsystem      2 / 10 / 151

So subsystem -> module and file -> resource land in roughly the right range at
the module level. Three derivable candidates were measured for "how many groups
does this produce per subsystem", against a 3-8 target.

RE-MEASURED 2026-08-17 against corrected graphs (the original figures came from
a 398-file fixture and from edge weights in which is_test_file misweighted 59%
of eslint's edges -- contract §17.26 and §17.28, so the SUBSYSTEMS themselves
were different objects). Original figures in brackets:

    grouping            Athena-OS      eslint             superset
    parent directory    4/4  (100%)    8/17  (47%) [57%]  22/122 (18%) [16%]
    2nd path segment    1/4  (25%)     6/17  (35%) [0%]    7/122 (6%)  [4%]
    prior_category      0/4  (0%)      1/17  (6%)  [0%]    4/122 (3%)  [3%]

**The in-band rates broadly reproduce and the conclusion holds -- but the
argument for it does not, and has been rewritten.**

What no longer holds: the structural claim. The original said eslint's largest
subsystem splits by parent directory into 149/1/1, "one directory with two
strays, not three concepts". That was a fixture artifact. On the real corpora
the largest module splits into:

    eslint    (413 files)  ->  285, 17, 13, 12, 10, 5, ...   top group 69%
    superset (1138 files)  ->   94, 75, 56, 41, 36, 34, ...  top group 8%

Superset's is a genuinely even split. A concept level DOES exist in that data;
parent directory finds it. Athena-OS lands 4/4 in band -- though at n=4 that is
a fact about the corpus, not the method (§17.5c).

What does hold, for a different reason: group COUNT is uncorrelated with the
3-8 band because module SIZE spans three orders of magnitude (3 to 1,138 files
per module). Superset's largest module yields 230 parent-directory groups --
far out of band, yet averaging ~5 files each, which is a reasonable topic size.
The band was never the right test; it is the count/size coupling already
recorded as §17.17's third instance, showing up one level down.

So `single_topic` remains the default, now on this basis: **no strategy is
reliable ACROSS modules, because the right number of topics depends on a module
size that varies enormously.** That is a statement about needing a size-aware
split (§17.17's budget answer), not about the data lacking sub-structure -- the
earlier, stronger claim that it lacks any is withdrawn.

**So `TOPIC_STRATEGIES` is explicit and named rather than silently chosen.**
The default is the least-bad option, the alternatives are one argument away, and
the preview reports the resulting distribution so the shape can be judged from
output instead of from this docstring. Inventing a concept level that the data
does not support would be the same error as generating a summary from filenames.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from statistics import median
from typing import Callable, Optional

# `modules.source` holds "seed" (hand-written) and "generated" (roadmap flow).
# `codebase` is a third provenance and not a reuse of `generated`: a codebase
# module has a commit SHA, can go stale, and is regenerable from the repo, and
# an LLM-generated one has none of those properties. No CHECK constraint exists
# on the column, so this is additive with no migration.
SOURCE = "codebase"

# `modules.kind` observed values are "tool" and "skill". A subsystem is neither.
KIND = "codebase"

# `resources.kind` holds "video" and "article". A code reference is a third
# thing a resource can BE -- which is the axis `kind` describes. Deliberately
# not a new `status`: status is the lifecycle (intent -> saved) and a code_ref
# has a lifecycle too, so overloading it would conflate two axes.
RESOURCE_KIND = "code_ref"

# Below this a group is a coupling pair, not a subsystem. Matches the cluster
# list, which already treats singletons as a separate category.
MIN_FILES_FOR_MODULE = 3

# node_priors.py already marks "migration" as generated-and-forgotten -- code
# that exists, but that nobody sits down to read (weighted 0.15 in ranking,
# against 1.0 for source). A subsystem built mostly of migrations does not
# become a better module by down-weighting them further; it becomes a module
# whose real content is buried under hundreds of files that were never meant
# to be studied. So they are excluded from module generation entirely, the
# same way the ranking prior already excludes them from mattering -- one
# category, not the full NOISE_CATEGORIES set in node_priors.py, because
# "config" and "generated" files are still things a person plausibly reads.
EXCLUDED_PRIOR_CATEGORIES = frozenset({"migration"})

# ## Catalogue classification: REMOVED, 2026-08-17
#
# A `classify_catalogue` predicate lived here, flagging subsystems that were
# "many structurally homogeneous members with no sibling relationships once
# the dominant hub is excluded" -- eslint's ~300 sibling rule files, which no
# topic strategy can find structure in because there is none to find. Two
# constants (>=30 members, hub-excluded density < 0.2) were calibrated
# against eslint repo 3.
#
# It never fired on a real corpus. Measured across Athena-OS, the fully
# re-cloned eslint/eslint and Apache Superset: 282 subsystems, 34 of them at
# or above the 30-member floor, ZERO flagged, with the nearest candidate 2.7x
# above the density threshold. The calibration figures (`lib/rules · index`
# at hub-excluded density 0.01) came from a 398-file stripped fixture in
# which `lib/rules` was cut off from the shared helpers that give it real
# internal structure in the actual repository; on the real clone that same
# region measures 0.53-0.71.
#
# Removed rather than made configurable: the question was whether the
# classification should exist, not what its numbers should be, and leaving
# dead code behind a config seam invites someone to tune it until it fires.
# The full reasoning, including why hub exclusion was the right idea even
# though the thresholds were not, is preserved in docs/code-health-contract.md
# §17.27 -- if a genuine catalogue turns up on a future repo this is a small
# rebuild from a recorded argument, not a rediscovery.


_SLUG_UNSAFE = re.compile(r"[^a-z0-9]+")


def _parent_directory(path: str) -> str:
    return path.rsplit("/", 1)[0] if "/" in path else "(root)"


def _second_segment(path: str) -> str:
    return "/".join(path.split("/")[:2]) or "(root)"


def _prior_category(path: str, category: Optional[str]) -> str:
    return category or "unknown"


# Named, measured, and one argument away from each other. See the module
# docstring for what each produced against a 3-8 target -- none of them hits it,
# which is a finding about the data rather than a reason to pick quietly.
#
# `single_topic` is the DEFAULT, and it is the honest one.
#
# A zero-topic module is not available: `resources.topic_id` is NOT NULL, so a
# resource cannot exist without a topic, and a module with no topics returns no
# resources at all (modules.py fetches resources per topic). Making
# module-level resources possible would mean altering an existing column from
# NOT NULL to nullable.
#
# Given that a topic must exist, the choice is between applying a grouping that
# is unreliable across modules and declining to. `single_topic` declines: one
# topic per module, holding every file in reading-rank order.
#
# REVISED 2026-08-17 (see the re-measurement in this module's docstring). The
# earlier justification was "this module has no sub-structure the analysis can
# see". That was too strong and is withdrawn: on Superset, parent directory
# splits the largest module into 94/75/56/41/36/34... -- real, even structure.
# What `single_topic` now says is narrower and still true: the number of topics
# a module should have depends on its size, module sizes span 3 to 1,138 files,
# and no fixed strategy produces a sensible count across that range. Choosing
# one anyway would assert a level of confidence the measurement does not
# support -- but so would claiming the level does not exist.
TOPIC_STRATEGIES: dict[str, Callable[[str, Optional[str]], str]] = {
    "single_topic": lambda path, cat: "Files",
    "parent_directory": lambda path, cat: _parent_directory(path),
    "second_segment": lambda path, cat: _second_segment(path),
    "prior_category": _prior_category,
}
DEFAULT_TOPIC_STRATEGY = "single_topic"

# How many resources a PREVIEW returns per topic before truncating. The full
# count always travels alongside.
#
# Cap and paginate rather than roll up. §17.17's first two instances had a
# hierarchy to roll up INTO -- a parent path that was itself meaningful. Files
# inside a module do not: 151 files in eslint's largest module are not nested in
# a way that yields meaningful groups, and inventing intermediate ones is the
# same objection as splitting a 122-file cycle by severity band.
#
# Reading rank is the ordering the ranker exists to produce, and it is exactly
# what a newcomer needs. A 151-resource module whose first 20 are the right 20
# is usable; the same module split into invented sub-groups is not.
RESOURCE_PREVIEW_LIMIT = 20


@dataclass
class CandidateResource:
    """One file, as a resource. `order_index` preserves reading-list rank ORDER
    within its topic.

    The absolute rank is NOT preserved: `resources` has no rank column, so
    "this is rank 3 of 398" cannot be recovered from `order_index` alone. That
    is a real cost of moving files from topics to resources and is recorded
    rather than absorbed -- relative order survives, absolute position does
    not."""

    path: str
    title: str
    kind: str
    order_index: int
    file_id: Optional[int] = None
    rank: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "path": self.path, "title": self.title, "kind": self.kind,
            "order_index": self.order_index, "file_id": self.file_id, "rank": self.rank,
        }


@dataclass
class CandidateTopic:
    slug: str
    title: str
    order_index: int
    resources: list[CandidateResource] = field(default_factory=list)

    def to_dict(self, limit: Optional[int] = RESOURCE_PREVIEW_LIMIT) -> dict:
        """Capped, with the TOTAL always present.

        A truncated list whose total is not stated is the graph endpoint's old
        "400 of 6,523" problem: the reader cannot tell a small module from a
        large one shown small. `resource_count` is the full figure and
        `resources_truncated` says plainly whether what follows is all of it."""
        shown = self.resources if limit is None else self.resources[:limit]
        return {
            "slug": self.slug, "title": self.title, "order_index": self.order_index,
            "resource_count": len(self.resources),
            "resources_shown": len(shown),
            "resources_truncated": len(shown) < len(self.resources),
            "resources": [r.to_dict() for r in shown],
        }


@dataclass
class CandidateModule:
    slug: str
    title: str
    kind: str
    source: str
    summary: str
    subsystem_id: int
    repo_id: int
    member_count: int
    topics: list[CandidateTopic] = field(default_factory=list)
    skipped_reason: Optional[str] = None
    # How many of `member_count` were excluded as migrations. `member_count`
    # deliberately still counts them -- it is the figure the Subsystems view
    # shows for this same group, and disagreeing with it silently would be the
    # exact honesty problem `skipped_reason` already exists to avoid.
    excluded_migration_count: int = 0

    @property
    def resource_count(self) -> int:
        return sum(len(t.resources) for t in self.topics)

    @property
    def centre_file(self) -> Optional[str]:
        """The best-ranked member's path, or None for a module with no members.

        Topics are ordered by their best-ranked member and resources within a
        topic are rank-ordered, so the first resource of the first topic IS the
        module's best-ranked file -- no second sort."""
        for topic in self.topics:
            if topic.resources:
                return topic.resources[0].path
        return None

    def to_dict(self, resource_limit: Optional[int] = RESOURCE_PREVIEW_LIMIT) -> dict:
        return {
            "slug": self.slug, "title": self.title, "kind": self.kind,
            "source": self.source, "summary": self.summary,
            "subsystem_id": self.subsystem_id, "repo_id": self.repo_id,
            "member_count": self.member_count,
            "excluded_migration_count": self.excluded_migration_count,
            "topic_count": len(self.topics),
            "resource_count": self.resource_count,
            "topics": [t.to_dict(resource_limit) for t in self.topics],
            "skipped_reason": self.skipped_reason,
        }


def slugify(text: str) -> str:
    """Lowercase, non-alphanumerics collapsed, truncated to the column width.

    `modules.slug` and `topics.slug` are both VARCHAR(120), and directory-derived
    labels on superset exceed that. Truncated on a hyphen boundary where
    possible so a cut slug does not end mid-word."""
    slug = _SLUG_UNSAFE.sub("-", (text or "").lower()).strip("-")
    if len(slug) <= 120:
        return slug or "unnamed"
    cut = slug[:120]
    if "-" in cut[80:]:
        cut = cut[:cut.rindex("-")]
    return cut.strip("-") or "unnamed"


def title_for(subsystem_label: Optional[str], subsystem_id: int) -> str:
    """The cluster's own label, else a stable fallback. Not generated prose:
    `SubsystemsView` already shows a label for this cluster and inventing a
    second name would mean one group is called two things in one product."""
    label = (subsystem_label or "").strip()
    return label if label else f"Cluster {subsystem_id}"


def map_subsystem_to_module(
    *,
    repo_id: int,
    subsystem_id: int,
    subsystem_label: Optional[str],
    member_count: int,
    members: list[dict],
    min_files: int = MIN_FILES_FOR_MODULE,
    topic_strategy: str = DEFAULT_TOPIC_STRATEGY,
) -> CandidateModule:
    """One subsystem -> one module of topics of resources. Pure: no DB, no IO.

    `members` are dicts with `path`, optionally `file_id`, `rank` and
    `prior_category`.
    """
    if topic_strategy not in TOPIC_STRATEGIES:
        raise ValueError(
            f"unknown topic strategy {topic_strategy!r}; known: {sorted(TOPIC_STRATEGIES)}"
        )
    keyfn = TOPIC_STRATEGIES[topic_strategy]
    title = title_for(subsystem_label, subsystem_id)

    module = CandidateModule(
        slug=slugify(f"{title}-{repo_id}-{subsystem_id}"),
        title=title, kind=KIND, source=SOURCE,
        # Empty, like every `generated` module row already in the table. Prose
        # synthesised from filenames would read as something a human wrote.
        summary="",
        subsystem_id=subsystem_id, repo_id=repo_id, member_count=member_count,
    )

    if member_count < min_files:
        module.skipped_reason = (
            f"{member_count} files is below the {min_files}-file minimum: a group this "
            "small is a coupling pair, not a subsystem"
        )
        return module

    usable_members = [m for m in members if m.get("prior_category") not in EXCLUDED_PRIOR_CATEGORIES]
    module.excluded_migration_count = len(members) - len(usable_members)

    if len(usable_members) < min_files:
        module.skipped_reason = (
            f"{len(usable_members)} non-migration files remain after excluding "
            f"{module.excluded_migration_count} migration file"
            f"{'s' if module.excluded_migration_count != 1 else ''}, below the {min_files}-file minimum"
        )
        return module

    # Rank order first, so it survives into each topic's resource ordering.
    # Unranked files sort LAST: "unranked" is not "rank 0", and sorting them
    # first would put the least-known files at the top of the reading order.
    ranked = sorted(
        usable_members,
        key=lambda m: (m.get("rank") is None, m.get("rank") or 0, m.get("path") or ""),
    )

    grouped: dict[str, list[dict]] = {}
    for m in ranked:
        grouped.setdefault(keyfn(m.get("path") or "", m.get("prior_category")), []).append(m)

    # Topics ordered by their best-ranked member, so the topic containing the
    # most important file comes first -- the same signal, one level up.
    def best_rank(items: list[dict]) -> tuple:
        ranks = [i["rank"] for i in items if i.get("rank") is not None]
        return (not ranks, min(ranks) if ranks else 0)

    for t_index, (group_key, items) in enumerate(
            sorted(grouped.items(), key=lambda kv: best_rank(kv[1]))):
        module.topics.append(CandidateTopic(
            # Scoped by GROUP KEY and position only -- deliberately NOT by
            # subsystem_id. `topics` is unique on (module_id, slug), so the id
            # added nothing; what it did add was instability, because
            # CodeSubsystem rows are replaced wholesale on every clustering run
            # and the id therefore changes. That made a topic un-matchable
            # across a re-cluster, so persistence created a SECOND topic beside
            # the first and stranded the original's resources and its
            # topic_progress on a module that no longer showed it. Same defect
            # as the module slug, one level down (contract §17.28).
            slug=slugify(f"{group_key}-{t_index}"),
            title=group_key,
            order_index=t_index,
            resources=[
                CandidateResource(
                    path=m.get("path") or "",
                    title=(m.get("path") or "").rsplit("/", 1)[-1],
                    kind=RESOURCE_KIND,
                    order_index=r_index,
                    file_id=m.get("file_id"),
                    rank=m.get("rank"),
                )
                for r_index, m in enumerate(items)
            ],
        ))
    return module


def disambiguate_titles(modules: list[CandidateModule]) -> list[CandidateModule]:
    """Where several modules share a title, append each one's centre file.

    Mutates and returns the list.

    Three of eslint's eight modules are titled `lib/rules`: three clusters
    legitimately share a dominant prefix, so the label carries less information
    than it appears to. Slugs differ, which prevents a collision and does
    nothing for a reader looking at three modules with one name.

    This is I3's labelling problem resurfacing one level up. Dominant-prefix was
    chosen as the default title with the top-fan-in stem as a SUBTITLE, and the
    ambiguous-prefix case is exactly where that subtitle earns its keep -- so the
    fix is to promote it into the title, and only where the prefix is not
    unique. An unambiguous title is left exactly as it was.

    The centre file is the module's best-RANKED member rather than its
    top-fan-in one: it is already computed here, and it is guaranteed distinct
    because a file belongs to exactly one subsystem. The prefix says WHERE a
    cluster lives; the centre file says what it is centred ON.
    """
    by_title: dict[str, list[CandidateModule]] = {}
    for m in modules:
        by_title.setdefault(m.title, []).append(m)

    for title, group in by_title.items():
        if len(group) < 2:
            continue
        for m in group:
            centre = m.centre_file
            if centre is None:
                continue  # a skipped module has no members to be centred on
            stem = centre.rsplit("/", 1)[-1].rsplit(".", 1)[0]
            m.title = f"{title} · {stem}"
            m.slug = slugify(f"{title}-{stem}-{m.repo_id}-{m.subsystem_id}")
    return modules


def unclustered_module(
    *,
    repo_id: int,
    members: list[dict],
    topic_strategy: str = DEFAULT_TOPIC_STRATEGY,
) -> Optional[CandidateModule]:
    """One module gathering every file that no real module claimed.

    Subsystems below the file floor are reported with a `skipped_reason`, which
    keeps the COUNTS honest -- but their files would still be absent from the
    library, and a file that exists in the repo and appears nowhere is worse
    than a file in an awkward module. The Dependency Clusters view already
    solves this the same way, with one "Unclustered" row rather than silence.

    Returns None when nothing was left over, so an empty module is never
    emitted just to have one.
    """
    if not members:
        return None
    module = map_subsystem_to_module(
        repo_id=repo_id,
        subsystem_id=0,          # not a real subsystem; nothing points at it
        subsystem_label="Unclustered",
        member_count=len(members),
        members=members,
        min_files=1,             # the floor is what put these files here
        topic_strategy=topic_strategy,
    )
    module.slug = slugify(f"unclustered-{repo_id}")
    return module


def group_modules_into_stages(
    modules: list[CandidateModule],
    layer_by_file_id: dict[int, Optional[int]],
) -> list[dict]:
    """Groups PRODUCED modules (skipped_reason is None) into stages by
    dependency layer -- the same BFS-from-entry-points depth the Layers view
    already computes and renders as columns ("Layer N" in LayersView.tsx). A
    repo-roadmap with every module in one stage is a bag; grouped by layer
    it is a reading order: stage "Layer 0" is entry points, "Layer 1" is
    what they reach, and so on -- the same thing the Layers view already
    demonstrates works, one level up (modules instead of files).

    A module's stage is the MINIMUM layer among its own members that have a
    known layer -- the earliest point a reader could reach ANY file in it --
    not its centre file's layer, which can sit considerably deeper than the
    module's most-reachable member and would place the whole module later
    than a reader could actually first encounter it.

    A module with no member reachable from any entry point (every member's
    layer is None) goes into a distinct "Unreachable" stage, appended last --
    the same convention LayersView already uses for individual files, not
    folded into the highest-numbered stage: reachable-but-far and
    reachable-by-nothing are structurally different facts, not points on the
    same scale.
    """
    produced = [m for m in modules if m.skipped_reason is None]

    def module_stage(m: CandidateModule) -> Optional[int]:
        known = [
            layer_by_file_id[r.file_id]
            for t in m.topics for r in t.resources
            if r.file_id is not None and layer_by_file_id.get(r.file_id) is not None
        ]
        return min(known) if known else None

    def reading_order_key(m: CandidateModule) -> tuple:
        # Best-ranked member first -- same ordering principle as topics
        # within a module and resources within a topic elsewhere here.
        centre_rank = None
        for t in m.topics:
            if t.resources:
                centre_rank = t.resources[0].rank
                break
        return (centre_rank is None, centre_rank or 0)

    by_stage: dict[Optional[int], list[CandidateModule]] = {}
    for m in produced:
        by_stage.setdefault(module_stage(m), []).append(m)

    stages = [
        {"title": f"Layer {layer}", "modules": sorted(by_stage[layer], key=reading_order_key)}
        for layer in sorted(k for k in by_stage if k is not None)
    ]
    if None in by_stage:
        stages.append({"title": "Unreachable", "modules": sorted(by_stage[None], key=reading_order_key)})
    return stages


DEFAULT_LAYER_COVERAGE_THRESHOLD = 0.40


def layer_coverage(layer_by_file_id: dict[int, Optional[int]]) -> float:
    """Fraction of files reachable from any entry point. The input for
    deciding whether layer-based staging is even applicable to a repo."""
    if not layer_by_file_id:
        return 0.0
    reached = sum(1 for v in layer_by_file_id.values() if v is not None)
    return reached / len(layer_by_file_id)


def _subsystem_depth(module_ids: list[int], dependencies: dict[int, set]) -> dict[int, int]:
    """Longest-path depth of each module in the module-level dependency DAG,
    with cycles collapsed by iterating to a fixed point rather than by
    condensing -- a module in a cycle gets the depth of the cycle's earliest
    member, which is the honest answer (there is no order within a cycle).

    Bounded by len(module_ids) iterations so a cycle cannot loop forever."""
    depth = {mid: 0 for mid in module_ids}
    known = set(module_ids)
    for _ in range(len(module_ids)):
        changed = False
        for mid in module_ids:
            deps = [d for d in dependencies.get(mid, ()) if d in known and d != mid]
            if not deps:
                continue
            candidate = max(depth[d] for d in deps) + 1
            if candidate > depth[mid] and candidate < len(module_ids):
                depth[mid] = candidate
                changed = True
        if not changed:
            break
    return depth


def stage_modules(
    modules: list[CandidateModule],
    layer_by_file_id: dict[int, Optional[int]],
    *,
    dependencies: Optional[dict[int, set]] = None,
    layer_coverage_threshold: float = DEFAULT_LAYER_COVERAGE_THRESHOLD,
) -> dict:
    """Stages a repo's modules on whichever basis its graph actually supports,
    and says which one it used.

    Layer staging assumes most of the repo is reachable from its entry points.
    That assumption is repo-specific, not generally true, and the spread is
    not marginal -- measured: Athena-OS 55.3%, eslint 26.9%, Superset 13.2%.
    Superset's figure is a CEILING, not a gap to be closed by better entry
    detection: it is a Flask app wired through `create_app()` and dynamic
    blueprint registration, which produce no static import edges at all, so
    adding its real `console_scripts` entry point (which this project did)
    moved reachability by two files. Presenting 87% of such a repo under one
    stage called "Unreachable" would report a property of static analysis as
    though it were a property of the codebase.

    Below the threshold, modules are staged by their own dependency depth
    instead -- which module must be read before which -- a relation that needs
    no entry points and is therefore available on exactly the repos where
    layers are not. `dependencies` maps a module's subsystem_id to the set of
    subsystem_ids it imports from; the caller queries them, this function
    stays pure.

    The threshold is a parameter, not a judgment call made here. On the three
    repos measured, 30%, 40% and 50% all produce the identical basis for all
    three -- no repo sits near a boundary -- so the exact value is not
    currently load-bearing, and that is a reason to state it rather than to
    treat any of the three as validated.
    """
    coverage = layer_coverage(layer_by_file_id)
    basis = "layer" if coverage >= layer_coverage_threshold else "subsystem"

    if basis == "layer":
        # Titles carry the basis, not just the number: "Layer 2" alone does
        # not tell a reader whether it means two hops from an entry point or
        # the third tier of a dependency ordering, and those are different
        # claims that this function can return on different repos.
        stages = [
            {**s, "title": s["title"] if s["title"] == "Unreachable"
                  else f"{s['title']} · from entry points"}
            for s in group_modules_into_stages(modules, layer_by_file_id)
        ]
        return {
            "basis": "layer",
            "layer_coverage": coverage,
            "layer_coverage_threshold": layer_coverage_threshold,
            "basis_reason": (
                f"{coverage:.1%} of files are reachable from an entry point, at or above "
                f"the {layer_coverage_threshold:.0%} threshold, so stages are dependency "
                f"layers from the entry points."
            ),
            "stages": stages,
        }

    produced = [m for m in modules if m.skipped_reason is None]

    def reading_order_key(m: CandidateModule) -> tuple:
        centre_rank = None
        for t in m.topics:
            if t.resources:
                centre_rank = t.resources[0].rank
                break
        return (centre_rank is None, centre_rank or 0)

    depth = _subsystem_depth([m.subsystem_id for m in produced], dependencies or {})
    by_depth: dict[int, list[CandidateModule]] = {}
    for m in produced:
        by_depth.setdefault(depth.get(m.subsystem_id, 0), []).append(m)

    # Stage numbers are the ORDINAL position of each occupied depth, not the
    # raw longest-path depth. Those are sparse -- a real run produced depths
    # 0, 1, 117, 118, 119, 120, 121 -- and printing them would imply 116
    # missing stages that never existed. The ordering is identical; only the
    # label is dense.
    stages = [
        {"title": f"Stage {position} · by dependency",
         "modules": sorted(by_depth[d], key=reading_order_key)}
        for position, d in enumerate(sorted(by_depth), start=1)
    ]
    return {
        "basis": "subsystem",
        "layer_coverage": coverage,
        "layer_coverage_threshold": layer_coverage_threshold,
        "basis_reason": (
            f"Only {coverage:.1%} of files are reachable from an entry point, below the "
            f"{layer_coverage_threshold:.0%} threshold. For this repo that is a limit of "
            f"static import analysis rather than a fact about the code, so stages are "
            f"ordered by which subsystem depends on which instead of by distance from an "
            f"entry point. No stage is labelled Unreachable, because reachability is not "
            f"the basis being used."
        ),
        "stages": stages,
    }


def summarise(modules: list[CandidateModule], *, topic_strategy: str) -> dict:
    """Counters for the preview, including the distributions that decide whether
    this shape is right -- against the curated numbers, so the comparison does
    not require going and looking them up."""
    produced = [m for m in modules if m.skipped_reason is None]
    skipped = [m for m in modules if m.skipped_reason is not None]
    topics_per = sorted(len(m.topics) for m in produced)
    res_per_module = sorted(m.resource_count for m in produced)
    res_per_topic = sorted(len(t.resources) for m in produced for t in m.topics)

    def stat(xs):
        return {"min": xs[0], "median": int(median(xs)), "max": xs[-1]} if xs else None

    return {
        "topic_strategy": topic_strategy,
        "subsystems_considered": len(modules),
        "modules_produced": len(produced),
        "subsystems_skipped": len(skipped),
        "migration_files_excluded": sum(m.excluded_migration_count for m in modules),
        "topics_per_module": stat(topics_per),
        "resources_per_module": stat(res_per_module),
        "resources_per_topic": stat(res_per_topic),
        # Measured live from the curated tables, for comparison in one glance.
        "curated_reference": {
            "topics_per_module": {"min": 5, "median": 7, "max": 8},
            "resources_per_topic": {"min": 2, "median": 2, "max": 3},
            "resources_per_module": {"min": 10, "median": 14, "max": 17},
        },
    }
