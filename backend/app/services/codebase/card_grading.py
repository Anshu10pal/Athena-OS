"""Phase 5: grading, dispatched on `card_source`.

The second half of the seam. A deterministic card grades by comparing against
a stored answer that was COMPUTED from the graph, so "correct" is a fact. An
LLM card would grade against a rubric, so "correct" is a judgement. Those are
different operations and the column says which applies -- the dispatch never
infers it from the question's shape, because a deterministic card that happens
to read like prose would be graded the wrong way the first time it occurred.

`grade_llm_card` exists and raises, for the same reason its generator does:
returning a default score would make "not built" look like "scored zero".
"""
from dataclasses import dataclass

from app.services.codebase.card_generation import SOURCE_DETERMINISTIC, SOURCE_LLM


@dataclass
class Grade:
    correct: bool
    # 0-100. A separate field from `correct` because a rubric-graded card can
    # be partially right, and collapsing that to a bool at grade time would
    # throw away the only thing a rubric adds.
    score: int
    # What the grade was based on, in the grader's own terms -- shown to the
    # learner, and the thing that makes a wrong grade reportable rather than
    # merely frustrating.
    rationale: str = ""


def _normalise(text: str) -> str:
    """Compare on trimmed, case-folded text.

    Options are rendered into a UI and come back as strings; a trailing space
    or a case change is not a wrong answer. Nothing more aggressive than this
    -- for a deterministic card the expected answer is one of the options the
    learner was shown, so fuzzy matching would only ever turn a genuinely
    wrong choice into a right one.
    """
    return " ".join((text or "").split()).casefold()


def grade_deterministic_card(card, response: str) -> Grade:
    expected = _normalise(getattr(card, "answer", ""))
    given = _normalise(response)
    if not expected:
        # A card with no stored answer cannot grade anything. Loud, because a
        # silent False would blame the learner for a defect in the card.
        raise ValueError(
            f"card {getattr(card, 'id', '?')} has no stored answer; it should "
            "never have been persisted"
        )
    correct = given == expected
    return Grade(
        correct=correct,
        score=100 if correct else 0,
        rationale=(getattr(card, "rationale", "") if correct
                   else f"The answer is {getattr(card, 'answer', '')}. "
                        f"{getattr(card, 'rationale', '')}".strip()),
    )


def grade_llm_card(card, response: str) -> Grade:
    """Rubric grading for explanation cards. NOT IMPLEMENTED.

    Raises rather than returning `Grade(correct=False, score=0)`: a default
    would silently mark every learner wrong on a card type nobody had built
    the grader for, which is worse than an error because it looks like data.
    """
    raise NotImplementedError(
        "Rubric grading for llm cards is a declared seam, not yet built. See "
        "card_generation.generate_llm_cards."
    )


GRADERS = {
    SOURCE_DETERMINISTIC: grade_deterministic_card,
    SOURCE_LLM: grade_llm_card,
}


def grade_card(card, response: str) -> Grade:
    """Grade one card by its OWN `card_source` -- never by inspecting the
    question, and never by a caller-supplied source that could disagree with
    the row."""
    source = getattr(card, "card_source", None)
    if source not in GRADERS:
        raise ValueError(
            f"card {getattr(card, 'id', '?')} has unknown card_source {source!r}; "
            f"known: {sorted(GRADERS)}"
        )
    return GRADERS[source](card, response)
