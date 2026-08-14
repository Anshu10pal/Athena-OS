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
the module level. **The topic level does not exist in the data.** Three
derivable candidates were measured for "how many groups does this produce per
subsystem", against a 3-8 target:

    grouping            eslint in band    superset in band
    parent directory    4/7  (57%)        19/119 (16%)
    2nd path segment    0/7  (0%)         5/119  (4%)
    prior_category      0/7  (0%)         4/119  (3%)

None is close, and the failure is not merely numerical: eslint's largest
subsystem (151 files) splits by parent directory into three groups of 149, 1 and
1. That is one directory with two strays, not three concepts.

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
TOPIC_STRATEGIES: dict[str, Callable[[str, Optional[str]], str]] = {
    "parent_directory": lambda path, cat: _parent_directory(path),
    "second_segment": lambda path, cat: _second_segment(path),
    "prior_category": _prior_category,
}
DEFAULT_TOPIC_STRATEGY = "parent_directory"


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

    def to_dict(self) -> dict:
        return {
            "slug": self.slug, "title": self.title, "order_index": self.order_index,
            "resource_count": len(self.resources),
            "resources": [r.to_dict() for r in self.resources],
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

    @property
    def resource_count(self) -> int:
        return sum(len(t.resources) for t in self.topics)

    def to_dict(self) -> dict:
        return {
            "slug": self.slug, "title": self.title, "kind": self.kind,
            "source": self.source, "summary": self.summary,
            "subsystem_id": self.subsystem_id, "repo_id": self.repo_id,
            "member_count": self.member_count,
            "topic_count": len(self.topics),
            "resource_count": self.resource_count,
            "topics": [t.to_dict() for t in self.topics],
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

    # Rank order first, so it survives into each topic's resource ordering.
    # Unranked files sort LAST: "unranked" is not "rank 0", and sorting them
    # first would put the least-known files at the top of the reading order.
    ranked = sorted(
        members,
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
            slug=slugify(f"{group_key}-{subsystem_id}-{t_index}"),
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
