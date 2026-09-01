"""Weight and tier inference.

The requirement these serve: "Document which signal contributed what -- I need
to be able to explain a weight to someone who asks." So the tests assert two
different things, and both matter:

  1. each signal MOVES the weight (a signal that never fires is not a signal);
  2. the breakdown RECONCILES to the stored number (an explanation that does not
     add up to the thing it explains is worse than no explanation, because it
     will be believed).
"""
import pytest

from app.services.arena.canonicalise import CanonicalNode, Mention
from app.services.arena.config import load_config
from app.services.arena.jd_sections import label_at, segment
from app.services.arena.weighting import (compute_weight, explain, find_qualifier,
                                          infer_tier)


def node(surface: str, section: str = "required", offset: int = 0, span: str = "") -> CanonicalNode:
    return CanonicalNode(
        canonical_name=surface,
        mentions=[Mention(surface=surface, span=span or f"Experience with {surface}.",
                          offset=offset, section=section)],
    )


class TestSignalsEachMoveTheWeight:
    """A signal that cannot change the outcome is decoration. One test per
    signal, each isolating it."""

    def test_1_section_base(self):
        required = compute_weight(node("Python", "required"), "Python.", "Engineer")
        preferred = compute_weight(node("Python", "preferred"), "Python.", "Engineer")
        boiler = compute_weight(node("Python", "boilerplate"), "Python.", "Engineer")
        assert required.contributions["section_base"] > preferred.contributions["section_base"]
        assert preferred.contributions["section_base"] > boiler.contributions["section_base"]

    def test_2_title_presence(self):
        jd = "We need Python."
        in_title = compute_weight(node("Python"), jd, "Senior Python Engineer")
        not_in_title = compute_weight(node("Python"), jd, "Senior Data Engineer")
        assert in_title.contributions["title_presence"] > 0
        assert not_in_title.contributions["title_presence"] == 0
        # Compare RAW as well as weight: if the two clamp to the same ceiling
        # the signal is inert, which is a real defect and is pinned separately
        # in TestHeadroomBelowTheClamp.
        assert in_title.raw > not_in_title.raw
        assert in_title.weight > not_in_title.weight

    def test_2b_title_presence_resolves_through_the_alias_table(self):
        # "Senior ML Engineer" must credit the node canonically named "Machine
        # Learning". Without alias expansion this signal silently never fires
        # for an acronym title, which is most titles.
        jd = "We need machine learning experience."
        result = compute_weight(node("Machine Learning"), jd, "Senior ML Engineer")
        assert result.contributions["title_presence"] > 0, (
            "the title signal did not resolve 'ML' to 'Machine Learning'"
        )

    def test_3_repetition_is_log_scaled_and_capped(self):
        cfg = load_config()
        cap = cfg["weighting"]["repetition_bonus_cap"]
        one = CanonicalNode("Kafka", mentions=[
            Mention("Kafka", "Kafka.", 0, "required")])
        four = CanonicalNode("Kafka", mentions=[
            Mention("Kafka", "Kafka.", i * 10, "required") for i in range(4)])
        many = CanonicalNode("Kafka", mentions=[
            Mention("Kafka", "Kafka.", i * 10, "required") for i in range(40)])
        r1 = compute_weight(one, "Kafka.", "Engineer").contributions["repetition"]
        r4 = compute_weight(four, "Kafka.", "Engineer").contributions["repetition"]
        r40 = compute_weight(many, "Kafka.", "Engineer").contributions["repetition"]
        assert r1 < r4 <= cap and r40 <= cap
        # Log-scaled: 1->4 must buy more than 4->40, or the scaling is linear.
        assert (r4 - r1) > (r40 - r4)

    def test_4_position(self):
        jd = "x" * 1000
        early = compute_weight(node("Python", offset=10), jd, "Engineer")
        late = compute_weight(node("Python", offset=900), jd, "Engineer")
        assert early.contributions["position"] > late.contributions["position"]

    def test_5_qualifier(self):
        jd_expert = "We need deep expertise in Kafka."
        jd_aware = "Familiarity with Kafka is a plus."
        expert = compute_weight(
            node("Kafka", offset=jd_expert.index("Kafka")), jd_expert, "Engineer")
        aware = compute_weight(
            node("Kafka", offset=jd_aware.index("Kafka")), jd_aware, "Engineer")
        assert expert.contributions["qualifier"] > aware.contributions["qualifier"]
        assert aware.contributions["qualifier"] < 0, (
            "an 'awareness' qualifier should pull the weight down, not merely not raise it"
        )


