"""Phase 1 code health: scoring engine unit tests.

Covers the four things the contract makes load-bearing and which are easy to
erode silently: severity ramps, category/axis caps, N/A propagation, and the
direction of each axis. Pure -- no DB, no filesystem, no parser.
"""
import pytest

from app.services.codebase.health_scoring import (
    MARKER_NO_INPUT,
    AXIS_CAP,
    CATEGORY_CAPS,
    CHANGE_HOTSPOT,
    HIGHER_IS_BETTER,
    HIGHER_NEEDS_ATTENTION,
    MAINTAINABILITY,
    REVIEW_COST_FLOOR_NLOC,
    SUBSTANCE_FLOOR_NLOC,
    FileInputs,
    RepoContext,
    adjusted_exposure,
    build_repo_context,
    percentile,
    review_cost_units,
    score_architecture_health,
    score_change_hotspot,
    score_file,
    score_maintainability,
    severity_for,
)


def clean_file(**over) -> FileInputs:
    """A file that fires nothing, so a test can turn on exactly one marker."""
    base = dict(
        file_id=1, path="a.py", language="python", nloc=100,
        ast_available=True, function_count=3,
        max_cyclomatic=1, max_nesting=0, max_conditional_operands=0,
        max_function_nloc=5, broad_handler_count=0,
        graph_available=True, fan_in=0, fan_out=0,
        # 1 = a measured trivial component, i.e. analysed and NOT in a cycle.
        # Deliberately not None: None means "no graph-structure pass has run",
        # which now correctly withholds the Architecture score, and a baseline
        # "clean file" must represent fully-analysed clean, not unanalysed.
        cycle_size=1,
        commit_count=1,
    )
    base.update(over)
    return FileInputs(**base)


def ctx(**over) -> RepoContext:
    base = dict(
        churn_usable=True, churn_p50=1, churn_p95=10,
        fan_in_p90=20, fan_in_p99=40, fan_out_p90=10, fan_out_p99=25,
    )
    base.update(over)
    return RepoContext(**base)


def marker(axis_result, key):
    return next(m for m in axis_result.markers if m.key == key)


class TestSeverityRamp:
    def test_at_or_below_warn_is_zero(self):
        assert severity_for(10, 10, 25) == 0.0
        assert severity_for(3, 10, 25) == 0.0

    def test_at_or_above_saturate_is_one(self):
        assert severity_for(25, 10, 25) == 1.0
        assert severity_for(999, 10, 25) == 1.0

    def test_midpoint_is_half(self):
        assert severity_for(17.5, 10, 25) == pytest.approx(0.5)

    def test_ramp_is_linear_not_stepped(self):
        a = severity_for(13, 10, 25)
        b = severity_for(16, 10, 25)
        c = severity_for(19, 10, 25)
        assert b - a == pytest.approx(c - b)

    def test_degenerate_range_collapses_to_a_step_instead_of_dividing_by_zero(self):
        # Happens for real: a repo whose churn P50 and P95 coincide.
        assert severity_for(5, 4, 4) == 1.0
        assert severity_for(4, 4, 4) == 0.0


class TestCategoryAndAxisCaps:
    def test_category_cap_binds_and_is_reported(self):
        # Every complexity marker maxed: 2.5 + 1.5 + 1.0 = 5.0 raw, capped to 4.0.
        f = clean_file(max_cyclomatic=99, max_nesting=99, max_conditional_operands=99)
        r = score_maintainability(f)
        assert r.category_deductions["complexity"] == pytest.approx(4.0)
        assert "complexity" in r.categories_capped

    def test_uncapped_category_is_not_flagged_as_capped(self):
        f = clean_file(max_cyclomatic=17.5)  # one marker, mid-ramp
        r = score_maintainability(f)
        assert r.categories_capped == []

    def test_axis_cap_is_currently_inert_because_categories_already_bound_it(self):
        # Contract Â§2 documents AXIS_CAP as a forward guard that cannot bind
        # today. This pins that claim so it cannot become quietly false.
        assert sum(CATEGORY_CAPS[MAINTAINABILITY].values()) == pytest.approx(AXIS_CAP)
        f = clean_file(max_cyclomatic=99, max_nesting=99, max_conditional_operands=99,
                       max_function_nloc=999, nloc=9999, broad_handler_count=99)
        r = score_maintainability(f)
        assert r.total_deduction == pytest.approx(9.0)
        assert r.axis_capped is False  # equal to the cap is not over it

    def test_worst_possible_file_floors_at_one_not_zero(self):
        f = clean_file(max_cyclomatic=99, max_nesting=99, max_conditional_operands=99,
                       max_function_nloc=999, nloc=9999, broad_handler_count=99)
        assert score_maintainability(f).score == pytest.approx(1.0)

    def test_clean_file_scores_ten(self):
        assert score_maintainability(clean_file()).score == pytest.approx(10.0)


