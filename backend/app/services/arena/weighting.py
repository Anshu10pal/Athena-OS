"""Deterministic weight and target-tier inference. Zero LLM calls.

The requirement is: "Document which signal contributed what -- I need to be
able to explain a weight to someone who asks." That rules out asking a model for
a number. An LLM-emitted weight has no derivation to offer; when someone asks
why Kafka scored 0.83, the only honest answer would be "the model said so",
which is not an answer.

So every weight here is arithmetic over five signals the JD actually provides,
and the per-signal contributions are persisted on the node
(arena_skill_nodes.weight_signals_json) rather than recomputed on demand. A
weight that can only be explained by re-running an extractor against a
since-changed prompt is not explainable -- that is the same argument
`generator_version` makes for items, applied to the weight itself.

The five signals, in the order they contribute:

  1  section_base   which JD section the mention sat in. The base; everything
                    else adjusts it.
  2  title_presence the skill (or an alias) appears in the job title. A title
                    is the single most deliberate sentence in a JD.
  3  repetition     distinct mention count, log-scaled -- one mention to two
                    says far more than nine to ten.
  4  position       earliest mention's position in the document.
  5  qualifier      the attached experience qualifier. "8+ years of Kafka" is a
                    different claim about importance than "exposure to Kafka".

Signals 1 and 5 read the same phrases from different angles and that is
intentional, not double-counting: the SECTION says how much the employer cares,
the QUALIFIER says how deep they need it. A "familiarity with Rust" under
"Required" is genuinely a required-but-shallow skill, and collapsing the two
signals would lose exactly that distinction -- which is the distinction the
interview needs, because it decides whether Rust is tested at MCQ or at voice.
"""
import math
import re
from dataclasses import dataclass, field
from typing import Optional

from app.services.arena.canonicalise import CanonicalNode, normalise
from app.services.arena.config import load_config

# How far before a mention to look for an experience qualifier. A qualifier
# governs the clause it introduces ("3+ years of Python, Go and Rust"), so the
# window looks BACKWARD from the mention and stops at a sentence boundary.
#
# 160 chars rather than "the whole bullet": a long bullet listing eight
# technologies after one qualifier should give all eight that qualifier, but a
# paragraph mentioning "expert" about something else 400 characters earlier
# should not leak. Sentence-boundary-bounded, so the number is a cap and not
# the actual reach in most cases.
QUALIFIER_LOOKBACK_CHARS = 160

_SENTENCE_END = re.compile(r"[.!?\n•;]")


@dataclass
class WeightBreakdown:
    """The explanation, and the thing that gets persisted.

    `contributions` sums to `raw`; `weight` is `raw` after the clamp. Both are
    kept because the clamp is itself a decision a reader may want to see -- a
    skill whose raw score was 1.4 and a skill whose raw score was 1.0 both come
    out at 1.0, and only this record distinguishes them.
    """

    weight: float
    raw: float
    clamped: bool
    contributions: dict[str, float] = field(default_factory=dict)
    # Human-readable evidence per signal, quoting the JD where it can.
    evidence: dict[str, str] = field(default_factory=dict)

    def as_json(self) -> dict:
        return {
            "weight": round(self.weight, 4),
            "raw": round(self.raw, 4),
            "clamped": self.clamped,
            "contributions": {k: round(v, 4) for k, v in self.contributions.items()},
            "evidence": self.evidence,
        }


def _strongest_section(node: CanonicalNode, section_base: dict) -> tuple[str, str]:
    """The highest-weight section any of this node's mentions appeared in.

    Highest, not first and not most common. A skill named once under "Required"
    and four times in the "About us" blurb is a required skill -- taking the
    mode would bury it under boilerplate, and taking the first would depend on
    whether the JD happens to lead with company framing, which most do.
    """
    best_label = "unknown"
    best_header = ""
    best_value = -1.0
    for mention in node.mentions:
        value = float(section_base.get(mention.section, section_base.get("unknown", 0.5)))
        if value > best_value:
            best_value, best_label, best_header = value, mention.section, mention.section_header
    return best_label, best_header


def find_qualifier(jd_text: str, offset: int, config: Optional[dict] = None) -> tuple[str, str]:
    """(tier, matched phrase) for the qualifier governing a mention, or
    (default_tier, "").

    Searches backward from the mention to the previous sentence boundary,
    capped at QUALIFIER_LOOKBACK_CHARS. Tiers are checked strongest-first and
    the LONGEST matching phrase within the winning tier is reported, so
    "5+ years of advanced" does not get reported as merely "advanced".
    """
    cfg = config or load_config()
    tiers = cfg["tiers"]
    default = tiers.get("default_tier", "working")

    start = max(0, offset - QUALIFIER_LOOKBACK_CHARS)
    window = jd_text[start:offset]
    # Trim to the last sentence boundary so a qualifier cannot leak across
    # sentences. Without this, "We are an expert-led team." three lines up marks
    # every skill below it as expert -- a plausible-looking, entirely wrong graph.
    boundaries = list(_SENTENCE_END.finditer(window))
    if boundaries:
        window = window[boundaries[-1].end():]
    window = window.casefold()

    for tier in tiers.get("order", []):
        matches = [p for p in (tiers.get("phrases", {}).get(tier) or [])
                   if p.casefold() in window]
        if matches:
            return tier, max(matches, key=len)
    return default, ""


