"""Phase 4 groundwork: subsystem -> module -> topic -> resource.

Pure and unwired. These pin the SHAPE the preview returns, so the mapping can be
argued with before anything writes into tables holding hand-curated content.
"""
import pytest

from app.services.codebase import module_mapping as mm


def members(n, start_rank=1, prefix="pkg", category="source"):
    return [
        {"path": f"{prefix}/file{i}.py", "file_id": 100 + i,
         "rank": start_rank + i, "prior_category": category}
        for i in range(n)
    ]


class TestSlugs:
    def test_slug_is_lowercase_hyphenated(self):
        assert mm.slugify("Superset Frontend/Plugins") == "superset-frontend-plugins"

    def test_LOADBEARING_a_slug_never_exceeds_the_column(self):
        # modules.slug and topics.slug are both VARCHAR(120); real cluster
        # labels on superset run past it, so an untruncated slug would fail at
        # insert time -- long after the preview looked fine.
        long_label = "superset-frontend/packages/superset-ui-chart-controls/src/" \
                     "components/some/deeply/nested/thing/that/keeps/going/further"
        assert len(mm.slugify(long_label)) <= 120

    def test_truncation_lands_on_a_boundary(self):
        slug = mm.slugify("alpha-" * 40)
        assert len(slug) <= 120 and not slug.endswith("-")

    def test_an_empty_label_still_produces_a_slug(self):
        assert mm.slugify("") == "unnamed"
        assert mm.slugify("!!!") == "unnamed"


class TestTitles:
    def test_the_clusters_own_label_is_reused(self):
        assert mm.title_for("superset/views", 10) == "superset/views"

    def test_a_missing_label_falls_back_to_the_cluster_id(self):
        assert mm.title_for(None, 10) == "Cluster 10"
        assert mm.title_for("   ", 7) == "Cluster 7"


class TestTheRevisedMapping:
    """The correction that matters: files are RESOURCES, not topics. Mapping
    them to topics produced 932 topics in one module on superset, against a
    curated median of 7."""

    def test_LOADBEARING_files_become_resources_not_topics(self):
        m = mm.map_subsystem_to_module(
            repo_id=6, subsystem_id=10, subsystem_label="superset/views",
            member_count=40, members=members(40))

        assert m.resource_count == 40
        # Every file in one directory is one topic -- the count that would have
        # been 40 under the old mapping.
        assert len(m.topics) == 1
        assert all(r.kind == mm.RESOURCE_KIND for t in m.topics for r in t.resources)

    def test_topics_come_from_the_named_strategy(self):
        ms = (members(3, prefix="pkg/a") + members(3, prefix="pkg/b")
              + members(3, prefix="pkg/c"))
        m = mm.map_subsystem_to_module(
            repo_id=1, subsystem_id=1, subsystem_label="x",
            member_count=9, members=ms, topic_strategy="parent_directory")
        assert {t.title for t in m.topics} == {"pkg/a", "pkg/b", "pkg/c"}

    def test_an_unknown_strategy_is_refused_rather_than_defaulted(self):
        with pytest.raises(ValueError, match="unknown topic strategy"):
            mm.map_subsystem_to_module(
                repo_id=1, subsystem_id=1, subsystem_label="x",
                member_count=3, members=members(3), topic_strategy="vibes")

    def test_every_named_strategy_produces_a_valid_module(self):
        ms = (members(2, prefix="pkg/a", category="source")
              + members(2, prefix="pkg/b", category="config"))
        for name in mm.TOPIC_STRATEGIES:
            m = mm.map_subsystem_to_module(
                repo_id=1, subsystem_id=1, subsystem_label="x",
                member_count=4, members=ms, topic_strategy=name)
            assert m.resource_count == 4, name
            assert m.topics, name


