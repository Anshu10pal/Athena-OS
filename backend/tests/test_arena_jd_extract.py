"""Span verification: the hallucination guard, and the four-way split.

WHY THIS FILE EXISTS
====================
The two-way split (accepted / rejected) reported 8 "hallucinations" on the long
fixture of which ZERO were inventions:

  - 4 were legitimate extractions from coordinated compounds ("Cataloging
    datasets" out of "cataloging and documenting datasets"), rejected because
    the skill was not a literal substring;
  - 4 were one-word competency lines ("Teamwork", "Flexibility", "Reasoning",
    "Learning") killed by a MIN_SPAN_CHARS floor of 12.

So the headline acceptance criterion was reporting the checker's defects as the
model's, and dropping eight real skills while doing it. These tests pin the
distinctions the four-way split now makes, because a count that mixes them is
worse than no count -- it will be believed.
"""
import pytest

from app.services.arena.jd_extract import (MAX_PARAPHRASE_GAP_TOKENS, is_fragment,
                                           span_supports_skill, verify_spans)
from app.services.arena.jd_sections import segment

JD = (
    "Data Scientist\n"
    "Requirements\n"
    "5+ years of strong Python in production.\n"
    "Responsible for cataloging and documenting datasets across the programme.\n"
    "Competencies\n"
    "Teamwork\n"
    "Flexibility\n"
    "We build data pipelines for science teams.\n"
)


def mention(skill, span):
    return {"skill": skill, "span": span, "kind": "technical"}


def run(items):
    return verify_spans(items, JD, segment(JD))


class TestAsymmetry:
    """The direction of the shortening is the whole signal.

    A symmetric bag-of-tokens comparison cannot tell legitimate paraphrase from
    a fabricated compound, which is precisely where the next silent defect
    would have hidden.
    """

    def test_skill_as_a_shortening_of_the_span_passes(self):
        ok, how = span_supports_skill("Cataloging datasets",
                                      "cataloging and documenting datasets")
        assert ok and how == "paraphrase"

    def test_span_as_a_shortening_of_the_skill_fails(self):
        # The model claiming more than the quote supports, and pointing at
        # nearby text. Under a symmetric check this is indistinguishable from
        # the case above.
        ok, how = span_supports_skill("cataloging and documenting datasets",
                                      "cataloging datasets")
        assert not ok and how == "unsupported"

    def test_a_broader_claim_than_the_quote_fails(self):
        ok, _ = span_supports_skill("machine learning operations", "machine learning")
        assert not ok


class TestScavengingIsRefused:
    """Ordered-subsequence alone is not enough. Both of these have exactly two
    intervening tokens, so no gap threshold separates them -- coordination
    does."""

    def test_coordinated_compound_is_accepted(self):
        ok, how = span_supports_skill("Cataloging datasets",
                                      "cataloging and documenting datasets")
        assert ok and how == "paraphrase"

    def test_tokens_welded_across_a_prepositional_phrase_are_refused(self):
        ok, how = span_supports_skill("data science",
                                      "data pipelines for science teams")
        assert not ok and how == "unsupported", (
            "a fabricated compound was accepted -- the coordination rule has "
            "been widened, which re-admits exactly this"
        )

    def test_the_gap_window_is_bounded(self):
        far = "data " + " ".join(["filler"] * (MAX_PARAPHRASE_GAP_TOKENS + 5)) + " and science"
        ok, _ = span_supports_skill("data science", far)
        assert not ok, "tokens matched across a window wider than the bound"


class TestNoLengthFloor:
    """The four one-word competency lines the old floor killed."""

    @pytest.mark.parametrize("word", ["Teamwork", "Flexibility", "Reasoning", "Learning"])
    def test_a_one_word_competency_line_is_accepted(self, word):
        jd = f"Competencies\n{word}\nRequirements\nPython.\n"
        accepted, invented, filtered, _para = verify_spans(
            [mention(word, word)], jd, segment(jd))
        assert len(accepted) == 1, (
            f"{word!r} was rejected: invented={invented} filtered={filtered}. "
            "A length floor is back, and it drops real skills while reporting "
            "them as hallucinations."
        )

    def test_a_literal_one_word_span_still_requires_the_word_to_be_in_the_jd(self):
        # Dropping the floor must NOT drop the guard. Pure invention still fails.
        jd = "Competencies\nTeamwork\n"
        accepted, invented, _f, _p = verify_spans(
            [mention("Kubernetes", "Kubernetes")], jd, segment(jd))
        assert accepted == [] and len(invented) == 1


