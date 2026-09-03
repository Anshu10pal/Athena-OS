"""LLM clustering: the pinned prompt, and the guards that keep it honest.

This component exists because a PRE-REGISTERED gate failed
(`clustering.min_coherent_parent_fraction` = 0.80, measured 43-50% across five
fixtures). It is the escalation firing on its trigger, once.
"""
import hashlib

import pytest

from app.services.arena.canonicalise import CanonicalNode, Mention
from app.services.arena.config import load_config
from app.services.arena.llm_clustering import (CLUSTERING_PROMPT, UNASSIGNED_PARENT,
                                               MalformedClusteringResponse,
                                               _build_prompt, _resolve_assignments,
                                               cluster_skills_llm)


# HARDCODED DIGEST, and it has to be hardcoded to mean anything.
#
# The first version of this file computed it from CLUSTERING_PROMPT at module
# load and compared the constant's hash to its own hash -- a test that CANNOT
# FAIL, which is the same class of defect as a check that certifies the wrong
# property. Caught before commit. A literal digest is the only form of this pin
# that has any force.
PINNED_PROMPT_SHA256 = "e7a4f252544cf416f8cc058d14497b6a184cc200b138c0b0550a6d7900bee14c"


def node(name: str) -> CanonicalNode:
    return CanonicalNode(canonical_name=name,
                         mentions=[Mention(name, f"experience with {name}", 0, "required")])


SKILLS = ["Python", "SQL", "Apache Spark", "Kubernetes", "Terraform",
          "stakeholder management", "technical writing"]
NODES = [node(s) for s in SKILLS]


class TestPromptIsPinned:
    """The prompt is pinned by HASH rather than by a second copy of its text.

    Asserting against a literal duplicate would itself create the two-sources-
    of-truth problem this pattern exists to prevent -- the copy in the test
    would drift from the copy in the module and the test would still pass,
    because it would be comparing the drifted copy to itself. A hash cannot
    drift silently: any edit to the prompt fails this test and forces the
    change to be deliberate.
    """


    def test_prompt_hash_is_stable(self):
        actual = hashlib.sha256(CLUSTERING_PROMPT.encode("utf-8")).hexdigest()
        expected = PINNED_PROMPT_SHA256
        assert actual == expected, (
            "CLUSTERING_PROMPT changed.\n"
            f"  was: {expected}\n"
            f"  now: {actual}\n"
            "If the change is deliberate, update PROMPT_SHA256 IN THE SAME COMMIT "
            "as the prompt edit and say in the message what was changed and why. "
            "The prompt must not be swept against the acceptance fixtures -- see "
            "the module docstring and docs/decisions.md."
        )

    def test_every_pinned_rule_is_present(self):
        # The hash catches any edit; these name the rules that must not be lost
        # in one, so a future rewrite has to consciously drop a constraint
        # rather than lose it in a reflow.
        for fragment in (
            "use these EXACT strings",
            "Never invent a skill",
            "EVERY skill to exactly one parent",
            "between {min_parents} and {max_parents} parents",
            "between 2 and {max_children} children",
            "one-line rationale",
            "not by surface word similarity",
        ):
            assert fragment in CLUSTERING_PROMPT, f"pinned rule missing: {fragment!r}"

    def test_numbers_come_from_config_not_literals(self):
        """Same argument as SPAN_MAX_WORDS: a bound written into the prompt text
        AND into config is two sources of truth, and the prompt is the copy that
        drifts because nothing imports it."""
        assert "{min_parents}" in CLUSTERING_PROMPT
        assert "{max_parents}" in CLUSTERING_PROMPT
        assert "{max_children}" in CLUSTERING_PROMPT

    def test_built_prompt_substitutes_every_placeholder(self):
        built = _build_prompt(NODES, "Senior Data Engineer", load_config())
        for placeholder in ("{title}", "{skills}", "{min_parents}",
                            "{max_parents}", "{max_children}"):
            assert placeholder not in built, f"{placeholder} left unsubstituted"
        cfg = load_config()
        assert str(cfg["max_children_per_parent"]) in built
        for s in SKILLS:
            assert s in built, f"skill {s!r} missing from the built prompt"


