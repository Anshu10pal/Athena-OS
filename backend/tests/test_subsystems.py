"""Phase I1: subsystem clustering.

Pure-function tests build small graphs/dicts directly (no DB, no git) for
anything whose correctness doesn't depend on real parsing -- labelling
rules, the agreement metric, and cycle-coherence's weak/strong threshold.
Integration tests use the same real-repo-on-disk convention as
test_repos_api.py (register_from_path -> ingest_repo -> rank_repo) since
clustering reads the same resolved CodeImport rows real ingestion produces,
and this project's own discipline is to test against real parsing/
resolution rather than hand-inserted ORM rows that could silently drift
from what ingest.py actually writes.
"""
from pathlib import Path

import networkx as nx
import numpy as np
import pytest

from app.db.models import CodeFile, CodeSubsystem, Repo
from app.services.codebase.git_ops import run_git
from app.services.codebase.ingest import ingest_repo
from app.services.codebase.ranking import rank_repo
from app.services.codebase.registry import register_from_path
from app.services.codebase.repo_lock import RepoBusyError, repo_lock
from app.services.codebase import subsystems as subsystems_module
from app.services.codebase.subsystems import (
    CYCLE_COHERENCE_WEAK_THRESHOLD,
    _dominant_prefix_label,
    _sorted_clusters,
    _top_fan_in_label,
    algorithm_agreement,
    cluster_hdbscan,
    cluster_louvain,
    cluster_modularity,
    compute_subsystems,
    compute_subsystems_hdbscan,
    subsystem_column_for,
)


def _write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _git(cwd: Path, *args):
    result = run_git(list(args), cwd=str(cwd))
    assert result.returncode == 0, f"git {args} failed: {result.stderr}"
    return result


