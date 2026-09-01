"""Canonicalisation: many JD surface forms -> one skill node.

WHY THIS IS A CASCADE AND NOT A THRESHOLD
=========================================

The Phase A design said "canonicalise via FastEmbed similarity; tune and report
the threshold you chose." Measured before implementing, that turned out not to
be achievable, so the design changed rather than the number being fudged.

A 15/12/10-pair reference set was hand-labelled into three bands, corresponding
to the three decisions this module and clustering.py have to make between them:

    SAME       "REST APIs" / "RESTful services"     must merge
    SIBLING    "Docker" / "Kubernetes"              must NOT merge, same parent
    UNRELATED  "Docker" / "PostgreSQL"              neither

bge-small-en-v1.5 cosine over the bare names:

    SAME       min 0.614  median 0.832  max 0.929
    SIBLING    min 0.639  median 0.723  max 0.835
    UNRELATED  min 0.418  median 0.588  max 0.636

SAME|SIBLING **overlaps**. SIBLING|UNRELATED **separates** (0.639 vs 0.636).
So the clustering boundary is a threshold problem and the canonicalisation
boundary is not. The sweep:

    thr    merge-recall   false-merge
    0.76      73%            25%
    0.82      60%             8%     <- vector_store.py's module threshold
    0.84      47%             0%
    0.86      27%             0%     <- shipped; see stage 3 below for why

There is no setting with usable recall at zero false merges. Worse, at the
existing 0.82 the module would BOTH leave 40% of duplicates standing AND merge
siblings -- against an acceptance criterion of zero surviving duplicates.

Two things rescued it, both found by looking at WHICH pairs failed rather than
at the aggregate:

1. WITHDRAWN. Context enrichment ("{name} -- {the JD sentence it came from}")
   appeared to move the zero-false-merge threshold from 0.84 to 0.76 and recall
   from 47% to 60%. That measurement was taken with a DIFFERENT sentence on each
   side of every pair, and it does not survive the realistic condition.

   Re-measured under TEMPLATE phrasing -- the same sentence shape on both sides,
   which is exactly how JD bullet lists are written ("Experience with Docker in
   a production environment." / "Experience with Kubernetes in a production
   environment.") -- enrichment inverts completely:

       thr    merge-recall   FALSE-MERGE
       0.76      93%            92%
       0.84      87%            42%
       0.88      73%             8%

   At the proposed 0.76 it merges PostgreSQL with MySQL (0.890), unit testing
   with integration testing (0.877), Python with Java (0.870) and AWS with
   Azure (0.867). The shared sentence template contributes a large common
   component to both vectors and swamps the difference between the skill names.

   This was caught by tests/test_arena_canonicalise.py::test_siblings_never_merge
   rather than by the calibration, because the calibration's context set was
   built to be helpful. Recorded rather than quietly dropped, per contract
   section 17.16: the first measurement was of the friendly case and was
   presented as the general one.

   Enrichment is therefore NOT a decision branch. It is still COMPUTED and
   PERSISTED as a shadow metric on every review-band suggestion, so whether a
   context-duplication-gated version would help can be evaluated on real JD
   data later -- measured in the shadow, deciding nothing.

2. The residual was a CLASS, not a gradient. Four of the six misses were
   acronym-or-short-form pairs with zero lexical overlap -- CI/CD, K8s, ML,
   Foundry. An acronym bears no semantic relation to its expansion in embedding
   space, so no threshold ever reaches these. They need a lookup, which is
   exactly what this repo's own content library already does
   (content/modules/*.yaml `aliases`, 52 strings across 15 entries, including
   "structured query language" for SQL and "version control" for Git). The
   authors hit this wall and solved it with a curated list. Stage 2 is that
   list.

A lexical-overlap gate was measured and REJECTED: OR-ing token Jaccard >= 0.20
with the embedding test raised recall to 67% but pushed false merges to 25%,
because "unit testing"/"integration testing" share "testing" and
"TypeScript"/"JavaScript" share "script". That is contract section 17.32's
odd-one-out failure in a new costume -- a shared token answering the question
without knowing it. Lexical overlap appears here ONLY as whole-token
containment (stage 2b), which is a different and much narrower claim.

THE FOUR STAGES
===============

    1  normalised exact match          free, zero false merges by construction
    2a alias table lookup              the acronym/short-form class
    2b whole-token containment         "Foundry" in "Palantir Foundry"
    3  bare cosine >= 0.86            context-free, 0% false merge measured
    4  review band [0.80, 0.86)       NOT merged; surfaced to the user

Stage 3 is bare-name cosine ONLY -- see point 1 above for why the enriched
branch was withdrawn. 0.86 rather than the 0.84 that first measured at zero
false merges: the highest SIBLING pair (Spark/Hadoop) sits at 0.835, so 0.84
leaves a 0.005 margin on a 12-pair sample, which contract section 17.0 says is
not a margin at all. 0.86 buys 0.025 and costs recall the review band absorbs.

The review band floor of 0.80 is chosen for PRECISION, not coverage: only one
sibling pair in the reference set reaches 0.80, so the band holds mostly real
duplicates and stays short enough to actually be read. A band that fills the
confirmation screen with noise is a band nobody reviews.

Stage 4 is the honest residual and it is a feature, not a shortfall. The
confirmation screen already exists and is this component's only validation
path; routing genuinely ambiguous pairs into it is strictly better than either
auto-merging them (destroys distinctions invisibly) or dropping them silently
(leaves duplicates with no signal).

Default state in the band is NOT MERGED, and merging takes an explicit action.
An unmerged duplicate is a redundant node the user can see and delete; a false
merge destroys a distinction the interview needed to test and nothing
downstream can notice it. Errors of omission are recoverable on the next
screen; errors of commission are not.

THE REFERENCE SET IS NOW SPENT FOR VALIDATION
=============================================
It was used to DESIGN this cascade, so it can no longer measure it -- reporting
"15/15 merged" against the set that chose the thresholds would be contract
section 17.27 exactly. It survives as the REGRESSION pin-set
(tests/test_arena_canonicalise.py): the pair that must merge and the pair that
must not, so a future prompt or config change that silently breaks
canonicalisation fails a test. Same object, different job. Validation is the
five held-out JDs.
"""
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from app.services.arena.config import load_config
from app.services.codebase.embeddings import embed_texts

