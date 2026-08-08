"""Unit tests for the answer-key comparison math in scripts/validate_ranking.py.

Most of this file tests the comparison math itself against synthetic data --
no dependency on any particular answer key existing. TestGetToolRanking is
the exception: an integration-level regression test for a real bug found by
actually running this script against a repo with more than one scorer's
rows (see get_tool_ranking's docstring).
"""
from app.db.models import CodeFile, CodeFileRank, Repo
from scripts.validate_ranking import get_tool_ranking, mismatches, overlap_at, parse_answer_key, spearman_on_intersection


class TestParseAnswerKey:
    def test_numbered_list(self, tmp_path):
        key = tmp_path / "key.md"
        key.write_text("1. app/main.py\n2. app/db/models.py\n3. app/core/config.py\n")
        assert parse_answer_key(key) == ["app/main.py", "app/db/models.py", "app/core/config.py"]

    def test_bullet_list_and_comments_and_blanks(self, tmp_path):
        key = tmp_path / "key.md"
        key.write_text("# Reading list\n\n- app/main.py\n* app/db/models.py\n\n# a comment\napp/core/config.py\n")
        assert parse_answer_key(key) == ["app/main.py", "app/db/models.py", "app/core/config.py"]

    def test_backticked_paths_stripped(self, tmp_path):
        key = tmp_path / "key.md"
        key.write_text("1. `app/main.py`\n2) `app/db/models.py`\n")
        assert parse_answer_key(key) == ["app/main.py", "app/db/models.py"]

    def test_empty_file_yields_empty_list(self, tmp_path):
        key = tmp_path / "key.md"
        key.write_text("# just a heading\n\n")
        assert parse_answer_key(key) == []


class TestOverlap:
    def test_full_overlap(self):
        tool = [f"f{i}.py" for i in range(20)]
        key = [f"f{i}.py" for i in range(20)]
        assert overlap_at(tool, key, 20) == (20, 20)

    def test_partial_overlap(self):
        tool = [f"f{i}.py" for i in range(20)]
        key = [f"f{i}.py" for i in range(10)] + [f"g{i}.py" for i in range(10)]
        assert overlap_at(tool, key, 20) == (10, 20)

    def test_overlap_at_10_is_independent_of_overlap_at_20(self):
        tool = [f"f{i}.py" for i in range(20)]
        key = [f"f{i}.py" for i in range(5)] + [f"g{i}.py" for i in range(15)]
        assert overlap_at(tool, key, 10) == (5, 10)

    def test_zero_overlap(self):
        tool = [f"t{i}.py" for i in range(20)]
        key = [f"k{i}.py" for i in range(20)]
        assert overlap_at(tool, key, 20) == (0, 20)


class TestSpearmanOnIntersection:
    def test_perfect_agreement(self):
        tool = [f"f{i}.py" for i in range(20)]
        key = [f"f{i}.py" for i in range(20)]
        rho, n = spearman_on_intersection(tool, key)
        assert n == 20
        assert rho == 1.0

    def test_perfect_disagreement_on_a_small_common_set(self):
        tool = ["a.py", "b.py"] + [f"t{i}.py" for i in range(18)]
        key = ["b.py", "a.py"] + [f"k{i}.py" for i in range(18)]
        rho, n = spearman_on_intersection(tool, key)
        assert n == 2
        assert rho == -1.0

    def test_no_common_files_returns_none(self):
        tool = [f"t{i}.py" for i in range(20)]
        key = [f"k{i}.py" for i in range(20)]
        rho, n = spearman_on_intersection(tool, key)
        assert rho is None
        assert n == 0

    def test_single_common_file_is_undefined_not_a_crash(self):
        tool = ["shared.py"] + [f"t{i}.py" for i in range(19)]
        key = ["shared.py"] + [f"k{i}.py" for i in range(19)]
        rho, n = spearman_on_intersection(tool, key)
        assert rho is None
        assert n == 1

    def test_common_items_at_different_absolute_positions_still_measures_relative_order(self):
        # Regression test for a real bug: 4 shared files appear in the SAME
        # relative order in both lists, but at very different absolute
        # positions (front of tool's list, back of key's). True Spearman rho
        # is about relative order among common items, not absolute position,
        # so this must still be a perfect 1.0 -- the buggy first version
        # produced a rho far outside [-1, 1] on exactly this shape of input.
        shared = ["s0.py", "s1.py", "s2.py", "s3.py"]
        tool = shared + [f"t{i}.py" for i in range(16)]
        key = [f"k{i}.py" for i in range(16)] + shared
        rho, n = spearman_on_intersection(tool, key)
        assert n == 4
        assert rho == 1.0

    def test_rho_is_always_within_valid_range(self):
        # A broad sweep, not just hand-picked cases -- the assertion inside
        # spearman_on_intersection itself is the real guard, but this exercises
        # many shapes of overlap/scatter in one pass.
        import random

        rng = random.Random(0)
        universe = [f"f{i}.py" for i in range(40)]
        for _ in range(200):
            tool = rng.sample(universe, 20)
            key = rng.sample(universe, 20)
            rho, n = spearman_on_intersection(tool, key)
            if rho is not None:
                assert -1.0 <= rho <= 1.0

    def test_only_considers_top_20_even_if_lists_are_longer(self):
        # identical top 20, then diverge completely after that -- must not
        # affect the correlation computed over the top-20 intersection.
        shared_top20 = [f"f{i}.py" for i in range(20)]
        tool = shared_top20 + ["tool_only.py"]
        key = shared_top20 + ["key_only.py"]
        rho, n = spearman_on_intersection(tool, key)
        assert n == 20
        assert rho == 1.0