def _init_repo(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init")
    _git(root, "config", "user.email", "t@t.com")
    _git(root, "config", "user.name", "Test User")


# ---------------- pure-function tests ----------------


class TestSortedClusters:
    def test_sorts_by_size_desc_then_min_id(self):
        raw = [[5, 6], [1, 2, 3], [9]]
        out = _sorted_clusters(raw)
        assert out == [[1, 2, 3], [5, 6], [9]]

    def test_deterministic_across_repeated_calls(self):
        raw = [{3, 1, 2}, {9, 8}]
        assert _sorted_clusters(raw) == _sorted_clusters(raw)


class TestLabellingRules:
    def test_dominant_prefix_picks_majority_directory(self):
        path_of = {1: "a/x.py", 2: "a/y.py", 3: "b/z.py"}
        label, count = _dominant_prefix_label([1, 2, 3], path_of)
        assert label == "a"
        assert count == 2

    def test_top_fan_in_picks_highest_fan_in_members_stem(self):
        path_of = {1: "a/models.py", 2: "a/util.py"}
        fan_in_of = {1: 10, 2: 2}
        label, fid = _top_fan_in_label([1, 2], fan_in_of, path_of)
        assert label == "models"
        assert fid == 1

    def test_top_fan_in_handles_none_fan_in_as_zero(self):
        # None means "no rank run has computed this yet" -- must not crash
        # a max() comparison against a real int on another member.
        path_of = {1: "a/one.py", 2: "a/two.py"}
        fan_in_of = {1: None, 2: 5}
        label, fid = _top_fan_in_label([1, 2], fan_in_of, path_of)
        assert label == "two"
        assert fid == 2


class TestClusterFunctions:
    def _two_triangles_graph(self) -> nx.Graph:
        g = nx.Graph()
        g.add_edge(1, 2, weight=1.0)
        g.add_edge(2, 3, weight=1.0)
        g.add_edge(1, 3, weight=1.0)
        g.add_edge(4, 5, weight=1.0)
        g.add_edge(5, 6, weight=1.0)
        g.add_edge(4, 6, weight=1.0)
        return g

    def test_modularity_finds_two_triangles(self):
        clusters = cluster_modularity(self._two_triangles_graph())
        assert sorted(len(c) for c in clusters) == [3, 3]

    def test_louvain_finds_two_triangles(self):
        clusters = cluster_louvain(self._two_triangles_graph())
        assert sorted(len(c) for c in clusters) == [3, 3]

    def test_modularity_deterministic_across_repeated_calls(self):
        g = self._two_triangles_graph()
        assert cluster_modularity(g) == cluster_modularity(g)


class TestAlgorithmAgreement:
    def test_full_agreement(self):
        a = [[1, 2, 3], [4, 5]]
        b = [[1, 2, 3], [4, 5]]
        assert algorithm_agreement(a, b) == 1.0

    def test_partial_agreement(self):
        a = [[1, 2, 3, 4]]
        b = [[1, 2], [3, 4]]
        # majority-matching cluster in b for a's cluster has 2 of 4 members
        assert algorithm_agreement(a, b) == 0.5

    def test_singleton_clusters_excluded_from_both_sides(self):
        # a has one real 4-member cluster and 3 singletons; only the real
        # cluster should count toward the ratio -- if singletons leaked in,
        # a lone file trivially "agreeing with itself" would inflate this
        # score regardless of the real cluster's actual agreement. Each of
        # the 4 real members lands in a DIFFERENT b-cluster, so the best
        # possible majority is 1 of 4 -- the lowest this formula can report
        # for a cluster this size (a 1-vs-1 tie on a 2-member cluster would
        # floor at 0.5, not 0.0, which is why this uses 4 members).
        a = [[1, 2, 3, 4], [5], [6], [7]]
        b = [[1, 10], [2, 11], [3, 12], [4, 13], [5], [6], [7]]
        assert algorithm_agreement(a, b) == 0.25

    def test_none_when_no_multi_member_cluster_exists(self):
        a = [[1], [2], [3]]
        b = [[1], [2], [3]]
        assert algorithm_agreement(a, b) is None


class TestCycleCoherenceThreshold:
    def test_strong_coherence_not_flagged_weak(self):
        path_of = {1: "core/a.py", 2: "core/b.py", 3: "db/c.py", 4: "db/d.py"}
        cluster_of = {1: 0, 2: 0, 3: 0, 4: 0}  # all four share one cluster
        # monkeypatch-free: call the pure math directly via a fake db/repo
        # is unnecessary here since _directory_scc_groups needs real
        # CodeImport rows -- this test exercises the coherence/threshold
        # arithmetic in isolation via the same shape cycle_cluster_coherence
        # produces, not the DB-querying half.
        from collections import Counter
        counts = Counter(cluster_of.get(fid) for fid in path_of)
        majority_cluster, majority_count = counts.most_common(1)[0]
        coherence = majority_count / len(path_of)
        assert coherence == 1.0
        assert coherence >= CYCLE_COHERENCE_WEAK_THRESHOLD

    def test_weak_coherence_flagged(self):
        # 2 of 4 share a cluster -- exactly the repo-1 core/db shape found
        # in I0 (half the files scatter elsewhere).
        cluster_of = {1: 0, 2: 0, 3: 1, 4: 2}
        from collections import Counter
        counts = Counter(cluster_of.values())
        _, majority_count = counts.most_common(1)[0]
        coherence = majority_count / len(cluster_of)
        assert coherence == 0.5
        assert coherence < CYCLE_COHERENCE_WEAK_THRESHOLD


# ---------------- integration tests (real repo on disk) ----------------


def _make_repo(tmp_path) -> Path:
    """Two dense, disconnected 4-file cliques (groupA, groupB) plus one
    genuinely isolated file (iso.py) -- a shape modularity clustering
    should recover cleanly regardless of resolution/tie-breaking details,
    unlike a shape designed to test a borderline split. Module-level (not
    a class method) so both the graph-based (modularity/Louvain) and the
    embedding-based (HDBSCAN) integration test classes below share one
    fixture instead of duplicating it."""
    root = tmp_path / "repo"
    _init_repo(root)
    _write(root / "groupA" / "a1.py",
           "from groupA.a2 import f2\nfrom groupA.a3 import f3\nfrom groupA.a4 import f4\n")
    _write(root / "groupA" / "a2.py", "from groupA.a3 import f3\nfrom groupA.a4 import f4\ndef f2(): pass\n")
    _write(root / "groupA" / "a3.py", "from groupA.a4 import f4\ndef f3(): pass\n")
    _write(root / "groupA" / "a4.py", "def f4(): pass\n")
    _write(root / "groupB" / "b1.py",
           "from groupB.b2 import g2\nfrom groupB.b3 import g3\nfrom groupB.b4 import g4\n")
    _write(root / "groupB" / "b2.py", "from groupB.b3 import g3\nfrom groupB.b4 import g4\ndef g2(): pass\n")
    _write(root / "groupB" / "b3.py", "from groupB.b4 import g4\ndef g3(): pass\n")
    _write(root / "groupB" / "b4.py", "def g4(): pass\n")
    _write(root / "iso.py", "def standalone(): pass\n")
    _git(root, "add", "-A")
    _git(root, "-c", "user.name=Alice", "-c", "user.email=alice@t.com", "commit", "-m", "initial")
    return root


def _ranked_repo(db_session, tmp_path) -> Repo:
    root = _make_repo(tmp_path)
    repo = register_from_path(db_session, str(root))
    ingest_repo(db_session, repo)
    rank_repo(db_session, repo)  # populates fan_in, used by the top-fan-in label
    return repo


def _path_of(db_session, repo) -> dict:
    files = db_session.query(CodeFile).filter(CodeFile.repo_id == repo.id).all()
    return {f.path: f.id for f in files}


class TestComputeSubsystemsIntegration:
    def test_two_dense_groups_recovered_as_separate_clusters(self, db_session, tmp_path):
        repo = _ranked_repo(db_session, tmp_path)
        report = compute_subsystems(db_session, repo)
        assert report["algorithms"]["modularity"]["cluster_count"] == 2

        ids = _path_of(db_session, repo)
        group_a_ids = {ids[f"groupA/a{i}.py"] for i in range(1, 5)}
        group_b_ids = {ids[f"groupB/b{i}.py"] for i in range(1, 5)}

        db_session.expire_all()
        subsystem_of = {
            f.id: f.subsystem_modularity_id
            for f in db_session.query(CodeFile).filter(CodeFile.repo_id == repo.id).all()
        }
        a_subsystems = {subsystem_of[fid] for fid in group_a_ids}
        b_subsystems = {subsystem_of[fid] for fid in group_b_ids}
        assert len(a_subsystems) == 1 and None not in a_subsystems
        assert len(b_subsystems) == 1 and None not in b_subsystems
        assert a_subsystems != b_subsystems

    def test_isolated_file_is_unclustered_not_a_singleton_row(self, db_session, tmp_path):
        repo = _ranked_repo(db_session, tmp_path)
        compute_subsystems(db_session, repo)
        ids = _path_of(db_session, repo)
        iso_file = db_session.get(CodeFile, ids["iso.py"])
        assert iso_file.subsystem_modularity_id is None
        assert iso_file.subsystem_louvain_id is None
        # and there is genuinely no CodeSubsystem row for a size-1 cluster
        singleton_rows = [
            s for s in db_session.query(CodeSubsystem).filter(CodeSubsystem.repo_id == repo.id).all()
            if s.member_count < 2
        ]
        assert singleton_rows == []

    def test_repo_level_agreement_persisted(self, db_session, tmp_path):
        repo = _ranked_repo(db_session, tmp_path)
        report = compute_subsystems(db_session, repo)
        db_session.refresh(repo)
        assert repo.subsystem_algorithm_agreement == report["agreement"]
        assert report["agreement"] == 1.0  # two cleanly separated cliques -- both algorithms must agree

    def test_two_algorithms_persist_independently(self, db_session, tmp_path):
        repo = _ranked_repo(db_session, tmp_path)
        compute_subsystems(db_session, repo)
        rows = db_session.query(CodeSubsystem).filter(CodeSubsystem.repo_id == repo.id).all()
        algorithms_present = {r.algorithm for r in rows}
        assert algorithms_present == {"modularity", "louvain"}

    def test_recompute_is_idempotent_in_shape(self, db_session, tmp_path):
        repo = _ranked_repo(db_session, tmp_path)
        first = compute_subsystems(db_session, repo)
        second = compute_subsystems(db_session, repo)
        assert first["algorithms"]["modularity"]["cluster_count"] == second["algorithms"]["modularity"]["cluster_count"]

    def test_custom_label_carries_over_when_membership_unchanged(self, db_session, tmp_path):
        repo = _ranked_repo(db_session, tmp_path)
        compute_subsystems(db_session, repo)
        ids = _path_of(db_session, repo)
        db_session.expire_all()
        a1 = db_session.get(CodeFile, ids["groupA/a1.py"])
        subsystem = db_session.get(CodeSubsystem, a1.subsystem_modularity_id)
        subsystem.custom_label = "Group A Renamed"
        subsystem.active_label_rule = "custom"
        db_session.commit()

        report = compute_subsystems(db_session, repo)
        assert report["algorithms"]["modularity"]["labels_carried_over"] >= 1

        db_session.expire_all()
        a1_after = db_session.get(CodeFile, ids["groupA/a1.py"])
        new_subsystem = db_session.get(CodeSubsystem, a1_after.subsystem_modularity_id)
        assert new_subsystem.custom_label == "Group A Renamed"
        assert new_subsystem.active_label_rule == "custom"

    def test_custom_label_resets_when_membership_diverges(self, db_session, tmp_path):
        # Same starting point, but the SECOND compute happens against a
        # repo where groupA's real membership has structurally changed
        # (a5 added, tightly coupled only to a1, decoupled from a2-a4)
        # enough that the >=50%-of-OLD-members overlap threshold isn't met.
        repo = _ranked_repo(db_session, tmp_path)
        compute_subsystems(db_session, repo)
        ids = _path_of(db_session, repo)
        db_session.expire_all()
        a1 = db_session.get(CodeFile, ids["groupA/a1.py"])
        old_subsystem_id = a1.subsystem_modularity_id
        subsystem = db_session.get(CodeSubsystem, old_subsystem_id)
        subsystem.custom_label = "Will Reset"
        subsystem.active_label_rule = "custom"
        db_session.commit()

        # Scatter the old 4-member clique into FOUR separate new triangles,
        # one old member each -- max overlap between the old cluster and
        # any single new cluster is 1/4=25%, genuinely below the >=50%
        # carry-over threshold (my first attempt at this only detached a1
        # and left a2/a3/a4 still 3-of-4 overlapping with the old cluster,
        # which correctly carried the label over -- that wasn't a bug, the
        # test's own construction hadn't actually broken the old cluster
        # apart enough).
        root = Path(repo.local_path)
        for i, member in enumerate(["a1", "a2", "a3", "a4"], start=1):
            _write(root / "groupA" / f"{member}.py",
                   f"from groupA.n{i}b import p{i}b\nfrom groupA.n{i}c import p{i}c\n")
            _write(root / "groupA" / f"n{i}b.py", f"from groupA.n{i}c import p{i}c\ndef p{i}b(): pass\n")
            _write(root / "groupA" / f"n{i}c.py", f"def p{i}c(): pass\n")
        _git(root, "add", "-A")
        _git(root, "-c", "user.name=Alice", "-c", "user.email=alice@t.com", "commit", "-m", "restructure")
        ingest_repo(db_session, repo)
        rank_repo(db_session, repo)

        report = compute_subsystems(db_session, repo)
        assert report["algorithms"]["modularity"]["labels_reset"] >= 1
        remaining_custom = db_session.query(CodeSubsystem).filter(
            CodeSubsystem.repo_id == repo.id, CodeSubsystem.custom_label == "Will Reset"
        ).count()
        assert remaining_custom == 0

    def test_cycle_coherence_wiring_end_to_end(self, db_session, tmp_path):
        """Doesn't assert a specific coherence value (that depends on real
        clustering behavior, not just this test's construction) -- proves
        the SCC-discovery + coherence wiring runs against a real cycle
        without erroring and returns a well-shaped report."""
        root = tmp_path / "cyclerepo"
        _init_repo(root)
        _write(root / "core" / "a.py", "from db.b import y\ndef x(): return y()\n")
        _write(root / "db" / "b.py", "from core.a import x\ndef y(): return 1\n")
        _git(root, "add", "-A")
        _git(root, "-c", "user.name=Alice", "-c", "user.email=alice@t.com", "commit", "-m", "initial")
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)
        rank_repo(db_session, repo)

        report = compute_subsystems(db_session, repo)
        coherence_entries = report["cycle_coherence"]
        assert len(coherence_entries) == 1
        entry = coherence_entries[0]
        assert entry["directories"] == ["core", "db"]
        assert entry["total_files"] == 2
        assert 0.0 <= entry["coherence"] <= 1.0

    def test_holds_repo_lock_for_the_whole_call(self, db_session, tmp_path):
        repo = _ranked_repo(db_session, tmp_path)
        with repo_lock(repo.id, "ingest"):
            with pytest.raises(RepoBusyError):
                compute_subsystems(db_session, repo)