logger = logging.getLogger("athena.arena.canonicalise")

# Merge methods, persisted per merge on arena_skill_nodes.merge_evidence_json.
# These are the MONITORING signal: if `enriched_cosine` or `bare_cosine` stops
# firing entirely across real JDs, the extraction sentences have changed shape
# and enrichment is no longer doing what it did on the reference set. That is
# not reconstructable after the fact, which is why the branch is recorded at the
# moment it decides rather than inferred later from the scores.
METHOD_EXACT = "exact"
METHOD_ALIAS = "alias"
METHOD_CONTAINMENT = "containment"
METHOD_ENRICHED = "enriched_cosine"
METHOD_BARE = "bare_cosine"
METHOD_USER = "user"

ALL_METHODS = (METHOD_EXACT, METHOD_ALIAS, METHOD_CONTAINMENT,
               METHOD_ENRICHED, METHOD_BARE, METHOD_USER)

_NON_ALNUM = re.compile(r"[^a-z0-9+#/\. ]+")
_WS = re.compile(r"\s+")


@dataclass
class Mention:
    """One skill mention as extracted, before canonicalisation."""

    surface: str
    span: str                 # verbatim JD text the mention was taken from
    offset: int               # char offset of `span` in the JD
    section: str = "unknown"
    section_header: str = ""


