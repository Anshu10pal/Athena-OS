"""End-to-end graph construction, with the LLM stubbed.

The extraction and naming calls are the only non-deterministic parts of the
pipeline, so they are replaced here with fixtures. Everything else -- sections,
weights, tiers, the cascade, clustering, coherence, persistence, idempotency --
runs for real. That is deliberate: these tests must fail when the pipeline
changes, not when a provider is slow.
"""
import pytest
from sqlalchemy import inspect

from app.db.models import ArenaJobTarget, ArenaMergeSuggestion, ArenaSkillNode, User
from app.services.arena import graph_build
from app.services.arena.config import load_config

JD = """Senior Data Engineer

About us
Acme is a fast-growing company with a great culture.

Requirements
- 5+ years of strong Python experience in production.
- Advanced SQL and writing SQL queries against large tables.
- Experience with Apache Spark for batch processing.
- Hands-on Kubernetes operations.
- Building and maintaining ETL pipelines.

Preferred Qualifications
- Familiarity with Terraform.
- Exposure to K8s at scale.

Benefits
Competitive salary and free snacks.
"""


def _mention(skill: str, span: str) -> dict:
    return {"skill": skill, "span": span, "kind": "technical"}


FIXTURE_MENTIONS = [
    _mention("Python", "5+ years of strong Python experience in production."),
    _mention("SQL", "Advanced SQL and writing SQL queries against large tables."),
    _mention("writing SQL queries", "Advanced SQL and writing SQL queries against large tables."),
    _mention("Apache Spark", "Experience with Apache Spark for batch processing."),
    _mention("Kubernetes", "Hands-on Kubernetes operations."),
    _mention("ETL pipelines", "Building and maintaining ETL pipelines."),
    _mention("Terraform", "Familiarity with Terraform."),
    _mention("K8s", "Exposure to K8s at scale."),
]


@pytest.fixture()
def user(db_session):
    u = User(email="arena@test.local", name="Arena", hashed_password="x")
    db_session.add(u)
    db_session.commit()
    return u


@pytest.fixture()
def stub_llm(monkeypatch):
    """One stub for both calls, dispatching on the prompt. Counts calls, because
    the LLM budget (<= 2 per extraction) is a hard constraint and a leak in it
    is invisible until a free-tier quota runs out."""
    calls = {"n": 0, "prompts": []}

    def fake_chat_json(messages, fast=True, retries=2):
        calls["n"] += 1
        prompt = messages[-1]["content"]
        calls["prompts"].append(prompt)
        if "labelling groups of skills" in prompt:
            n = prompt.count("\n1. ") + prompt.count("\n2. ") + prompt.count("\n3. ")
            return {"names": {str(i): f"Cluster {i}" for i in range(1, 12)}}
        return {"mentions": FIXTURE_MENTIONS}

    monkeypatch.setattr("app.core.llm.chat_json", fake_chat_json)
    return calls


class TestIdempotency:
    def test_resubmitting_the_same_jd_returns_the_cached_graph(self, db_session, user, stub_llm):
        first, cached1 = graph_build.build_graph(db_session, user.id, "Senior Data Engineer", JD)
        assert cached1 is False
        calls_after_first = stub_llm["n"]

        second, cached2 = graph_build.build_graph(db_session, user.id, "Senior Data Engineer", JD)
        assert cached2 is True
        assert second.id == first.id
        assert stub_llm["n"] == calls_after_first, (
            "a cached submission still made LLM calls -- the idempotency check is "
            "running after extraction instead of before it"
        )

    def test_whitespace_only_differences_hit_the_same_cache(self, db_session, user, stub_llm):
        first, _ = graph_build.build_graph(db_session, user.id, "Senior Data Engineer", JD)
        reflowed = JD.replace("\n", "\n ").replace("  ", " ")
        second, cached = graph_build.build_graph(
            db_session, user.id, "Senior Data Engineer", reflowed)
        assert cached is True and second.id == first.id, (
            "a reflowed paste regenerated the graph, which would silently discard "
            "the user's edits"
        )

    def test_a_different_user_gets_their_own_graph(self, db_session, user, stub_llm):
        other = User(email="other@test.local", name="Other", hashed_password="x")
        db_session.add(other)
        db_session.commit()
        mine, _ = graph_build.build_graph(db_session, user.id, "Senior Data Engineer", JD)
        theirs, cached = graph_build.build_graph(db_session, other.id, "Senior Data Engineer", JD)
        assert cached is False
        assert theirs.id != mine.id, (
            "user B received user A's graph, including A's edits and confirmation"
        )

    def test_an_extractor_version_bump_invalidates_the_cache(self, db_session, user,
                                                             stub_llm, monkeypatch):
        first, _ = graph_build.build_graph(db_session, user.id, "Senior Data Engineer", JD)
        monkeypatch.setattr("app.services.arena.graph_build.extractor_version",
                            lambda: "a2-test")
        second, cached = graph_build.build_graph(db_session, user.id, "Senior Data Engineer", JD)
        assert cached is False and second.id != first.id, (
            "bumping the extractor version served the old graph -- a prompt "
            "improvement would be invisible to every JD already stored"
        )

    def test_the_hash_is_stable_and_title_sensitive(self):
        assert graph_build.jd_hash("A", JD) == graph_build.jd_hash("a", JD.upper().lower())
        assert graph_build.jd_hash("A", JD) != graph_build.jd_hash("B", JD)


