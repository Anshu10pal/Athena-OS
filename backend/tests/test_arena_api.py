"""Interview Arena endpoints.

Calls the route functions directly with a real `db_session`, matching the
convention already established by tests/test_repos_api.py -- this app has no
TestClient-based API tests and adding one testing style for one router would
make the suite harder to read, not easier.
"""
import pytest
from fastapi import HTTPException

from app.api.arena import (create_job_target, decide_merge_suggestion, get_job_target,
                           list_job_targets, patch_graph, readiness)
from app.db.models import ArenaMergeSuggestion, ArenaSkillNode, User
from app.db.schemas import (ArenaGraphPatchIn, ArenaJobTargetIn, ArenaMergeDecisionIn,
                            ArenaNodeAddIn, ArenaNodeUpdateIn)
from app.services.arena import graph_build
from tests.test_arena_graph_build import JD, FIXTURE_MENTIONS  # noqa: F401


@pytest.fixture()
def user(db_session):
    u = User(email="api@test.local", name="Api", hashed_password="x")
    db_session.add(u)
    db_session.commit()
    return u


@pytest.fixture()
def other_user(db_session):
    u = User(email="other-api@test.local", name="Other", hashed_password="x")
    db_session.add(u)
    db_session.commit()
    return u


@pytest.fixture()
def stub_llm(monkeypatch):
    def fake_chat_json(messages, fast=True, retries=2):
        prompt = messages[-1]["content"]
        if "labelling groups of skills" in prompt:
            return {"names": {str(i): f"Cluster {i}" for i in range(1, 12)}}
        return {"mentions": FIXTURE_MENTIONS}
    monkeypatch.setattr("app.core.llm.chat_json", fake_chat_json)


@pytest.fixture()
def graph(db_session, user, stub_llm):
    return create_job_target(
        ArenaJobTargetIn(title="Senior Data Engineer", jd_text=JD), user, db_session)


class TestCreate:
    def test_returns_a_graph_with_parents(self, graph):
        assert graph["id"] and graph["parents"]
        assert graph["cached"] is False
        assert graph["graph_confirmed_at"] is None

    def test_second_submission_is_marked_cached(self, db_session, user, stub_llm, graph):
        again = create_job_target(
            ArenaJobTargetIn(title="Senior Data Engineer", jd_text=JD), user, db_session)
        assert again["cached"] is True and again["id"] == graph["id"]

    def test_a_too_short_jd_is_refused(self, db_session, user, stub_llm):
        with pytest.raises(HTTPException) as exc:
            create_job_target(ArenaJobTargetIn(title="x", jd_text="Python"), user, db_session)
        assert exc.value.status_code == 422


class TestOwnership:
    def test_another_user_cannot_read_the_graph(self, db_session, other_user, graph):
        with pytest.raises(HTTPException) as exc:
            get_job_target(graph["id"], other_user, db_session)
        assert exc.value.status_code == 404

    def test_another_user_cannot_patch_the_graph(self, db_session, other_user, graph):
        with pytest.raises(HTTPException) as exc:
            patch_graph(graph["id"], ArenaGraphPatchIn(confirm=True), other_user, db_session)
        assert exc.value.status_code == 404

    def test_listing_is_scoped_to_the_caller(self, db_session, user, other_user, graph):
        assert len(list_job_targets(user, db_session)) == 1
        assert list_job_targets(other_user, db_session) == []


