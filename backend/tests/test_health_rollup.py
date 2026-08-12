"""Directory and cohort rollups over stored health rows.

These are re-aggregations, not measurements, so the properties worth pinning
are the ones an aggregate silently breaks: N/A handling one level up, sample
size in rankings, and refusing to invent a cohort when the data cannot support
one.
"""
from dataclasses import dataclass
from typing import Optional

import pytest

from app.services.codebase.health_rollup import (
    MIN_FILES_TO_RANK,
    ROOT,
    ancestors_of,
    directory_rollup,
    hot_cohort,
    weakest_directories,
)
from app.services.codebase.health_scoring import ARCHITECTURE, CHANGE_HOTSPOT, MAINTAINABILITY


@dataclass
class Row:
    """Stands in for CodeFileHealth -- the rollup only ever reads these
    attributes, and using the real model would drag in a DB for a pure
    function."""
    path: str
    nloc: int = 100
    maintainability: Optional[float] = 10.0
    architecture_health: Optional[float] = 10.0
    change_hotspot_points: Optional[float] = 0.0
    file_id: int = 0


class TestAncestors:
    def test_every_containing_directory_outermost_first(self):
        assert ancestors_of("backend/app/api/repos.py") == [
            "backend", "backend/app", "backend/app/api",
        ]

    def test_a_root_file_belongs_only_to_the_root_sentinel(self):
        assert ancestors_of("run.py") == [ROOT]

    def test_single_directory(self):
        assert ancestors_of("tests/test_thing.py") == ["tests"]


class TestDirectoryAggregation:
    def test_a_file_counts_at_every_level_above_it(self):
        rows = [Row("backend/app/api/repos.py")]
        by_path = {d.path: d for d in directory_rollup(rows)}
        assert set(by_path) == {"backend", "backend/app", "backend/app/api"}
        for d in by_path.values():
            assert d.files_total == 1

    def test_weighted_mean_follows_size_not_file_count(self):
        """Twenty tiny perfect files must not bury one large bad one -- that is
        the failure the size weighting exists to prevent."""
        rows = [Row(f"pkg/small{i}.py", nloc=5, maintainability=10.0) for i in range(20)]
        rows.append(Row("pkg/huge.py", nloc=2000, maintainability=2.0))
        d = directory_rollup(rows)[0]
        m = d.axes[MAINTAINABILITY]

        assert m.mean > 9.5, "unweighted mean is dominated by file count"
        assert m.weighted_mean < 3.0, "weighted mean must follow where the code actually is"

    def test_unweighted_mean_is_reported_alongside(self):
        """Both are kept precisely because they diverge -- the divergence is
        the signal that one file dominates."""
        rows = [Row("pkg/a.py", nloc=10, maintainability=10.0),
                Row("pkg/b.py", nloc=990, maintainability=4.0)]
        m = directory_rollup(rows)[0].axes[MAINTAINABILITY]
        assert m.mean == 7.0
        assert m.weighted_mean < 4.1

    def test_worst_file_is_named(self):
        rows = [Row("pkg/fine.py", maintainability=9.0),
                Row("pkg/bad.py", maintainability=3.0)]
        m = directory_rollup(rows)[0].axes[MAINTAINABILITY]
        assert m.worst == 3.0
        assert m.worst_path == "pkg/bad.py"

    def test_worst_means_highest_for_change_hotspot(self):
        """Direction is per axis: hotspot points run the other way, so 'worst'
        is the maximum. Taking the minimum would name the calmest file as the
        one most worth reviewing."""
        rows = [Row("pkg/calm.py", change_hotspot_points=0.5),
                Row("pkg/busy.py", change_hotspot_points=6.0)]
        h = directory_rollup(rows)[0].axes[CHANGE_HOTSPOT]
        assert h.worst == 6.0
        assert h.worst_path == "pkg/busy.py"

    def test_nloc_totals_are_summed_per_directory(self):
        rows = [Row("a/x.py", nloc=100), Row("a/b/y.py", nloc=50)]
        by_path = {d.path: d for d in directory_rollup(rows)}
        assert by_path["a"].nloc == 150
        assert by_path["a/b"].nloc == 50

    def test_max_depth_prunes_deeper_directories(self):
        rows = [Row("a/b/c/d.py")]
        paths = {d.path for d in directory_rollup(rows, max_depth=2)}
        assert paths == {"a", "a/b"}

    def test_ordering_is_outermost_first_then_alphabetical(self):
        rows = [Row("z/one.py"), Row("a/b/two.py"), Row("a/three.py")]
        assert [d.path for d in directory_rollup(rows)] == ["a", "z", "a/b"]