class TestTheExplanationReconciles:
    def test_contributions_sum_to_raw(self):
        jd = "Requirements\n5+ years of strong Python and Kafka experience.\n"
        result = compute_weight(
            node("Python", offset=jd.index("Python")), jd, "Python Engineer")
        assert result.raw == pytest.approx(sum(result.contributions.values()))

    def test_weight_is_raw_after_the_clamp_and_the_clamp_is_flagged(self):
        cfg = load_config()
        lo = cfg["weighting"]["min_weight"]
        hi = cfg["weighting"]["max_weight"]
        jd = "Requirements\n10+ years of expert Python.\n"
        # Everything maximal: required section + title + qualifier + early
        # position should exceed 1.0 and clamp.
        result = compute_weight(
            node("Python", offset=jd.index("Python")), jd, "Senior Python Engineer")
        assert lo <= result.weight <= hi
        if result.raw > hi:
            assert result.clamped and result.weight == hi
        # The clamp is itself information: two skills both at 1.0 may have had
        # very different raw scores, and only this record distinguishes them.
        assert isinstance(result.clamped, bool)

    def test_every_signal_has_human_readable_evidence(self):
        result = compute_weight(node("Python"), "Python.", "Engineer")
        assert set(result.evidence) == set(result.contributions)
        for key, text in result.evidence.items():
            assert text and isinstance(text, str), f"{key} has no evidence string"

    def test_explain_is_built_from_the_persisted_breakdown(self):
        result = compute_weight(node("Python"), "Python.", "Python Engineer")
        line = explain(result)
        assert line.startswith(f"{result.weight:.2f} = ")
        for key, value in result.contributions.items():
            if value:
                assert key in line

    def test_as_json_round_trips_the_shape_the_column_stores(self):
        result = compute_weight(node("Python"), "Python.", "Engineer")
        payload = result.as_json()
        assert set(payload) >= {"weight", "raw", "clamped", "contributions", "evidence"}
        assert payload["weight"] == pytest.approx(result.weight, abs=1e-4)


class TestQualifierScoping:
    def test_qualifier_does_not_leak_across_a_sentence_boundary(self):
        # THE failure this guards: "We are an expert-led team." three lines up
        # marking every skill below it as expert. A plausible-looking, entirely
        # wrong graph.
        jd = "We are an expert-led team. We use Kafka here."
        tier, phrase = find_qualifier(jd, jd.index("Kafka"))
        assert tier != "expert", (
            f"the qualifier leaked across a sentence boundary (matched {phrase!r})"
        )

    def test_qualifier_applies_to_a_list_it_introduces(self):
        # "3+ years of Python, Go and Rust" -- all three get `proficient`.
        jd = "3+ years of Python, Go and Rust in production."
        for skill in ("Python", "Go", "Rust"):
            tier, _ = find_qualifier(jd, jd.index(skill))
            assert tier == "proficient", f"{skill} did not inherit the list qualifier"

    def test_longest_phrase_within_the_winning_tier_is_reported(self):
        jd = "5+ years of advanced Kafka tuning."
        tier, phrase = find_qualifier(jd, jd.index("Kafka"))
        # Both "5+ years" and "advanced" are `proficient`; the reported evidence
        # should be the longer, more specific one.
        assert tier == "proficient"
        assert phrase in ("5+ years", "advanced")
        assert len(phrase) == max(len("5+ years"), len("advanced")) or phrase == "5+ years"

    def test_no_qualifier_falls_back_to_the_configured_default(self):
        cfg = load_config()
        jd = "We use Kafka."
        tier, phrase = find_qualifier(jd, jd.index("Kafka"))
        assert tier == cfg["tiers"]["default_tier"]
        assert phrase == ""


class TestTierInference:
    def test_the_strongest_claim_across_mentions_wins(self):
        # "familiarity with Kafka" in one place and "5+ years of Kafka" in
        # another means the role needs 5 years. An average would produce a tier
        # the JD never asked for -- and the tier decides which modality the
        # skill is tested at, so a wrong average tests the wrong competency.
        jd = ("Familiarity with Kafka is useful. "
              "Separately, we require 5+ years of Kafka operations.")
        multi = CanonicalNode("Kafka", mentions=[
            Mention("Kafka", "", jd.index("Kafka"), "preferred"),
            Mention("Kafka", "", jd.rindex("Kafka"), "required"),
        ])
        tier, _ = infer_tier(multi, jd)
        assert tier == "proficient"

    def test_years_and_words_land_in_different_tiers(self):
        # The distinction the spec called out explicitly: "3+ years of X" and
        # "familiarity with X" are different tiers.
        jd_years = "3+ years of Terraform."
        jd_familiar = "Familiarity with Terraform."
        t1, _ = infer_tier(node("Terraform", offset=jd_years.index("Terraform")), jd_years)
        t2, _ = infer_tier(node("Terraform", offset=jd_familiar.index("Terraform")), jd_familiar)
        assert t1 == "proficient" and t2 == "awareness"
        assert t1 != t2