class TestTheModelCannotChangeTheSkillSet:
    """It groups and names. It does not get to introduce or lose skills."""

    def test_invented_child_names_are_dropped_and_counted(self):
        parents, invented, unassigned = _resolve_assignments(
            [{"name": "Data", "rationale": "r",
              "children": ["Python", "SQL", "Rust", "Haskell"]}], NODES)
        assigned = [i for _n, _r, idx in parents for i in idx]
        assert sorted(invented) == ["Haskell", "Rust"]
        assert len(assigned) == 2, "an invented name was mapped onto a real node"

    def test_a_skill_assigned_twice_is_kept_once(self):
        parents, _inv, _un = _resolve_assignments([
            {"name": "A", "rationale": "r", "children": ["Python", "SQL"]},
            {"name": "B", "rationale": "r", "children": ["Python", "Kubernetes"]},
        ], NODES)
        flat = [i for _n, _r, idx in parents for i in idx]
        assert len(flat) == len(set(flat)), "a skill landed under two parents"

    def test_unassigned_skills_are_reported_not_lost(self):
        parents, _inv, unassigned = _resolve_assignments(
            [{"name": "Data", "rationale": "r", "children": ["Python", "SQL"]}], NODES)
        assert len(unassigned) == len(SKILLS) - 2, (
            "skills the model omitted were silently discarded. 'Never lose a "
            "skill the JD named' is an invariant this pipeline has held since "
            "Phase A began; a clustering swap is not licence to break it."
        )

    def test_name_matching_tolerates_case_and_plural_only(self):
        parents, invented, _u = _resolve_assignments(
            [{"name": "A", "rationale": "r", "children": ["python", "SQL "]}], NODES)
        assert invented == []
        assert len([i for _n, _r, idx in parents for i in idx]) == 2


class TestMalformedResponsesRaiseRatherThanRepair:
    """A loosened parser would report a number for a grouping the model did not
    produce. The acceptance script reports NOT MEASURED instead, which is true."""

    def _stub(self, monkeypatch, payload):
        monkeypatch.setattr("app.core.llm.chat_json",
                            lambda messages, fast=True, retries=2: payload)

    def test_missing_parents_key_raises(self, monkeypatch):
        self._stub(monkeypatch, {"groups": []})
        with pytest.raises(MalformedClusteringResponse):
            cluster_skills_llm(NODES, "Engineer")

    def test_empty_parents_raises(self, monkeypatch):
        self._stub(monkeypatch, {"parents": []})
        with pytest.raises(MalformedClusteringResponse):
            cluster_skills_llm(NODES, "Engineer")

    def test_all_children_invented_raises(self, monkeypatch):
        self._stub(monkeypatch, {"parents": [
            {"name": "X", "rationale": "r", "children": ["Rust", "Haskell"]}]})
        with pytest.raises(MalformedClusteringResponse):
            cluster_skills_llm(NODES, "Engineer")

    def test_a_transport_failure_raises_the_typed_error(self, monkeypatch):
        def boom(messages, fast=True, retries=2):
            raise RuntimeError("429 rate limit")
        monkeypatch.setattr("app.core.llm.chat_json", boom)
        with pytest.raises(MalformedClusteringResponse):
            cluster_skills_llm(NODES, "Engineer")


