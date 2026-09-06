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
        # An explicit multi-topic strategy: the DEFAULT is single_topic, which
        # has nothing to order. Topic ordering only means anything when a
        # grouping produced more than one.
        ms = [
            {"path": "late/x.py", "file_id": 1, "rank": 90, "prior_category": "source"},
            {"path": "early/y.py", "file_id": 2, "rank": 3, "prior_category": "source"},
        ]
        m = mm.map_subsystem_to_module(repo_id=1, subsystem_id=1, subsystem_label="x",
                                       member_count=2, members=ms, min_files=1,
                                       topic_strategy="parent_directory")
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


class TestMigrationExclusion:
    """Migrations are code nobody sits down to read -- node_priors.py already
    weights them at 0.15 for that reason. A module should not be built out of
    them at all, not merely rank them last."""

    def test_LOADBEARING_migration_files_produce_no_resources(self):
        mixed = members(4, category="source") + members(3, prefix="alembic/versions",
                                                         start_rank=100, category="migration")
        m = mm.map_subsystem_to_module(repo_id=1, subsystem_id=1, subsystem_label="x",
                                       member_count=7, members=mixed)
        assert m.resource_count == 4
        assert all(r.path.startswith("pkg/") for t in m.topics for r in t.resources)

    def test_excluded_migration_count_is_reported(self):
        mixed = members(4, category="source") + members(3, prefix="alembic/versions",
                                                         start_rank=100, category="migration")
        m = mm.map_subsystem_to_module(repo_id=1, subsystem_id=1, subsystem_label="x",
                                       member_count=7, members=mixed)
        assert m.excluded_migration_count == 3

    def test_a_group_that_is_entirely_migrations_is_skipped_with_a_reason(self):
        # This is superset's migrations/versions subsystem: 900 files, all
        # migrations. member_count alone (>= min_files) must not be enough to
        # produce a module out of files nobody reads.
        migrations = members(10, category="migration")
        m = mm.map_subsystem_to_module(repo_id=1, subsystem_id=1, subsystem_label="migrations",
                                       member_count=10, members=migrations)
        assert m.topics == [] and m.resource_count == 0
        assert m.skipped_reason and "migration" in m.skipped_reason

    def test_a_mostly_migration_group_below_the_floor_after_exclusion_is_skipped(self):
        # 5 total clears MIN_FILES_FOR_MODULE, but only 2 are usable.
        mixed = members(2, category="source") + members(3, prefix="alembic/versions",
                                                         start_rank=100, category="migration")
        m = mm.map_subsystem_to_module(repo_id=1, subsystem_id=1, subsystem_label="x",
                                       member_count=5, members=mixed)
        assert m.skipped_reason and "2 non-migration files" in m.skipped_reason
        assert m.excluded_migration_count == 3

    def test_member_count_still_reports_the_full_subsystem_size(self):
        # member_count must keep matching the Subsystems view's count for this
        # same group -- excluded_migration_count is what makes the gap honest,
        # not a silent change to what member_count means.
        mixed = members(4, category="source") + members(3, prefix="alembic/versions",
                                                         start_rank=100, category="migration")
        m = mm.map_subsystem_to_module(repo_id=1, subsystem_id=1, subsystem_label="x",
                                       member_count=7, members=mixed)
        assert m.member_count == 7

    def test_a_group_with_no_migrations_is_unaffected(self):
        m = mm.map_subsystem_to_module(repo_id=1, subsystem_id=1, subsystem_label="x",
                                       member_count=4, members=members(4))
        assert m.excluded_migration_count == 0
        assert m.resource_count == 4

    def test_unclustered_module_also_excludes_migrations(self):
        leftovers = members(2, category="source") + members(5, prefix="alembic/versions",
                                                             start_rank=100, category="migration")
        m = mm.unclustered_module(repo_id=1, members=leftovers, topic_strategy="single_topic")
        assert m is not None
        assert m.resource_count == 2
        assert m.excluded_migration_count == 5

    def test_to_dict_reports_the_excluded_count(self):
        mixed = members(4, category="source") + members(3, prefix="alembic/versions",
                                                         start_rank=100, category="migration")
        m = mm.map_subsystem_to_module(repo_id=1, subsystem_id=1, subsystem_label="x",
                                       member_count=7, members=mixed)
        assert m.to_dict()["excluded_migration_count"] == 3

    def test_summary_totals_migration_files_excluded_across_modules(self):
        mods = [
            mm.map_subsystem_to_module(
                repo_id=1, subsystem_id=i, subsystem_label=f"c{i}", member_count=7,
                members=members(4, category="source") + members(
                    3, prefix=f"alembic{i}/versions", start_rank=100, category="migration"),
            )
            for i in range(2)
        ]
        s = mm.summarise(mods, topic_strategy="single_topic")
        assert s["migration_files_excluded"] == 6


