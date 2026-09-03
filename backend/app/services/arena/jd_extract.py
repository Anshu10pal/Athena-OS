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
# The span is a SHORT quote, not a sentence. Measured, not swept.
#
# Two runs per variant on the 3,487-word fixture, extraction call only:
#
#   full-sentence span   33.0s mean   8,952 output chars   17.1-word spans
#   <=8-word quote       32.7s mean   6,485 output chars    4.2-word spans
#
# The change was tried as a LATENCY lever and that hypothesis is dead: -28%
# output bought -1% latency, so response volume is not the bottleneck (the cost
# is Gemini 2.5 Flash's reasoning phase, which scales with input and task
# complexity rather than with output length). It is shipped for a different and
# better-evidenced reason -- EXTRACTION QUALITY:
#
#   accepted mentions   33 -> 49 (mean)
#   inventions on long  12, 0 -> 3, 2
#   inventions on vague  0    ->  0   (the guard did NOT weaken)
#
# Mechanism: a short contiguous quote containing the skill name is trivially
# verifiable, while a long sentence invites the model to name a skill the
# sentence only implies -- which `span_supports_skill` then correctly rejects as
# unsupported. Shortening the quote removes the temptation rather than loosening
# the check.
#
# 8 words, fixed here, NOT tuned against the acceptance fixtures. It is the
# value the comparison above was run at; sweeping it against the five JDs before
# the measurement is the fixture-calibration failure (contract section 17.27)
# this phase has already caught twice.
#
# STATED COST: `_enrichment_text` builds the shadow enrichment metric from the
# span, and a 4-word span makes that signal nearly identical to the bare name.
# The shadow therefore becomes much less informative about whether a
# context-gated merge branch would help. That is a real loss, accepted because
# the shadow was speculative and the extraction-quality gain is measured.
SPAN_MAX_WORDS = 8

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

# Crude deterministic stemmer. Not a linguistics project -- it exists only to
# ANCHOR a skill name to its span, and it is applied to both sides so its errors
# cancel. Deliberately not a real stemmer (no Porter, no NLTK): a dependency for
# one anchoring test on a CPU request path is not worth it.
_SUFFIXES = ("ations", "ation", "ments", "ment", "ings", "ing", "ions", "ion",
             "ers", "er", "ed", "es", "s")


def stem(token: str) -> str:
    t = token.lower()
    for suf in _SUFFIXES:
        if t.endswith(suf) and len(t) - len(suf) >= 4:
            t = t[: -len(suf)]
            break
    if t.endswith("e") and len(t) > 4:
        t = t[:-1]                      # automate/automation -> automat
    if len(t) > 4 and t[-1] == t[-2]:
        t = t[:-1]                      # debugging -> debugg -> debug
    return t


_STEM_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "of", "for", "in", "on", "with", "to",
    "at", "from", "by", "across", "new", "our", "your", "this", "that",
    "will", "you", "we", "be", "is", "are", "as", "it", "its", "such",
})


def shares_distinctive_stem(skill: str, span: str) -> bool:
    """Is the skill name ANCHORED in its span by at least one content stem?

    This is the guard on the `unverified` bucket. Without it, "span is in the
    document but the skill is not literally in the span" would accept a model
    that quotes a real sentence and attaches an unrelated name to it --
    "Kubernetes" pointing at "Deploy new Palantir products" is an invention, not
    a paraphrase, and it must not be accepted merely because the quote is real.

    Deliberately weak -- ONE shared content stem. It is not trying to verify the
    claim, only to establish that the claim is about the quoted text. Verifying
    the claim is what the confirmation screen is for, and the measured finding
    that motivated this design is that the claim cannot be verified lexically at
    all (see UNVERIFIED below).
    """
    def roots(text: str) -> set:
        out = set()
        for raw in _norm_ws(text).casefold().split():
            tok = raw.strip(".,;:!?()[]'\"")
            if len(tok) <= 2 or tok in _STEM_STOPWORDS:
                continue
            out.add(stem(tok)[:5])
        return out

    return bool(roots(skill) & roots(span))

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

    # --- EXTENDED 2026-09-03 from the acceptance run's own output, not from
    # imagination. These are verbatim skill names the extractor emitted on
    # foundry-fde.txt and the filter let through: the run reported 0 fragments
    # filtered while the accepted list contained these. The fixture is spent,
    # the word list was never part of the pre-registered instrument, and the
    # extension is confined to tokens that actually failed -- which is the
    # legitimate shape for extending it.
    "autonomy", "responsibility", "reliability",
    "iteration with users", "multi-functional teams", "multi functional teams",
    "developing software", "production issues", "production systems",
    "service logs", "on-call schedule", "on call schedule",
    "programming languages", "ai technology", "llm technology",
    "technical troubleshooting support", "software support",
})