class TestDirection:
    def test_health_axes_expose_score_and_never_points(self):
        r = score_maintainability(clean_file())
        assert r.direction == HIGHER_IS_BETTER
        assert r.score is not None and r.points is None

        a = score_architecture_health(clean_file(), ctx())
        assert a.direction == HIGHER_IS_BETTER
        assert a.score is not None and a.points is None

    def test_hotspot_exposes_points_and_never_score(self):
        # The direction guard: a caller cannot read hotspot points as a health
        # score, because `score` is None.
        r = score_change_hotspot(clean_file(commit_count=10), ctx())
        assert r.direction == HIGHER_NEEDS_ATTENTION
        assert r.points is not None and r.score is None

    def test_more_churn_means_more_points_not_fewer(self):
        low = score_change_hotspot(clean_file(commit_count=1), ctx())
        high = score_change_hotspot(clean_file(commit_count=10), ctx())
        assert high.points > low.points

    def test_worse_code_means_a_lower_maintainability_score(self):
        good = score_maintainability(clean_file(max_cyclomatic=1))
        bad = score_maintainability(clean_file(max_cyclomatic=30))
        assert bad.score < good.score


class TestNaPropagation:
    def test_trivial_file_is_na_on_maintainability_and_hotspot(self):
        f = clean_file(nloc=SUBSTANCE_FLOOR_NLOC - 1, commit_count=5)
        assert score_maintainability(f).available is False
        assert score_change_hotspot(f, ctx()).available is False

    def test_trivial_file_still_gets_architecture_health(self):
        # Contract Â§5.1: a 5-line barrel can still sit in a cycle. Excluding it
        # would blind the axis to files that exist to matter structurally.
        f = clean_file(nloc=4, cycle_size=6)
        a = score_architecture_health(f, ctx())
        assert a.available is True
        assert a.score < 10.0

    def test_unsupported_language_is_na_not_a_perfect_score(self):
        f = clean_file(language="go", ast_available=False)
        r = score_maintainability(f)
        assert r.available is False
        assert r.score is None
        assert "go" in r.na_reason

    def test_na_marker_has_zero_deduction_but_is_not_available(self):
        # The pairing that stops aggregation mistaking absence for cleanliness.
        f = clean_file(function_count=0)
        m = marker(score_maintainability(f), "complex_method")
        assert m.available is False
        assert m.deduction == 0.0
        assert m.fired is False

    def test_file_with_no_functions_keeps_size_and_error_markers(self):
        f = clean_file(function_count=0, nloc=900, broad_handler_count=3)
        r = score_maintainability(f)
        assert marker(r, "complex_method").available is False
        assert marker(r, "large_method").available is False
        assert marker(r, "large_file").available is True
        assert marker(r, "broad_error_handling").available is True
        assert r.score < 10.0

    def test_no_graph_data_at_all_means_architecture_is_na(self):
        """Narrowed deliberately. This previously asserted that a missing
        fan-in/fan-out alone made the axis N/A; that gate discarded complete
        cycle data whenever the ranking pass had not run. It now takes BOTH
        inputs missing -- see TestArchitectureGateRequiresTheDominantMarkerOnly
        for the case that changed."""
        f = clean_file(graph_available=False, fan_in=None, fan_out=None, cycle_size=None)
        assert score_architecture_health(f, ctx()).available is False

    def test_degenerate_churn_makes_the_whole_hotspot_axis_na(self):
        r = score_change_hotspot(clean_file(), ctx(churn_usable=False,
                                                  churn_na_reason="shallow clone"))
        assert r.available is False
        assert r.points is None

    def test_file_without_history_is_na_and_says_so_neutrally(self):
        r = score_change_hotspot(clean_file(commit_count=0), ctx())
        assert r.available is False
        # Must not claim the file is new/uncommitted -- we never ran git status.
        assert r.na_reason == "No history available in this clone."


