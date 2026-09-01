"""Deterministic JD segmentation: character range -> section label.

Why this exists at all, and why it runs BEFORE the LLM call: weight inference
has to be explainable, and "which section did this appear in" is the single
strongest importance signal a JD offers. Asking a model for it would produce a
label with no derivation; matching a header line against a phrase list produces
a label plus the header that caused it.

The labels are the five in config/arena_extraction.yaml:

    required | preferred | nice_to_have | responsibilities | boilerplate

plus `unknown` for text before any recognised header, which is the normal state
for the opening paragraph and is NOT treated as an error.

`boilerplate` earns its place. Without it, "competitive salary", "we are an
equal opportunity employer" and "free snacks" contribute skill mentions at
`unknown` weight, and the graph fills with nodes nobody will be interviewed on.
That failure is not hypothetical -- it is what any extractor does to the second
half of a modern JD, which is mostly not about the job.
"""
import re
from dataclasses import dataclass
from typing import Optional

from app.services.arena.config import load_config

# A header is a SHORT line. Long prose sentences that happen to contain the word
# "requirements" are not headers, and treating them as one silently relabels
# everything after them -- the expensive failure mode here, because it is
# invisible in the output and shifts every downstream weight.
MAX_HEADER_CHARS = 80

# How much text may follow a matched header phrase and still count as a header.
# "What you'll need to succeed" is a header; "Competitive salary and free
# snacks." is a sentence. 14 characters separates the two in practice.
HEADER_SUFFIX_SLACK = 14

# Leading bullet/number/decoration stripped before matching, so "## Requirements",
# "- Requirements:" and "3. REQUIREMENTS" all match the same phrase.
_DECORATION = re.compile(r"^[\s\#\*\-\u2022\u2023\u25e6\u2043\u2219\d\.\)\(\[\]:>]+")
_TRAILING = re.compile(r"[\s:\-\u2013\u2014]+$")


@dataclass(frozen=True)
class Section:
    """One labelled character range of the JD. `header` is the line that caused
    the label, kept so a weight can be explained by quoting the JD rather than
    by asserting a category."""

    label: str
    start: int
    end: int
    header: str


def _normalise_header_candidate(line: str) -> str:
    stripped = _DECORATION.sub("", line)
    stripped = _TRAILING.sub("", stripped)
    return " ".join(stripped.split()).casefold()


def _match_label(candidate: str, sections_config: dict) -> Optional[str]:
    """Which section label this header line names, or None.

    Longest phrase first, across ALL labels rather than within each. Otherwise
    "nice to have" is shadowed by "have" -shaped short phrases in another
    label's list, and label precedence becomes an accident of dict ordering.
    Real case this protects: "preferred qualifications" must win over
    "qualifications" (required), and it only does so if length decides.
    """
    if not candidate or len(candidate) > MAX_HEADER_CHARS:
        return None

    best: Optional[tuple[int, str]] = None
    for label, phrases in sections_config.items():
        for phrase in phrases or []:
            p = phrase.casefold()
            # Exact, or a prefix with only a SHORT remainder ("what you'll need
            # to succeed", "requirements (must have)").
            #
            # A bare `phrase in candidate` substring test was tried and is
            # WRONG -- it made "Competitive salary and free snacks." a
            # boilerplate header (via "salary") and "We are an equal opportunity
            # employer." another (via "equal opportunity"). That is precisely
            # the prose-as-header failure this module exists to prevent, and the
            # matcher had the hole. Caught by
            # test_boilerplate_is_labelled_so_it_can_be_down_weighted, which
            # counted two headers and found four.
            if candidate == p:
                score = len(p) + 1000  # exact beats any prefix match
            elif candidate.startswith(p) and len(candidate) - len(p) <= HEADER_SUFFIX_SLACK:
                score = len(p)
            else:
                continue
            if best is None or score > best[0]:
                best = (score, label)
    return best[1] if best else None


def segment(jd_text: str, config: Optional[dict] = None) -> list[Section]:
    """Split a JD into labelled ranges, in document order.

    Always returns at least one section covering the whole document. A JD with
    no recognisable headers -- which is common for short postings and for the
    deliberately-vague case -- yields exactly one `unknown` section, and that is
    a correct answer rather than a degraded one: everything in it then gets the
    `unknown` section base weight, which is deliberately mid-scale.
    """
    cfg = (config or load_config())["sections"]
    if not jd_text:
        return [Section(label="unknown", start=0, end=0, header="")]

    boundaries: list[tuple[int, int, str, str]] = []  # (header_start, section_start, label, header)
    offset = 0
    for raw_line in jd_text.splitlines(keepends=True):
        line = raw_line.rstrip("\r\n")
        label = _match_label(_normalise_header_candidate(line), cfg)
        if label:
            # The section starts at the HEADER, not after it. Two reasons: a
            # skill named inside the header line ("Required Python Skills")
            # belongs to that section, and starting after the header leaves the
            # header's own characters covered by no section at all -- so
            # `label_at` returned `unknown` for offsets inside the document,
            # which broke the full-coverage guarantee the callers rely on.
            boundaries.append((offset, offset, label, line.strip()))
        offset += len(raw_line)

    if not boundaries:
        return [Section(label="unknown", start=0, end=len(jd_text), header="")]

    out: list[Section] = []
    # Text before the first header. Kept as `unknown`, not folded into the first
    # labelled section -- the opening paragraph of a JD is usually company
    # framing, and attributing it to whatever header happens to come next would
    # inherit that header's weight.
    if boundaries[0][0] > 0:
        out.append(Section(label="unknown", start=0, end=boundaries[0][0], header=""))

    for i, (_h_start, section_start, label, header) in enumerate(boundaries):
        end = boundaries[i + 1][0] if i + 1 < len(boundaries) else len(jd_text)
        # A header immediately followed by the next header contributes a body of
        # just the header line. Emitted anyway: an empty `required` section is a
        # real fact about a badly-written JD, and dropping it would make the
        # section list disagree with the document.
        out.append(Section(label=label, start=section_start,
                           end=max(section_start, end), header=header))
    return out


def label_at(sections: list[Section], offset: int) -> str:
    """Section label covering a character offset, or `unknown`.

    Linear rather than bisecting: a JD has single-digit sections, and a bisect
    over a list this size buys nothing while adding an ordering precondition
    that a future caller could violate without noticing.
    """
    for section in sections:
        if section.start <= offset < section.end:
            return section.label
    return "unknown"


def header_at(sections: list[Section], offset: int) -> str:
    """The header line that gave `offset` its label -- the quotable evidence."""
    for section in sections:
        if section.start <= offset < section.end:
            return section.header
    return ""
