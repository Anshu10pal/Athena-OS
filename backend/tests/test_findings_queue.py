"""Tests for the findings queue aggregation.

Naming follows section 15.1: test_LOADBEARING_ for a test that fails anywhere if
the behaviour is reverted, test_DOCUMENTS_INTENT_ for one that cannot fail in
some environments and is recording a decision rather than guarding it.
"""
import pytest

from app.services.codebase import findings_queue as fq


def marker(key, severity, label=None, axis="maintainability"):
    return {"key": key, "label": label or key, "severity": severity}


def health_row(path, file_id=1, exposure=1.0, markers=None, axis="maintainability"):
    return (path, file_id, exposure, {axis: {"markers": markers or []}})


class TestExtract:
    def test_LOADBEARING_churn_is_promoted_out_of_the_findings_list(self):
        """churn_volume must never appear as a finding -- it is the ordering
        weight. It fires on 47.8% of evaluable files, so a regression here puts
        it back as ~41% of the queue."""
        rows = [health_row("a/b.py", markers=[
            marker(fq.CHURN_MARKER, 0.8),
            marker("large_method", 0.6),
        ])]
        findings, hidden, churn_files = fq.extract_findings(rows)

        assert [f.marker for f in findings] == ["large_method"]
        assert churn_files == 1
        assert findings[0].churn == 0.8

    def test_LOADBEARING_churn_below_the_floor_still_counts_as_a_multiplier(self):
        """The floor applies to findings, not to the weight. A file with churn
        0.1 is still a file that changes, and dropping that would silently zero
        the multiplier for the majority of churning files."""
        rows = [health_row("a/b.py", markers=[
            marker(fq.CHURN_MARKER, 0.1),
            marker("large_method", 0.6),
        ])]
        findings, hidden, _ = fq.extract_findings(rows)

        assert findings[0].churn == 0.1
        assert hidden == 0, "churn must not be counted in the hidden-below-floor total"

    def test_LOADBEARING_hidden_count_excludes_churn(self):
        """The UI shows this number as 'N below threshold'. Counting churn in it
        overstates what a user would see by toggling the floor off, because
        churn is not in this list at any severity."""
        rows = [health_row("a/b.py", markers=[
            marker(fq.CHURN_MARKER, 0.05),
            marker("large_method", 0.10),
            marker("deep_nesting", 0.20),
            marker("complex_method", 0.90),
        ])]
        findings, hidden, _ = fq.extract_findings(rows)

        assert hidden == 2
        assert [f.marker for f in findings] == ["complex_method"]

    def test_LOADBEARING_null_exposure_does_not_become_a_measured_zero(self):
        """A file excluded from the hotspot axis has NULL exposure. It scores
        zero (ranking last, which is the same answer as excluding it from the
        ordering) but must not contribute to the churn multiplier or be counted
        as a file with measured exposure."""
        rows = [health_row("a/b.py", exposure=None, markers=[marker("large_file", 0.9)])]
        findings, _, _ = fq.extract_findings(rows)

        assert findings[0].exposure == 0.0
        assert findings[0].churn == 0.0
        assert fq.build_rows(findings)[0].score == 0.0

    def test_LOADBEARING_zero_severity_markers_are_not_findings(self):
        """85% of marker slots evaluate to zero severity. They are evidence the
        marker ran, not findings, and must not reach the queue or the hidden
        count."""
        rows = [health_row("a/b.py", markers=[
            marker("large_file", 0.0),
            marker("deep_nesting", None),
        ])]
        findings, hidden, _ = fq.extract_findings(rows)

        assert findings == []
        assert hidden == 0

    def test_LOADBEARING_all_three_axes_are_read(self):
        """Architecture and hotspot markers are 58.7% of the queue. Reading only
        maintainability was the shape of an earlier bug elsewhere in this
        codebase and would silently halve the list."""
        row = ("a/b.py", 1, 1.0, {
            "maintainability": {"markers": [marker("large_method", 0.9)]},
            "architecture_health": {"markers": [marker("cycle_participation", 0.9)]},
            "change_hotspot": {"markers": [marker("complexity_under_churn", 0.9)]},
        })
        findings, _, _ = fq.extract_findings([row])

        assert {f.marker for f in findings} == {
            "large_method", "cycle_participation", "complexity_under_churn"}


