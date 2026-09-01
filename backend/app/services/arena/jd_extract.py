"""Skill-mention extraction: the ONE generative call that reads the JD.

The model is asked for exactly one thing -- skill mentions, each paired with the
verbatim JD text it came from -- and nothing it returns is trusted without that
span being checked against the source document in Python.

THE SPAN IS THE HALLUCINATION GUARD
===================================
Acceptance criterion: "Hallucinated skills not in the JD: 0, hard fail >= 2 per
JD." A guard that asks the model to be careful is not a guard. Requiring a
verbatim span turns the claim into something checkable: `verify_spans` locates
each span in the JD by exact (case-insensitive, whitespace-normalised) match and
DROPS any mention whose span is not literally present. A model that invents
"Kubernetes" for a JD that never mentions it has to also invent a sentence
containing it, and that invention fails a string search.

The rejects are counted and reported, not silently discarded --
`ExtractionResult.rejected` is a per-JD number in the acceptance table. A
rejection count of zero and a rejection count of nine mean very different things
about how much to trust the run, and a pipeline that hid the difference would
report the same "0 hallucinations" either way.

Whitespace normalisation before matching, and why it is not a loophole: JD text
arrives with soft-wrapped lines and non-breaking spaces, and a model that
reproduces a span with a single space where the source had a newline is quoting
correctly. Normalising whitespace on both sides preserves every word and their
order, so the check still requires the words to exist in the document in that
sequence. Nothing weaker than that is applied -- no stemming, no fuzzy ratio,
no per-token matching.
"""
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Optional

from app.services.arena.canonicalise import Mention
from app.services.arena.config import load_config
from app.services.arena.jd_sections import Section, header_at, label_at

logger = logging.getLogger("athena.arena.extract")

# A span shorter than this cannot locate a mention usefully -- "Go" as a span
# matches half the document and tells us nothing about which sentence the skill
# came from, which is what the span is FOR (section attribution and enrichment).
MIN_SPAN_CHARS = 12

# Cap on mentions accepted from one response. A model that returns 400 "skills"
# for a 200-word JD has failed in a way that should not become 400 database rows
# and 400 embedding vectors on a request path.
MAX_MENTIONS = 80

_WS = re.compile(r"\s+")

# Deterministic fragment filter, behind the prompt rules rather than instead of
# them. A prompt is a request; this is the check. Caught live: "Building",
# "maintaining" and "large warehouses" were returned as skills, and the span
# check passed all three because the spans really are in the document.
#
# Bare gerunds and verbs that are not themselves skill names. "Testing" and
# "Monitoring" are deliberately NOT here -- they are real skill names.
_FRAGMENT_WORDS = frozenset({
    "building", "maintaining", "developing", "creating", "working",
    "using", "supporting", "managing", "ensuring", "delivering",
    "collaborating", "partnering", "driving", "owning", "leading",
    "experience", "years", "knowledge", "understanding", "familiarity",
    "ability", "skills", "background", "exposure", "plus", "bonus",
    "environment", "production", "team", "teams", "role", "opportunity",
    "warehouses", "scale", "production environment", "large warehouses",
})


def is_fragment(skill: str) -> bool:
    """True when a "skill" is a sentence fragment rather than a nameable thing.

    Conservative by design: it rejects the shapes that are obviously not skills
    and leaves anything borderline in. A dropped real skill costs one node the
    user must add by hand; a kept fragment becomes a parent group named
    "large warehouses", which is what happened.
    """
    text = " ".join((skill or "").split()).casefold().strip(" .,:;-")
    if not text or len(text) < 2:
        return True
    if text in _FRAGMENT_WORDS:
        return True
    tokens = text.split()
    # A single bare gerund/abstract noun. Multi-word names containing one are
    # fine ("continuous integration", "stakeholder management").
    if len(tokens) == 1 and tokens[0] in _FRAGMENT_WORDS:
        return True
    # Every token is a filler word -- "production environment", "large warehouses".
    if tokens and all(t in _FRAGMENT_WORDS for t in tokens):
        return True
    return False