class TestRepoContext:
    def test_three_distinct_commit_counts_makes_churn_usable(self):
        files = [clean_file(commit_count=c) for c in (1, 2, 5)]
        assert build_repo_context(files).churn_usable is True

    def test_single_distinct_value_is_degenerate_with_a_shallow_clone_reason(self):
        files = [clean_file(commit_count=1) for _ in range(50)]
        c = build_repo_context(files)
        assert c.churn_usable is False
        assert "shallow clone" in c.churn_na_reason

    def test_two_distinct_values_is_still_degenerate(self):
        c = build_repo_context([clean_file(commit_count=1), clean_file(commit_count=2)])
        assert c.churn_usable is False
        assert "2 distinct" in c.churn_na_reason

    def test_percentiles_come_from_the_repo_not_a_constant(self):
        files = [clean_file(commit_count=c) for c in range(1, 101)]
        c = build_repo_context(files)
        assert c.churn_p50 == pytest.approx(50, abs=2)
        assert c.churn_p95 == pytest.approx(95, abs=2)

    def test_percentile_helper_handles_empty_and_single(self):
        assert percentile([], 50) == 0.0
        assert percentile([7], 90) == 7.0


class TestBidirectionalCouplingHub:
    def test_pure_high_fan_in_does_not_fire(self):
        # The reason it is not called a "hub": a heavily-imported utility that
        # imports nothing is not a finding.
        f = clean_file(fan_in=100, fan_out=0)
        assert marker(score_architecture_health(f, ctx()), "bidirectional_coupling_hub").deduction == 0.0

    def test_pure_high_fan_out_does_not_fire(self):
        f = clean_file(fan_in=0, fan_out=100)
        assert marker(score_architecture_health(f, ctx()), "bidirectional_coupling_hub").deduction == 0.0

    def test_high_on_both_sides_fires(self):
        f = clean_file(fan_in=40, fan_out=25)
        m = marker(score_architecture_health(f, ctx()), "bidirectional_coupling_hub")
        assert m.deduction > 0

    def test_reports_raw_value_alongside_repo_relative_thresholds(self):
        f = clean_file(fan_in=40, fan_out=25)
        m = marker(score_architecture_health(f, ctx()), "bidirectional_coupling_hub")
        assert m.raw_value == 25
        assert m.effective_warn == 10   # min(fan_in_p90=20, fan_out_p90=10)
        assert m.effective_saturate == 25  # min(fan_in_p99=40, fan_out_p99=25)


class TestComplexityUnderChurn:
    def test_needs_both_signals_not_just_one(self):
        # Complex but never changed, and churned but simple, both stay silent.
        complex_stable = clean_file(max_cyclomatic=30, commit_count=1)
        simple_churned = clean_file(max_cyclomatic=1, commit_count=10)
        for f in (complex_stable, simple_churned):
            m = marker(score_change_hotspot(f, ctx()), "complexity_under_churn")
            assert m.deduction == 0.0

    def test_fires_when_both_are_high(self):
        f = clean_file(max_cyclomatic=30, commit_count=10)
        m = marker(score_change_hotspot(f, ctx()), "complexity_under_churn")
        assert m.deduction > 0

    def test_trace_amounts_of_both_stay_below_the_warn_floor(self):
        # Why warn was raised from 0 to 0.2: otherwise this marker appears in
        # the explanation of nearly every file with any churn and any
        # complexity, as explanation noise.
        f = clean_file(max_cyclomatic=11, commit_count=2)
        m = marker(score_change_hotspot(f, ctx()), "complexity_under_churn")
        assert m.deduction == 0.0

    def test_is_na_when_complexity_cannot_be_measured(self):
        f = clean_file(ast_available=False, commit_count=10)
        m = marker(score_change_hotspot(f, ctx()), "complexity_under_churn")
        assert m.available is False