class TestCatalogueClassificationIsGone:
    """`classify_catalogue` and its two fixture-calibrated constants were
    removed on 2026-08-17 after measuring zero fires across 282 subsystems on
    three real repos (contract §17.27). These assertions exist so the removal
    is a decision the suite protects rather than something a later change can
    quietly reintroduce -- reviving it needs a real corpus where it fires,
    not a merge that puts the symbol back."""

    def test_the_classifier_and_its_constants_are_removed(self):
        for name in ("classify_catalogue", "CATALOGUE_MIN_MEMBERS",
                     "CATALOGUE_MAX_HUB_EXCLUDED_DENSITY"):
            assert not hasattr(mm, name), f"{name} is back -- see contract §17.27"

    def test_modules_no_longer_carry_an_is_catalogue_flag(self):
        m = mm.map_subsystem_to_module(repo_id=1, subsystem_id=1, subsystem_label="x",
                                       member_count=40, members=members(40))
        assert not hasattr(m, "is_catalogue")
        assert "is_catalogue" not in m.to_dict()

    def test_the_summary_no_longer_reports_a_flagged_count(self):
        a = mm.map_subsystem_to_module(repo_id=1, subsystem_id=1, subsystem_label="a",
                                       member_count=4, members=members(4))
        assert "modules_flagged_catalogue" not in mm.summarise(
            [a], topic_strategy="single_topic")


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


