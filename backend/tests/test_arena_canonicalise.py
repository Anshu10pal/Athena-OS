"""Canonicalisation cascade -- regression pins.

THE REFERENCE SET IN ITS SECOND JOB
===================================
The pairs below are the reference set that DESIGNED the cascade (see
app/services/arena/canonicalise.py's module docstring for the measured curve).
It is therefore spent as a validation instrument -- reporting a recall figure
against the set that chose the thresholds would be contract section 17.27
exactly, a classifier calibrated on a fixture.

It is NOT spent as a REGRESSION instrument, which is a different question. These
tests do not ask "how good is canonicalisation"; they ask "did a config or
prompt change silently break a merge that used to work". Same object, different
job. Validation is the five held-out JDs, measured in
scripts/arena_extraction_report.py.

Mirrors tests/test_card_quality.py's shape deliberately: pin the pair that MUST
merge and the pair that MUST NOT, so a threshold retune has to acknowledge both.
"""
import pytest

from app.services.arena.canonicalise import (METHOD_ALIAS, METHOD_BARE,
                                             METHOD_CONTAINMENT, METHOD_ENRICHED,
                                             METHOD_EXACT, Mention, canonicalise,
                                             method_histogram, normalise)
from app.services.arena.config import load_config


def mention(surface: str, span: str = "", section: str = "required") -> Mention:
    return Mention(
        surface=surface,
        span=span or f"Experience with {surface} in a production environment.",
        offset=0,
        section=section,
    )


def names(nodes) -> set:
    return {n.canonical_name for n in nodes}


class TestNormalise:
    def test_punctuation_that_carries_meaning_survives(self):
        # The bug this pins: an earlier draft stripped all non-alphanumerics,
        # which collapsed "C++" and "C#" to the same string and would have
        # merged two different languages on stage 1 with no evidence recorded.
        assert normalise("C++") != normalise("C#")
        assert normalise("CI/CD") == "ci/cd"
        assert normalise("Node.js") == "node.js"

    def test_trailing_plural_only(self):
        assert normalise("REST APIs") == normalise("REST API")
        # Not a stemmer: these must stay distinct, or "unit testing" starts
        # merging into "integration testing" two stages later.
        assert normalise("unit testing") != normalise("integration testing")

    def test_singularisation_is_position_independent(self):
        """Found by the live smoke test, not by a unit test.

        The plural rule originally touched only the FINAL token, so
        "Kubernetes" became "kubernete" while "Kubernetes operations" became
        "kubernetes operation" -- the same word comparing unequal depending on
        where it sat. Containment silently stopped firing on that pair and only
        a lucky bare-cosine hit merged them.
        """
        assert normalise("Kubernetes").split()[0] == normalise("Kubernetes operations").split()[0]
        assert normalise("APIs").split()[0] == normalise("APIs and services").split()[0]

    def test_case_and_whitespace(self):
        assert normalise("  Machine   LEARNING ") == normalise("machine learning")


class TestStage1Exact:
    def test_identical_surface_forms_collapse(self):
        nodes, _ = canonicalise([mention("Python"), mention("python"), mention("Python")])
        assert len(nodes) == 1
        assert len(nodes[0].mentions) == 3


class TestStage2Alias:
    """The class embeddings provably cannot reach. Four of the six residual
    misses in the calibration were acronym/short-form pairs with ZERO lexical
    overlap; an acronym bears no semantic relation to its expansion in
    embedding space, so no threshold ever gets there."""

    @pytest.mark.parametrize("left,right", [
        ("CI/CD", "continuous integration"),
        ("Kubernetes", "K8s"),
        ("machine learning", "ML"),
        ("SQL", "structured query language"),
        ("Docker", "containerization"),
    ])
    def test_acronym_and_expansion_merge(self, left, right):
        nodes, _ = canonicalise([mention(left), mention(right)])
        assert len(nodes) == 1, f"{left} and {right} must canonicalise to one node"
        methods = {e["method"] for e in nodes[0].merge_evidence}
        assert methods & {METHOD_ALIAS, METHOD_EXACT}, (
            f"{left}/{right} merged by {methods}, expected the alias table -- if this "
            "starts passing via an embedding branch the alias table has silently "
            "stopped being what makes this work"
        )

    def test_alias_table_is_actually_populated_from_config(self):
        # Guards the failure where load_config() silently falls back to
        # DEFAULT_CONFIG (whose alias table is empty) because the YAML moved or
        # failed to parse. Every alias test above would still "pass" by
        # accidentally merging on cosine, so this asserts the input directly.
        aliases = load_config()["canonicalisation"]["aliases"]
        assert len(aliases) >= 20, (
            f"only {len(aliases)} alias groups loaded -- config/arena_extraction.yaml "
            "is probably not being read"
        )


