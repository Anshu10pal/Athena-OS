"""Phase A: repo registration and acquisition. No live network calls here --
`register_from_path` needs no network at all, and clone/fetch are mocked so the
suite stays fast and doesn't depend on the proxy being reachable. The real
blobless clone through the proxy was verified manually (see the Phase A report),
not re-asserted here.
"""
from pathlib import Path
from unittest.mock import patch

import pytest

from app.db.models import Repo
from app.services.codebase import git_ops
from app.services.codebase.policy import RepoBlocked, check_policy
from app.services.codebase.registry import (
    check_clone_root_safety,
    protected_data_exclusion_patterns,
    register_from_path,
    register_from_url,
    resync,
)


class TestParseGitUrl:
    def test_https(self):
        assert git_ops.parse_git_url("https://github.com/pallets/click.git") == ("github.com", "pallets", "click")

    def test_https_no_dot_git_suffix(self):
        assert git_ops.parse_git_url("https://github.com/pallets/click") == ("github.com", "pallets", "click")

    def test_ssh_scp_form(self):
        assert git_ops.parse_git_url("git@github.com:pallets/click.git") == ("github.com", "pallets", "click")

    def test_trailing_slash(self):
        assert git_ops.parse_git_url("https://github.com/pallets/click/") == ("github.com", "pallets", "click")

    def test_unparseable_raises(self):
        with pytest.raises(ValueError):
            git_ops.parse_git_url("not-a-url")


class TestPolicy:
    def test_blocked_host_rejected(self, tmp_path, monkeypatch):
        policy_file = tmp_path / "repo_policy.yaml"
        policy_file.write_text("blocked_hosts: [github.com]\nblocked_orgs: []\n")
        with patch("app.services.codebase.policy._policy_path", return_value=policy_file):
            with pytest.raises(RepoBlocked):
                check_policy("github.com", "anyone")

    def test_blocked_org_rejected(self, tmp_path):
        policy_file = tmp_path / "repo_policy.yaml"
        policy_file.write_text("blocked_hosts: []\nblocked_orgs: [some-org]\n")
        with patch("app.services.codebase.policy._policy_path", return_value=policy_file):
            with pytest.raises(RepoBlocked):
                check_policy("github.com", "some-org")

    def test_unblocked_passes(self, tmp_path):
        policy_file = tmp_path / "repo_policy.yaml"
        policy_file.write_text("blocked_hosts: []\nblocked_orgs: []\n")
        with patch("app.services.codebase.policy._policy_path", return_value=policy_file):
            check_policy("github.com", "pallets")  # must not raise

    def test_missing_policy_file_allows_everything(self, tmp_path):
        with patch("app.services.codebase.policy._policy_path", return_value=tmp_path / "nope.yaml"):
            check_policy("github.com", "pallets")  # must not raise