class TestStageGrouping:
    """Roadmap-preview groundwork: modules grouped by BFS-from-entry layer,
    the same depth the Layers view already computes and renders as "Layer N"
    columns (LayersView.tsx) -- one level up, modules instead of files."""

    def _module(self, subsystem_id, file_ids, ranks=None):
        ranks = ranks or list(range(len(file_ids)))
        mems = [{"path": f"pkg{subsystem_id}/f{i}.py", "file_id": fid, "rank": r,
                 "prior_category": "source"} for i, (fid, r) in enumerate(zip(file_ids, ranks))]
        return mm.map_subsystem_to_module(repo_id=1, subsystem_id=subsystem_id,
                                          subsystem_label=f"m{subsystem_id}",
                                          member_count=len(mems), members=mems, min_files=1)

    def test_LOADBEARING_a_module_s_stage_is_its_earliest_reachable_member(self):
        # File 1 is layer 0, file 2 is layer 3 -- the module must land in
        # stage 0, the earliest a reader could reach ANY of its files, not
        # its centre (best-ranked) file's own depth.
        m = self._module(1, [1, 2], ranks=[9, 1])  # file 2 (layer 3) ranks higher -> centre file
        layers = {1: 0, 2: 3}
        stages = mm.group_modules_into_stages([m], layers)
        assert [s["title"] for s in stages] == ["Layer 0"]

    def test_modules_land_in_different_stages_by_layer(self):
        a = self._module(1, [1])
        b = self._module(2, [2])
        stages = mm.group_modules_into_stages([a, b], {1: 0, 2: 1})
        assert [s["title"] for s in stages] == ["Layer 0", "Layer 1"]
        assert stages[0]["modules"] == [a]
        assert stages[1]["modules"] == [b]

    def test_LOADBEARING_a_module_with_no_reachable_member_is_unreachable_not_the_last_layer(self):
        reachable = self._module(1, [1])
        orphan = self._module(2, [2])
        stages = mm.group_modules_into_stages([reachable, orphan], {1: 5, 2: None})
        titles = [s["title"] for s in stages]
        assert titles == ["Layer 5", "Unreachable"]

    def test_a_file_id_missing_from_the_layer_map_entirely_counts_as_unknown(self):
        # Not every member file is guaranteed a layer entry (e.g. a file
        # dropped from the graph build) -- missing must behave like None,
        # not raise.
        m = self._module(1, [1, 2])
        stages = mm.group_modules_into_stages([m], {1: 2})  # file 2 absent
        assert stages[0]["title"] == "Layer 2"

    def test_skipped_modules_are_excluded_entirely(self):
        tiny = mm.map_subsystem_to_module(repo_id=1, subsystem_id=1, subsystem_label="tiny",
                                          member_count=1, members=members(1))
        assert tiny.skipped_reason is not None
        stages = mm.group_modules_into_stages([tiny], {})
        assert stages == []

    def test_stages_are_ordered_numerically_not_by_first_appearance(self):
        a = self._module(1, [1])
        b = self._module(2, [2])
        c = self._module(3, [3])
        stages = mm.group_modules_into_stages([c, a, b], {1: 0, 2: 1, 3: 2})
        assert [s["title"] for s in stages] == ["Layer 0", "Layer 1", "Layer 2"]

    def test_within_a_stage_modules_are_ordered_by_their_best_rank(self):
        a = self._module(1, [1], ranks=[50])
        b = self._module(2, [2], ranks=[3])
        stages = mm.group_modules_into_stages([a, b], {1: 0, 2: 0})
        assert stages[0]["modules"] == [b, a]

    def test_empty_input_produces_no_stages(self):
        assert mm.group_modules_into_stages([], {}) == []