class TestEffortAwareRanking:
    def test_floor_stops_tiny_files_dominating(self):
        assert review_cost_units(4) == review_cost_units(REVIEW_COST_FLOOR_NLOC)

    def test_large_file_costs_proportionally_more_to_review(self):
        assert review_cost_units(600) == pytest.approx(6.0)

    def test_adjusted_exposure_ranks_a_small_risky_file_above_a_large_one(self):
        small = adjusted_exposure(4.0, 50)
        large = adjusted_exposure(4.0, 500)
        assert small > large

    def test_raw_and_adjusted_can_disagree_which_is_the_point(self):
        # A big file with more raw exposure can still be the worse use of a
        # fixed review budget than a small one -- both columns are shown.
        big_raw, big_nloc = 6.0, 1200
        small_raw, small_nloc = 3.0, 60
        assert big_raw > small_raw
        assert adjusted_exposure(small_raw, small_nloc) > adjusted_exposure(big_raw, big_nloc)


class TestArchitectureEvidenceGate:
    """Until file-level SCCs are persisted, Architecture Health is carried by
    one marker firing on ~1% of files and reports ~9.98. An inline caveat
    still leaves that number on screen anchoring the reader, so the value is
    withheld structurally instead."""

    def test_missing_cycle_data_withholds_the_score_entirely(self):
        f = clean_file(cycle_size=None)
        r = score_architecture_health(f, ctx())
        assert r.available is True            # the axis ran
        assert r.inputs_complete is False   # but on partial evidence
        assert r.score is None                # so there is nothing to render
        assert "cycle_participation" in r.missing_inputs

    def test_provisional_value_is_kept_for_diagnostics_only(self):
        r = score_architecture_health(clean_file(cycle_size=None), ctx())
        assert r.provisional_value is not None
        assert r.score is None  # and must not be swapped in by a caller

    def test_present_cycle_data_restores_a_real_score(self):
        r = score_architecture_health(clean_file(cycle_size=1), ctx())
        assert r.inputs_complete is True
        assert r.score == pytest.approx(10.0)
        assert r.missing_inputs == []

    def test_a_file_in_a_real_cycle_scores_below_ten(self):
        r = score_architecture_health(clean_file(cycle_size=8), ctx())
        assert r.inputs_complete is True
        assert r.score < 10.0

    def test_trivial_component_of_one_is_not_a_cycle(self):
        # scc_size == 1 is a measured "not in a cycle", distinct from None
        # meaning "never analysed" -- only the persisted difference lets the
        # scorer tell an absent measurement from a clean one.
        r = score_architecture_health(clean_file(cycle_size=1), ctx())
        assert marker(r, "cycle_participation").deduction == 0.0

    def test_other_axes_are_unaffected_by_the_architecture_gate(self):
        s = score_file(clean_file(cycle_size=None, commit_count=5), ctx())
        assert s.architecture_health.score is None
        assert s.maintainability.score is not None


class TestChurnResolutionBadge:
    def test_narrow_percentile_span_flags_limited_resolution(self):
        # repo 1's real shape: P50=1, P95=3 -- maximum exposure at three
        # commits. Ranking is fine; magnitude is not claimable.
        files = [clean_file(commit_count=c) for c in (0, 1, 1, 1, 2, 2, 3, 3)]
        c = build_repo_context(files)
        assert c.churn_usable is True
        assert c.churn_resolution_limited is True
        assert "Limited history resolution" in c.churn_resolution_note

    def test_wide_span_is_not_flagged(self):
        files = [clean_file(commit_count=c) for c in range(0, 100)]
        c = build_repo_context(files)
        assert c.churn_usable is True
        assert c.churn_resolution_limited is False
        assert c.churn_resolution_note is None

    def test_limited_resolution_does_not_make_the_axis_unavailable(self):
        # Deliberately a badge, not a gate -- withholding the ranking would
        # lose real signal, unlike the architecture case where the missing
        # marker was the dominant one.
        files = [clean_file(commit_count=c) for c in (0, 1, 1, 2, 3, 3)]
        c = build_repo_context(files)
        r = score_change_hotspot(clean_file(commit_count=3), c)
        assert r.available is True
        assert r.points is not None
        assert r.resolution_limited is True

    def test_the_badge_is_span_based_not_distinct_value_based(self):
        # Three distinct values pass the Â§5.2 gate, but 1..3 is too short a
        # ramp to grade with -- these are different questions.
        files = [clean_file(commit_count=c) for c in (1, 2, 3)]
        c = build_repo_context(files)
        assert c.churn_usable is True          # distinct-value gate passes
        assert c.churn_resolution_limited is True  # span gate does not