class TestEdits:
    def _first_child(self, graph):
        for parent in graph["parents"]:
            if parent["children"]:
                return parent["children"][0]
        return graph["parents"][0]

    def test_rename_sets_user_edited(self, db_session, user, graph):
        child = self._first_child(graph)
        result = patch_graph(
            graph["id"],
            ArenaGraphPatchIn(updates=[ArenaNodeUpdateIn(id=child["id"],
                                                        canonical_name="Renamed Skill")]),
            user, db_session)
        assert result["edits_applied"] == 1
        row = db_session.get(ArenaSkillNode, child["id"])
        assert row.canonical_name == "Renamed Skill"
        assert row.user_edited is True, (
            "the edit flag was not set -- this is the only correction signal this "
            "component will ever get"
        )

    def test_an_empty_name_is_refused(self, db_session, user, graph):
        child = self._first_child(graph)
        with pytest.raises(HTTPException) as exc:
            patch_graph(graph["id"],
                        ArenaGraphPatchIn(updates=[ArenaNodeUpdateIn(id=child["id"],
                                                                     canonical_name="   ")]),
                        user, db_session)
        assert exc.value.status_code == 422

    def test_a_hand_set_weight_stops_claiming_a_signal_derivation(self, db_session, user, graph):
        child = self._first_child(graph)
        patch_graph(graph["id"],
                    ArenaGraphPatchIn(updates=[ArenaNodeUpdateIn(id=child["id"], jd_weight=0.9)]),
                    user, db_session)
        row = db_session.get(ArenaSkillNode, child["id"])
        assert row.jd_weight == pytest.approx(0.9)
        assert row.weight_signals_json["derivation"] == "set by user", (
            "a user-set weight kept the model's breakdown, so the UI would explain "
            "a hand-typed number with arithmetic that did not produce it"
        )
        assert "previous" in row.weight_signals_json

    def test_out_of_range_weight_is_refused(self, db_session, user, graph):
        child = self._first_child(graph)
        with pytest.raises(HTTPException) as exc:
            patch_graph(graph["id"],
                        ArenaGraphPatchIn(updates=[ArenaNodeUpdateIn(id=child["id"],
                                                                     jd_weight=1.7)]),
                        user, db_session)
        assert exc.value.status_code == 422

    def test_unknown_tier_is_refused(self, db_session, user, graph):
        child = self._first_child(graph)
        with pytest.raises(HTTPException) as exc:
            patch_graph(graph["id"],
                        ArenaGraphPatchIn(updates=[ArenaNodeUpdateIn(id=child["id"],
                                                                     target_tier="wizard")]),
                        user, db_session)
        assert exc.value.status_code == 422

    def test_deleting_a_parent_reparents_rather_than_cascading(self, db_session, user, graph):
        parent = next(p for p in graph["parents"] if p["children"])
        child_ids = [c["id"] for c in parent["children"]]
        patch_graph(graph["id"], ArenaGraphPatchIn(deletes=[parent["id"]]), user, db_session)
        for child_id in child_ids:
            row = db_session.get(ArenaSkillNode, child_id)
            assert row is not None, (
                "deleting a parent deleted the skills under it -- those came from "
                "the JD and losing them is the one thing this pipeline must not do"
            )
            assert row.parent_id is None

    def test_a_node_cannot_become_its_own_parent(self, db_session, user, graph):
        child = self._first_child(graph)
        with pytest.raises(HTTPException) as exc:
            patch_graph(graph["id"],
                        ArenaGraphPatchIn(updates=[ArenaNodeUpdateIn(id=child["id"],
                                                                     parent_id=child["id"])]),
                        user, db_session)
        assert exc.value.status_code == 422

    def test_reparenting_under_a_child_is_refused(self, db_session, user, graph):
        parent = next(p for p in graph["parents"] if p["children"])
        child = parent["children"][0]
        sibling_parent = next(p for p in graph["parents"] if p["id"] != parent["id"])
        with pytest.raises(HTTPException) as exc:
            patch_graph(graph["id"],
                        ArenaGraphPatchIn(updates=[ArenaNodeUpdateIn(id=sibling_parent["id"],
                                                                     parent_id=child["id"])]),
                        user, db_session)
        assert exc.value.status_code == 422
        assert "two levels" in exc.value.detail

    def test_parent_id_zero_promotes_to_top_level(self, db_session, user, graph):
        parent = next(p for p in graph["parents"] if p["children"])
        child = parent["children"][0]
        patch_graph(graph["id"],
                    ArenaGraphPatchIn(updates=[ArenaNodeUpdateIn(id=child["id"], parent_id=0)]),
                    user, db_session)
        assert db_session.get(ArenaSkillNode, child["id"]).parent_id is None

    def test_added_nodes_are_attributed_to_the_user(self, db_session, user, graph):
        result = patch_graph(
            graph["id"],
            ArenaGraphPatchIn(additions=[ArenaNodeAddIn(canonical_name="Rust")]),
            user, db_session)
        assert result["edits_applied"] == 1
        row = db_session.query(ArenaSkillNode).filter(
            ArenaSkillNode.canonical_name == "Rust").one()
        assert row.extraction_source == graph_build.SOURCE_USER, (
            "a user-added skill was recorded as one the model extracted, which "
            "corrupts the hallucination count"
        )
        assert row.user_edited is True


