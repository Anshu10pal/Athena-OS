"""Deterministic hierarchical clustering of canonical skills into parent nodes.

Structure is decided in Python; the LLM only NAMES what Python grouped. That
split is deliberate and is the same one the codebase agent makes in
subsystems.py: community detection chooses the clusters, nothing generative gets
to decide coverage. Letting a model pick the groups would make the graph
unexplainable and non-reproducible, and the whole point of the confirmation
screen is that a user can check it.

THE COHERENCE GATE, PRE-REGISTERED
==================================
A parent with >= 2 children is COHERENT when the mean pairwise bare cosine among
its children is >= `coherence_threshold` (0.64).

0.64 is not a guess. It is the measured SIBLING|UNRELATED separation point on
the same hand-labelled reference set that redesigned canonicalise.py:

    SIBLING   ("Docker"/"Kubernetes")     min 0.639
    UNRELATED ("Docker"/"PostgreSQL")     max 0.636

At 0.64: 92% of sibling pairs retained, 0% of unrelated pairs admitted. The
mechanism, which contract section 17.0b requires a prediction to name: skills
belonging under one parent sit above this line, skills from different parents
sit below it. Unlike the SAME|SIBLING boundary, this one genuinely separates,
which is why clustering gets a threshold and canonicalisation got a cascade.

Pass condition for the whole run: >= `min_coherent_parent_fraction` (0.80) of
parents coherent. Escalation to LLM clustering happens ONLY on failure, with
the failing numbers reported -- `ClusterResult.escalation_required` exists so
that decision is data rather than a judgement call made later, and 0.80 rather
than 1.00 because with 5-9 parents one mis-grouped skill would fail an entire
run. This tolerates one bad parent in five and fails at two.

`cluster_llm_names` is the ONLY generative call, and a failure in it degrades to
deterministic names rather than raising: a graph with dull parent names is
usable, and a graph that does not exist is not.
"""
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from sklearn.cluster import AgglomerativeClustering

from app.services.arena.canonicalise import CanonicalNode
from app.services.arena.config import load_config
from app.services.codebase.embeddings import embed_texts

logger = logging.getLogger("athena.arena.clustering")


@dataclass
class ParentCluster:
    name: str
    child_indices: list[int]
    # Mean pairwise cosine among children. None for a single-child cluster,
    # where the statistic does not exist -- NOT 0.0 and NOT 1.0. A number
    # standing in for "not applicable" is contract section 17.25's defect, and
    # it would silently drag the coherent fraction in whichever direction the
    # placeholder was chosen.
    coherence: Optional[float] = None
    coherent: Optional[bool] = None


@dataclass
class ClusterResult:
    parents: list[ParentCluster] = field(default_factory=list)
    coherent_fraction: Optional[float] = None
    escalation_required: bool = False
    n_parents_measured: int = 0
    budget_applied: dict = field(default_factory=dict)
    # Wall time for the naming call alone -- see jd_extract.ExtractionResult
    # for why per-call numbers exist here at all.
    naming_call_seconds: float = 0.0

    def as_json(self) -> dict:
        return {
            "n_parents": len(self.parents),
            "n_parents_measured": self.n_parents_measured,
            "coherent_fraction": (round(self.coherent_fraction, 4)
                                  if self.coherent_fraction is not None else None),
            "escalation_required": self.escalation_required,
            "naming_call_seconds": round(self.naming_call_seconds, 3),
            "budget_applied": self.budget_applied,
            "per_parent": [
                {
                    "name": p.name,
                    "n_children": len(p.child_indices),
                    "coherence": round(p.coherence, 4) if p.coherence is not None else None,
                    "coherent": p.coherent,
                }
                for p in self.parents
            ],
        }


def resolve_budget(n_mentions: int, config: Optional[dict] = None) -> dict:
    """The parent-count band a graph of this size is allowed to occupy.

    Keyed on post-canonicalisation node count, NOT word count. A 2,000-word JD
    that is 90% benefits boilerplate has little more to say than a 150-word one,
    and word count cannot tell the difference. This is the mechanism that lets a
    short JD honestly produce three parents and PASS, instead of being pushed
    into inventing seven.
    """
    cfg = config or load_config()
    for band in cfg["node_budget"]:
        if n_mentions <= int(band["max_mentions"]):
            return dict(band)
    return dict(cfg["node_budget"][-1])


def _mean_pairwise(sim: np.ndarray, members: list[int]) -> Optional[float]:
    if len(members) < 2:
        return None
    vals = [float(sim[a][b]) for i, a in enumerate(members) for b in members[i + 1:]]
    return float(np.mean(vals)) if vals else None