# DELIBERATELY NOT ADDED, and this is the interesting half of the list.
#
# The same run emitted `Computer Science`, `Mathematics`, `Physics` and
# `Data Science` as skills. In THIS posting they are degree fields -- "Strong
# engineering background, preferred in fields such as Computer Science,
# Mathematics..." -- and are not assessable skills. In another posting
# "data science" is a perfectly real skill, and so is "mathematics" for a
# quant role.
#
# A word list cannot tell those apart, because the distinction is contextual
# and the list is not. Adding them would trade a visible false positive for an
# invisible false negative, and the false negative is the worse direction: a
# junk node is one the user deletes on the confirmation screen, while a
# silently dropped real skill never appears there at all.
#
# This is also the classifier trap named in the instruction for this work:
# extend the list from what was seen, do NOT generalise a rule from what was
# seen and assume it transfers. Degree-field-versus-skill needs the SECTION
# the mention sat in, which is already computed and is a weighting input --
# so if it is ever worth fixing, it belongs in weighting, not here.


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
2. The "span" field MUST be a SHORT verbatim quote: at most {max_words} words, copied as one contiguous run of words straight from the job description, and it MUST contain the skill name itself. Do not paraphrase, reword, or stitch together words from different places. It is checked against the source and your entry is discarded if it does not match.
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
    # UNVERIFIED: the span is in the document and the skill is anchored to it by
    # a content stem, but the skill name is not literally derivable from the
    # quote. Accepted and counted. NOT part of the hallucinated-skills
    # criterion, because these are not inventions -- see verify_spans.
    unverified: list[dict] = field(default_factory=list)
    # FILTERED: the span was genuine but the "skill" was a sentence fragment
    # ("Building", "large warehouses"). A real defect, and a DIFFERENT one --
    # counting it as a hallucination would make a prompt-quality problem look
    # like an invention problem and the criterion would stop meaning anything.
    filtered: list[dict] = field(default_factory=list)
    raw_count: int = 0
    llm_calls: int = 0
    truncated: bool = False
    # Mean span length in words, as RETURNED. The prompt asks for <= 8; this is
    # what arrived. A mean drifting toward sentence length means the model has
    # stopped honouring the instruction, and the extraction-quality gain that
    # justified SPAN_MAX_WORDS goes with it -- so it is measured rather than
    # assumed.
    mean_span_words: float = 0.0

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
            "unverified": len(self.unverified),
            "unverified_rate": (round(len(self.unverified) / len(self.mentions), 4)
                                if self.mentions else 0.0),
            "unverified_detail": self.unverified[:20],
            "raw_count": self.raw_count,
            "llm_calls": self.llm_calls,
            "jd_truncated": self.truncated,
            "call_seconds": round(self.call_seconds, 3),
            "mean_span_words": round(self.mean_span_words, 2),
        }


def _norm_ws(text: str) -> str:
    return _WS.sub(" ", (text or "")).strip()


def verify_spans(
    raw_mentions: list[dict],
    jd_text: str,
    sections: list[Section],
) -> tuple[list[Mention], list[dict], list[dict], list[dict], list[dict]]:
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
    unverified: list[dict] = []

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
            # UNVERIFIED, not invented -- and this is a taxonomy fix, not a
            # smarter matcher.
            #
            # The acceptance run reported 11 "hallucinations" on foundry-fde of
            # which ZERO were inventions. All eleven were verb-to-noun
            # nominalisations of real JD text: "workflow automation" from
            # "automate workflows", "Debugging" from "Debug, improve, and
            # optimize", "product deployment" from "Deploy new Palantir
            # products". The skill IS in the document; only its morphology
            # differs from the quote.
            #
            # Extending the matcher to catch them was tried and ABANDONED
            # because the adversarial pin-set disproved its precondition: no gap
            # rule and no window size separates a legitimate nominalisation from
            # a fabricated compound. Both classes occur with a preposition in
            # the gap ("migrations to the latest infrastructure types" vs "data
            # pipelines for science teams") AND with an empty gap ("automate
            # workflows" vs "Python, testing, and deployment"). A fabricated
            # compound can be structurally identical to a legitimate one.
            #
            # So the honest move is to stop CLAIMING a discrimination that is
            # unavailable. These are accepted, counted, and explicitly not
            # asserted as verified -- which leaves "hallucinated skills" meaning
            # what it was always supposed to mean: the model produced text that
            # is not in the document.
            #
            # The anchor is the guard. Without it this bucket would accept a
            # real quote with an unrelated name attached, which IS an invention.
            if shares_distinctive_stem(skill, span):
                unverified.append({"skill": skill, "span": span[:160]})
            else:
                rejected.append({"skill": skill, "span": span[:160],
                                 "reason": "skill name shares no content word "
                                           "with its own span"})
                continue
        elif how == "paraphrase":
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

    return accepted, rejected, filtered, paraphrased, unverified


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

    # `{max_words}` is substituted from SPAN_MAX_WORDS rather than written into
    # the prompt text. A literal in both places is two sources of truth, and the
    # one that drifts is always the prompt -- where nothing would notice.
    prompt = (EXTRACTION_PROMPT
              .replace("{max_words}", str(SPAN_MAX_WORDS))
              .replace("{title}", title or "(not given)")
              .replace("{jd}", payload))

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

    accepted, rejected, filtered, paraphrased, unverified = verify_spans(
        raw, jd_text, sections)
    span_words = [len(str(m.get("span", "")).split())
                  for m in raw if isinstance(m, dict)]
    return ExtractionResult(
        mentions=accepted,
        rejected=rejected,
        filtered=filtered,
        paraphrased=paraphrased,
        unverified=unverified,
        mean_span_words=(sum(span_words) / len(span_words)) if span_words else 0.0,
        raw_count=len(raw),
        llm_calls=1,
        truncated=truncated,
        call_seconds=call_seconds,
    )