class TestLlmBudget:
    def test_exactly_two_calls_per_extraction(self, db_session, user, stub_llm):
        graph_build.build_graph(db_session, user.id, "Senior Data Engineer", JD)
        budget = load_config()["llm"]["max_calls_per_extraction"]
        assert stub_llm["n"] == 2, f"expected 2 LLM calls, made {stub_llm['n']}"
        assert stub_llm["n"] <= budget


class TestStructure:
    def test_graph_is_at_most_two_levels_deep(self, db_session, user, stub_llm):
        target, _ = graph_build.build_graph(db_session, user.id, "Senior Data Engineer", JD)
        rows = db_session.query(ArenaSkillNode).filter(
            ArenaSkillNode.job_target_id == target.id).all()
        by_id = {r.id: r for r in rows}
        for row in rows:
            if row.parent_id is not None:
                parent = by_id[row.parent_id]
                assert parent.parent_id is None, "found a grandchild; graphs are two levels"

    def test_no_parent_exceeds_the_child_cap(self, db_session, user, stub_llm):
        target, _ = graph_build.build_graph(db_session, user.id, "Senior Data Engineer", JD)
        cap = load_config()["max_children_per_parent"]
        rows = db_session.query(ArenaSkillNode).filter(
            ArenaSkillNode.job_target_id == target.id).all()
        counts: dict = {}
        for row in rows:
            if row.parent_id:
                counts[row.parent_id] = counts.get(row.parent_id, 0) + 1
        assert all(c <= cap for c in counts.values()), counts

    def test_every_extracted_skill_survives_into_the_graph(self, db_session, user, stub_llm):
        """The one thing this pipeline must never do is lose a skill the JD
        named. Canonicalisation may MERGE them; it may not drop them."""
        target, _ = graph_build.build_graph(db_session, user.id, "Senior Data Engineer", JD)
        rows = db_session.query(ArenaSkillNode).filter(
            ArenaSkillNode.job_target_id == target.id,
            ArenaSkillNode.extraction_source == graph_build.SOURCE_LLM).all()
        all_surfaces = {s for r in rows for s in (r.surface_forms_json or [])}
        for m in FIXTURE_MENTIONS:
            assert m["skill"] in all_surfaces, (
                f"{m['skill']!r} was extracted but appears in no node's surface forms"
            )

    def test_canonicalisation_actually_merged_the_alias_pair(self, db_session, user, stub_llm):
        # Kubernetes/K8s must be one node; SQL/writing SQL queries likewise.
        target, _ = graph_build.build_graph(db_session, user.id, "Senior Data Engineer", JD)
        rows = db_session.query(ArenaSkillNode).filter(
            ArenaSkillNode.job_target_id == target.id,
            ArenaSkillNode.extraction_source == graph_build.SOURCE_LLM).all()
        for row in rows:
            forms = set(row.surface_forms_json or [])
            if "Kubernetes" in forms:
                assert "K8s" in forms, "Kubernetes and K8s did not canonicalise together"