class TestFourWaySplit:
    def test_invented_span_is_counted_as_invention(self):
        accepted, invented, filtered, para = run([
            mention("Kubernetes", "We orchestrate everything with Kubernetes at scale.")])
        assert accepted == [] and len(invented) == 1
        assert filtered == [] and para == []
        assert "not found" in invented[0]["reason"]

    def test_a_fragment_is_not_counted_as_an_invention(self):
        accepted, invented, filtered, _p = run([
            mention("Building", "Responsible for cataloging and documenting datasets "
                                "across the programme.")])
        assert accepted == []
        assert invented == [], (
            "a sentence fragment was counted as a hallucination -- that makes a "
            "prompt-quality problem look like an invention problem and the "
            "criterion stops meaning anything"
        )
        assert len(filtered) == 1

    def test_a_paraphrase_is_ACCEPTED_and_counted_separately(self):
        accepted, invented, filtered, para = run([
            mention("Cataloging datasets",
                    "Responsible for cataloging and documenting datasets across the programme.")])
        assert len(accepted) == 1, "a legitimate paraphrase was rejected"
        assert invented == [] and filtered == []
        assert len(para) == 1, (
            "the paraphrase was accepted but not counted -- its rate is a signal "
            "about model behaviour per JD and rolling it into `accepted` hides it"
        )

    def test_a_literal_match_is_not_counted_as_a_paraphrase(self):
        accepted, _i, _f, para = run([
            mention("Python", "5+ years of strong Python in production.")])
        assert len(accepted) == 1 and para == [], (
            "a literal quote was counted in the paraphrase bucket, which would "
            "make the rate meaningless"
        )

    def test_the_four_buckets_are_disjoint_and_total(self):
        items = [
            mention("Python", "5+ years of strong Python in production."),          # literal
            mention("Cataloging datasets",
                    "Responsible for cataloging and documenting datasets across the programme."),
            mention("Building", "5+ years of strong Python in production."),        # fragment
            mention("Rust", "We write everything in Rust."),                        # invented
        ]
        accepted, invented, filtered, para = run(items)
        # paraphrased is a SUBSET of accepted, so the total is accepted+invented+filtered.
        assert len(accepted) + len(invented) + len(filtered) == len(items)
        assert len(para) <= len(accepted)


class TestFragmentFilterUnchanged:
    """Ships as-is. The word list is extended only from real five-JD output,
    never tuned against the fixtures before the run."""

    @pytest.mark.parametrize("junk", ["Building", "maintaining", "large warehouses",
                                      "production environment", "experience"])
    def test_rejects_fragments(self, junk):
        assert is_fragment(junk)

    @pytest.mark.parametrize("real", ["Python", "REST APIs", "Testing", "Monitoring",
                                      "data modelling", "stakeholder management",
                                      "Teamwork", "ETL pipelines"])
    def test_keeps_real_skills(self, real):
        assert not is_fragment(real)


class TestSpanLengthInstructionMatchesTheConstant:
    """One source of truth for the quote length.

    A literal in the prompt text and a constant in code is two sources of truth,
    and the prompt is the one that drifts -- nothing imports it, so nothing
    notices. These pin the substitution instead of the number.
    """

    def test_the_prompt_has_no_hardcoded_word_count(self):
        from app.services.arena.jd_extract import EXTRACTION_PROMPT
        assert "{max_words}" in EXTRACTION_PROMPT, (
            "the span-length instruction stopped reading SPAN_MAX_WORDS"
        )

    def test_the_built_prompt_carries_the_constant(self, monkeypatch):
        from app.services.arena import jd_extract as m

        captured = {}

        def fake_chat_json(messages, fast=True, retries=2):
            captured["prompt"] = messages[-1]["content"]
            return {"mentions": []}

        monkeypatch.setattr("app.core.llm.chat_json", fake_chat_json)
        jd = "Requirements\nStrong Python experience is required for this role.\n"
        m.extract_mentions(jd, "Engineer", segment(jd))
        assert f"at most {m.SPAN_MAX_WORDS} words" in captured["prompt"]
        assert "{max_words}" not in captured["prompt"], "placeholder left unsubstituted"


class TestSpanLengthIsMonitored:
    def test_mean_span_words_is_reported(self, monkeypatch):
        from app.services.arena import jd_extract as m

        def fake_chat_json(messages, fast=True, retries=2):
            return {"mentions": [
                {"skill": "Python", "span": "Strong Python experience", "kind": "technical"},
                {"skill": "SQL", "span": "Advanced SQL required", "kind": "technical"},
            ]}

        monkeypatch.setattr("app.core.llm.chat_json", fake_chat_json)
        jd = "Requirements\nStrong Python experience. Advanced SQL required.\n"
        result = m.extract_mentions(jd, "Engineer", segment(jd))
        # The prompt asks for <= 8 words; this records what actually arrived, so
        # a model drifting back toward sentence-length spans is visible.
        assert result.mean_span_words == pytest.approx(3.0)
        assert result.as_json()["mean_span_words"] == pytest.approx(3.0)