class TestConditionalStagingBasis:
    """Layer staging assumes most of a repo is reachable from its entry
    points. Measured, that assumption holds on one of three real repos
    (Athena-OS 55.3%, eslint 26.9%, Superset 13.2%), so the basis has to be
    chosen from the graph rather than assumed."""

    def _module(self, subsystem_id, file_ids, ranks=None):
        ranks = ranks or list(range(len(file_ids)))
        mems = [{"path": f"pkg{subsystem_id}/f{i}.py", "file_id": fid, "rank": r,
                 "prior_category": "source"} for i, (fid, r) in enumerate(zip(file_ids, ranks))]
        return mm.map_subsystem_to_module(repo_id=1, subsystem_id=subsystem_id,
                                          subsystem_label=f"m{subsystem_id}",
                                          member_count=len(mems), members=mems, min_files=1)

    def test_layer_coverage_is_the_reachable_fraction(self):
        assert mm.layer_coverage({1: 0, 2: 1, 3: None, 4: None}) == 0.5
        assert mm.layer_coverage({}) == 0.0

    def test_high_coverage_uses_layers(self):
        a, b = self._module(1, [1]), self._module(2, [2])
        out = mm.stage_modules([a, b], {1: 0, 2: 1}, layer_coverage_threshold=0.4)
        assert out["basis"] == "layer"
        assert out["layer_coverage"] == 1.0
        assert [s["title"] for s in out["stages"]] == [
            "Layer 0 · from entry points", "Layer 1 · from entry points"]

    def test_LOADBEARING_low_coverage_uses_subsystem_depth_and_names_no_unreachable_stage(self):
        """Superset's case: 13.2% reachable is a ceiling of static analysis,
        not a fact about the code. Filing 87% of a repo under one stage
        called "Unreachable" would report the former as the latter."""
        a, b = self._module(1, [1]), self._module(2, [2])
        # b depends on a; only a is reachable, so coverage is 50% -> below 0.6
        out = mm.stage_modules([a, b], {1: 0, 2: None},
                               dependencies={2: {1}}, layer_coverage_threshold=0.6)
        assert out["basis"] == "subsystem"
        assert "Unreachable" not in [s["title"] for s in out["stages"]]
        assert [s["title"] for s in out["stages"]] == [
            "Stage 1 · by dependency", "Stage 2 · by dependency"]
        assert out["stages"][0]["modules"] == [a]
        assert out["stages"][1]["modules"] == [b]

    def test_stage_numbers_are_ordinal_not_raw_depth(self):
        """A real run produced longest-path depths 0, 1, 117, 118 -- printing
        those would imply 115 stages that never existed."""
        mods = [self._module(i, [i]) for i in (1, 2, 3)]
        # 3 depends on 2 depends on 1, so raw depths are 0, 1, 2 -- but drop
        # the middle module from the produced set and the survivors are 0 and 2.
        out = mm.stage_modules([mods[0], mods[2]], {1: None, 3: None},
                               dependencies={3: {2}, 2: {1}}, layer_coverage_threshold=0.6)
        assert [s["title"] for s in out["stages"]] == ["Stage 1 · by dependency"]

    def test_a_dependency_cycle_terminates(self):
        a, b = self._module(1, [1]), self._module(2, [2])
        out = mm.stage_modules([a, b], {1: None, 2: None},
                               dependencies={1: {2}, 2: {1}}, layer_coverage_threshold=0.6)
        assert out["basis"] == "subsystem"
        assert sum(len(s["modules"]) for s in out["stages"]) == 2

    def test_the_basis_reason_is_always_stated(self):
        a = self._module(1, [1])
        for layers, threshold in (({1: 0}, 0.4), ({1: None}, 0.4)):
            out = mm.stage_modules([a], layers, layer_coverage_threshold=threshold)
            assert out["basis_reason"]
            assert out["layer_coverage_threshold"] == threshold


class TestCapAndPaginate:
    """Cap and paginate rather than roll up.

    §17.17's first two instances had a hierarchy to roll up INTO. Files inside a
    module do not, so inventing intermediate groups would be manufacturing
    structure the analysis never found -- the same objection as splitting a
    122-file cycle by severity band. Reading rank orders them; the top N are
    shown; the total always travels."""

    def test_LOADBEARING_the_total_travels_with_a_truncated_list(self):
        # A truncated list whose total is not stated is the graph endpoint's old
        # "400 of 6,523" problem: a small module and a large one shown small are
        # indistinguishable.
        m = mm.map_subsystem_to_module(
            repo_id=1, subsystem_id=1, subsystem_label="big",
            member_count=151, members=members(151))
        t = m.to_dict()["topics"][0]

        assert t["resource_count"] == 151
        assert t["resources_shown"] == mm.RESOURCE_PREVIEW_LIMIT
        assert t["resources_truncated"] is True
        assert len(t["resources"]) == mm.RESOURCE_PREVIEW_LIMIT

    def test_a_short_list_is_not_marked_truncated(self):
        m = mm.map_subsystem_to_module(
            repo_id=1, subsystem_id=1, subsystem_label="small",
            member_count=5, members=members(5))
        t = m.to_dict()["topics"][0]
        assert t["resource_count"] == 5 and t["resources_shown"] == 5
        assert t["resources_truncated"] is False

    def test_LOADBEARING_the_shown_resources_are_the_best_ranked_ones(self):
        # "Read these first" is the whole point; a cap that showed an arbitrary
        # 20 would defeat it.
        ms = [{"path": f"p/f{i}.py", "file_id": i, "rank": 200 - i,
               "prior_category": "source"} for i in range(50)]
        m = mm.map_subsystem_to_module(repo_id=1, subsystem_id=1, subsystem_label="x",
                                       member_count=50, members=ms)
        shown = m.to_dict()["topics"][0]["resources"]
        assert [r["rank"] for r in shown] == sorted(r["rank"] for r in shown)
        assert shown[0]["rank"] == 151      # the best-ranked of the 50

    def test_limit_none_returns_everything(self):
        m = mm.map_subsystem_to_module(
            repo_id=1, subsystem_id=1, subsystem_label="big",
            member_count=151, members=members(151))
        t = m.to_dict(resource_limit=None)["topics"][0]
        assert t["resources_shown"] == 151 and t["resources_truncated"] is False

    def test_the_full_model_always_keeps_every_resource(self):
        """The cap is a PREVIEW concern. Truncating the model would make
        resource_count a lie and lose files on the way to the database."""
        m = mm.map_subsystem_to_module(
            repo_id=1, subsystem_id=1, subsystem_label="big",
            member_count=151, members=members(151))
        assert m.resource_count == 151
        assert len(m.topics[0].resources) == 151


