"""Orchestration: JD text -> persisted, unconfirmed skill graph.

Idempotency key is (user_id, jd_hash, extractor_version), enforced by a UNIQUE
constraint rather than an application check -- a double-clicked submit button is
the realistic concurrent case and only the database can promise one graph.

  - user_id, because without it user B pasting user A's JD receives A's
    hand-edited, hand-confirmed graph.
  - extractor_version, because the prompt and the cascade will change. Keyed on
    jd_hash alone, the first graph built for a JD is served forever and a
    prompt improvement is invisible to every JD already stored.

jd_hash is taken over NORMALISED text plus the title, not the raw paste. Hashing
raw text means one stray newline from a different copy-paste regenerates the
graph and silently discards the user's edits -- the opposite of what idempotency
is for.
"""
import hashlib
import logging
import time
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ArenaJobTarget, ArenaMergeSuggestion, ArenaSkillNode
from app.services.arena import canonicalise as canon
from app.services.arena import clustering, jd_extract, jd_sections, weighting
from app.services.arena.config import extractor_version, load_config

logger = logging.getLogger("athena.arena.graph")

SOURCE_LLM = "llm_extraction"
SOURCE_PARENT = "cluster_parent"
SOURCE_USER = "user_added"


def jd_hash(title: str, jd_text: str) -> str:
    """sha256 over normalised title + JD.

    Normalisation is whitespace collapse and casefold only. Deliberately NOT
    punctuation-stripping: two JDs differing only in punctuation are plausibly
    two different postings, and over-normalising here would serve the wrong
    graph with no way for the user to force a rebuild.
    """
    payload = f"{' '.join((title or '').split()).casefold()}\n" \
              f"{' '.join((jd_text or '').split()).casefold()}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def find_existing(
    db: Session, user_id: int, title: str, jd_text: str
) -> Optional[ArenaJobTarget]:
    """The cached graph for this (user, JD, extractor), or None."""
    return db.execute(
        select(ArenaJobTarget).where(
            ArenaJobTarget.user_id == user_id,
            ArenaJobTarget.jd_hash == jd_hash(title, jd_text),
            ArenaJobTarget.extractor_version == extractor_version(),
        )
    ).scalar_one_or_none()


def build_graph(
    db: Session,
    user_id: int,
    title: str,
    jd_text: str,
    config: Optional[dict] = None,
) -> tuple[ArenaJobTarget, bool]:
    """Extract, weight, canonicalise, cluster and persist. Returns
    (job_target, was_cached).

    Nothing here sets `graph_confirmed_at`. A freshly built graph is
    unconfirmed by construction, and the confirmation gate is the only
    validation path this component has.
    """
    cfg = config or load_config()

    cached = find_existing(db, user_id, title, jd_text)
    if cached is not None:
        return cached, True

    started = time.perf_counter()
    sections = jd_sections.segment(jd_text, cfg)

    extraction = jd_extract.extract_mentions(jd_text, title, sections, cfg)
    nodes, suggestions = canon.canonicalise(extraction.mentions, cfg)
    cluster_result = clustering.cluster_skills(nodes, cfg)
    cluster_result = clustering.cluster_llm_names(cluster_result, nodes, title)

    llm_calls = extraction.llm_calls + 1  # extraction + naming
    budget = int(cfg["llm"]["max_calls_per_extraction"])
    if llm_calls > budget:
        # Loud, not logged-and-continued. Free-tier RPD is the scarce resource
        # and a call-count leak is invisible until the day the quota runs out
        # mid-demo.
        raise RuntimeError(
            f"extraction used {llm_calls} LLM calls, budget is {budget}. "
            "The pipeline is only permitted one extraction call and one naming call."
        )

    weights = [weighting.compute_weight(node, jd_text, title, cfg) for node in nodes]
    tiers = [weighting.infer_tier(node, jd_text, cfg) for node in nodes]

    elapsed = time.perf_counter() - started

    target = ArenaJobTarget(
        user_id=user_id,
        title=title,
        jd_text=jd_text,
        jd_hash=jd_hash(title, jd_text),
        extractor_version=extractor_version(),
        graph_confirmed_at=None,
        extraction_metadata_json={
            # Everything the acceptance table needs, captured at the moment it
            # was true. Recomputing these later means re-running a
            # since-changed extractor, which measures something else.
            "latency_seconds": round(elapsed, 3),
            "llm_calls": llm_calls,
            "extraction": extraction.as_json(),
            "clustering": cluster_result.as_json(),
            "canonicalisation": {
                "nodes_after": len(nodes),
                "mentions_before": len(extraction.mentions),
                "merge_methods": canon.method_histogram(nodes),
                "suggestions_in_review_band": len(suggestions),
                "thresholds": {
                    "enriched": cfg["canonicalisation"]["enriched_cosine_threshold"],
                    "bare": cfg["canonicalisation"]["bare_cosine_threshold"],
                    "review_band_low": cfg["canonicalisation"]["review_band_low"],
                },
            },
            "sections_found": sorted({s.label for s in sections}),
        },
    )
    db.add(target)
    db.flush()  # need target.id for the node rows

    # Parents first, then children, because a child needs its parent's id.
    child_to_parent: dict[int, int] = {}
    for order, parent in enumerate(cluster_result.parents):
        parent_children = parent.child_indices
        # A single-child cluster is stored FLAT -- the skill itself becomes a
        # parent rather than being wrapped in a synthetic one-child group. A
        # wrapper parent named after its only child is structure that reads as
        # information and carries none.
        if len(parent_children) == 1:
            continue
        row = ArenaSkillNode(
            job_target_id=target.id,
            parent_id=None,
            canonical_name=parent.name,
            # A parent's weight is the max of its children, not the mean. A
            # cluster containing one critical skill and three peripheral ones is
            # a critical cluster; averaging would bury the skill that matters
            # and mis-order the whole graph.
            jd_weight=max(weights[i].weight for i in parent_children),
            target_tier=max(
                (tiers[i][0] for i in parent_children),
                key=lambda t: -cfg["tiers"]["order"].index(t)
                if t in cfg["tiers"]["order"] else 0,
            ),
            weight_signals_json={
                "derivation": "max of children",
                "children": [nodes[i].canonical_name for i in parent_children],
                "coherence": parent.coherence,
                "coherent": parent.coherent,
            },
            surface_forms_json=[],
            merge_evidence_json=[],
            source_spans_json=[],
            extraction_source=SOURCE_PARENT,
            order_index=order,
        )
        db.add(row)
        db.flush()
        for i in parent_children:
            child_to_parent[i] = row.id

    for i, node in enumerate(nodes):
        db.add(ArenaSkillNode(
            job_target_id=target.id,
            parent_id=child_to_parent.get(i),
            canonical_name=node.canonical_name,
            jd_weight=weights[i].weight,
            target_tier=tiers[i][0],
            weight_signals_json=weights[i].as_json(),
            surface_forms_json=node.surface_forms,
            merge_evidence_json=node.merge_evidence,
            source_spans_json=[
                {"span": m.span, "offset": m.offset, "section": m.section}
                for m in node.mentions
            ],
            extraction_source=SOURCE_LLM,
            order_index=i,
        ))
    db.flush()

    # Review-band suggestions. Persisted as `pending`, which the UI renders as
    # NOT MERGED. Resolving the names to node ids after the nodes exist, because
    # the suggestion is about two rows and a suggestion pointing at nothing is
    # not reviewable.
    by_name = {
        row.canonical_name: row.id
        for row in db.execute(
            select(ArenaSkillNode).where(ArenaSkillNode.job_target_id == target.id)
        ).scalars()
    }
    for suggestion in suggestions:
        left_id, right_id = by_name.get(suggestion.left), by_name.get(suggestion.right)
        if left_id is None or right_id is None:
            continue
        db.add(ArenaMergeSuggestion(
            job_target_id=target.id,
            left_node_id=left_id,
            right_node_id=right_id,
            left_name=suggestion.left,
            right_name=suggestion.right,
            enriched_cosine=suggestion.enriched_cosine,
            bare_cosine=suggestion.bare_cosine,
            status="pending",
        ))

    db.commit()
    db.refresh(target)
    return target, False


