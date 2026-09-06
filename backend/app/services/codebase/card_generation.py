"""Phase 5: comprehension card generation, and the seam between its two
sources.

The seam is real, not promised. It is:

  * a `card_source` COLUMN on every row from the first one, while only
    "deterministic" occurs;
  * `GENERATORS`, a dispatch table both sources are registered in;
  * `generate_llm_cards`, which EXISTS and raises NotImplementedError, so
    wiring the LLM path later is filling a hole rather than cutting one;
  * `grading.grade_card`, which dispatches on the column rather than guessing
    from the question's shape.

The two sources answer different questions and the product needs both. A queue
of only deterministic cards is a geography quiz -- where things live, what
imports what. A queue of only LLM cards is expensive and, worse, unverifiable:
nothing can check its answers against a stored fact. Deterministic cards grade
against a value that was COMPUTED; LLM cards would grade against a rubric.

**Zero LLM calls happen here today.** The codebase agent's non-negotiable #5
still holds for everything this module actually does; `generate_llm_cards` is
a declared hole, and calling it fails loudly rather than silently returning
nothing.
"""
import zlib
from dataclasses import dataclass, field
from typing import Optional

from app.services.codebase import card_quality

SOURCE_DETERMINISTIC = "deterministic"
SOURCE_LLM = "llm"

# How many cards one module may contribute. A cap rather than "every card that
# applies": six templates across 122 modules would otherwise produce a queue
# nobody finishes, dominated by whichever template happens to fire most.
MAX_CARDS_PER_MODULE = 6

# Fill by rotating through templates rather than exhausting one at a time.
# Variety across templates beats coverage within one -- four different
# questions about a module teach more than four instances of "which does this
# import", and the rotation is what makes the cap produce a mix instead of a
# prefix.
PREFER_VARIETY = True


@dataclass
class Card:
    """One generated card, before it becomes a row. Pure data -- generation
    stays free of the DB so the templates can be tested on plain dicts."""

    template: str
    question: str
    answer: str
    options: list = field(default_factory=list)
    rationale: str = ""
    subject_path: Optional[str] = None
    card_source: str = SOURCE_DETERMINISTIC
    order_index: int = 0
    # What the QUALITY FILTER should treat as the question's subject, when that
    # differs from `subject_path`.
    #
    # These are two different things and conflating them was a real bug. For
    # "which of these does X import?" the stem names a file, and that file is
    # both the code link and the thing a guesser would pattern-match against.
    # For "within module M, which file is imported most?" the stem names the
    # MODULE -- there is no file identifier on screen to guess from -- yet
    # `subject_path` is set to the ANSWER so the card can link to it. Passing
    # that to the filter compared the answer against itself and rejected the
    # card whenever the answer's filename was distinctive, which is always.
    #
    # Measured cost of that confusion before it was fixed: 6 cards on
    # Athena-OS, 11 on eslint, 24 on Superset -- every one of them a legitimate
    # question, discarded for resembling itself.
    filter_subject: Optional[str] = None

    @property
    def distractors(self) -> list:
        return [o for o in self.options if o != self.answer]


def _shortest_distinct(paths: list, subject: str) -> list:
    """Trim paths to their last two segments where that stays unambiguous.

    Full paths make options long and, worse, make the shared prefix do the
    discriminating -- every option starting `backend/app/services/codebase/`
    turns the question into a suffix-reading exercise.
    """
    def tail(p: str) -> str:
        parts = p.split("/")
        return "/".join(parts[-2:]) if len(parts) > 1 else p

    tails = [tail(p) for p in paths]
    return tails if len(set(tails)) == len(tails) else list(paths)


def _stable_offset(seed: str, modulo: int) -> int:
    """A per-subject rotation offset that is identical across processes.

    `zlib.crc32`, not `hash()`: Python salts string hashing per process
    (PYTHONHASHSEED), so `hash()` would make card generation non-reproducible
    between runs -- which would silently break the conservation check's ability
    to compare a regeneration against its predecessor.
    """
    return zlib.crc32(seed.encode("utf-8")) % modulo if modulo else 0