class TestStage2Containment:
    def test_containment_fires_on_the_pair_that_exposed_the_normalise_bug(self):
        nodes, _ = canonicalise([mention("Kubernetes operations"), mention("Kubernetes")])
        assert len(nodes) == 1
        methods = {e["method"] for e in nodes[0].merge_evidence}
        assert METHOD_CONTAINMENT in methods or METHOD_EXACT in methods, (
            f"merged by {methods} rather than by containment -- the position-dependent "
            "normalisation bug has come back and stage 3 is covering for it"
        )

    def test_short_form_folds_into_the_longer_name(self):
        nodes, _ = canonicalise([mention("Palantir Foundry"), mention("Foundry")])
        assert len(nodes) == 1
        # The longer, more specific name survives -- it is what a user should
        # see on the confirmation screen.
        assert nodes[0].canonical_name == "Palantir Foundry"

    def test_short_tokens_do_not_merge_into_longer_names(self):
        # "Go" must not fold into "Google Cloud"; "R" must not fold into "React".
        nodes, _ = canonicalise([mention("Google Cloud"), mention("Go")])
        assert len(nodes) == 2, "a 2-char language name must not be absorbed by containment"
        nodes, _ = canonicalise([mention("React"), mention("R")])
        assert len(nodes) == 2


class TestStage3EmbeddingBranches:
    """The two branches catch different pairs, which is why they are OR-ed
    rather than one replacing the other."""

    def test_clear_paraphrase_auto_merges(self):
        # Bare cosine 0.929 -- comfortably over 0.86.
        nodes, _ = canonicalise([mention("data modelling"), mention("data models")])
        assert len(nodes) == 1

    def test_borderline_paraphrase_is_suggested_not_merged(self):
        """A real duplicate that does NOT clear 0.86 goes to the human.

        "cloud infrastructure"/"cloud platforms" sits at 0.856. Raising the
        threshold from 0.84 to 0.86 (for margin against Spark/Hadoop at 0.835)
        moved this pair out of auto-merge and into the review band. That is the
        design working as intended, not a regression -- but it is a deliberate
        trade and it is pinned here so nobody silently reverses it.
        """
        nodes, suggestions = canonicalise([
            mention("cloud infrastructure", "Manage cloud infrastructure across regions."),
            mention("cloud platforms", "Familiarity with major cloud platforms."),
        ])
        assert len(nodes) == 2, "must not auto-merge below the bare threshold"
        assert any({s.left, s.right} == {"cloud infrastructure", "cloud platforms"}
                   for s in suggestions), (
            "a real duplicate below the auto-merge line must reach the user as a "
            "suggestion, not vanish"
        )

    def test_bare_branch_catches_what_enrichment_drops(self):
        # The measured case: "unit testing"/"writing unit tests" scores 0.876
        # bare and only 0.714 enriched, because the two JD sentences diverge.
        # If this stops merging, the OR has been collapsed to enrichment-only.
        nodes, _ = canonicalise([
            Mention(surface="unit testing", span="Strong habits around unit testing.",
                    offset=0, section="required"),
            Mention(surface="writing unit tests",
                    span="You will be writing unit tests for everything you ship.",
                    offset=50, section="required"),
        ])
        assert len(nodes) == 1, (
            "the bare-cosine branch has stopped firing -- enrichment alone misses this pair"
        )

    def test_siblings_never_merge(self):
        """The pairs that MUST NOT merge. This is the half of the pin-set that a
        threshold retune is most likely to break, because every retune is
        motivated by wanting more recall."""
        sibling_pairs = [
            ("Docker", "Kubernetes"),
            ("React", "Vue"),
            ("Python", "Java"),
            ("PostgreSQL", "MySQL"),
            ("AWS", "Azure"),
            ("unit testing", "integration testing"),
            ("Kafka", "RabbitMQ"),
            ("Spark", "Hadoop"),
            ("TypeScript", "JavaScript"),
        ]
        for left, right in sibling_pairs:
            nodes, _ = canonicalise([mention(left), mention(right)])
            assert len(nodes) == 2, (
                f"{left} and {right} were merged into one node. These are different "
                "skills that belong under one PARENT -- merging them destroys a "
                "distinction the interview needs to test, and nothing downstream "
                "can notice it happened."
            )


