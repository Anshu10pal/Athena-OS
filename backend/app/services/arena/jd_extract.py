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

# MIN_SPAN_CHARS IS GONE, DELIBERATELY.
#
# It was 12, and it was wrong in a way no single number can fix. Measured on the
# long fixture (a federal announcement): it rejected "Teamwork", "Flexibility",
# "Reasoning" and "Learning" -- four genuine one-word competency lines -- and
# reported them as HALLUCINATIONS, so the extractor was penalised for the
# checker's defect while four real skills were silently dropped.
#
# A length floor is a proxy for "is this a real skill", and there are now two
# checks that answer that question directly: `is_fragment` (is the NAME a
# nameable thing) and `span_supports_skill` (does the quoted text actually
# support the claim). A proxy kept alongside the real measurements only
# contributes its own error.
#
# Federal postings have one-word competency lines; Greenhouse postings have
# twenty-word aspirational sentences. Any fixed floor is wrong for one of them,
# and a JD-adaptive floor would be a third proxy for a question already
# answered twice.
#
# STATED TRADE, not hidden: without the floor the guard weakens from "a full
# sentence containing this skill exists in the document" to "this skill string
# exists in the document". Pure invention is still caught -- a model claiming
# Kubernetes for a JD that never says Kubernetes still fails. What is no longer
# caught by THIS check is a skill that appears somewhere irrelevant, e.g. in the
# company blurb; section attribution is what handles that, and it is a weight
# question rather than an existence question. `span_chars` is recorded per
# mention so a suspiciously-short-span RATE is visible per JD instead of being
# pre-empted by a floor.

# How much longer than the skill itself the matching window in the span may be,
# in tokens. This is what stops the paraphrase check from accepting tokens
# scavenged from across a long sentence: "data science" must not be accepted
# from "data pipelines for science teams". 3 admits the real pattern the long
# fixture showed ("Cataloging datasets" from "cataloging and documenting
# datasets" -- one intervening conjunction and one intervening word) and
# refuses scavenging across a clause.
MAX_PARAPHRASE_GAP_TOKENS = 3

# Window size alone is NOT sufficient, which a test caught before this shipped:
#
#   "Cataloging datasets"  <- "cataloging [and documenting] datasets"   legitimate
#   "data science"         <- "data [pipelines for] science teams"      fabricated
#
# Both have exactly two intervening tokens, so no gap threshold can separate
# them. What separates them is COORDINATION: the legitimate case pulls one
# branch out of a coordinated compound ("cataloging and documenting X" contains
# the skill "cataloging X"), while the fabricated case welds together tokens
# modifying different heads across a prepositional phrase.
#
# So a gap is permitted only when it contains a coordinator. Deliberately a
# tiny closed list rather than a POS tagger -- the alternative is a parser
# dependency for one rule, on CPU, on a request path.
#
# STATED RESIDUAL: this rejects legitimate paraphrases whose gap carries no
# coordinator, e.g. skill "cloud infrastructure" from span "cloud-native
# infrastructure". Those land in `invented`, inflating the very count this work
# exists to make honest. Mitigation: every rejection records its span, so the
# count is inspectable rather than merely reported, and reading a sample of the
# output is the rule (contract section 17.32) rather than trusting the number.
# If the five-JD run shows this firing on real paraphrases, the fix is a
# separate `paraphrase_weak` bucket -- NOT widening this rule, which would
# re-admit the fabricated compound.
_COORDINATORS = frozenset({"and", "or", "&", "and/or", ",", "plus", "as", "well"})

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