class TestGetToolRanking:
    """Regression test for a real bug: without filtering by scorer,
    get_tool_ranking ordered CodeFileRank rows across ALL scorers for a
    repo together. Scorers live on different scales (legacy's weighted sum
    can exceed 0.7 on a real repo; weighted_pagerank tops out around 0.3;
    RRF around 0.08) -- interleaving them means whichever scorer happens to
    have the largest raw numbers silently dominates the "top" of the
    result, and the other two never appear at all. Caught by actually
    running this script against a repo with more than one scorer's rows."""

    def _make_repo_with_two_files(self, db_session) -> Repo:
        repo = Repo(host="local", owner="", name="r", local_path="/tmp/r", source_kind="local")
        db_session.add(repo)
        db_session.flush()
        db_session.add_all([
            CodeFile(repo_id=repo.id, path="a.py", language="python", content_sha256="a"),
            CodeFile(repo_id=repo.id, path="b.py", language="python", content_sha256="b"),
        ])
        db_session.commit()
        return repo

    def test_default_scorer_is_legacy(self, db_session):
        repo = self._make_repo_with_two_files(db_session)
        files = {f.path: f.id for f in db_session.query(CodeFile).filter(CodeFile.repo_id == repo.id).all()}
        db_session.add_all([
            CodeFileRank(repo_id=repo.id, file_id=files["a.py"], scorer="legacy", score=0.9),
            CodeFileRank(repo_id=repo.id, file_id=files["b.py"], scorer="legacy", score=0.1),
        ])
        db_session.commit()
        assert get_tool_ranking(db_session, repo.id) == ["a.py", "b.py"]

    def test_scorers_are_never_mixed_even_on_wildly_different_scales(self, db_session):
        repo = self._make_repo_with_two_files(db_session)
        files = {f.path: f.id for f in db_session.query(CodeFile).filter(CodeFile.repo_id == repo.id).all()}
        # legacy's "a.py" (0.05) genuinely ranks BELOW weighted_pagerank's
        # "b.py" (0.30) in raw score -- a scorer-blind ordering would put
        # b.py first for BOTH queries. Each scorer's own query must ignore
        # the other scorer's rows entirely, not just deprioritize them.
        db_session.add_all([
            CodeFileRank(repo_id=repo.id, file_id=files["a.py"], scorer="legacy", score=0.05),
            CodeFileRank(repo_id=repo.id, file_id=files["b.py"], scorer="legacy", score=0.02),
            CodeFileRank(repo_id=repo.id, file_id=files["a.py"], scorer="weighted_pagerank", score=0.10),
            CodeFileRank(repo_id=repo.id, file_id=files["b.py"], scorer="weighted_pagerank", score=0.30),
        ])
        db_session.commit()
        assert get_tool_ranking(db_session, repo.id, scorer="legacy") == ["a.py", "b.py"]
        assert get_tool_ranking(db_session, repo.id, scorer="weighted_pagerank") == ["b.py", "a.py"]

    def test_unrequested_scorer_with_no_rows_returns_empty_not_someone_elses_rows(self, db_session):
        repo = self._make_repo_with_two_files(db_session)
        files = {f.path: f.id for f in db_session.query(CodeFile).filter(CodeFile.repo_id == repo.id).all()}
        db_session.add(CodeFileRank(repo_id=repo.id, file_id=files["a.py"], scorer="legacy", score=0.5))
        db_session.commit()
        assert get_tool_ranking(db_session, repo.id, scorer="rrf") == []


class TestMismatches:
    def test_reports_both_directions(self):
        tool = ["a.py", "b.py", "c.py"]
        key = ["b.py", "c.py", "d.py"]
        mm = mismatches(tool, key, n=3)
        assert mm["in_key_not_tool"] == ["d.py"]
        assert mm["in_tool_not_key"] == ["a.py"]

    def test_no_mismatches_on_identical_lists(self):
        tool = ["a.py", "b.py"]
        key = ["b.py", "a.py"]
        mm = mismatches(tool, key, n=2)
        assert mm["in_key_not_tool"] == []
        assert mm["in_tool_not_key"] == []