class TestNAHandling:
    """Exclude-don't-zero, one level up. An aggregate that averages a None as
    zero undoes the discipline the engine spent its whole design on."""

    def test_na_files_are_excluded_from_averages_not_scored_zero(self):
        rows = [Row("pkg/scored.py", maintainability=8.0),
                Row("pkg/na.py", maintainability=None)]
        m = directory_rollup(rows)[0].axes[MAINTAINABILITY]
        assert m.mean == 8.0, "an N/A file must not drag the mean toward zero"
        assert m.files_scored == 1
        assert m.files_na == 1

    def test_na_files_are_not_given_full_marks_either(self):
        rows = [Row("pkg/scored.py", maintainability=4.0),
                Row("pkg/na.py", maintainability=None)]
        m = directory_rollup(rows)[0].axes[MAINTAINABILITY]
        assert m.mean == 4.0, "an N/A file must not lift the mean toward 10 either"

    def test_a_fully_na_directory_reports_no_score_at_all(self):
        rows = [Row("pkg/a.py", maintainability=None), Row("pkg/b.py", maintainability=None)]
        m = directory_rollup(rows)[0].axes[MAINTAINABILITY]
        assert m.weighted_mean is None and m.mean is None and m.worst is None
        assert m.files_na == 2

    def test_counts_travel_with_the_number(self):
        """A directory reporting 9.8 across 2 of 40 files must say so, or the
        number reads as though it described all 40."""
        rows = [Row(f"pkg/na{i}.py", maintainability=None) for i in range(38)]
        rows += [Row("pkg/a.py", maintainability=9.8), Row("pkg/b.py", maintainability=9.8)]
        m = directory_rollup(rows)[0].axes[MAINTAINABILITY]
        assert (m.files_scored, m.files_na) == (2, 38)

    def test_zero_nloc_falls_back_to_the_unweighted_mean(self):
        rows = [Row("pkg/a.py", nloc=0, maintainability=6.0),
                Row("pkg/b.py", nloc=0, maintainability=8.0)]
        m = directory_rollup(rows)[0].axes[MAINTAINABILITY]
        assert m.weighted_mean == 7.0


class TestRanking:
    def test_a_directory_below_the_file_floor_is_not_ranked(self):
        """One unusual file must not make its directory the worst in the repo
        on a sample size of one."""
        rows = [Row("tiny/only.py", maintainability=1.0)]
        rows += [Row(f"big/f{i}.py", maintainability=7.0) for i in range(MIN_FILES_TO_RANK)]
        weakest = weakest_directories(directory_rollup(rows), MAINTAINABILITY)
        assert [d.path for d in weakest] == ["big"]

    def test_the_unrankable_directory_is_still_reported(self):
        """Gated from ranking, not hidden -- suppressing it would lose real
        information about a real file."""
        rows = [Row("tiny/only.py", maintainability=1.0)]
        by_path = {d.path: d for d in directory_rollup(rows)}
        assert "tiny" in by_path
        assert by_path["tiny"].axes[MAINTAINABILITY].weighted_mean == 1.0
        assert by_path["tiny"].axes[MAINTAINABILITY].rankable is False

    def test_ranking_is_by_weighted_mean_ascending(self):
        rows = []
        for name, score in (("good", 9.0), ("mid", 6.0), ("bad", 3.0)):
            rows += [Row(f"{name}/f{i}.py", maintainability=score) for i in range(3)]
        weakest = weakest_directories(directory_rollup(rows), MAINTAINABILITY, limit=3)
        assert [d.path for d in weakest] == ["bad", "mid", "good"]

    def test_change_hotspot_ranks_the_other_way(self):
        rows = []
        for name, points in (("calm", 0.5), ("busy", 7.0)):
            rows += [Row(f"{name}/f{i}.py", change_hotspot_points=points) for i in range(3)]
        weakest = weakest_directories(directory_rollup(rows), CHANGE_HOTSPOT, limit=1)
        assert [d.path for d in weakest] == ["busy"]

    def test_size_breaks_ties_so_the_bigger_problem_ranks_first(self):
        rows = [Row(f"small/f{i}.py", nloc=10, maintainability=5.0) for i in range(3)]
        rows += [Row(f"large/f{i}.py", nloc=500, maintainability=5.0) for i in range(3)]
        weakest = weakest_directories(directory_rollup(rows), MAINTAINABILITY, limit=1)
        assert [d.path for d in weakest] == ["large"]

    def test_an_axis_with_no_scores_ranks_nothing(self):
        rows = [Row(f"pkg/f{i}.py", architecture_health=None) for i in range(5)]
        assert weakest_directories(directory_rollup(rows), ARCHITECTURE) == []