# ---------------- Phase I6: HDBSCAN (pure-function) ----------------


class TestSubsystemColumnFor:
    def test_maps_each_valid_algorithm_to_its_own_column(self):
        assert subsystem_column_for("modularity") is CodeFile.subsystem_modularity_id
        assert subsystem_column_for("louvain") is CodeFile.subsystem_louvain_id
        assert subsystem_column_for("hdbscan") is CodeFile.subsystem_hdbscan_id


class TestClusterHdbscan:
    """Deliberately uses 4-member groups, not exactly HDBSCAN_MIN_CLUSTER_SIZE
    (3) -- verified empirically (see subsystems.py's HDBSCAN_MIN_CLUSTER_SIZE
    comment) that a real cluster whose size exactly EQUALS min_cluster_size
    is a genuine HDBSCAN edge case that can go either way depending on the
    surrounding data's density contrast; that sensitivity is a known,
    documented characteristic of the library at this scale, not something
    these tests exist to pin down further with more synthetic tuning. What
    these tests verify is the *contract* cluster_hdbscan owns on top of the
    library call: singleton/below-threshold handling, id-to-vector mapping,
    and determinism."""

    def test_finds_two_dense_clusters(self):
        # Small jitter, not exact duplicates -- real embeddings never
        # produce identical vectors for different files, and exact
        # duplicates are an unnecessary edge case for this function to
        # have to handle correctly.
        vectors = np.array([
            [1.0, 0.0], [1.0, 0.01], [1.0, -0.01], [1.0, 0.02],
            [0.0, 1.0], [0.0, 1.01], [0.0, 0.99], [0.0, 1.02],
        ])
        ids = [10, 11, 12, 13, 20, 21, 22, 23]
        clusters = cluster_hdbscan(vectors, ids, min_cluster_size=3)
        assert sorted(len(c) for c in clusters) == [4, 4]
        assert set(clusters[0]) | set(clusters[1]) == set(ids)

    def test_noise_point_becomes_its_own_singleton(self):
        # The outlier must be angularly distinct after L2 normalization,
        # not just far in raw magnitude -- a magnitude-only outlier like
        # [50, 50] normalizes to the same unit-circle neighborhood as
        # everything else in 2D and stops being an outlier at all post-
        # normalization (this is a 2D-toy-geometry artifact of testing a
        # cosine-via-normalization approach with only 2 dimensions; real
        # 384-dim embeddings don't collapse this way).
        vectors = np.array([
            [1.0, 0.0], [1.0, 0.01], [1.0, -0.01], [1.0, 0.02],
            [0.0, 1.0], [0.0, 1.01], [0.0, 0.99], [0.0, 1.02],
            [-1.0, -1.0],
        ])
        ids = [1, 2, 3, 4, 5, 6, 7, 8, 9]
        clusters = cluster_hdbscan(vectors, ids, min_cluster_size=3)
        assert sorted(len(c) for c in clusters) == [1, 4, 4]
        singleton = next(c for c in clusters if len(c) == 1)
        assert singleton == [9]

    def test_fewer_files_than_min_cluster_size_returns_all_singletons(self):
        # Below the sizing threshold, HDBSCAN itself is never invoked --
        # same "too sparse to cluster" outcome modularity/Louvain reach on
        # a graph with too few edges, reached here without risking
        # whatever the hdbscan library does on a 1-2 row input.
        vectors = np.array([[1.0, 0.0], [0.0, 1.0]])
        ids = [1, 2]
        clusters = cluster_hdbscan(vectors, ids, min_cluster_size=3)
        assert clusters == [[1], [2]]

    def test_deterministic_across_repeated_calls(self):
        vectors = np.array([
            [1.0, 0.0], [1.0, 0.01], [1.0, -0.01], [1.0, 0.02],
            [0.0, 1.0], [0.0, 1.01], [0.0, 0.99], [0.0, 1.02],
        ])
        ids = [10, 11, 12, 13, 20, 21, 22, 23]
        assert cluster_hdbscan(vectors, ids) == cluster_hdbscan(vectors, ids)


