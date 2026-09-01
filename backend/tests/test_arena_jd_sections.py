"""JD section segmentation.

The expensive failure this guards is silent relabelling: a long prose sentence
containing the word "requirements" being treated as a header shifts the label of
everything after it, which shifts every downstream weight, and produces a graph
that is plausibly wrong with nothing indicating why.
"""
from app.services.arena.jd_sections import (MAX_HEADER_CHARS, header_at, label_at,
                                            segment)


class TestHeaderDetection:
    def test_decorated_headers_all_match(self):
        for header in ("Requirements", "## Requirements", "- Requirements:",
                       "3. REQUIREMENTS", "* Requirements", "requirements:"):
            jd = f"Intro paragraph.\n{header}\nPython experience.\n"
            sections = segment(jd)
            assert any(s.label == "required" for s in sections), header

    def test_long_prose_containing_a_header_word_is_not_a_header(self):
        # THE failure this module exists to avoid. If this line is taken as a
        # header, everything below it is relabelled `required` and every weight
        # in the graph shifts.
        prose = ("We have a long list of requirements for this role and we would "
                 "love to tell you all about them in this sentence which is far "
                 "too long to be a heading of any kind.")
        jd = f"{prose}\nPython experience.\n"
        assert len(prose) > MAX_HEADER_CHARS
        sections = segment(jd)
        assert all(s.label == "unknown" for s in sections), (
            "a prose sentence was treated as a section header"
        )

    def test_longest_phrase_wins_across_labels(self):
        # "Preferred Qualifications" must resolve to `preferred`, not to
        # `required` via the shorter "qualifications". Without longest-match this
        # depends on dict ordering, which is an accident, not a rule.
        jd = "Preferred Qualifications\nKafka is a plus.\n"
        sections = segment(jd)
        assert [s.label for s in sections] == ["preferred"]

    def test_nice_to_have_is_distinct_from_preferred(self):
        jd = ("Requirements\nPython.\n"
              "Preferred Qualifications\nGo.\n"
              "Nice to have\nRust.\n")
        labels = [s.label for s in segment(jd)]
        assert labels == ["required", "preferred", "nice_to_have"]

    def test_boilerplate_is_labelled_so_it_can_be_down_weighted(self):
        # Without this label, "competitive salary" contributes skill mentions at
        # mid-scale `unknown` weight and the graph fills with non-skills.
        jd = ("Requirements\nPython.\n"
              "Benefits\nCompetitive salary and free snacks.\n"
              "Equal Opportunity\nWe are an equal opportunity employer.\n")
        labels = [s.label for s in segment(jd)]
        assert labels.count("boilerplate") == 2


class TestStructuralGuarantees:
    def test_always_covers_the_whole_document(self):
        jd = "Requirements\nPython.\nBenefits\nSnacks.\n"
        sections = segment(jd)
        assert sections[0].start == 0
        assert sections[-1].end == len(jd)
        for a, b in zip(sections, sections[1:]):
            assert a.end <= b.start, "sections must not overlap"

    def test_no_headers_yields_one_unknown_section(self):
        # The common case for a short posting and for the deliberately-vague
        # one. A correct answer, not a degraded one.
        jd = "We want someone who can code in Python and talk to customers."
        sections = segment(jd)
        assert len(sections) == 1
        assert sections[0].label == "unknown"
        assert sections[0].end == len(jd)

    def test_preamble_before_the_first_header_stays_unknown(self):
        # Company framing must not inherit the weight of whatever header
        # happens to follow it.
        jd = "About Acme: we are a fast-growing startup.\nRequirements\nPython.\n"
        sections = segment(jd)
        assert sections[0].label == "unknown"
        assert sections[0].start == 0

    def test_empty_document(self):
        sections = segment("")
        assert len(sections) == 1 and sections[0].label == "unknown"

    def test_empty_section_body_is_still_emitted(self):
        # An empty `required` section is a real fact about a badly-written JD;
        # dropping it would make the section list disagree with the document.
        jd = "Requirements\nBenefits\nSnacks.\n"
        labels = [s.label for s in segment(jd)]
        assert "required" in labels and "boilerplate" in labels


class TestLookup:
    def test_label_and_header_at_offset(self):
        jd = "Requirements\nStrong Python skills.\nBenefits\nSnacks.\n"
        sections = segment(jd)
        offset = jd.index("Python")
        assert label_at(sections, offset) == "required"
        assert header_at(sections, offset) == "Requirements"

    def test_offset_outside_any_section_is_unknown(self):
        sections = segment("Requirements\nPython.\n")
        assert label_at(sections, 10_000) == "unknown"
        assert header_at(sections, 10_000) == ""