class TestAdaptiveSplit:
    def test_LOADBEARING_a_row_within_budget_is_not_split(self):
        findings, _, _ = fq.extract_findings([
            health_row(f"src/pkg/mod{i}.py", file_id=i, markers=[marker("large_file", 0.5)])
            for i in range(5)
        ])
        rows = fq.build_rows(findings, max_files=10)

        assert len(rows) == 1
        assert rows[0].directory == "src"
        assert rows[0].file_count == 5
        assert rows[0].irreducible is False

    def test_LOADBEARING_an_oversized_row_splits_deeper(self):
        findings, _, _ = fq.extract_findings(
            [health_row(f"src/a/m{i}.py", file_id=i, markers=[marker("large_file", 0.5)])
             for i in range(6)]
            + [health_row(f"src/b/m{i}.py", file_id=100 + i, markers=[marker("large_file", 0.5)])
               for i in range(6)]
        )
        rows = fq.build_rows(findings, max_files=10)

        assert {r.directory for r in rows} == {"src/a", "src/b"}
        assert all(r.file_count == 6 for r in rows)

    def test_LOADBEARING_an_irreducible_row_is_marked_not_silently_oversized(self):
        """All files in one directory: no cap divides this row. It must be
        flagged, or the next person tunes the cap trying to fix it."""
        findings, _, _ = fq.extract_findings([
            health_row(f"pkg/core/m{i}.py", file_id=i,
                       markers=[marker("cycle_participation", 0.9)])
            for i in range(30)
        ])
        rows = fq.build_rows(findings, max_files=10)

        assert len(rows) == 1
        assert rows[0].irreducible is True
        assert rows[0].file_count == 30

    def test_LOADBEARING_splitting_never_loses_or_duplicates_a_finding(self):
        """The property that matters most: the split is a partition. Any bug
        that drops a subtree would quietly shrink the queue, which is invisible
        without this check."""
        findings, _, _ = fq.extract_findings([
            health_row(f"a/b{i % 3}/c{i % 5}/m{i}.py", file_id=i,
                       markers=[marker("large_file", 0.5)])
            for i in range(60)
        ])
        for cap in (1, 2, 5, 13, 60, 500):
            rows = fq.build_rows(findings, max_files=cap)
            regrouped = [f.path for r in rows for f in r.findings]
            assert sorted(regrouped) == sorted(f.path for f in findings), f"cap={cap}"
            assert len(regrouped) == len(set(regrouped)), f"duplicated at cap={cap}"

    def test_LOADBEARING_root_level_files_group_under_dot_not_their_own_name(self):
        """A file at the repo root has no directory. An earlier draft keyed on
        path.split('/')[0], which for a root file is the FILENAME -- producing
        one row per root-level file."""
        findings, _, _ = fq.extract_findings([
            health_row("setup.py", file_id=1, markers=[marker("large_file", 0.5)]),
            health_row("conftest.py", file_id=2, markers=[marker("large_file", 0.5)]),
        ])
        rows = fq.build_rows(findings)

        assert len(rows) == 1
        assert rows[0].directory == "."
        assert rows[0].file_count == 2

    def test_LOADBEARING_markers_never_share_a_row(self):
        findings, _, _ = fq.extract_findings([
            health_row("src/a.py", file_id=1, markers=[
                marker("large_file", 0.5), marker("deep_nesting", 0.5)]),
        ])
        rows = fq.build_rows(findings)

        assert len(rows) == 2
        assert {r.marker for r in rows} == {"large_file", "deep_nesting"}

    def test_rejects_a_nonsense_budget(self):
        with pytest.raises(ValueError):
            fq.build_rows([], max_files=0)


class TestOrdering:
    def test_LOADBEARING_score_is_severity_times_exposure_times_churn(self):
        findings, _, _ = fq.extract_findings([
            health_row("a/x.py", file_id=1, exposure=2.0,
                       markers=[marker(fq.CHURN_MARKER, 0.5), marker("large_file", 0.4)]),
        ])
        rows = fq.build_rows(findings)

        assert rows[0].score == pytest.approx(0.4 * 2.0 * 1.5)

    def test_LOADBEARING_zero_exposure_rows_sort_last(self):
        findings, _, _ = fq.extract_findings([
            health_row("dead/a.py", file_id=1, exposure=0.0,
                       markers=[marker("large_file", 1.0)]),
            health_row("live/b.py", file_id=2, exposure=0.1,
                       markers=[marker("large_file", 0.3)]),
        ])
        rows = fq.build_rows(findings)

        assert [r.directory for r in rows] == ["live", "dead"]

    def test_LOADBEARING_zero_score_ties_break_deterministically(self):
        """Without a deterministic tail the list reorders between renders for no
        visible reason -- the same reason cluster sorting breaks ties on id."""
        findings, _, _ = fq.extract_findings([
            health_row("z/a.py", file_id=1, exposure=0.0, markers=[marker("large_file", 0.5)]),
            health_row("m/b.py", file_id=2, exposure=0.0, markers=[marker("large_file", 0.5)]),
            health_row("a/c.py", file_id=3, exposure=0.0, markers=[marker("large_file", 0.9)]),
        ])
        first = [r.directory for r in fq.build_rows(findings)]
        again = [r.directory for r in fq.build_rows(list(reversed(findings)))]

        assert first == again
        assert first[0] == "a", "peak severity breaks the zero-score tie before path does"

    def test_LOADBEARING_row_files_are_worst_first(self):
        findings, _, _ = fq.extract_findings([
            health_row("a/low.py", file_id=1, markers=[marker("large_file", 0.3)]),
            health_row("a/high.py", file_id=2, markers=[marker("large_file", 0.9)]),
        ])
        files = fq.build_rows(findings)[0].files_payload()

        assert [f["path"] for f in files] == ["a/high.py", "a/low.py"]

    def test_LOADBEARING_row_summary_carries_no_file_list(self):
        """Members are a separate request: inline they cost 296 KB on
        apache/superset. A regression that re-inlines them is invisible except
        as a slow view."""
        findings, _, _ = fq.extract_findings([
            health_row(f"a/m{i}.py", file_id=i, markers=[marker("large_file", 0.5)])
            for i in range(3)
        ])
        payload = fq.build_rows(findings)[0].to_dict()

        assert "files" not in payload
        assert payload["file_count"] == 3

    def test_DOCUMENTS_INTENT_file_count_is_the_finding_count(self):
        """A marker fires at most once per file, so these are identically equal
        and the payload exposes ONE number. This cannot fail while that holds --
        it records why there is no separate instances field."""
        findings, _, _ = fq.extract_findings([
            health_row(f"a/m{i}.py", file_id=i, markers=[marker("large_file", 0.5)])
            for i in range(4)
        ])
        row = fq.build_rows(findings)[0]

        assert row.file_count == len(row.findings)
        assert "instances" not in row.to_dict()