def serialise_graph(db: Session, target: ArenaJobTarget) -> dict:
    """Wire format for the confirmation screen.

    Parents carry their children inline. `weight_explanation` is built from the
    PERSISTED breakdown rather than recomputed, so what the user reads is
    provably the arithmetic that produced the stored number.
    """
    rows = list(db.execute(
        select(ArenaSkillNode)
        .where(ArenaSkillNode.job_target_id == target.id)
        .order_by(ArenaSkillNode.order_index, ArenaSkillNode.id)
    ).scalars())

    suggestions = list(db.execute(
        select(ArenaMergeSuggestion)
        .where(ArenaMergeSuggestion.job_target_id == target.id)
        .order_by(ArenaMergeSuggestion.enriched_cosine.desc())
    ).scalars())

    def node_json(row: ArenaSkillNode) -> dict:
        signals = row.weight_signals_json or {}
        contributions = signals.get("contributions") or {}
        explanation = " ".join(
            f"{k} {v:+.2f}" for k, v in contributions.items() if v
        ) or signals.get("derivation", "")
        return {
            "id": row.id,
            "parent_id": row.parent_id,
            "canonical_name": row.canonical_name,
            "jd_weight": round(row.jd_weight, 3),
            "target_tier": row.target_tier,
            "surface_forms": row.surface_forms_json or [],
            "merge_evidence": row.merge_evidence_json or [],
            "source_spans": row.source_spans_json or [],
            "weight_signals": signals,
            "weight_explanation": explanation,
            "extraction_source": row.extraction_source,
            "user_edited": bool(row.user_edited),
        }

    by_parent: dict[Optional[int], list[dict]] = {}
    for row in rows:
        by_parent.setdefault(row.parent_id, []).append(node_json(row))

    parents = []
    for parent in by_parent.get(None, []):
        parent["children"] = by_parent.get(parent["id"], [])
        parents.append(parent)

    return {
        "id": target.id,
        "title": target.title,
        "jd_text": target.jd_text,
        "extractor_version": target.extractor_version,
        "graph_confirmed_at": (target.graph_confirmed_at.isoformat()
                               if target.graph_confirmed_at else None),
        "extraction_metadata": target.extraction_metadata_json or {},
        "parents": parents,
        # Default state is NOT MERGED. The UI must require an explicit action to
        # accept one; see the model docstring for why the asymmetry matters.
        "merge_suggestions": [
            {
                "id": s.id,
                "left_node_id": s.left_node_id,
                "right_node_id": s.right_node_id,
                "left_name": s.left_name,
                "right_name": s.right_name,
                "enriched_cosine": round(s.enriched_cosine, 4),
                "bare_cosine": round(s.bare_cosine, 4),
                "status": s.status,
            }
            for s in suggestions
        ],
    }