class TestHotCohort:
    def _rows(self, n=20, score=9.0):
        return [Row(f"pkg/f{i}.py", maintainability=score, file_id=i) for i in range(n)]

    def test_degenerate_churn_reports_na_rather_than_an_arbitrary_slice(self):
        """Every file on a shallow clone reports the same commit count. Taking
        a 'top 10%' of a constant would silently mean 'whichever files sorted
        first'."""
        rows = self._rows()
        result = hot_cohort(rows, {r.file_id: 1 for r in rows})
        assert result.available is False
        assert "no information" in result.na_reason

    def test_two_distinct_values_is_still_degenerate(self):
        rows = self._rows()
        counts = {r.file_id: (1 if r.file_id % 2 else 2) for r in rows}
        assert hot_cohort(rows, counts).available is False

    def test_missing_history_reports_na(self):
        rows = self._rows()
        assert hot_cohort(rows, {}).available is False

    def test_hot_files_are_compared_against_the_whole_repo(self):
        rows = self._rows(n=20, score=9.0)
        for r in rows[:3]:
            r.maintainability = 4.0
        counts = {r.file_id: (50 - r.file_id) for r in rows}

        result = hot_cohort(rows, counts)
        assert result.available is True
        assert result.hot_mean < result.baseline_mean
        assert result.delta < 0
        assert result.baseline_files == 20

    def test_the_cohort_never_swallows_the_whole_repo(self):
        rows = self._rows(n=8)
        counts = {r.file_id: (10 - r.file_id) for r in rows}
        result = hot_cohort(rows, counts)
        assert result.available is True
        assert result.hot_files < result.baseline_files

    def test_ties_at_the_boundary_are_kept_together(self):
        """Two files with the same commit count must not land on opposite
        sides of the cutoff because of sort order."""
        rows = self._rows(n=30)
        counts = {}
        for r in rows:
            counts[r.file_id] = 9 if r.file_id < 6 else (5 if r.file_id < 15 else 1)
        result = hot_cohort(rows, counts)
        assert result.hot_files == 6, "all six files at the top count, no more and no fewer"
        assert result.churn_threshold == 9

    def test_young_history_carries_its_confound(self):
        """'Changed most' overlaps with 'written most recently' in a young
        repo. The caveat belongs beside the number."""
        rows = self._rows()
        counts = {r.file_id: (1 + r.file_id % 5) for r in rows}
        result = hot_cohort(rows, counts)
        assert result.available is True
        assert result.caveat and "written most recently" in result.caveat

    def test_deep_history_carries_no_confound(self):
        rows = self._rows(n=40)
        counts = {r.file_id: (1 + r.file_id * 4) for r in rows}
        result = hot_cohort(rows, counts)
        assert result.available is True
        assert result.caveat is None

    def test_the_payload_states_why_the_comparison_is_not_circular(self):
        rows = self._rows()
        counts = {r.file_id: (1 + r.file_id % 7) for r in rows}
        payload = hot_cohort(rows, counts).as_dict()
        assert payload["axis"] == MAINTAINABILITY
        assert "no change-history input" in payload["axis_note"]