@dataclass
class CanonicalNode:
    """One skill after canonicalisation: a canonical name plus every surface
    form that collapsed into it, with the evidence for each collapse."""

    canonical_name: str
    mentions: list[Mention] = field(default_factory=list)
    # [{surface, method, score}] -- one entry per absorbed surface form.
    merge_evidence: list[dict] = field(default_factory=list)

    @property
    def surface_forms(self) -> list[str]:
        seen: list[str] = []
        for m in self.mentions:
            if m.surface not in seen:
                seen.append(m.surface)
        return seen


@dataclass
class MergeSuggestion:
    """A review-band pair. Deliberately carries BOTH branch scores even though
    only one put it in the band -- the pair of numbers is the diagnostic, either
    alone is not."""

    left: str
    right: str
    enriched_cosine: float
    bare_cosine: float


def normalise(name: str) -> str:
    """Casefold, strip decoration, collapse whitespace, singularise trivially.

    Keeps `+`, `#`, `/` and `.` because they are load-bearing in real skill
    names -- C++, C#, CI/CD, Node.js. An earlier draft stripped all
    non-alphanumerics and turned "C++" and "C#" into the same string "c",
    which would have merged two different languages on stage 1 with zero
    evidence recorded. Cheap to get wrong, expensive to notice.
    """
    lowered = _NON_ALNUM.sub(" ", (name or "").casefold())
    collapsed = _WS.sub(" ", lowered).strip()
    # Trailing plural only, and only on the final token. Not a stemmer: "APIs"
    # -> "api" is safe, whereas anything more aggressive starts merging
    # "testing" into "test" and then "unit testing" into "unit tests" into
    # "integration testing".
    # Singularise EVERY token, not just the last.
    #
    # The last-token-only version was a real defect, found by the live smoke
    # test: "Kubernetes" normalised to "kubernete" while "Kubernetes operations"
    # normalised to "kubernetes operation", so the SAME word compared unequal
    # depending on its position. Containment therefore did not fire on
    # Kubernetes / Kubernetes operations, and only a lucky bare-cosine hit
    # (>= 0.86) merged them at stage 3 instead. Exact matching was affected the
    # same way and would have failed silently.
    #
    # `isalpha()` guard per token: without it "node.js" becomes "node.j" and
    # "ci/cd"-style names get mangled -- the same family as the C++/C# collapse
    # above, and why that test exists.
    def _singularise(token: str) -> str:
        if (token.isalpha() and len(token) > 3
                and token.endswith("s") and not token.endswith("ss")):
            return token[:-1]
        return token

    return " ".join(_singularise(t) for t in collapsed.split(" "))


def _alias_index(aliases: dict) -> dict[str, str]:
    """{normalised surface form -> canonical name}, including each canonical
    name mapped to itself so a JD that uses the canonical spelling also hits
    stage 2a rather than falling through to the embedding stage."""
    index: dict[str, str] = {}
    for canonical, forms in (aliases or {}).items():
        index[normalise(canonical)] = canonical
        for form in forms or []:
            index[normalise(form)] = canonical
    return index


def _token_set(name: str) -> list[str]:
    return [t for t in normalise(name).split(" ") if t]


def _contains_whole_tokens(longer: str, shorter: str, min_chars: int) -> bool:
    """True when every token of `shorter` appears in `longer`, in order.

    Whole tokens and in order, so "Foundry" merges into "Palantir Foundry" but
    "Go" does not merge into "Google Cloud" and "R" does not merge into
    "React". `min_chars` is the second guard on exactly that: a two-character
    language name is a whole token and would otherwise pass.
    """
    short_tokens = _token_set(shorter)
    long_tokens = _token_set(longer)
    if not short_tokens or len(short_tokens) >= len(long_tokens):
        return False
    if len(normalise(shorter)) < min_chars:
        return False
    i = 0
    for token in long_tokens:
        if i < len(short_tokens) and token == short_tokens[i]:
            i += 1
    return i == len(short_tokens)