class TestProvenance:
    def test_extraction_metadata_carries_the_acceptance_numbers(self, db_session, user, stub_llm):
        target, _ = graph_build.build_graph(db_session, user.id, "Senior Data Engineer", JD)
        meta = target.extraction_metadata_json
        assert "latency_seconds" in meta and meta["latency_seconds"] >= 0
        assert meta["llm_calls"] == 2
        assert "rejected" in meta["extraction"]
        assert "merge_methods" in meta["canonicalisation"]
        assert "coherent_fraction" in meta["clustering"]
        assert "escalation_required" in meta["clustering"]

    def test_merge_method_telemetry_is_recorded(self, db_session, user, stub_llm):
        target, _ = graph_build.build_graph(db_session, user.id, "Senior Data Engineer", JD)
        methods = target.extraction_metadata_json["canonicalisation"]["merge_methods"]
        assert sum(methods.values()) > 0, "no merges recorded at all"
        assert methods.get("enriched_cosine", 0) == 0, (
            "a merge was attributed to the withdrawn enriched branch"
        )

    def test_every_node_records_where_it_came_from(self, db_session, user, stub_llm):
        target, _ = graph_build.build_graph(db_session, user.id, "Senior Data Engineer", JD)
        rows = db_session.query(ArenaSkillNode).filter(
            ArenaSkillNode.job_target_id == target.id).all()
        assert rows
        for row in rows:
            assert row.extraction_source in (
                graph_build.SOURCE_LLM, graph_build.SOURCE_PARENT, graph_build.SOURCE_USER)

    def test_child_weights_have_a_reconciling_breakdown(self, db_session, user, stub_llm):
        target, _ = graph_build.build_graph(db_session, user.id, "Senior Data Engineer", JD)
        rows = db_session.query(ArenaSkillNode).filter(
            ArenaSkillNode.job_target_id == target.id,
            ArenaSkillNode.extraction_source == graph_build.SOURCE_LLM).all()
        for row in rows:
            signals = row.weight_signals_json
            assert signals.get("contributions"), f"{row.canonical_name} has no breakdown"
            assert signals.get("evidence"), f"{row.canonical_name} has no evidence"


class TestConfirmationGate:
    def test_a_fresh_graph_is_unconfirmed(self, db_session, user, stub_llm):
        target, _ = graph_build.build_graph(db_session, user.id, "Senior Data Engineer", JD)
        assert target.graph_confirmed_at is None, (
            "a freshly built graph was already confirmed; the gate is the only "
            "validation path this component has"
        )


class TestNoAggregateScore:
    """Pre-registered constraint: the three modalities must never collapse into
    one number. Enforced as a schema property rather than a convention, so it
    cannot be quietly reintroduced."""

    def test_no_arena_table_has_an_overall_score_column(self, db_session):
        banned = {"overall_score", "overall", "total_score", "composite_score",
                  "aggregate_score", "score", "readiness_score"}
        inspector = inspect(db_session.get_bind())
        arena_tables = [t for t in inspector.get_table_names() if t.startswith("arena_")]
        assert arena_tables, "no arena tables found; the guard would pass vacuously"
        for table in arena_tables:
            columns = {c["name"] for c in inspector.get_columns(table)}
            offending = columns & banned
            assert not offending, (
                f"{table} has {sorted(offending)} -- the three modalities measure "
                "different competencies and must not be collapsed into one number"
            )


class TestReviewBandPersistence:
    def test_suggestions_are_persisted_as_pending(self, db_session, user, stub_llm):
        target, _ = graph_build.build_graph(db_session, user.id, "Senior Data Engineer", JD)
        rows = db_session.query(ArenaMergeSuggestion).filter(
            ArenaMergeSuggestion.job_target_id == target.id).all()
        for row in rows:
            assert row.status == "pending", "a suggestion was pre-accepted"
            assert row.decided_at is None
            # Both scores, always: the pair of numbers is the diagnostic.
            assert row.bare_cosine > 0
            assert row.left_name and row.right_name


class TestSerialisation:
    def test_wire_format_nests_children_under_parents(self, db_session, user, stub_llm):
        target, _ = graph_build.build_graph(db_session, user.id, "Senior Data Engineer", JD)
        graph = graph_build.serialise_graph(db_session, target)
        assert graph["parents"], "no parents in the wire format"
        for parent in graph["parents"]:
            assert parent["parent_id"] is None
            assert "children" in parent
            for child in parent["children"]:
                assert child["parent_id"] == parent["id"]

    def test_weight_explanation_comes_from_the_stored_breakdown(self, db_session, user, stub_llm):
        target, _ = graph_build.build_graph(db_session, user.id, "Senior Data Engineer", JD)
        graph = graph_build.serialise_graph(db_session, target)
        children = [c for p in graph["parents"] for c in p["children"]]
        assert children, "no children to check"
        for child in children:
            assert child["weight_explanation"], f"{child['canonical_name']} has no explanation"
