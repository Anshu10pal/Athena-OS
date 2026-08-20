"""Phase 5: the card-quality filter.

A card answerable from the identifier alone is worthless however it was
generated. "What does `validate_password` do?" is not a question -- the name
is the answer, and a reader who has never opened the file scores full marks.
This filter was specified early in the project and never built; it applies to
BOTH card sources, which is why it lives here rather than inside the
deterministic generator.

The rule this implements: **a card fails if its correct option is
identifiable by lexical similarity to the question's subject alone.** Not
"shares a word" -- distractors drawn from the same subsystem legitimately
share words. It fails when the correct answer is the *most* similar option by
a clear margin, because then picking the most-similar option is a winning
strategy that requires no knowledge.

Deliberately not a model, and deliberately conservative: it rejects the shape
that is obviously guessable and leaves genuinely borderline cards in, because
the cost of dropping a good card is one fewer question and the cost of keeping
a guessable one is a quiz that measures nothing.
"""
import re

# How much more similar the correct answer may be than the best distractor
# before the card counts as name-guessable. 0.0 would reject any card whose
# answer is even marginally closest; 1.0 would never reject.
#
# 0.34 is chosen so that ONE shared distinctive token out of three decides it
# -- the observed failure mode is exactly that (`code-path-state.js` ->
# `lib/linter/code-path-analysis`), not a subtle gradient. Tuned against the
# real corpora rather than guessed: see tests/test_card_quality.py, which pins
# both a card this must reject and a card it must not.
MAX_SIMILARITY_MARGIN = 0.34

# Tokens that carry no discriminating information -- present in most paths in
# most repos, so overlap on them says nothing about whether a name gives the
# answer away.
_STOPWORDS = frozenset({
    "src", "lib", "app", "index", "main", "js", "ts", "tsx", "jsx", "py",
    "test", "tests", "spec", "core", "utils", "util", "common", "shared",
    "helpers", "helper", "base", "the", "a", "of", "js", "mjs", "cjs",
})


def tokenize(text: str) -> set:
    """Path/identifier -> its distinctive lowercase word tokens.

    Splits on non-alphanumerics AND on camelCase boundaries, because
    `sourceCodeFixer` and `source-code-fixer` are the same name wearing
    different clothes and a filter that missed that would pass exactly the
    cards it exists to catch.
    """
    if not text:
        return set()
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
    parts = re.split(r"[^A-Za-z0-9]+", spaced)
    return {p.lower() for p in parts if p and p.lower() not in _STOPWORDS and len(p) > 1}


def _similarity(a: set, b: set) -> float:
    """Jaccard, on distinctive tokens. Symmetric and bounded, so the margin
    between two options is comparable regardless of how long the paths are --
    a raw shared-token count would make deep paths look more similar simply
    for having more segments."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def is_name_guessable(subject: str, answer: str, distractors: list) -> bool:
    """True if the correct answer can be picked by name similarity alone.

    `subject` is what the question is about (a path or identifier); `answer`
    is the correct option; `distractors` are the wrong ones. With no
    distractors the question is not multiple choice and this cannot apply --
    returns False rather than guessing, because a free-text card's guessability
    is a different question this filter does not answer.
    """
    if not distractors:
        return False
    subject_tokens = tokenize(subject)
    if not subject_tokens:
        return False

    answer_similarity = _similarity(subject_tokens, tokenize(answer))
    best_distractor = max(
        (_similarity(subject_tokens, tokenize(d)) for d in distractors), default=0.0
    )
    return (answer_similarity - best_distractor) > MAX_SIMILARITY_MARGIN


def reject_reason(subject: str, answer: str, distractors: list) -> str:
    """The rejection reason, or "" if the card passes.

    A string rather than a bool so a caller can REPORT why a card was dropped.
    A generator that silently produced fewer cards than expected would be
    indistinguishable from one that found fewer opportunities, and those need
    different responses.
    """
    if not answer:
        return "no answer"
    if answer in distractors:
        return "the answer also appears among the distractors"
    if len(set(distractors)) != len(distractors):
        return "duplicate distractors"
    if is_name_guessable(subject, answer, distractors):
        return "answerable from the identifier alone"
    return ""