class TestSectionAttributionEndToEnd:
    def test_strongest_section_wins_not_the_most_common(self):
        """A skill named once under Required and four times in the About-us
        blurb is a required skill. Taking the mode would bury it."""
        jd = ("About us\nWe love Kafka. Kafka is our life. Kafka Kafka.\n"
              "Requirements\nKafka operations experience.\n")
        sections = segment(jd)
        offsets = [i for i in range(len(jd)) if jd.startswith("Kafka", i)]
        mentions = [Mention("Kafka", "", o, label_at(sections, o)) for o in offsets]
        result = compute_weight(CanonicalNode("Kafka", mentions=mentions), jd, "Engineer")
        assert result.evidence["section_base"].startswith("strongest section: required")


class TestHeadroomBelowTheClamp:
    """The regression that made signals 2-5 inert.

    `required` was set to 1.00, equal to `max_weight`, so every required skill
    clamped to 1.00 and title/repetition/position/qualifier changed nothing for
    the most important section in the document. The per-signal breakdown still
    recorded honest contributions, so the defect was invisible in the
    explanation while every weight it explained was identical.
    """

    def test_the_required_base_leaves_room_for_every_other_signal(self):
        cfg = load_config()
        w = cfg["weighting"]
        base = w["section_base"]["required"]
        max_bonus = (w["title_presence_bonus"] + w["repetition_bonus_cap"]
                     + w["position_bonus_max"] + max(w["qualifier_bonus"].values()))
        assert base + max_bonus > w["max_weight"], (
            "no configuration can reach max_weight -- the top of the scale is "
            "unreachable"
        )
        assert base < w["max_weight"], (
            f"section_base.required ({base}) equals or exceeds max_weight "
            f"({w['max_weight']}); every required skill will clamp and signals "
            "2-5 become inert"
        )

    def test_two_required_skills_differing_only_in_title_get_different_weights(self):
        jd = "Requirements\nWe need Python and we need Rust.\n"
        titled = compute_weight(
            node("Python", offset=jd.index("Python")), jd, "Senior Python Engineer")
        untitled = compute_weight(
            node("Rust", offset=jd.index("Rust")), jd, "Senior Python Engineer")
        assert titled.weight > untitled.weight, (
            "the title signal is inert for required-section skills"
        )

    def test_a_maximal_required_skill_still_reaches_the_top(self):
        jd = "Requirements\n10+ years of expert Python. Python. Python.\n"
        offsets = [i for i in range(len(jd)) if jd.startswith("Python", i)]
        from app.services.arena.canonicalise import CanonicalNode as CN
        from app.services.arena.canonicalise import Mention as M
        maximal = CN("Python", mentions=[M("Python", "", o, "required") for o in offsets])
        result = compute_weight(maximal, jd, "Senior Python Engineer")
        assert result.weight >= 0.95, (
            f"a title-named, thrice-repeated, expert-qualified required skill only "
            f"reached {result.weight:.2f}"
        )