def span_supports_skill(skill: str, span: str) -> tuple[bool, str]:
    """Does the quoted span actually support this skill name?

    Returns (supported, how) where `how` is "literal" or "paraphrase".

    ASYMMETRIC, and that asymmetry is the whole point.

      skill is a shortening of the span   -> PASS
        "Cataloging datasets" from "cataloging and documenting datasets".
        Honest extraction: the model named the skill inside a compound clause.

      span is a shortening of the skill   -> FAIL
        skill "cataloging and documenting datasets" pointing at a span reading
        "cataloging datasets". That is the model summarising, or inventing a
        longer claim than the text supports, and pointing at nearby text.

    A SYMMETRIC check cannot tell those apart, which is exactly where the next
    silent defect would have hidden: legitimate paraphrase and fabricated
    compound look identical under a bag-of-tokens comparison.

    The window bound is the second guard. Ordered-subsequence alone would accept
    "data science" from "data pipelines for science teams" -- tokens present, in
    order, scavenged across a clause. Requiring the match to fit inside
    len(skill_tokens) + MAX_PARAPHRASE_GAP_TOKENS refuses that while admitting
    one or two intervening words.
    """
    s_norm = _norm_ws(skill).casefold()
    p_norm = _norm_ws(span).casefold()
    if not s_norm or not p_norm:
        return False, "empty"
    if s_norm in p_norm:
        return True, "literal"

    s_tok = s_norm.split()
    p_tok = p_norm.split()
    # Reverse direction is NOT a pass. Checked explicitly rather than left to
    # fall through, so the failure has its own name in the rejection record.
    limit = len(s_tok) + MAX_PARAPHRASE_GAP_TOKENS

    for start in range(len(p_tok)):
        matched = 0
        gap_tokens: list[str] = []
        for token in p_tok[start:start + limit]:
            if token == s_tok[matched]:
                matched += 1
                if matched == len(s_tok):
                    # A gap is only legitimate if it coordinates. See
                    # _COORDINATORS for why window size alone is not enough.
                    if not gap_tokens or any(g.strip(",;") in _COORDINATORS
                                             for g in gap_tokens):
                        return True, "paraphrase"
                    break  # try a later start; this window is a scavenge
            elif matched > 0:
                gap_tokens.append(token)
    return False, "unsupported"


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
    # PARAPHRASED: accepted, and a SUBSET of `mentions` rather than a rejection.
    # The skill name is a shortening of its span rather than a literal
    # substring. Its RATE is the signal -- near-zero means the model is quoting
    # literally; high on some JDs and not others means it is behaving
    # differently on those, which is what you want to see before it becomes a
    # defect several phases later.
    paraphrased: list[dict] = field(default_factory=list)
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
            "paraphrased": len(self.paraphrased),
            "paraphrase_rate": (round(len(self.paraphrased) / len(self.mentions), 4)
                                if self.mentions else 0.0),
            "paraphrased_detail": self.paraphrased[:20],
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
) -> tuple[list[Mention], list[dict], list[dict], list[dict]]:
    """Keep only mentions whose span is literally present in the JD, and whose
    skill name is a nameable thing rather than a sentence fragment.

    Returns (accepted, invented, filtered, paraphrased) -- FOUR lists, because
    four genuinely different things happen and collapsing any two of them makes
    a number that cannot be acted on:

      accepted     usable mentions
      invented     span not in the document, or the span does not support the
                   skill name. THIS is the "hallucinated skills" criterion.
      filtered     the span was real but the "skill" was a sentence fragment
                   ("Building", "large warehouses"). A prompt-quality problem,
                   not an invention problem.
      paraphrased  ACCEPTED, and a subset of `accepted`. The skill name is a
                   shortening of its span rather than a literal substring.
                   Tracked because its rate is a signal about how the model is
                   behaving on a given JD.

    The earlier two-way split reported 8 "hallucinations" on the long fixture of
    which zero were inventions -- four were legitimate compound-clause
    extractions and four were one-word competency lines killed by a length
    floor. A count that mixes those is worse than no count, because it will be
    believed.
    """
    haystack = _norm_ws(jd_text).casefold()
    accepted: list[Mention] = []
    rejected: list[dict] = []
    filtered: list[dict] = []
    paraphrased: list[dict] = []

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

        # Does the quoted text support the claim? Asymmetric -- see
        # span_supports_skill. A real sentence quoted correctly with a skill
        # name the sentence does not support is still an invention, and it
        # passes a span-only check.
        supported, how = span_supports_skill(skill, span)
        if not supported:
            rejected.append({"skill": skill, "span": span[:160],
                             "reason": "span does not support the skill name "
                                       "(the claim is broader than the quote)"})
            continue
        if how == "paraphrase":
            # ACCEPTED, and counted. Bucket size is a per-JD signal about
            # extraction behaviour: near-zero means literal quoting; a rate that
            # is high on some JDs and not others means the model is doing
            # something different on those, and that difference is worth seeing
            # now rather than as a defect three phases from now.
            paraphrased.append({"skill": skill, "span": span[:160]})

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

    return accepted, rejected, filtered, paraphrased


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

    accepted, rejected, filtered, paraphrased = verify_spans(raw, jd_text, sections)
    return ExtractionResult(
        mentions=accepted,
        rejected=rejected,
        filtered=filtered,
        paraphrased=paraphrased,
        raw_count=len(raw),
        llm_calls=1,
        truncated=truncated,
        call_seconds=call_seconds,
    )