def _pick_distractors(pool: list, exclude: set, count: int,
                      seed: str = "", like: str = "") -> list:
    """`count` PLAUSIBLE distractors from `pool`, deterministically.

    Two failure modes had to be designed out, and both were found by reading
    generated cards rather than by any test:

    1. **Repetition across cards.** Taking the first N of a sorted pool gave
       every card in a module the same three distractors -- on eslint,
       `['bin/eslint.js', 'conf/ecma-version.js', 'conf/globals.js']` under
       nearly every question. A learner simply learns which options are never
       the answer. Fixed by rotating the pool by a stable checksum of `seed`.

    2. **The odd one out.** Rotating alone drew three CONSECUTIVE paths, so a
       question whose answer was `lib/cli.js` offered three `rules/prefer-*.js`
       distractors and the answer stood out as the only option of a different
       kind. Fixed by `like`: distractors are drawn preferentially from paths
       resembling the ANSWER, so every option is the same sort of thing.

    Note the interaction with `card_quality`: making distractors resemble the
    answer also makes them resemble the subject where the answer does, which
    NARROWS the similarity margin and lets genuinely-hard cards through the
    filter that a lazy distractor set would have failed. The two mechanisms
    push the same way rather than fighting.

    KNOWN FLOOR, measured rather than assumed: the rotation can only vary the
    result while the candidate pool is LARGER than `count`. On a 4-file module
    the pool after excluding the subject and the answer is exactly 2, so every
    card in it necessarily shares one distractor set -- the very repetition
    this fixes, reappearing where no alternative exists. Checked on the
    smallest module of each repo: Athena-OS's 4-file module yields 3 cards over
    2 distinct sets (one set twice); eslint's and Superset's 3-file modules
    yield no multiple-choice cards at all, because the `len(distractors) < 2`
    guard skips them first.

    This is an information floor, not a defect to code around: a 4-file module
    contains no fourth file to offer. It is documented so the degenerate case
    is recognised as expected rather than re-diagnosed later as a regression,
    and such modules produce at most 3 cards anyway.

    Fully deterministic -- no RNG, and a checksum rather than `hash()`.
    """
    candidates = [p for p in pool if p not in exclude]
    if not candidates:
        return []

    if like:
        like_tokens = card_quality.tokenize(like)
        # Most-similar-to-the-answer first, ties broken by path so the order is
        # total and stable. Then take a WINDOW rather than the top slice, so
        # different subjects in the same module get different distractors.
        candidates.sort(
            key=lambda p: (-len(like_tokens & card_quality.tokenize(p)), p))
        window = candidates[:max(count * 4, count)]
    else:
        window = candidates

    start = _stable_offset(seed, len(window))
    rotated = window[start:] + window[:start]
    out = []
    for item in rotated:
        if item in out:
            continue
        out.append(item)
        if len(out) == count:
            break
    return out


# --------------------------------------------------------------------------
# Deterministic templates. Each takes a `facts` dict and returns Cards.
# Every answer is COMPUTED from a stored fact, never authored, so a card can
# be checked against the database rather than believed.
# --------------------------------------------------------------------------

def _t_which_does_it_import(facts: dict) -> list:
    """"Which of these does X import?" -- from resolved CodeImport edges."""
    cards = []
    for path, imported in sorted(facts.get("imports_by_path", {}).items()):
        if not imported:
            continue
        answer = sorted(imported)[0]
        pool = [p for p in facts["module_paths"] if p not in imported and p != path]
        distractors = _pick_distractors(pool, {answer, path}, 3, seed=path, like=answer)
        if len(distractors) < 2:
            continue
        options = _shortest_distinct([answer] + distractors, path)
        cards.append(Card(
            template="which_does_it_import",
            question=f"Which of these does `{path}` import?",
            answer=options[0],
            options=sorted(options),
            rationale=(f"`{path}` has a resolved import edge to `{answer}`; "
                       "the other options are files it does not import."),
            subject_path=path,
        ))
    return cards