EXTRACTION_PROMPT = """You are extracting the skills a candidate will be assessed on, from one job description.

Return every distinct skill, technology, tool, domain or competency the job description names. For EACH one, return the verbatim sentence or bullet it appears in, copied exactly from the job description.

Rules, in order of importance:
1. NEVER return a skill the job description does not name. Do not add skills that "usually go with" the ones present. Do not infer a tech stack.
2. The "span" field MUST be copied verbatim from the job description text. Do not paraphrase, summarise, correct or shorten it. It is checked against the source and your entry is discarded if it does not match.
3. Return the skill name as the job description words it, not a normalised form. If it says "RESTful services", return "RESTful services".
4. Skip benefits, salary, location, company history, and equal-opportunity boilerplate. They are not skills.
5. If the job description is vague and names few concrete skills, return the few it names. Returning fewer, accurate skills is correct. Padding the list is a failure.
6. Each "skill" must be a NAMEABLE capability, technology, tool or domain - something a person could be asked an interview question about. It must stand alone as a noun phrase.
   GOOD: "Python", "REST APIs", "Kubernetes", "data modelling", "stakeholder management"
   BAD: "Building", "maintaining", "experience", "large warehouses", "production environment", "a plus", "years"
   Never return a bare verb, a gerund on its own, or a fragment of a sentence. "Building and maintaining ETL pipelines" contains ONE skill: "ETL pipelines".
7. Return the smallest complete name for each skill. If a bullet names one skill in a long clause, return the skill, not the clause.

Respond with JSON only:
{"mentions": [{"skill": "...", "span": "...", "kind": "technical|domain|soft"}]}

Job title: {title}

Job description:
{jd}
"""


@dataclass
class ExtractionResult:
    mentions: list[Mention] = field(default_factory=list)
    # Wall time for the extraction call alone. Split out from the pipeline
    # total because the first latency fix was applied to the wrong call: the
    # naming call was moved to a faster provider on the assumption it was the
    # expensive one, and the total went UP. Per-call numbers or no numbers.
    call_seconds: float = 0.0
    # HALLUCINATIONS: the span was not in the JD, or the skill name was not
    # inside its own span. This is the number the acceptance criterion
    # ("hallucinated skills: 0, hard fail >= 2") is about.
    rejected: list[dict] = field(default_factory=list)
    # FILTERED: the span was genuine but the "skill" was a sentence fragment
    # ("Building", "large warehouses"). A real defect, and a DIFFERENT one --
    # counting it as a hallucination would make a prompt-quality problem look
    # like an invention problem and the criterion would stop meaning anything.
    filtered: list[dict] = field(default_factory=list)
    raw_count: int = 0
    llm_calls: int = 0
    truncated: bool = False

    def as_json(self) -> dict:
        return {
            "accepted": len(self.mentions),
            "rejected": len(self.rejected),
            "rejected_detail": self.rejected[:20],
            "filtered": len(self.filtered),
            "filtered_detail": self.filtered[:20],
            "raw_count": self.raw_count,
            "llm_calls": self.llm_calls,
            "jd_truncated": self.truncated,
            "call_seconds": round(self.call_seconds, 3),
        }


def _norm_ws(text: str) -> str:
    return _WS.sub(" ", (text or "")).strip()