def infer_tier(node: CanonicalNode, jd_text: str, config: Optional[dict] = None) -> tuple[str, str]:
    """Target tier for a node: the STRONGEST tier claimed by any of its mentions.

    Strongest rather than an average: if a JD says "familiarity with Kafka" in
    one place and "5+ years of Kafka" in another, the role needs 5 years. An
    average would produce a tier the JD never asked for, and the tier decides
    which modality the skill is tested at -- so a wrong average silently tests
    the wrong competency.
    """
    cfg = config or load_config()
    order = cfg["tiers"].get("order", ["expert", "proficient", "working", "awareness"])
    rank = {tier: i for i, tier in enumerate(order)}  # 0 = strongest

    best_tier = cfg["tiers"].get("default_tier", "working")
    best_phrase = ""
    best_rank = len(order)
    for mention in node.mentions:
        tier, phrase = find_qualifier(jd_text, mention.offset, cfg)
        if rank.get(tier, len(order)) < best_rank:
            best_rank, best_tier, best_phrase = rank.get(tier, len(order)), tier, phrase
    return best_tier, best_phrase


def _title_tokens(title: str, aliases: dict) -> set[str]:
    """Normalised tokens of the job title, expanded through the alias table.

    Expanded because a title of "Senior ML Engineer" should credit the node
    canonically named "Machine Learning". Without the expansion, signal 2
    silently never fires for any acronym title -- which is most of them.
    """
    tokens = set(normalise(title).split())
    for canonical, forms in (aliases or {}).items():
        canon_norm = normalise(canonical)
        all_forms = [canon_norm] + [normalise(f) for f in (forms or [])]
        if any(f and f in normalise(title) for f in all_forms):
            tokens.update(canon_norm.split())
    return {t for t in tokens if t}


def compute_weight(
    node: CanonicalNode,
    jd_text: str,
    title: str,
    config: Optional[dict] = None,
) -> WeightBreakdown:
    """The weight, plus the explanation for it."""
    cfg = config or load_config()
    w = cfg["weighting"]
    aliases = cfg["canonicalisation"].get("aliases", {})

    contributions: dict[str, float] = {}
    evidence: dict[str, str] = {}

    # --- signal 1: section base
    section_base = w["section_base"]
    label, header = _strongest_section(node, section_base)
    base = float(section_base.get(label, section_base.get("unknown", 0.5)))
    contributions["section_base"] = base
    evidence["section_base"] = (
        f"strongest section: {label}" + (f' (under "{header}")' if header else " (no header)")
    )

    # --- signal 2: presence in the job title
    title_toks = _title_tokens(title, aliases)
    node_toks = set(normalise(node.canonical_name).split())
    in_title = bool(node_toks) and node_toks.issubset(title_toks)
    bonus = float(w["title_presence_bonus"]) if in_title else 0.0
    contributions["title_presence"] = bonus
    evidence["title_presence"] = (
        f'named in the job title "{title}"' if in_title else "not in the job title"
    )

    # --- signal 3: repetition, log2-scaled and capped
    distinct = len({(m.offset, m.surface) for m in node.mentions})
    rep = min(
        float(w["repetition_bonus_cap"]),
        float(w["repetition_bonus_per_log2"]) * math.log2(max(1, distinct)),
    )
    contributions["repetition"] = rep
    evidence["repetition"] = f"{distinct} distinct mention(s)"

    # --- signal 4: position of the earliest mention
    earliest = min((m.offset for m in node.mentions), default=0)
    doc_len = max(1, len(jd_text))
    remaining = 1.0 - (earliest / doc_len)
    pos = float(w["position_bonus_max"]) * remaining
    contributions["position"] = pos
    evidence["position"] = (
        f"first mentioned {round(100 * earliest / doc_len)}% through the document"
    )

    # --- signal 5: experience qualifier
    tier, phrase = infer_tier(node, jd_text, cfg)
    qual = float(w["qualifier_bonus"].get(tier, 0.0))
    contributions["qualifier"] = qual
    evidence["qualifier"] = (
        f'tier {tier} from "{phrase}"' if phrase else f"tier {tier} (no qualifier found)"
    )

    raw = sum(contributions.values())
    lo, hi = float(w["min_weight"]), float(w["max_weight"])
    weight = max(lo, min(hi, raw))
    return WeightBreakdown(
        weight=weight,
        raw=raw,
        clamped=weight != raw,
        contributions=contributions,
        evidence=evidence,
    )


def explain(breakdown: WeightBreakdown) -> str:
    """One-line human explanation, for the UI tooltip and for the report.

    Built from the persisted breakdown rather than recomputed, so what a user
    reads is provably the same arithmetic that produced the stored number.
    """
    parts = [f"{k} {v:+.2f}" for k, v in breakdown.contributions.items() if v]
    tail = " (clamped)" if breakdown.clamped else ""
    return f"{breakdown.weight:.2f} = " + " ".join(parts) + tail