class TestRegisterFromPath:
    def test_registers_a_plain_folder(self, db_session, tmp_path):
        repo = register_from_path(db_session, str(tmp_path))
        assert repo.source_kind == "local"
        assert repo.host == "local"
        assert repo.name == tmp_path.name

    def test_never_modifies_the_directory(self, db_session, tmp_path):
        marker = tmp_path / "marker.txt"
        marker.write_text("original content")
        before = marker.stat().st_mtime_ns
        register_from_path(db_session, str(tmp_path))
        after = marker.stat().st_mtime_ns
        assert before == after
        assert marker.read_text() == "original content"

    def test_idempotent_returns_same_row(self, db_session, tmp_path):
        first = register_from_path(db_session, str(tmp_path))
        second = register_from_path(db_session, str(tmp_path))
        assert first.id == second.id
        assert db_session.query(Repo).count() == 1

    def test_nonexistent_path_raises(self, db_session, tmp_path):
        with pytest.raises(ValueError):
            register_from_path(db_session, str(tmp_path / "does-not-exist"))

    def test_derives_host_owner_name_from_origin_remote(self, db_session, tmp_path):
        with patch("app.services.codebase.git_ops.get_remote_url", return_value="https://github.com/pallets/click.git"):
            with patch("app.services.codebase.git_ops.get_current_branch", return_value="main"):
                repo = register_from_path(db_session, str(tmp_path))
        assert (repo.host, repo.owner, repo.name) == ("github.com", "pallets", "click")
        assert repo.default_branch == "main"

    def test_second_local_path_with_same_origin_raises_clean_error(self, db_session, tmp_path):
        # Two different local_paths (e.g. a checkout root and one of its own
        # subdirectories) can derive the identical (host, owner, name) from a
        # shared git origin -- found live against this repo's own real git
        # remote, where the repos table's unique constraint on that triple
        # otherwise surfaces as a raw IntegrityError/500 instead of a clean error.
        first_dir = tmp_path / "checkout"
        second_dir = tmp_path / "checkout-subdir"
        first_dir.mkdir()
        second_dir.mkdir()
        with patch("app.services.codebase.git_ops.get_remote_url", return_value="https://github.com/pallets/click.git"):
            with patch("app.services.codebase.git_ops.get_current_branch", return_value="main"):
                register_from_path(db_session, str(first_dir))
                with pytest.raises(ValueError, match="already registered"):
                    register_from_path(db_session, str(second_dir))


class TestRegisterFromUrl:
    def test_clones_and_registers(self, db_session, tmp_path):
        dest_seen = {}

        def fake_clone(url, dest):
            dest_seen["dest"] = dest

        with patch("app.services.codebase.registry.clone_cache_root", return_value=tmp_path):
            with patch("app.services.codebase.git_ops.clone_repo", side_effect=fake_clone) as mock_clone:
                with patch("app.services.codebase.git_ops.get_current_branch", return_value="main"):
                    repo = register_from_url(db_session, "https://github.com/pallets/click.git")

        assert mock_clone.called
        assert repo.source_kind == "clone"
        assert (repo.host, repo.owner, repo.name) == ("github.com", "pallets", "click")
        assert repo.local_path == dest_seen["dest"]

    def test_second_call_does_not_reclone(self, db_session, tmp_path):
        with patch("app.services.codebase.registry.clone_cache_root", return_value=tmp_path):
            with patch("app.services.codebase.git_ops.clone_repo") as mock_clone:
                with patch("app.services.codebase.git_ops.get_current_branch", return_value="main"):
                    first = register_from_url(db_session, "https://github.com/pallets/click.git")
                    second = register_from_url(db_session, "https://github.com/pallets/click.git")
        assert mock_clone.call_count == 1
        assert first.id == second.id


class TestResync:
    def test_rejects_local_repos(self, db_session, tmp_path):
        repo = register_from_path(db_session, str(tmp_path))
        with pytest.raises(ValueError, match="never modified"):
            resync(db_session, repo)

    def test_fetches_and_checks_out_clone_repos(self, db_session, tmp_path):
        with patch("app.services.codebase.registry.clone_cache_root", return_value=tmp_path):
            with patch("app.services.codebase.git_ops.clone_repo"):
                with patch("app.services.codebase.git_ops.get_current_branch", return_value="main"):
                    repo = register_from_url(db_session, "https://github.com/pallets/click.git")

        with patch("app.services.codebase.git_ops.fetch_repo") as mock_fetch:
            with patch("app.services.codebase.git_ops.checkout_branch") as mock_checkout:
                resync(db_session, repo)
        mock_fetch.assert_called_once_with(repo.local_path)
        mock_checkout.assert_called_once_with(repo.local_path, "main")


def _patch_all_protected_dirs(clone=None, resources=None, qdrant=None, app_data=None):
    """All four protected_data_exclusion_patterns inputs, patched to a
    controlled location (defaulting to somewhere that can never be nested
    inside a tmp_path used by a test) so only the ones a given test cares
    about actually land inside its ingest_root."""
    safe = Path("Z:/nonexistent-safe-default")
    return [
        patch("app.services.codebase.registry.clone_cache_root", return_value=clone or safe),
        patch("app.services.codebase.registry._resources_dir", return_value=resources or safe),
        patch("app.services.codebase.registry._qdrant_dir", return_value=qdrant or safe),
        patch("app.services.codebase.registry.APP_DATA_ROOT", app_data or safe),
    ]


