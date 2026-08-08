"""Phase F5: comparison.py. Pure-function tests -- no DB, no ingest."""
from app.services.codebase.comparison import (
    kendall_tau,
    pearson_correlation,
    signal_correlation_matrix,
    spearman_on_intersection,
    top_n_ablation_report,
)


class TestKendallTau:
    def test_perfect_agreement_gives_one(self):
        a = {"x": 3, "y": 2, "z": 1}
        b = {"x": 30, "y": 20, "z": 10}  # same order, different scale
        tau, n = kendall_tau(a, b)
        assert n == 3
        assert abs(tau - 1.0) < 1e-9

    def test_perfect_disagreement_gives_negative_one(self):
        a = {"x": 3, "y": 2, "z": 1}
        b = {"x": 1, "y": 2, "z": 3}
        tau, n = kendall_tau(a, b)
        assert n == 3
        assert abs(tau - (-1.0)) < 1e-9

    def test_only_common_keys_are_compared(self):
        a = {"x": 3, "y": 2, "z": 1, "extra_a": 99}
        b = {"x": 30, "y": 20, "z": 10, "extra_b": -5}
        tau, n = kendall_tau(a, b)
        assert n == 3
        assert abs(tau - 1.0) < 1e-9

    def test_ties_in_one_side_only_are_handled_via_tau_b(self):
        a = {"w": 1, "x": 1, "y": 2, "z": 3}  # w, x tied
        b = {"w": 10, "x": 20, "y": 30, "z": 40}  # no ties, otherwise agrees
        tau, n = kendall_tau(a, b)
        assert n == 4
        assert 0 < tau < 1.0  # not a perfect 1.0 because of the tie, but still positive

    def test_fewer_than_two_common_returns_none(self):
        tau, n = kendall_tau({"x": 1}, {"x": 1, "y": 2})
        assert tau is None
        assert n == 1

    def test_zero_variance_on_one_side_returns_none(self):
        a = {"x": 5, "y": 5, "z": 5}  # every pair tied on a
        b = {"x": 1, "y": 2, "z": 3}
        tau, n = kendall_tau(a, b)
        assert tau is None
        assert n == 3


class TestPearsonCorrelation:
    def test_perfect_positive_correlation(self):
        a = {"x": 1, "y": 2, "z": 3}
        b = {"x": 10, "y": 20, "z": 30}
        r, n = pearson_correlation(a, b)
        assert n == 3
        assert abs(r - 1.0) < 1e-9

    def test_perfect_negative_correlation(self):
        a = {"x": 1, "y": 2, "z": 3}
        b = {"x": 30, "y": 20, "z": 10}
        r, n = pearson_correlation(a, b)
        assert abs(r - (-1.0)) < 1e-9

    def test_zero_variance_returns_none_not_zero(self):
        a = {"x": 1, "y": 1, "z": 1}
        b = {"x": 1, "y": 2, "z": 3}
        r, n = pearson_correlation(a, b)
        assert r is None
        assert n == 3

    def test_fewer_than_two_common_returns_none(self):
        r, n = pearson_correlation({"x": 1}, {"y": 2})
        assert r is None
        assert n == 0


class TestSignalCorrelationMatrix:
    def test_flags_highly_correlated_pair_as_redundant(self):
        signals = {
            "commit_count": {"a": 1, "b": 2, "c": 3},
            "distinct_authors": {"a": 1, "b": 2, "c": 3},  # identical -> r=1.0
            "fan_in": {"a": 10, "b": 0, "c": 5},  # unrelated
        }
        result = signal_correlation_matrix(signals, threshold=0.8)
        redundant_pairs = {(a, b) for a, b, _r in result["redundant"]}
        assert ("commit_count", "distinct_authors") in redundant_pairs
        assert ("fan_in", "commit_count") not in redundant_pairs

    def test_degenerate_signal_never_flagged_redundant(self):
        # a signal with no variance can't correlate with anything -- must
        # not spuriously appear in `redundant` via some r=None-treated-as-0 bug.
        signals = {
            "distinct_authors": {"a": 1, "b": 1, "c": 1},
            "fan_in": {"a": 10, "b": 0, "c": 5},
        }
        result = signal_correlation_matrix(signals)
        assert result["redundant"] == []
        assert result["pairs"][("distinct_authors", "fan_in")]["r"] is None


class TestSpearmanOnIntersection:
    def test_identical_top_n_gives_rho_one(self):
        order = ["a", "b", "c", "d"]
        rho, n = spearman_on_intersection(order, list(order), top_n=4)
        assert n == 4
        assert abs(rho - 1.0) < 1e-9

    def test_reversed_top_n_gives_rho_negative_one(self):
        order = ["a", "b", "c", "d"]
        rho, n = spearman_on_intersection(order, list(reversed(order)), top_n=4)
        assert abs(rho - (-1.0)) < 1e-9

    def test_fewer_than_two_common_returns_none(self):
        rho, n = spearman_on_intersection(["a"], ["b", "a"], top_n=5)
        assert rho is None
        assert n == 1

    def test_rho_never_escapes_valid_range_on_a_scattered_small_overlap(self):
        # regression shape for the exact bug validate_ranking.py hit: a small
        # common set scattered near opposite ends of two long, mostly-disjoint lists.
        order_a = ["shared1"] + [f"only_a_{i}" for i in range(18)] + ["shared2"]
        order_b = ["shared2"] + [f"only_b_{i}" for i in range(18)] + ["shared1"]
        rho, n = spearman_on_intersection(order_a, order_b, top_n=20)
        assert n == 2
        assert -1.0 - 1e-9 <= rho <= 1.0 + 1e-9


class TestTopNAblationReport:
    def test_ablating_an_irrelevant_signal_leaves_top_n_unchanged(self):
        baseline = {"a": 10, "b": 9, "c": 8, "d": 1, "e": 0.5}
        # "noise" ablation barely perturbs anything relative to baseline
        ablated = {"a": 9.9, "b": 8.9, "c": 7.9, "d": 0.9, "e": 0.4}
        report = top_n_ablation_report(baseline, {"noise": ablated}, top_n=3)
        assert report["noise"]["left_top_n"] == []
        assert report["noise"]["entered_top_n"] == []
        assert abs(report["noise"]["spearman"] - 1.0) < 1e-9

    def test_ablating_a_dominant_signal_changes_top_n_membership(self):
        baseline = {"a": 10, "b": 9, "c": 1, "d": 0.5}
        # removing whatever made "a" and "b" dominant flips the ranking
        ablated = {"a": 0.1, "b": 0.2, "c": 5, "d": 4}
        report = top_n_ablation_report(baseline, {"dominant": ablated}, top_n=2)
        assert set(report["dominant"]["left_top_n"]) == {"a", "b"}
        assert set(report["dominant"]["entered_top_n"]) == {"c", "d"}

    def test_multiple_signals_reported_independently(self):
        baseline = {"a": 10, "b": 5, "c": 1}
        report = top_n_ablation_report(
            baseline,
            {
                "sig1": {"a": 10, "b": 5, "c": 1},  # no change
                "sig2": {"a": 1, "b": 5, "c": 10},  # fully reversed
            },
            top_n=2,
        )
        assert report["sig1"]["left_top_n"] == []
        assert set(report["sig2"]["left_top_n"]) == {"a"}