def _t_who_imports_it(facts: dict) -> list:
    """"Which of these imports X?" -- the same edges read backwards, which is
    a genuinely different recall task from following them forwards."""
    cards = []
    for path, importers in sorted(facts.get("importers_by_path", {}).items()):
        if not importers:
            continue
        answer = sorted(importers)[0]
        pool = [p for p in facts["module_paths"] if p not in importers and p != path]
        distractors = _pick_distractors(pool, {answer, path}, 3, seed=path, like=answer)
        if len(distractors) < 2:
            continue
        options = _shortest_distinct([answer] + distractors, path)
        cards.append(Card(
            template="who_imports_it",
            question=f"Which of these imports `{path}`?",
            answer=options[0],
            options=sorted(options),
            rationale=f"`{answer}` has a resolved import edge to `{path}`.",
            subject_path=path,
        ))
    return cards


def _t_most_depended_on(facts: dict) -> list:
    """"Which file in this module is depended on most?" -- fan_in, the signal
    the ranker is built on, asked directly."""
    ranked = facts.get("fan_in_ranked") or []
    if len(ranked) < 4:
        return []
    answer, answer_fan_in = ranked[0]
    runner_up = ranked[1][1]
    if answer_fan_in <= runner_up:
        return []   # a tie has no single right answer; do not manufacture one
    options = _shortest_distinct([answer] + [p for p, _ in ranked[1:4]], "")
    return [Card(
        template="most_depended_on",
        question=(f"Within **{facts['module_title']}**, which file is imported "
                  "by the most other files?"),
        answer=options[0],
        options=sorted(options),
        rationale=(f"`{answer}` has fan-in {answer_fan_in}; the next highest "
                   f"among these is {runner_up}."),
        subject_path=answer,
        filter_subject=facts["module_title"],
    )]


def _t_closest_to_entry(facts: dict) -> list:
    """"Which is closest to an entry point?" -- BFS layer depth, which is what
    "where does execution reach this from" means concretely."""
    layered = [(p, d) for p, d in (facts.get("layer_by_path") or {}).items() if d is not None]
    if len(layered) < 4:
        return []
    layered.sort(key=lambda t: (t[1], t[0]))
    answer, answer_depth = layered[0]
    deeper = [p for p, d in layered[1:] if d > answer_depth]
    if len(deeper) < 2:
        return []
    options = _shortest_distinct([answer] + deeper[:3], "")
    return [Card(
        template="closest_to_entry",
        question=(f"Within **{facts['module_title']}**, which file is reached "
                  "in the fewest steps from an entry point?"),
        answer=options[0],
        options=sorted(options),
        rationale=(f"`{answer}` sits at layer {answer_depth}; the others are "
                   "deeper in the import graph."),
        subject_path=answer,
        filter_subject=facts["module_title"],
    )]


# REMOVED: _t_which_module_owns_it -- "Which module does X belong to?"
#
# Dropped after reading its output rather than its counts, having been the
# second-most productive template (135 cards on Superset, 24 on eslint). It has
# no useful middle:
#
#   * when the module's title IS a prefix of the subject path, the answer is
#     the subject's own directory and `card_quality` correctly kills the card
#     as answerable from the identifier alone;
#   * when it is NOT, the answer is a cluster LABEL rather than a location, and
#     the card teaches something false. The observed case: "Which module does
#     `bin/eslint.js` belong to?" -> "tests/lib/rules", because that is the
#     dominant-prefix label of the 413-member cluster it landed in. True about
#     the clustering; read as a claim about where the file lives, it is wrong.
#
# A card that misleads is worse than one that is merely guessable -- the
# guessable card teaches nothing, this one teaches an error. Reinstating it
# needs a module label that is representative of its members, which is the
# `dominant_prefix_label` problem on a heterogeneous cluster and not something
# a card template can paper over.