class TestSingleTopicDefault:
    """A zero-topic module is not available: `resources.topic_id` is NOT NULL,
    so a resource cannot exist without a topic. Given one must exist, the choice
    is between inventing a grouping and declining to."""

    def test_the_default_is_one_topic_holding_everything(self):
        m = mm.map_subsystem_to_module(
            repo_id=1, subsystem_id=1, subsystem_label="x",
            member_count=40, members=members(40, prefix="a/b"))
        assert len(m.topics) == 1
        assert m.topics[0].title == "Files"
        assert m.resource_count == 40

    def test_LOADBEARING_single_topic_does_not_invent_groups_from_paths(self):
        # parent_directory on this input finds three "concepts" that are three
        # directories; single_topic reports one module with no sub-structure,
        # which is what the analysis actually found.
        ms = (members(3, prefix="a") + members(3, prefix="b") + members(3, prefix="c"))
        single = mm.map_subsystem_to_module(
            repo_id=1, subsystem_id=1, subsystem_label="x", member_count=9,
            members=ms, topic_strategy="single_topic")
        grouped = mm.map_subsystem_to_module(
            repo_id=1, subsystem_id=1, subsystem_label="x", member_count=9,
            members=ms, topic_strategy="parent_directory")

        assert len(single.topics) == 1
        assert len(grouped.topics) == 3
        assert single.resource_count == grouped.resource_count == 9


class TestUnclusteredModule:
    """Files from below-floor subsystems are gathered, not dropped. A
    skipped_reason keeps the COUNTS honest; it does not keep the FILES."""

    def test_leftover_files_become_one_module(self):
        m = mm.unclustered_module(repo_id=7, members=members(5))
        assert m is not None
        assert m.title == "Unclustered"
        assert m.slug == "unclustered-7"
        assert m.resource_count == 5
        assert m.skipped_reason is None

    def test_LOADBEARING_the_file_floor_does_not_apply_to_it(self):
        # The floor is what put these files here; applying it again would drop
        # them a second time.
        m = mm.unclustered_module(repo_id=1, members=members(2))
        assert m is not None and m.resource_count == 2

    def test_nothing_left_over_produces_no_module(self):
        assert mm.unclustered_module(repo_id=1, members=[]) is None