class TestConfirmationGate:
    def test_readiness_blocks_before_confirmation(self, db_session, user, graph):
        state = readiness(graph["id"], user, db_session)
        assert state["confirmed"] is False
        assert state["can_start"] is False
        assert state["blocking_reason"]

    def test_confirming_opens_the_gate(self, db_session, user, graph):
        patch_graph(graph["id"], ArenaGraphPatchIn(confirm=True), user, db_session)
        state = readiness(graph["id"], user, db_session)
        assert state["confirmed"] is True and state["can_start"] is True
        assert state["blocking_reason"] is None

    def test_pending_suggestions_do_not_block_starting(self, db_session, user, graph):
        patch_graph(graph["id"], ArenaGraphPatchIn(confirm=True), user, db_session)
        state = readiness(graph["id"], user, db_session)
        # An undecided pair simply stays unmerged, which is the safe default.
        # Forcing a decision on each would make the gate a chore rather than a check.
        assert state["can_start"] is True

    def test_an_empty_graph_cannot_be_confirmed(self, db_session, user, graph):
        all_ids = [p["id"] for p in graph["parents"]] + [
            c["id"] for p in graph["parents"] for c in p["children"]]
        with pytest.raises(HTTPException) as exc:
            patch_graph(graph["id"],
                        ArenaGraphPatchIn(deletes=all_ids, confirm=True), user, db_session)
        assert exc.value.status_code == 422


class TestMergeSuggestions:
    def _suggestion(self, db_session, graph):
        return db_session.query(ArenaMergeSuggestion).filter(
            ArenaMergeSuggestion.job_target_id == graph["id"]).first()

    def test_rejection_is_recorded_as_labelled_data(self, db_session, user, graph):
        suggestion = self._suggestion(db_session, graph)
        if suggestion is None:
            pytest.skip("no review-band pair in this fixture")
        before = db_session.query(ArenaSkillNode).filter(
            ArenaSkillNode.job_target_id == graph["id"]).count()
        decide_merge_suggestion(graph["id"], suggestion.id,
                                ArenaMergeDecisionIn(decision="rejected"), user, db_session)
        row = db_session.get(ArenaMergeSuggestion, suggestion.id)
        assert row.status == "rejected"
        assert row.decided_at is not None, (
            "a rejection without a timestamp is not usable as labelled data"
        )
        after = db_session.query(ArenaSkillNode).filter(
            ArenaSkillNode.job_target_id == graph["id"]).count()
        assert after == before, "a rejection changed the graph"

    def test_acceptance_merges_and_is_attributed_to_the_user(self, db_session, user, graph):
        suggestion = self._suggestion(db_session, graph)
        if suggestion is None:
            pytest.skip("no review-band pair in this fixture")
        before = db_session.query(ArenaSkillNode).filter(
            ArenaSkillNode.job_target_id == graph["id"]).count()
        decide_merge_suggestion(graph["id"], suggestion.id,
                                ArenaMergeDecisionIn(decision="accepted"), user, db_session)
        after = db_session.query(ArenaSkillNode).filter(
            ArenaSkillNode.job_target_id == graph["id"]).count()
        assert after == before - 1
        survivors = db_session.query(ArenaSkillNode).filter(
            ArenaSkillNode.job_target_id == graph["id"]).all()
        methods = {e.get("method") for r in survivors for e in (r.merge_evidence_json or [])}
        assert "user" in methods, (
            "a user-accepted merge was not recorded as METHOD_USER, so the "
            "branch-firing telemetry now counts it as a cascade decision"
        )

    def test_an_invalid_decision_is_refused(self, db_session, user, graph):
        suggestion = self._suggestion(db_session, graph)
        if suggestion is None:
            pytest.skip("no review-band pair in this fixture")
        with pytest.raises(HTTPException) as exc:
            decide_merge_suggestion(graph["id"], suggestion.id,
                                    ArenaMergeDecisionIn(decision="maybe"), user, db_session)
        assert exc.value.status_code == 422