def cluster_skills(
    nodes: list[CanonicalNode],
    config: Optional[dict] = None,
) -> ClusterResult:
    """Group canonical skills into parents and measure the result.

    Names are placeholders here (`Group 1`, ...); `cluster_llm_names` replaces
    them. Kept separate so the structural decision is testable with no network
    at all, which is what makes the coherence numbers reproducible.
    """
    cfg = config or load_config()
    clust_cfg = cfg["clustering"]
    budget = resolve_budget(len(nodes), cfg)

    result = ClusterResult(budget_applied=budget)
    if not nodes:
        return result

    # Below the smallest band, a flat graph is the honest answer. Emitting
    # min_parents singleton parents here would be inventing structure the JD
    # does not contain -- the exact dishonest degradation the acceptance
    # criteria are designed to catch.
    if len(nodes) <= 2:
        result.parents = [ParentCluster(name=n.canonical_name, child_indices=[i])
                          for i, n in enumerate(nodes)]
        result.coherent_fraction = None
        return result

    texts = [n.canonical_name for n in nodes]
    vecs = embed_texts(texts)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    unit = vecs / norms
    sim = unit @ unit.T

    # Target parent count: the middle of the allowed band, bounded by how many
    # nodes there actually are. Mid-band rather than max: overshooting produces
    # singleton parents, which read as structure while carrying none.
    lo, hi = int(budget["min_parents"]), int(budget["max_parents"])
    target = max(1, min(len(nodes) - 1, (lo + hi) // 2))

    labels = AgglomerativeClustering(
        n_clusters=target,
        metric=clust_cfg.get("metric", "cosine"),
        linkage=clust_cfg.get("linkage", "average"),
    ).fit_predict(1.0 - sim if clust_cfg.get("metric") == "precomputed" else unit)

    grouped: dict[int, list[int]] = {}
    for idx, label in enumerate(labels):
        grouped.setdefault(int(label), []).append(idx)

    max_children = int(cfg["max_children_per_parent"])
    parents: list[ParentCluster] = []
    for _label, members in sorted(grouped.items()):
        # Hard structural cap. Split oversized clusters by similarity to the
        # cluster's own centroid rather than truncating: dropping children would
        # lose skills the JD actually named, which is the one thing this
        # pipeline must never do.
        chunks = [members]
        if len(members) > max_children:
            centroid = unit[members].mean(axis=0)
            ordered = sorted(members, key=lambda m: -float(unit[m] @ centroid))
            chunks = [ordered[i:i + max_children]
                      for i in range(0, len(ordered), max_children)]
        for chunk in chunks:
            coherence = _mean_pairwise(sim, chunk)
            parents.append(ParentCluster(
                name=f"Group {len(parents) + 1}",
                child_indices=chunk,
                coherence=coherence,
                coherent=(None if coherence is None
                          else coherence >= float(clust_cfg["coherence_threshold"])),
            ))

    measured = [p for p in parents if p.coherent is not None]
    result.parents = parents
    result.n_parents_measured = len(measured)
    if measured:
        frac = sum(1 for p in measured if p.coherent) / len(measured)
        result.coherent_fraction = frac
        result.escalation_required = frac < float(clust_cfg["min_coherent_parent_fraction"])
    else:
        # Every parent is a singleton, so coherence is undefined for the run.
        # NOT reported as 1.0 (which would look like a perfect score) and NOT as
        # an escalation trigger (there is nothing to escalate about).
        result.coherent_fraction = None
        result.escalation_required = False
    return result


def cluster_llm_names(
    result: ClusterResult,
    nodes: list[CanonicalNode],
    job_title: str,
) -> ClusterResult:
    """Name the clusters. The second and last LLM call in the pipeline.

    Structure is already fixed before this runs -- the model is shown the
    grouping and asked only for labels. It cannot move a skill, add one, or drop
    one, because nothing downstream reads anything from this response except the
    strings.

    Degrades to a deterministic name (the highest-weight child) on any failure.
    A graph with dull parent names is fully usable; a 500 on the JD-submission
    endpoint because a naming call timed out is not.
    """
    # Imported here rather than at module scope so the deterministic path, and
    # every test of it, never touches the LLM client or its config.
    from app.core.llm import chat_json

    if not result.parents:
        return result

    def fallback(cluster: ParentCluster) -> str:
        if not cluster.child_indices:
            return "Other"
        best = max(cluster.child_indices, key=lambda i: len(nodes[i].mentions))
        return nodes[best].canonical_name

    listing = "\n".join(
        f"{i + 1}. " + ", ".join(nodes[c].canonical_name for c in p.child_indices)
        for i, p in enumerate(result.parents)
    )
    prompt = (
        "You are labelling groups of skills extracted from a job description.\n"
        f'The role is: "{job_title}".\n\n'
        "For each numbered group below, return a short parent-category name of "
        "2-4 words that covers the skills in that group. Use the vocabulary a "
        "hiring manager for this role would use.\n\n"
        "Rules:\n"
        "- Do NOT move, add, remove or rename any skill. Name the group only.\n"
        "- Return exactly one name per group, keyed by the group number.\n"
        '- Respond as JSON: {"names": {"1": "...", "2": "..."}}\n\n'
        f"Groups:\n{listing}"
    )

    call_started = time.perf_counter()
    try:
        # fast=True -> Groq first, and this is the ONE call in the pipeline where
        # that is right. The two calls have opposite requirements:
        #
        #   extraction  large input (a whole JD), needs TPM headroom  -> Gemini
        #   naming      tiny input (a skill list), needs low latency  -> Groq
        #
        # Measured: the live smoke test came in at 15.6s with both calls on
        # Gemini, missing the pre-registered <15s target on a 54-word JD -- the
        # smallest input there is. Gemini 2.5 Flash reasons before answering,
        # which is worth paying for on extraction and pure overhead on a
        # request for six short labels. Groq's free tier is TPM-poor and
        # latency-rich, which is exactly the wrong way round for extraction and
        # exactly right here.
        response = chat_json(
            [{"role": "user", "content": prompt}], fast=True, retries=1
        )
        names = response.get("names") or {}
    except Exception:
        logger.warning("cluster naming failed; using deterministic names", exc_info=True)
        names = {}

    result.naming_call_seconds = time.perf_counter() - call_started
    for i, parent in enumerate(result.parents):
        proposed = str(names.get(str(i + 1), "") or "").strip()
        # Length guard: a model that returns a sentence instead of a label would
        # otherwise put a paragraph in a String(200) column and into the UI.
        parent.name = proposed if 0 < len(proposed) <= 60 else fallback(parent)
    return result