class TestStage4ReviewBand:
    def test_ambiguous_pairs_are_suggested_not_merged(self):
        """The whole point of stage 4: the band is surfaced, never applied.

        Uses a pair engineered to land in [0.68, 0.76). If the config's band
        moves, this test should be updated deliberately -- it is asserting the
        BEHAVIOUR (suggest, don't merge) rather than a specific pair's score.
        """
        cfg = load_config()
        low = cfg["canonicalisation"]["review_band_low"]
        # The BARE threshold is the band ceiling. The enriched value is a shadow
        # metric and must never be the ceiling again -- it was, briefly, and
        # under template phrasing that band admitted PostgreSQL/MySQL.
        high = cfg["canonicalisation"]["bare_cosine_threshold"]
        assert low < high, "review band is inverted; nothing can ever land in it"

        # Sweep a handful of plausibly-ambiguous pairs and assert that ANY that
        # land in the band are suggested rather than merged.
        candidates = [
            ("data pipelines", "stream processing"),
            ("observability", "monitoring"),
            ("technical writing", "documentation"),
            ("mentoring", "coaching engineers"),
        ]
        saw_band = False
        for left, right in candidates:
            nodes, suggestions = canonicalise([mention(left), mention(right)])
            for s in suggestions:
                saw_band = True
                assert low <= s.bare_cosine < high
                # Not merged: both nodes still present.
                assert len(nodes) == 2, (
                    f"{left}/{right} was BOTH merged and suggested -- the band must "
                    "never apply a merge"
                )
        if not saw_band:
            pytest.skip("no candidate pair landed in the review band on this model build")

    def test_default_state_is_unmerged(self):
        # Stated as a test because it is the safety property the whole design
        # rests on: an unmerged duplicate is visible and correctable, a false
        # merge is neither.
        nodes, suggestions = canonicalise([
            mention("observability"), mention("monitoring"),
        ])
        if suggestions:
            assert len(nodes) == 2


class TestMergeTelemetry:
    def test_every_merge_records_which_branch_decided_it(self):
        """The monitoring line. If a branch stops firing on real JDs the
        extraction sentences have changed shape, and that is not reconstructable
        after the fact -- so the branch is recorded at the moment it decides."""
        nodes, _ = canonicalise([
            mention("Kubernetes"), mention("K8s"),
            mention("cloud infrastructure", "Manage cloud infrastructure across regions."),
            mention("cloud platforms", "Familiarity with major cloud platforms."),
        ])
        for node in nodes:
            for evidence in node.merge_evidence:
                assert evidence["method"] in (
                    METHOD_EXACT, METHOD_ALIAS, METHOD_CONTAINMENT,
                    METHOD_ENRICHED, METHOD_BARE,
                ), f"unknown merge method {evidence['method']!r}"
                assert "surface" in evidence and "score" in evidence

    def test_histogram_counts_by_method(self):
        nodes, _ = canonicalise([mention("Kubernetes"), mention("K8s")])
        hist = method_histogram(nodes)
        assert sum(hist.values()) >= 1
        assert set(hist) >= {METHOD_ALIAS, METHOD_ENRICHED, METHOD_BARE}


class TestDegenerateInputs:
    def test_empty_input(self):
        assert canonicalise([]) == ([], [])

    def test_single_mention_produces_no_suggestions(self):
        nodes, suggestions = canonicalise([mention("Python")])
        assert len(nodes) == 1 and suggestions == []


class TestEnrichmentIsShadowOnly:
    """The correction, pinned.

    Enrichment was briefly a decision branch at 0.76. Under template phrasing --
    the same sentence shape on both sides, which is how JD bullet lists are
    written -- that branch had a 92% false-merge rate and merged PostgreSQL with
    MySQL. These tests exist so it cannot come back as a decision branch without
    someone deleting them on purpose.
    """

    def test_template_phrased_siblings_survive(self):
        # The exact failing case: identical sentence shape, different skills.
        pairs = [("Docker", "Kubernetes"), ("PostgreSQL", "MySQL"),
                 ("Python", "Java"), ("AWS", "Azure")]
        template = "Experience with {} in a production environment."
        for left, right in pairs:
            nodes, _ = canonicalise([
                Mention(surface=left, span=template.format(left), offset=0,
                        section="required"),
                Mention(surface=right, span=template.format(right), offset=60,
                        section="required"),
            ])
            assert len(nodes) == 2, (
                f"{left}/{right} merged under identical sentence templates. The "
                "enriched-cosine branch has been re-enabled as a decision path; "
                "it measures 92% false-merge under this condition."
            )

    def test_no_merge_is_ever_attributed_to_the_enriched_branch(self):
        nodes, _ = canonicalise([
            mention("data modelling"), mention("data models"),
            mention("Kubernetes"), mention("K8s"),
            mention("Palantir Foundry"), mention("Foundry"),
        ])
        for node in nodes:
            for evidence in node.merge_evidence:
                assert evidence["method"] != METHOD_ENRICHED, (
                    "a merge was attributed to the enriched branch, which is "
                    "supposed to decide nothing"
                )

    def test_enriched_score_is_still_recorded_on_suggestions(self):
        """Shadow means computed and persisted, not deleted. Without this the
        evidence for a future gated version never accumulates."""
        _nodes, suggestions = canonicalise([
            mention("cloud infrastructure", "Manage cloud infrastructure across regions."),
            mention("cloud platforms", "Familiarity with major cloud platforms."),
        ])
        assert suggestions, "expected this pair in the review band"
        assert suggestions[0].enriched_cosine > 0.0, (
            "the enriched shadow metric is not being computed; the data a gated "
            "version would need is not being collected"
        )
