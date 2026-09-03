"""LLM clustering: the PRE-REGISTERED escalation, fired by a measured failure.

WHY THIS EXISTS, AND WHY IT IS NOT A CHANGE OF MIND
===================================================
Phase A's design chose deterministic clustering on purpose: structure is decided
in Python and the model only names what Python grouped, so coverage is
explainable and reproducible. The escape hatch was pinned at the same time --
`clustering.min_coherent_parent_fraction` (0.80) with an explicit rule that
escalation to LLM clustering happens ONLY on failure of that gate, with the
failing numbers reported rather than the swap being made quietly.

The gate failed. Measured 2026-09-03 across five fixtures, three runs each:

    fixture       coherence (median)     parents    max children
    short              50%                 5             4
    foundry-fde        50%                 6             7
    vague              50%                 6             7
    target-role        50%                 7             8
    long               43%                 7             8

Five of five below the 80% bar, and `max children per parent` missing its 2-5
target on four of five. Both are outputs of the same component, so the
diagnosis localised to clustering rather than to extraction -- extraction closed
with 0 invented skills across all 15 runs and the vague-JD honest-degradation
criterion passed.

So this is the pre-registered response firing on its trigger, once. It is not a
second bite at the extractor.

WHAT THE MODEL IS AND IS NOT ALLOWED TO DO
==========================================
It groups and names. It does NOT get to change the skill set. Every name it
returns is checked against the canonicalised input list, and anything it
invented is dropped and counted. Anything it omitted is recovered into an
explicit `Unassigned` parent rather than silently lost, because "never lose a
skill the JD named" is an invariant this pipeline has held since Phase A began
and a clustering swap is not licence to break it.

Structural violations are NOT repaired. If the model returns ten parents or a
parent with nine children, that is reported as the criterion failure it is. A
repair pass here would be tuning the measurement instead of measuring the
component, and the whole acceptance protocol exists to make that impossible to
do quietly.

Coherence is computed exactly as before -- mean pairwise bare cosine among a
parent's children, same threshold, same embedding model. That is the point: the
number has to be comparable to the deterministic run's number, and it is only
comparable if the instrument is unchanged.
"""
import json
import logging
import time
from typing import Optional

import numpy as np

from app.services.arena.canonicalise import CanonicalNode, normalise
from app.services.arena.clustering import (ClusterResult, ParentCluster,
                                           _mean_pairwise, resolve_budget)
from app.services.arena.config import load_config
from app.services.codebase.embeddings import embed_texts

logger = logging.getLogger("athena.arena.llm_clustering")

# Name given to the parent that collects skills the model failed to assign.
# Deliberately visible rather than tidy: these skills came from the JD, they
# must not vanish, and a bucket named "Unassigned" tells the user on the
# confirmation screen that the grouping was incomplete. Its coherence is
# measured like any other parent's, which drags the coherent fraction down
# honestly rather than hiding an incomplete grouping behind a good number.
UNASSIGNED_PARENT = "Unassigned"


class MalformedClusteringResponse(RuntimeError):
    """The model's response could not be used as a grouping.

    Raised rather than repaired. The acceptance script reports the fixture as
    NOT MEASURED, which is a true statement; a loosened parser that salvaged
    something would report a number for a grouping the model did not actually
    produce. Pin-set-first discipline says the fix for a prompt-shape defect is
    a new pinned prompt, not an in-flight retry with weaker parsing.
    """


# =============================================================================
# THE PROMPT. Pinned by tests/test_arena_llm_clustering.py::TestPromptIsPinned.
#
# Pinned before any fixture was run under it, and NOT swept against fixture
# output. The five fixtures are visible to anyone designing this prompt now,
# which is a real limitation of this measurement and is recorded as such in
# docs/decisions.md -- a prompt tuned to what these five graphs looked like
# could not claim general validity, so it was not tuned to them at all.
#
# `{max_children}`, `{min_parents}` and `{max_parents}` are substituted from
# config rather than written in as literals, for the same reason
# SPAN_MAX_WORDS is: a number living in both the prompt text and the config is
# two sources of truth, and the prompt is the copy that drifts because nothing
# imports it.
# =============================================================================
CLUSTERING_PROMPT = """You are organising a flat list of skills, extracted from one job description, into a two-level skill graph for a technical interview.

Job title: {title}

Skills (use these EXACT strings, and only these):
{skills}

Group them into parent categories.

Rules, in order of importance:
1. Use ONLY the skill strings listed above, copied exactly. Never invent a skill, never reword one, never split one into two.
2. Assign EVERY skill to exactly one parent. Do not leave any skill out and do not place any skill under two parents.
3. Produce between {min_parents} and {max_parents} parents.
4. Give each parent between 2 and {max_children} children. Prefer balanced parents over one large parent and several tiny ones.
5. A parent's name is what a hiring manager for this role would call that group: 2-4 words, concrete, no filler like "Other" or "Miscellaneous" or "General Skills".
6. Group by what an interviewer would test together in one conversation, not by surface word similarity. "Docker" and "Kubernetes" belong together because you would probe them in one deployment discussion, not because both are container words.
7. Give each parent a one-line rationale naming what its children have in common. If you cannot state that in one line, the group is wrong.

Respond with JSON only:
{"parents": [{"name": "...", "rationale": "...", "children": ["...", "..."]}]}
"""


def _build_prompt(nodes: list[CanonicalNode], title: str, cfg: dict) -> str:
    budget = resolve_budget(len(nodes), cfg)
    return (CLUSTERING_PROMPT
            .replace("{title}", title or "(not given)")
            .replace("{skills}", "\n".join(f"- {n.canonical_name}" for n in nodes))
            .replace("{min_parents}", str(int(budget["min_parents"])))
            .replace("{max_parents}", str(int(budget["max_parents"])))
            .replace("{max_children}", str(int(cfg["max_children_per_parent"]))))