class TestScoreFile:
    def test_returns_all_three_axes_independently(self):
        s = score_file(clean_file(commit_count=5), ctx())
        assert {a.axis for a in s.axes()} == {
            "maintainability", "architecture_health", "change_hotspot"}

    def test_axes_are_independent_one_being_na_does_not_affect_the_others(self):
        # cycle_size=None as well as graph_available=False: since the gate
        # narrowed to the dominant marker, cycle data alone is enough to score
        # the axis, so making it genuinely N/A now takes both inputs missing.
        f = clean_file(graph_available=False, fan_in=None, fan_out=None, cycle_size=None,
                       commit_count=8, max_cyclomatic=20)
        s = score_file(f, ctx())
        assert s.architecture_health.available is False
        assert s.maintainability.available is True
        assert s.change_hotspot.available is True

    def test_there_is_no_combined_score_field(self):
        # Structural guard for "three axes, never blended".
        s = score_file(clean_file(), ctx())
        for banned in ("overall", "combined", "health_score", "total"):
            assert not hasattr(s, banned)


class TestArchitectureGateRequiresTheDominantMarkerOnly:
    """Cascade suppression, instance 5. The axis gated on fan-in/fan-out, which
    come from the ranking pass -- so when ranking failed on apache/superset,
    all 6,516 files reported Architecture Health N/A despite complete cycle
    data, 828 of them inside real import cycles with the largest spanning 604
    files. A 4.0-weight marker suppressed by a missing 3.0-weight one."""

    def _inputs(self, **over):
        base = dict(
            file_id=1, path="pkg/a.py", language="python", nloc=100,
            ast_available=True, function_count=2, max_cyclomatic=3,
            max_nesting=1, max_conditional_operands=1, max_function_nloc=20,
            broad_handler_count=0,
            graph_available=False, fan_in=None, fan_out=None, cycle_size=None,
            commit_count=None,
        )
        base.update(over)
        return FileInputs(**base)

    def test_cycle_data_alone_produces_a_score(self):
        f = self._inputs(cycle_size=604)
        result = score_architecture_health(f, RepoContext())
        assert result.available is True, (
            "a file known to sit in a 604-file import cycle must not report N/A "
            "because a different pass has not run"
        )
        assert result.score is not None

    def test_a_big_cycle_actually_deducts(self):
        clean = score_architecture_health(self._inputs(cycle_size=1), RepoContext())
        cyclic = score_architecture_health(self._inputs(cycle_size=604), RepoContext())
        assert cyclic.score < clean.score
        assert cyclic.score <= 6.01, "saturated cycle participation should hit the category cap"

    def test_the_missing_coupling_marker_is_declared_not_hidden(self):
        """Scoring without an input is only honest if the payload says so --
        otherwise this trades one silent misstatement for another."""
        result = score_architecture_health(self._inputs(cycle_size=3), RepoContext())
        assert result.inputs_complete is False
        assert "bidirectional_coupling_hub" in result.missing_inputs
        states = {m.key: m.state for m in result.markers}
        assert states["bidirectional_coupling_hub"] == MARKER_NO_INPUT

    def test_coupling_data_alone_still_produces_a_score(self):
        """Symmetric case: cycles not yet computed, ranking done."""
        ctx = RepoContext()
        ctx.fan_in_p90, ctx.fan_in_p99 = 5, 20
        ctx.fan_out_p90, ctx.fan_out_p99 = 5, 20
        f = self._inputs(graph_available=True, fan_in=2, fan_out=2, cycle_size=None)
        result = score_architecture_health(f, ctx)
        assert result.available is True
        assert "cycle_participation" in result.missing_inputs

    def test_neither_input_still_reports_na(self):
        """The gate did not disappear -- it narrowed. With no graph data at all
        there is genuinely nothing to say."""
        result = score_architecture_health(self._inputs(), RepoContext())
        assert result.available is False
        assert result.score is None

    def test_both_inputs_present_reports_complete(self):
        ctx = RepoContext()
        ctx.fan_in_p90, ctx.fan_in_p99 = 5, 20
        ctx.fan_out_p90, ctx.fan_out_p99 = 5, 20
        f = self._inputs(graph_available=True, fan_in=2, fan_out=2, cycle_size=1)
        result = score_architecture_health(f, ctx)
        assert result.inputs_complete is True
        assert result.missing_inputs == []