# ---------------- Phase I6: HDBSCAN (integration, fake embeddings) ----------------


def _fake_embed_by_group(texts: list) -> np.ndarray:
    """Stands in for embeddings.embed_texts in these tests -- deterministic,
    no ONNX model, no CPU inference pass, same reasoning as this project
    never hitting a real LLM in a fast test. Assigns each text a vector
    based on which fixture group its (always-included, per
    build_file_embedding_text) file path belongs to, with tiny per-index
    jitter so no two vectors are exact duplicates. iso.py's fallback vector
    must be ANGULARLY distinct from both groups after L2 normalization, not
    just far in raw magnitude -- see TestClusterHdbscan.test_noise_point_
    becomes_its_own_singleton for why a magnitude-only outlier like
    [50, 50] stops being an outlier at all once normalized in 2D."""
    vecs = []
    for i, t in enumerate(texts):
        jitter = (i % 5) * 0.001
        if "groupA" in t:
            vecs.append([1.0 + jitter, 0.0])
        elif "groupB" in t:
            vecs.append([0.0, 1.0 + jitter])
        else:
            vecs.append([-1.0, -1.0])
    return np.array(vecs)


class TestComputeSubsystemsHdbscanIntegration:
    def test_persists_third_algorithm_independently(self, db_session, tmp_path, monkeypatch):
        monkeypatch.setattr(subsystems_module.embeddings, "embed_texts", _fake_embed_by_group)
        repo = _ranked_repo(db_session, tmp_path)

        report = compute_subsystems_hdbscan(db_session, repo)
        assert report["cluster_count"] == 2
        assert report["embedded_file_count"] == 9  # 4 + 4 + iso.py

        ids = _path_of(db_session, repo)
        group_a_ids = {ids[f"groupA/a{i}.py"] for i in range(1, 5)}
        group_b_ids = {ids[f"groupB/b{i}.py"] for i in range(1, 5)}

        db_session.expire_all()
        hdbscan_of = {
            f.id: f.subsystem_hdbscan_id
            for f in db_session.query(CodeFile).filter(CodeFile.repo_id == repo.id).all()
        }
        a_clusters = {hdbscan_of[fid] for fid in group_a_ids}
        b_clusters = {hdbscan_of[fid] for fid in group_b_ids}
        assert len(a_clusters) == 1 and None not in a_clusters
        assert len(b_clusters) == 1 and None not in b_clusters
        assert a_clusters != b_clusters

    def test_modularity_and_louvain_rows_untouched(self, db_session, tmp_path, monkeypatch):
        monkeypatch.setattr(subsystems_module.embeddings, "embed_texts", _fake_embed_by_group)
        repo = _ranked_repo(db_session, tmp_path)
        compute_subsystems(db_session, repo)
        compute_subsystems_hdbscan(db_session, repo)
        rows = db_session.query(CodeSubsystem).filter(CodeSubsystem.repo_id == repo.id).all()
        assert {r.algorithm for r in rows} == {"modularity", "louvain", "hdbscan"}

    def test_agreement_with_modularity_none_when_modularity_not_run_yet(self, db_session, tmp_path, monkeypatch):
        monkeypatch.setattr(subsystems_module.embeddings, "embed_texts", _fake_embed_by_group)
        repo = _ranked_repo(db_session, tmp_path)
        report = compute_subsystems_hdbscan(db_session, repo)
        assert report["agreement_with_modularity"] is None

    def test_agreement_with_modularity_computed_when_both_present(self, db_session, tmp_path, monkeypatch):
        monkeypatch.setattr(subsystems_module.embeddings, "embed_texts", _fake_embed_by_group)
        repo = _ranked_repo(db_session, tmp_path)
        compute_subsystems(db_session, repo)  # modularity finds the same two cliques via the import graph
        report = compute_subsystems_hdbscan(db_session, repo)
        assert report["agreement_with_modularity"] == 1.0
        db_session.refresh(repo)
        assert repo.subsystem_hdbscan_agreement == 1.0

    def test_holds_repo_lock_for_the_whole_call(self, db_session, tmp_path, monkeypatch):
        monkeypatch.setattr(subsystems_module.embeddings, "embed_texts", _fake_embed_by_group)
        repo = _ranked_repo(db_session, tmp_path)
        with repo_lock(repo.id, "ingest"):
            with pytest.raises(RepoBusyError):
                compute_subsystems_hdbscan(db_session, repo)