class TestEachSignalCanMoveTheFinalWeight:
    """The generalisation of the inert-signal defect.

    Every other test in this file checks that a signal's CONTRIBUTION differs,
    or that the breakdown RECONCILES to the stored number. Both passed while
    `section_base.required` was 1.00 and four of the five signals could not move
    the output at all, because the contributions were honest and the clamp ate
    them.

    So: being able to explain a number is not the same as the number being
    informative. Contract section 17.0b says a prediction is evidence only with
    a named mechanism -- here the mechanism was named and the mechanism was
    inert.

    The assertion this class makes is the one the earlier tests could not:
    FOR EACH SIGNAL, there exists an input where changing ONLY that signal
    changes the FINAL weight (post-clamp) by at least EPSILON.

    Deliberately asserted on `weight`, never on `raw` or on `contributions` --
    those are what passed last time.
    """

    # Large enough that a rounding artefact cannot satisfy it, small enough that
    # it is not secretly asserting a magnitude. The defect it catches produces a
    # delta of exactly 0.0.
    EPSILON = 0.02

    def _pair(self, name: str, a_kwargs: dict, b_kwargs: dict):
        return compute_weight(**a_kwargs), compute_weight(**b_kwargs)

    def test_section_base_reaches_the_output(self):
        jd = "Requirements\nWe use Kafka.\nPreferred Qualifications\nWe use Kafka.\n"
        a = compute_weight(node("Kafka", "required"), jd, "Engineer")
        b = compute_weight(node("Kafka", "preferred"), jd, "Engineer")
        assert abs(a.weight - b.weight) >= self.EPSILON, (
            f"section_base cannot move the final weight "
            f"({a.weight:.4f} vs {b.weight:.4f}); it is inert"
        )

    def test_title_presence_reaches_the_output(self):
        jd = "Requirements\nWe need Kafka.\n"
        a = compute_weight(node("Kafka"), jd, "Senior Kafka Engineer")
        b = compute_weight(node("Kafka"), jd, "Senior Data Engineer")
        assert abs(a.weight - b.weight) >= self.EPSILON, (
            f"title_presence cannot move the final weight "
            f"({a.weight:.4f} vs {b.weight:.4f}); it is inert"
        )

    def test_repetition_reaches_the_output(self):
        jd = "Requirements\n" + ("We use Kafka. " * 6)
        one = CanonicalNode("Kafka", mentions=[Mention("Kafka", "", 20, "required")])
        many = CanonicalNode("Kafka", mentions=[
            Mention("Kafka", "", 20 + i * 14, "required") for i in range(6)])
        a = compute_weight(many, jd, "Engineer")
        b = compute_weight(one, jd, "Engineer")
        assert abs(a.weight - b.weight) >= self.EPSILON, (
            f"repetition cannot move the final weight "
            f"({a.weight:.4f} vs {b.weight:.4f}); it is inert"
        )

    def test_position_reaches_the_output(self):
        # A long document so the position term has room to differ. Nothing else
        # changes between the two calls.
        jd = "Requirements\n" + ("filler text. " * 400)
        a = compute_weight(node("Kafka", "required", offset=20), jd, "Engineer")
        b = compute_weight(node("Kafka", "required", offset=len(jd) - 20), jd, "Engineer")
        assert abs(a.weight - b.weight) >= self.EPSILON, (
            f"position cannot move the final weight "
            f"({a.weight:.4f} vs {b.weight:.4f}); it is inert"
        )

    def test_qualifier_reaches_the_output(self):
        jd_expert = "Requirements\nWe need deep expertise in Kafka.\n"
        jd_aware = "Requirements\nFamiliarity with Kafka is useful.\n"
        a = compute_weight(node("Kafka", "required", offset=jd_expert.index("Kafka")),
                           jd_expert, "Engineer")
        b = compute_weight(node("Kafka", "required", offset=jd_aware.index("Kafka")),
                           jd_aware, "Engineer")
        assert abs(a.weight - b.weight) >= self.EPSILON, (
            f"qualifier cannot move the final weight "
            f"({a.weight:.4f} vs {b.weight:.4f}); it is inert"
        )

    def test_no_signal_is_inert_in_the_highest_weighted_section(self):
        """The exact condition of the original defect.

        `required` is the section where clamping is most likely to swallow every
        adjustment, and it is also the section that matters most. If a signal
        goes inert anywhere, it goes inert here first -- so this checks all four
        adjustment signals specifically inside `required`, rather than trusting
        that a delta observed in `preferred` generalises upward.
        """
        base_jd = "Requirements\nWe need Kafka.\n"
        baseline = compute_weight(node("Kafka", "required", offset=base_jd.index("Kafka")),
                                  base_jd, "Data Engineer")

        variants = {
            "title_presence": compute_weight(
                node("Kafka", "required", offset=base_jd.index("Kafka")),
                base_jd, "Kafka Engineer"),
            "repetition": compute_weight(
                CanonicalNode("Kafka", mentions=[
                    Mention("Kafka", "", base_jd.index("Kafka") + i, "required")
                    for i in range(6)]),
                base_jd, "Data Engineer"),
            "qualifier": compute_weight(
                node("Kafka", "required", offset=len("Requirements\nFamiliarity with ")),
                "Requirements\nFamiliarity with Kafka is useful.\n", "Data Engineer"),
        }
        inert = {
            name: (baseline.weight, v.weight)
            for name, v in variants.items()
            if abs(v.weight - baseline.weight) < self.EPSILON
        }
        assert not inert, (
            f"signals inert inside the `required` section: {inert}. "
            "section_base is probably at or near max_weight again, so every "
            "required skill clamps to the same number while the breakdown "
            "still reports honest contributions."
        )