class TestTitleDisambiguation:
    """Three of eslint's eight modules are titled `lib/rules`. Slugs differ,
    which prevents a collision and does nothing for a reader.

    I3's labelling problem one level up: dominant-prefix is the title and the
    centre file was already the SUBTITLE, so the ambiguous case is where the
    subtitle earns its keep."""

    def _module(self, sid, label, paths_and_ranks):
        return mm.map_subsystem_to_module(
            repo_id=1, subsystem_id=sid, subsystem_label=label,
            member_count=len(paths_and_ranks),
            members=[{"path": p, "file_id": i, "rank": r, "prior_category": "source"}
                     for i, (p, r) in enumerate(paths_and_ranks)])

    def test_LOADBEARING_shared_titles_gain_their_centre_file(self):
        a = self._module(1, "lib/rules", [("lib/rules/index.js", 12),
                                          ("lib/rules/eqeqeq.js", 90),
                                          ("lib/rules/semi.js", 91)])
        b = self._module(2, "lib/rules", [("lib/rules/utils/ast-utils.js", 30),
                                          ("lib/rules/utils/keywords.js", 95),
                                          ("lib/rules/utils/fix-tracker.js", 96)])

        mm.disambiguate_titles([a, b])

        assert a.title == "lib/rules · index"
        assert b.title == "lib/rules · ast-utils"
        assert a.title != b.title

    def test_LOADBEARING_an_unambiguous_title_is_left_alone(self):
        # Only where the prefix is not unique. A module whose name already
        # identifies it does not get a suffix it did not need.
        a = self._module(1, "lib/rules", [("lib/rules/index.js", 12),
                                          ("lib/rules/a.js", 20), ("lib/rules/b.js", 21)])
        b = self._module(2, "lib/shared", [("lib/shared/x.js", 30),
                                           ("lib/shared/y.js", 31), ("lib/shared/z.js", 32)])

        mm.disambiguate_titles([a, b])

        assert a.title == "lib/rules"
        assert b.title == "lib/shared"

    def test_the_centre_file_is_the_best_RANKED_member(self):
        m = self._module(1, "x", [("p/low.js", 400), ("p/best.js", 3), ("p/mid.js", 50)])
        assert m.centre_file == "p/best.js"

    def test_the_stem_drops_the_directory_and_the_extension(self):
        a = self._module(1, "dup", [("deep/nested/path/thing.test.js", 5),
                                    ("deep/a.js", 6), ("deep/b.js", 7)])
        b = self._module(2, "dup", [("other/second.py", 8),
                                    ("other/c.py", 9), ("other/d.py", 10)])
        mm.disambiguate_titles([a, b])
        assert a.title == "dup · thing.test"
        assert b.title == "dup · second"

    def test_slugs_stay_unique_and_within_the_column(self):
        a = self._module(1, "lib/rules", [("lib/rules/index.js", 12),
                                          ("lib/rules/a.js", 20), ("lib/rules/b.js", 21)])
        b = self._module(2, "lib/rules", [("lib/rules/utils/ast-utils.js", 30),
                                          ("lib/rules/utils/c.js", 31), ("lib/rules/utils/d.js", 32)])
        mm.disambiguate_titles([a, b])
        assert a.slug != b.slug
        assert len(a.slug) <= 120 and len(b.slug) <= 120

    def test_a_skipped_module_has_no_centre_and_is_not_renamed(self):
        # Below the floor, so it has no resources to be centred on. Renaming it
        # with an empty stem would produce a trailing separator.
        skipped = mm.map_subsystem_to_module(
            repo_id=1, subsystem_id=3, subsystem_label="dup",
            member_count=2, members=members(2))
        other = self._module(4, "dup", [("p/a.js", 1), ("p/b.js", 2), ("p/c.js", 3)])

        mm.disambiguate_titles([skipped, other])

        assert skipped.centre_file is None
        assert skipped.title == "dup"

    def test_three_way_collision_disambiguates_all_three(self):
        mods = [
            self._module(i, "lib/rules",
                         [(f"lib/rules/{name}.js", rank), (f"lib/rules/{name}_b.js", rank + 1),
                          (f"lib/rules/{name}_c.js", rank + 2)])
            for i, (name, rank) in enumerate([("index", 12), ("eqeqeq", 40), ("semi", 70)])
        ]
        mm.disambiguate_titles(mods)
        assert len({m.title for m in mods}) == 3
        assert all(" · " in m.title for m in mods)