class TestProtectedDataExclusion:
    def test_empty_when_nothing_nested_inside_ingest_root(self, tmp_path):
        ingest_root = tmp_path / "some_repo"
        ingest_root.mkdir()
        cache_root = tmp_path / "elsewhere" / "cache"
        patches = _patch_all_protected_dirs(clone=cache_root)
        with patches[0], patches[1], patches[2], patches[3]:
            assert protected_data_exclusion_patterns(ingest_root) == []

    def test_pattern_when_clone_cache_nested_inside_ingest_root(self, tmp_path):
        ingest_root = tmp_path / "monorepo"
        cache_root = ingest_root / "cachedir" / "repos"
        cache_root.mkdir(parents=True)
        patches = _patch_all_protected_dirs(clone=cache_root)
        with patches[0], patches[1], patches[2], patches[3]:
            patterns = protected_data_exclusion_patterns(ingest_root)
        assert patterns == ["cachedir/repos/"]

    def test_all_four_nested_produce_four_deduped_patterns(self, tmp_path):
        ingest_root = tmp_path / "monorepo"
        clone = ingest_root / "a" / "repos"
        resources = ingest_root / "b" / "resources"
        qdrant = ingest_root / "c" / "qdrant"
        app_data = ingest_root / "d"
        for p in (clone, resources, qdrant, app_data):
            p.mkdir(parents=True)
        patches = _patch_all_protected_dirs(clone=clone, resources=resources, qdrant=qdrant, app_data=app_data)
        with patches[0], patches[1], patches[2], patches[3]:
            patterns = protected_data_exclusion_patterns(ingest_root)
        assert set(patterns) == {"a/repos/", "b/resources/", "c/qdrant/", "d/"}

    def test_literal_data_dir_fallback_even_when_no_configured_path_matches(self, tmp_path):
        # Defense-in-depth for this project's own history: backend/data/ was
        # where both the clone cache and resources dir used to live. A stray
        # leftover there must still be excluded even if it no longer matches
        # any currently-configured path exactly.
        ingest_root = tmp_path / "monorepo"
        (ingest_root / "data").mkdir(parents=True)
        patches = _patch_all_protected_dirs()  # nothing configured points inside ingest_root
        with patches[0], patches[1], patches[2], patches[3]:
            patterns = protected_data_exclusion_patterns(ingest_root)
        assert patterns == ["data/"]

    def test_pattern_when_cache_equals_ingest_root(self, tmp_path):
        # Degenerate but must not crash: registering the cache root itself.
        patches = _patch_all_protected_dirs(clone=tmp_path)
        with patches[0], patches[1], patches[2], patches[3]:
            patterns = protected_data_exclusion_patterns(tmp_path)
        assert patterns == ["./"]


class TestCloneRootSafetyCheck:
    def test_raises_when_clone_root_inside_a_registered_repo(self, db_session, tmp_path):
        repo_root = tmp_path / "myrepo"
        repo_root.mkdir()
        clone_root = repo_root / "cache"
        register_from_path(db_session, str(repo_root))
        with patch("app.services.codebase.registry.clone_cache_root", return_value=clone_root):
            with pytest.raises(RuntimeError, match="Refusing to start"):
                check_clone_root_safety(db_session)

    def test_passes_when_clone_root_outside_every_registered_repo(self, db_session, tmp_path):
        repo_root = tmp_path / "myrepo"
        repo_root.mkdir()
        clone_root = tmp_path / "elsewhere" / "cache"
        register_from_path(db_session, str(repo_root))
        with patch("app.services.codebase.registry.clone_cache_root", return_value=clone_root):
            check_clone_root_safety(db_session)  # must not raise

    def test_passes_with_no_registered_repos_at_all(self, db_session):
        check_clone_root_safety(db_session)  # must not raise