class TestStructuralViolationsAreReportedNotRepaired:
    def _stub(self, monkeypatch, payload):
        monkeypatch.setattr("app.core.llm.chat_json",
                            lambda messages, fast=True, retries=2: payload)

    def test_an_oversized_parent_survives_to_be_measured(self, monkeypatch):
        """If the model puts everything in one parent, that is a
        max-children-per-parent failure and must reach the acceptance table.
        Splitting it here would tune the measurement instead of measuring the
        component."""
        self._stub(monkeypatch, {"parents": [
            {"name": "Everything", "rationale": "r", "children": SKILLS}]})
        result = cluster_skills_llm(NODES, "Engineer")
        assert len(result.parents) == 1
        assert len(result.parents[0].child_indices) == len(SKILLS)

    def test_unassigned_skills_become_a_visible_parent(self, monkeypatch):
        self._stub(monkeypatch, {"parents": [
            {"name": "Data", "rationale": "r", "children": ["Python", "SQL"]}]})
        result = cluster_skills_llm(NODES, "Engineer")
        names = [p.name for p in result.parents]
        assert UNASSIGNED_PARENT in names
        recovered = next(p for p in result.parents if p.name == UNASSIGNED_PARENT)
        assert len(recovered.child_indices) == len(SKILLS) - 2

    def test_provenance_is_recorded_for_the_acceptance_table(self, monkeypatch):
        self._stub(monkeypatch, {"parents": [
            {"name": "Data", "rationale": "r",
             "children": ["Python", "SQL", "Rust"]}]})
        result = cluster_skills_llm(NODES, "Engineer")
        b = result.budget_applied
        assert b["clusterer"] == "llm"
        assert b["invented_assignments"] == 1
        assert b["unassigned_recovered"] == len(SKILLS) - 2
        assert b["n_parents_returned"] == 1


class TestCoherenceInstrumentIsUnchanged:
    def test_coherence_uses_the_same_threshold_as_the_deterministic_path(self, monkeypatch):
        """The number has to be COMPARABLE to the deterministic run's, and it is
        only comparable if the instrument did not change."""
        monkeypatch.setattr("app.core.llm.chat_json",
                            lambda messages, fast=True, retries=2: {"parents": [
                                {"name": "Infra", "rationale": "r",
                                 "children": ["Kubernetes", "Terraform"]},
                                {"name": "Data", "rationale": "r",
                                 "children": ["Python", "SQL", "Apache Spark"]},
                                {"name": "Soft", "rationale": "r",
                                 "children": ["stakeholder management", "technical writing"]},
                            ]})
        result = cluster_skills_llm(NODES, "Engineer")
        threshold = load_config()["clustering"]["coherence_threshold"]
        for p in result.parents:
            if p.coherence is not None:
                assert p.coherent == (p.coherence >= threshold)
        assert result.coherent_fraction is not None
        assert 0.0 <= result.coherent_fraction <= 1.0

    def test_a_single_child_parent_has_no_coherence_number(self, monkeypatch):
        # None, never 0.0 or 1.0 -- a placeholder would drag the coherent
        # fraction in whichever direction it was chosen (contract 17.25).
        monkeypatch.setattr("app.core.llm.chat_json",
                            lambda messages, fast=True, retries=2: {"parents": [
                                {"name": "Solo", "rationale": "r", "children": ["Python"]},
                                {"name": "Rest", "rationale": "r",
                                 "children": [s for s in SKILLS if s != "Python"]},
                            ]})
        result = cluster_skills_llm(NODES, "Engineer")
        solo = next(p for p in result.parents if p.name == "Solo")
        assert solo.coherence is None and solo.coherent is None


class TestDegenerateInputs:
    def test_no_skills_returns_empty(self):
        assert cluster_skills_llm([], "Engineer").parents == []

    def test_two_skills_stay_flat_without_calling_the_model(self, monkeypatch):
        def must_not_be_called(*a, **k):
            raise AssertionError("the model was called for a 2-skill graph")
        monkeypatch.setattr("app.core.llm.chat_json", must_not_be_called)
        result = cluster_skills_llm(NODES[:2], "Engineer")
        assert len(result.parents) == 2
        assert all(len(p.child_indices) == 1 for p in result.parents)