def verify_spans(
    raw_mentions: list[dict],
    jd_text: str,
    sections: list[Section],
) -> tuple[list[Mention], list[dict]]:
    """Keep only mentions whose span is literally present in the JD, and whose
    skill name is a nameable thing rather than a sentence fragment.

    Returns (accepted, hallucinated, filtered) -- three lists, because the two
    failure modes are different and the acceptance criterion is about the first. Rejection reasons are recorded per item so a
    hard-fail count can be explained rather than merely reported -- "the model
    invented a sentence" and "the model returned an empty skill name" are both
    rejections and are not the same problem.
    """
    haystack = _norm_ws(jd_text).casefold()
    accepted: list[Mention] = []
    rejected: list[dict] = []
    filtered: list[dict] = []

    for item in raw_mentions[:MAX_MENTIONS]:
        if not isinstance(item, dict):
            rejected.append({"skill": None, "reason": "not an object"})
            continue
        skill = str(item.get("skill") or "").strip()
        span = str(item.get("span") or "").strip()

        if not skill:
            rejected.append({"skill": skill, "reason": "empty skill name"})
            continue
        if is_fragment(skill):
            filtered.append({"skill": skill, "reason": "not a nameable skill (fragment)"})
            continue
        if len(span) < MIN_SPAN_CHARS:
            rejected.append({"skill": skill, "span": span,
                             "reason": f"span shorter than {MIN_SPAN_CHARS} chars"})
            continue

        needle = _norm_ws(span).casefold()
        position = haystack.find(needle)
        if position < 0:
            # The hallucination case: the model produced a sentence that is not
            # in the document. Recorded with the span so the failure is
            # inspectable, which is what makes reading a sample of output
            # possible (contract section 17.32).
            rejected.append({"skill": skill, "span": span[:160],
                             "reason": "span not found in the job description"})
            continue

        # The skill name itself must also appear inside its own span. Catches the
        # subtler failure: a real sentence quoted correctly, with a skill name
        # attached that the sentence does not contain. That passes a
        # span-only check while still being an invention.
        if _norm_ws(skill).casefold() not in needle:
            rejected.append({"skill": skill, "span": span[:160],
                             "reason": "skill name not present within its own span"})
            continue

        # Offset in NORMALISED space maps only approximately back to the raw
        # document. Re-find the skill in the raw text to get a usable offset for
        # section attribution, falling back to the normalised position.
        raw_offset = jd_text.casefold().find(_norm_ws(skill).casefold())
        offset = raw_offset if raw_offset >= 0 else position

        accepted.append(Mention(
            surface=skill,
            span=_norm_ws(span),
            offset=offset,
            section=label_at(sections, offset),
            section_header=header_at(sections, offset),
        ))

    return accepted, rejected, filtered


def extract_mentions(
    jd_text: str,
    title: str,
    sections: list[Section],
    config: Optional[dict] = None,
) -> ExtractionResult:
    """One LLM call, then verification. Raises only if the call itself fails.

    A response the model returns with zero usable mentions is NOT an error -- it
    is the honest answer for a JD that names no concrete skills, and turning it
    into an exception would push the caller toward retrying until something came
    back, which is how a vague JD acquires invented skills.
    """
    from app.core.llm import chat_json

    cfg = config or load_config()
    max_chars = int(cfg["llm"]["max_jd_chars"])
    truncated = len(jd_text) > max_chars
    payload = jd_text[:max_chars]
    if truncated:
        # Marked in the prompt AND on the result. A silent truncation would make
        # a long-JD acceptance number incomparable to a short-JD one with
        # nothing indicating why.
        payload += "\n\n[job description truncated for length]"

    prompt = EXTRACTION_PROMPT.replace("{title}", title or "(not given)").replace(
        "{jd}", payload)

    call_started = time.perf_counter()
    response = chat_json(
        [{"role": "user", "content": prompt}],
        fast=bool(cfg["llm"]["use_fast_lane"]),
        retries=1,
    )
    call_seconds = time.perf_counter() - call_started
    raw = response.get("mentions")
    if not isinstance(raw, list):
        logger.warning("extraction response had no 'mentions' list; treating as empty")
        raw = []

    accepted, rejected, filtered = verify_spans(raw, jd_text, sections)
    return ExtractionResult(
        mentions=accepted,
        rejected=rejected,
        filtered=filtered,
        raw_count=len(raw),
        llm_calls=1,
        truncated=truncated,
        call_seconds=call_seconds,
    )