class TestOrdering:
    def test_LOADBEARING_reading_rank_order_survives_into_resources(self):
        # The one piece of ordering here that is measured rather than invented.
        ms = [
            {"path": "pkg/c.py", "file_id": 3, "rank": 9, "prior_category": "source"},
            {"path": "pkg/a.py", "file_id": 1, "rank": 2, "prior_category": "source"},
            {"path": "pkg/b.py", "file_id": 2, "rank": 5, "prior_category": "source"},
        ]
        m = mm.map_subsystem_to_module(repo_id=1, subsystem_id=1, subsystem_label="x",
                                       member_count=3, members=ms)
        paths = [r.path for r in m.topics[0].resources]
        assert paths == ["pkg/a.py", "pkg/b.py", "pkg/c.py"]
        assert [r.order_index for r in m.topics[0].resources] == [0, 1, 2]

    def test_LOADBEARING_unranked_files_sort_last(self):
        ms = [
            {"path": "pkg/unranked.py", "file_id": 9, "rank": None, "prior_category": "source"},
            {"path": "pkg/ranked.py", "file_id": 1, "rank": 50, "prior_category": "source"},
        ]
        m = mm.map_subsystem_to_module(repo_id=1, subsystem_id=1, subsystem_label="x",
                                       member_count=2, members=ms, min_files=1)
        assert [r.path for r in m.topics[0].resources] == ["pkg/ranked.py", "pkg/unranked.py"]

    def test_topics_are_ordered_by_their_best_ranked_member(self):
        ms = [
            {"path": "late/x.py", "file_id": 1, "rank": 90, "prior_category": "source"},
            {"path": "early/y.py", "file_id": 2, "rank": 3, "prior_category": "source"},
        ]
        m = mm.map_subsystem_to_module(repo_id=1, subsystem_id=1, subsystem_label="x",
                                       member_count=2, members=ms, min_files=1)
        assert [t.title for t in m.topics] == ["early", "late"]
        assert [t.order_index for t in m.topics] == [0, 1]

    def test_DOCUMENTS_INTENT_absolute_rank_is_not_recoverable_from_order_index(self):
        """A real cost of moving files from topics to resources, recorded rather
        than absorbed: `resources` has no rank column, so relative order
        survives and "rank 3 of 398" does not. `rank` rides along in the
        PREVIEW payload only."""
        m = mm.map_subsystem_to_module(
            repo_id=1, subsystem_id=1, subsystem_label="x", member_count=3,
            members=[{"path": f"p/{i}.py", "file_id": i, "rank": 300 + i,
                      "prior_category": "source"} for i in range(3)])
        r = m.topics[0].resources[0]
        assert r.order_index == 0 and r.rank == 300
        assert "rank" not in mm.CandidateResource.__dataclass_fields__["order_index"].name


class TestSkipping:
    def test_LOADBEARING_a_tiny_cluster_is_skipped_WITH_a_reason(self):
        m = mm.map_subsystem_to_module(repo_id=1, subsystem_id=2, subsystem_label="pair",
                                       member_count=2, members=members(2))
        assert m.topics == [] and m.resource_count == 0
        assert m.skipped_reason and "minimum" in m.skipped_reason

    def test_the_summary_is_empty_rather_than_invented(self):
        m = mm.map_subsystem_to_module(repo_id=1, subsystem_id=1, subsystem_label="x",
                                       member_count=4, members=members(4))
        assert m.summary == ""

    def test_provenance_is_codebase_not_generated(self):
        # A codebase module has a commit SHA, can go stale and is regenerable;
        # an LLM-generated one has none of those properties.
        m = mm.map_subsystem_to_module(repo_id=1, subsystem_id=1, subsystem_label="x",
                                       member_count=4, members=members(4))
        assert m.source == "codebase" and m.kind == "codebase"


class TestSummary:
    def test_reports_distributions_against_the_curated_reference(self):
        mods = [
            mm.map_subsystem_to_module(repo_id=1, subsystem_id=i, subsystem_label=f"c{i}",
                                       member_count=n, members=members(n))
            for i, n in enumerate([10, 5, 2, 1])
        ]
        s = mm.summarise(mods, topic_strategy="parent_directory")
        assert s["modules_produced"] == 2
        assert s["subsystems_skipped"] == 2
        assert s["resources_per_module"]["max"] == 10
        assert s["curated_reference"]["topics_per_module"]["median"] == 7
        assert s["topic_strategy"] == "parent_directory"

    def test_empty_input_does_not_divide_by_zero(self):
        s = mm.summarise([], topic_strategy="parent_directory")
        assert s["modules_produced"] == 0
        assert s["topics_per_module"] is None