def _resolve_assignments(
    raw_parents: list, nodes: list[CanonicalNode]
) -> tuple[list[tuple[str, str, list[int]]], list[str], list[int]]:
    """Map the model's child names back onto node INDICES.

    Returns (parents, invented_names, unassigned_indices).

    Matching is on `normalise`d names -- the same normalisation
    canonicalisation uses -- so a difference of case, plural or punctuation is
    not treated as an invention. Nothing weaker than that: the model was told to
    copy the strings exactly, and a fuzzy match here would let a reworded skill
    through as if it had been copied.
    """
    by_norm: dict[str, int] = {}
    for i, node in enumerate(nodes):
        by_norm.setdefault(normalise(node.canonical_name), i)

    parents: list[tuple[str, str, list[int]]] = []
    invented: list[str] = []
    claimed: set[int] = set()

    for entry in raw_parents:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        rationale = str(entry.get("rationale") or "").strip()
        children = entry.get("children")
        if not name or not isinstance(children, list):
            continue

        indices: list[int] = []
        for child in children:
            idx = by_norm.get(normalise(str(child)))
            if idx is None:
                # The model produced a skill that is not in the input list. It
                # is DROPPED, not renamed onto the nearest match: this component
                # is allowed to group skills, not to introduce them.
                invented.append(str(child))
                continue
            if idx in claimed:
                # Assigned twice. The first parent keeps it -- rule 2 said
                # exactly one, and silently duplicating a skill across parents
                # would inflate every per-parent count.
                continue
            claimed.add(idx)
            indices.append(idx)

        if indices:
            parents.append((name[:60], rationale[:200], indices))

    unassigned = [i for i in range(len(nodes)) if i not in claimed]
    return parents, invented, unassigned


def cluster_skills_llm(
    nodes: list[CanonicalNode],
    title: str,
    config: Optional[dict] = None,
) -> ClusterResult:
    """One LLM call: group and name. Coherence measured exactly as before.

    Replaces BOTH `cluster_skills` and `cluster_llm_names` from the
    deterministic path, so the call budget is unchanged at two per JD
    (extraction + clustering) rather than three.
    """
    from app.core.llm import chat_json

    cfg = config or load_config()
    clust_cfg = cfg["clustering"]
    budget = resolve_budget(len(nodes), cfg)
    result = ClusterResult(budget_applied=budget)

    if not nodes:
        return result
    if len(nodes) <= 2:
        # Below the smallest band a flat graph is the honest answer, and asking
        # a model to invent structure over two skills is how a graph acquires
        # groups the JD does not support. Same guard as the deterministic path.
        result.parents = [ParentCluster(name=n.canonical_name, child_indices=[i])
                          for i, n in enumerate(nodes)]
        return result

    prompt = _build_prompt(nodes, title, cfg)
    started = time.perf_counter()
    try:
        # fast=True -> Groq first. The payload is a skill list, not a document,
        # so this wants latency rather than context headroom -- the same
        # reasoning that put the deterministic path's naming call on the fast
        # lane.
        response = chat_json([{"role": "user", "content": prompt}], fast=True, retries=1)
    except Exception as exc:  # noqa: BLE001 -- re-raised as a typed failure
        raise MalformedClusteringResponse(
            f"clustering call failed: {type(exc).__name__}: {exc}") from exc
    result.naming_call_seconds = time.perf_counter() - started

    raw_parents = response.get("parents")
    if not isinstance(raw_parents, list) or not raw_parents:
        raise MalformedClusteringResponse(
            f"response carried no usable 'parents' list; keys={sorted(response)[:6]}")

    parents, invented, unassigned = _resolve_assignments(raw_parents, nodes)
    if not parents:
        raise MalformedClusteringResponse(
            "no parent in the response matched any input skill")

    if unassigned:
        # Recovered, never dropped. See UNASSIGNED_PARENT.
        parents.append((UNASSIGNED_PARENT,
                        "skills the model did not assign to any group",
                        unassigned))

    # ---- coherence, measured with the UNCHANGED instrument so the number is
    # comparable to the deterministic run's.
    texts = [n.canonical_name for n in nodes]
    vecs = embed_texts(texts)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    unit = vecs / norms
    sim = unit @ unit.T

    threshold = float(clust_cfg["coherence_threshold"])
    built: list[ParentCluster] = []
    for name, _rationale, indices in parents:
        coherence = _mean_pairwise(sim, indices)
        built.append(ParentCluster(
            name=name,
            child_indices=indices,
            coherence=coherence,
            coherent=(None if coherence is None else coherence >= threshold),
        ))

    # Structural violations are NOT repaired -- an oversized parent or an
    # out-of-band parent count is reported as the criterion failure it is.
    result.parents = built
    measured = [p for p in built if p.coherent is not None]
    result.n_parents_measured = len(measured)
    if measured:
        frac = sum(1 for p in measured if p.coherent) / len(measured)
        result.coherent_fraction = frac
        result.escalation_required = frac < float(clust_cfg["min_coherent_parent_fraction"])
    else:
        result.coherent_fraction = None
        result.escalation_required = False

    # Provenance for the acceptance table. `invented_assignments` is the
    # clustering analogue of the extractor's hallucination count and is
    # reported rather than merely guarded against.
    result.budget_applied = {
        **budget,
        "clusterer": "llm",
        "invented_assignments": len(invented),
        "invented_detail": invented[:10],
        "unassigned_recovered": len(unassigned),
        "n_parents_returned": len(raw_parents),
    }
    if invented:
        logger.warning("clustering invented %d skill name(s): %s",
                       len(invented), invented[:5])
    return result