def _cosine_matrix(texts: list[str]) -> np.ndarray:
    """Pairwise cosine over one embedding batch.

    One `embed_texts` call for the whole set rather than per pair: the model is
    a process-level singleton but each call still pays ONNX session overhead,
    and this runs on the JD-submission critical path.
    """
    if len(texts) < 2:
        return np.ones((len(texts), len(texts)))
    vecs = embed_texts(texts)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    unit = vecs / norms
    return unit @ unit.T


def _enrichment_text(mention: Mention) -> str:
    """"{name} -- {the JD sentence it came from}".

    Falls back to the bare name when the span is empty or is just the skill name
    repeated, because enriching with nothing measurably HURTS: the reference set
    showed enrichment dropping a 0.876 bare pair to 0.714 when the two contexts
    diverged, and an empty context is the most divergent context there is.
    """
    span = (mention.span or "").strip()
    if not span or normalise(span) == normalise(mention.surface):
        return mention.surface
    return f"{mention.surface} -- {span}"


def canonicalise(
    mentions: list[Mention],
    config: Optional[dict] = None,
) -> tuple[list[CanonicalNode], list[MergeSuggestion]]:
    """Run the four-stage cascade.

    Returns (nodes, suggestions). Suggestions are pairs the cascade REFUSED to
    decide; they are not merged and the caller is expected to surface them.

    Order matters and is not arbitrary: the two zero-false-merge-by-
    construction stages run first, so the embedding stage only ever sees pairs
    that the cheap deterministic tests could not resolve. That keeps the
    embedding stage's measured false-merge rate meaningful -- it was measured on
    exactly such residual pairs.
    """
    cfg = config or load_config()
    canon_cfg = cfg["canonicalisation"]
    bare_thr = float(canon_cfg["bare_cosine_threshold"])
    band_low = float(canon_cfg["review_band_low"])
    min_chars = int(canon_cfg["containment_min_chars"])
    alias_index = _alias_index(canon_cfg.get("aliases", {}))

    if not mentions:
        return [], []

    # ---- stages 1 + 2a: exact and alias, both by lookup. Single pass, because
    # neither depends on any other mention -- they map a surface form onto a key.
    buckets: dict[str, CanonicalNode] = {}
    for mention in mentions:
        norm = normalise(mention.surface)
        alias_target = alias_index.get(norm)
        if alias_target:
            key = normalise(alias_target)
            display = alias_target
            method = METHOD_ALIAS if norm != normalise(alias_target) else METHOD_EXACT
        else:
            key = norm
            display = mention.surface
            method = METHOD_EXACT

        node = buckets.get(key)
        if node is None:
            buckets[key] = CanonicalNode(canonical_name=display, mentions=[mention])
        else:
            node.mentions.append(mention)
            if mention.surface not in node.surface_forms[:-1]:
                node.merge_evidence.append(
                    {"surface": mention.surface, "method": method, "score": 1.0}
                )

    nodes = list(buckets.values())

    # ---- stage 2b: whole-token containment. Longest name first, so
    # "Palantir Foundry" is the survivor and "Foundry" folds into it rather than
    # the other way round -- the longer name is the more specific one and is
    # what a user should see on the confirmation screen.
    nodes.sort(key=lambda n: (-len(normalise(n.canonical_name)), n.canonical_name))
    absorbed: set[int] = set()
    for i, keeper in enumerate(nodes):
        if i in absorbed:
            continue
        for j in range(i + 1, len(nodes)):
            if j in absorbed:
                continue
            if _contains_whole_tokens(keeper.canonical_name, nodes[j].canonical_name, min_chars):
                keeper.mentions.extend(nodes[j].mentions)
                keeper.merge_evidence.append({
                    "surface": nodes[j].canonical_name,
                    "method": METHOD_CONTAINMENT,
                    "score": 1.0,
                })
                keeper.merge_evidence.extend(nodes[j].merge_evidence)
                absorbed.add(j)
    nodes = [n for i, n in enumerate(nodes) if i not in absorbed]

    if len(nodes) < 2:
        return nodes, []

    # ---- stage 3: bare-name cosine only.
    #
    # The enriched branch was WITHDRAWN after measurement -- see point 1 of the
    # module docstring. Under template phrasing it reaches a 92% false-merge
    # rate, because a shared sentence shape contributes a large common component
    # to both vectors. It is still computed below as a SHADOW metric so a gated
    # version can be evaluated on real JDs; it decides nothing.
    bare_texts = [n.canonical_name for n in nodes]
    enriched_texts = [_enrichment_text(n.mentions[0]) for n in nodes]
    bare_sim = _cosine_matrix(bare_texts)
    enriched_sim = _cosine_matrix(enriched_texts)  # shadow only

    parent = list(range(len(nodes)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    suggestions: list[MergeSuggestion] = []
    merge_decisions: list[tuple[int, int, str, float]] = []

    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            e = float(enriched_sim[i][j])   # shadow metric, decides nothing
            b = float(bare_sim[i][j])
            if b >= bare_thr:
                merge_decisions.append((i, j, METHOD_BARE, b))
            elif band_low <= b < bare_thr:
                # Both scores persisted. The enriched value is the shadow: if a
                # future retune wants the gated enrichment branch back, this is
                # the only place real-JD evidence for it will exist.
                suggestions.append(MergeSuggestion(
                    left=nodes[i].canonical_name, right=nodes[j].canonical_name,
                    enriched_cosine=round(e, 4), bare_cosine=round(b, 4),
                ))

    # Union-find, applied after every pair is scored rather than during, so the
    # decisions do not depend on iteration order. Merging as we go would make
    # A~B~C transitivity dependent on which pair was visited first, and the
    # thresholds were not measured under that condition.
    for i, j, _method, _score in merge_decisions:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[max(ri, rj)] = min(ri, rj)

    groups: dict[int, list[int]] = {}
    for idx in range(len(nodes)):
        groups.setdefault(find(idx), []).append(idx)

    evidence_by_pair = {(i, j): (m, s) for i, j, m, s in merge_decisions}
    merged: list[CanonicalNode] = []
    for root, members in groups.items():
        # The keeper is the highest-weight-bearing name, approximated here by
        # most mentions then longest name -- the form the JD used most is the
        # form the user will recognise.
        members.sort(key=lambda idx: (-len(nodes[idx].mentions),
                                      -len(nodes[idx].canonical_name)))
        keeper = nodes[members[0]]
        for other_idx in members[1:]:
            other = nodes[other_idx]
            pair = (min(members[0], other_idx), max(members[0], other_idx))
            method, score = evidence_by_pair.get(pair, (METHOD_BARE, 0.0))
            keeper.mentions.extend(other.mentions)
            keeper.merge_evidence.append({
                "surface": other.canonical_name,
                "method": method,
                "score": round(float(score), 4),
            })
            keeper.merge_evidence.extend(other.merge_evidence)
        merged.append(keeper)

    # Suggestions naming a pair that a later transitive merge absorbed are
    # dropped: asking the user to merge two things already in one node is noise,
    # and noise on the confirmation screen is what stops it being read.
    surviving = {n.canonical_name for n in merged}
    suggestions = [s for s in suggestions
                   if s.left in surviving and s.right in surviving]

    merged.sort(key=lambda n: (-len(n.mentions), n.canonical_name))
    return merged, suggestions


def method_histogram(nodes: list[CanonicalNode]) -> dict[str, int]:
    """{merge method -> count} across a graph.

    The monitoring line for stage 3's OR. Reported per JD in the extraction
    metadata so a branch that stops firing is visible in the acceptance table
    rather than discovered later by reading rows.
    """
    counts = {m: 0 for m in ALL_METHODS}
    for node in nodes:
        for evidence in node.merge_evidence:
            method = evidence.get("method")
            if method in counts:
                counts[method] += 1
    return counts