def _t_reading_order(facts: dict) -> list:
    """"Which of these would you read first?" -- reading rank, i.e. the whole
    point of the ranked list, asked as a question."""
    ranked = facts.get("rank_ordered") or []
    if len(ranked) < 4:
        return []
    answer = ranked[0]
    options = _shortest_distinct([answer] + ranked[1:4], "")
    return [Card(
        template="reading_order",
        question=(f"Starting on **{facts['module_title']}**, which of these "
                  "does the reading list put first?"),
        answer=options[0],
        options=sorted(options),
        rationale=(f"`{answer}` is the highest-ranked file of this module in "
                   "the repo-wide reading order."),
        subject_path=answer,
        filter_subject=facts["module_title"],
    )]


DETERMINISTIC_TEMPLATES = (
    _t_which_does_it_import,
    _t_who_imports_it,
    _t_most_depended_on,
    _t_closest_to_entry,
    _t_reading_order,
)


def generate_deterministic_cards(facts: dict, *, cap: int = MAX_CARDS_PER_MODULE) -> tuple:
    """Cards for one module from graph facts, filtered and capped.

    Returns `(cards, rejected)` where `rejected` is a list of
    (template, reason). The rejections are RETURNED rather than dropped: a
    generator that produced three cards because three opportunities existed
    and one that produced three because five were rejected as guessable are
    different situations needing different responses, and a bare count cannot
    tell them apart.
    """
    by_template: dict = {}
    rejected = []
    for template_fn in DETERMINISTIC_TEMPLATES:
        for card in template_fn(facts):
            reason = card_quality.reject_reason(
                card.filter_subject or card.subject_path
                or facts.get("module_title", ""),
                card.answer, card.distractors,
            )
            if reason:
                rejected.append((card.template, reason))
                continue
            by_template.setdefault(card.template, []).append(card)

    # Round-robin across templates: variety beats coverage, so the cap yields
    # a mix rather than the first template's output truncated.
    chosen = []
    if PREFER_VARIETY:
        depth = 0
        while len(chosen) < cap:
            added = False
            for template in sorted(by_template):
                bucket = by_template[template]
                if depth < len(bucket):
                    chosen.append(bucket[depth])
                    added = True
                    if len(chosen) == cap:
                        break
            if not added:
                break
            depth += 1
    else:
        for template in sorted(by_template):
            chosen.extend(by_template[template])
        chosen = chosen[:cap]

    for i, card in enumerate(chosen):
        card.order_index = i
    return chosen, rejected


def generate_llm_cards(facts: dict, *, cap: int = MAX_CARDS_PER_MODULE) -> tuple:
    """Explanation cards -- what this does, why it exists, what breaks if it
    changes. NOT IMPLEMENTED.

    This exists, with its real signature, so that adding the LLM source later
    is filling a declared hole rather than cutting a new one. It raises rather
    than returning `[]`: an empty list would make "the LLM source is not built"
    indistinguishable from "the LLM source found nothing to ask about", and the
    whole point of the seam is that those are different.

    Implementing this means explicitly lifting the codebase agent's
    non-negotiable #5 (zero LLM calls) for this path, which is a decision to
    take on its own and record -- not something to inherit by editing here.
    """
    raise NotImplementedError(
        "The llm card source is a declared seam, not yet built. Implementing it "
        "requires explicitly lifting the codebase agent's zero-LLM-calls "
        "non-negotiable for this path; see card_generation's module docstring."
    )


# The dispatch table. Both sources are registered from day one -- a caller
# selects by the same string the `card_source` column stores, so a row and the
# function that made it cannot drift apart.
GENERATORS = {
    SOURCE_DETERMINISTIC: generate_deterministic_cards,
    SOURCE_LLM: generate_llm_cards,
}


def generate_cards(facts: dict, *, card_source: str = SOURCE_DETERMINISTIC,
                   cap: int = MAX_CARDS_PER_MODULE) -> tuple:
    if card_source not in GENERATORS:
        raise ValueError(
            f"unknown card_source {card_source!r}; known: {sorted(GENERATORS)}")
    cards, rejected = GENERATORS[card_source](facts, cap=cap)
    for card in cards:
        card.card_source = card_source
    return cards, rejected
