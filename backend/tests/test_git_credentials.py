"""Credential resolution and the askpass helper.

This path had no coverage at all, which is exactly why the Render failure
shipped: every clone test patches `clone_repo` wholesale, so `_askpass_env`
was never executed by a test on any platform.
"""
import os
import stat
import subprocess
from unittest.mock import patch

import pytest

from app.services.codebase import git_ops


class NoKeyringError(RuntimeError):
    """Mirrors keyring.errors.NoKeyringError, which really does subclass
    RuntimeError -- the reason a missing backend surfaced to the user as
    'Could not acquire the repository'."""


@pytest.fixture(autouse=True)
def _reset_warn_flag():
    git_ops._keyring_warned = False
    yield
    git_ops._keyring_warned = False


class TestMissingKeyringBackend:
    def test_get_credential_returns_none_instead_of_raising(self, monkeypatch):
        monkeypatch.delenv(git_ops.token_env_var("github.com"), raising=False)
        with patch("app.services.codebase.git_ops.keyring.get_password",
                   side_effect=NoKeyringError("No recommended backend was available")):
            assert git_ops.get_credential("github.com") is None

    def test_askpass_env_survives_a_missing_backend(self, monkeypatch):
        """The regression itself: a public clone must not fail because the
        optional credential lookup could not be performed."""
        monkeypatch.delenv(git_ops.token_env_var("github.com"), raising=False)
        with patch("app.services.codebase.git_ops.keyring.get_password",
                   side_effect=NoKeyringError("No recommended backend was available")):
            env = git_ops._askpass_env("github.com")
        assert "GIT_ASKPASS" not in env
        assert env["GIT_TERMINAL_PROMPT"] == "0"

    def test_set_credential_reports_the_env_var_alternative(self):
        with patch("app.services.codebase.git_ops.keyring.set_password",
                   side_effect=NoKeyringError("No recommended backend was available")):
            with pytest.raises(RuntimeError, match="ATHENA_GIT_TOKEN_GITHUB_COM"):
                git_ops.set_credential("github.com", "tok")


class TestEnvVarCredential:
    def test_env_var_is_used(self, monkeypatch):
        monkeypatch.setenv(git_ops.token_env_var("github.com"), "env-token")
        with patch("app.services.codebase.git_ops.keyring.get_password") as kr:
            assert git_ops.get_credential("github.com") == "env-token"
        kr.assert_not_called()

    def test_env_var_name_is_derived_from_the_host(self):
        assert git_ops.token_env_var("github.com") == "ATHENA_GIT_TOKEN_GITHUB_COM"
        assert git_ops.token_env_var("gitlab.example.co.uk") == "ATHENA_GIT_TOKEN_GITLAB_EXAMPLE_CO_UK"

    def test_a_token_is_never_offered_to_a_different_host(self, monkeypatch):
        """No generic ATHENA_GIT_TOKEN: one mistyped URL must not disclose a
        GitHub token to an attacker-controlled host."""
        monkeypatch.setenv("ATHENA_GIT_TOKEN_GITHUB_COM", "gh-token")
        monkeypatch.setenv("ATHENA_GIT_TOKEN", "generic-token")
        monkeypatch.delenv("ATHENA_GIT_TOKEN_EVIL_EXAMPLE_COM", raising=False)
        with patch("app.services.codebase.git_ops.keyring.get_password", return_value=None):
            assert git_ops.get_credential("evil.example.com") is None

    def test_no_host_means_no_credential(self, monkeypatch):
        with patch("app.services.codebase.git_ops.keyring.get_password") as kr:
            assert git_ops.get_credential("") is None
        kr.assert_not_called()


class TestAskpassScript:
    def test_script_echoes_the_token_and_never_contains_it(self, monkeypatch):
        monkeypatch.setenv(git_ops.token_env_var("github.com"), "s3cret-token")
        env = git_ops._askpass_env("github.com")
        path = env["GIT_ASKPASS"]
        try:
            assert env["ATHENA_GIT_TOKEN"] == "s3cret-token"
            assert env["GIT_TERMINAL_PROMPT"] == "0"
            with open(path) as f:
                body = f.read()
            assert "s3cret-token" not in body, "the token must live in the env, not on disk"

            # Actually run it: a .cmd file on Linux is the second half of the
            # Render bug, and only executing it catches that.
            out = subprocess.run([path, "Password for 'https://github.com':"],
                                 capture_output=True, text=True, env=env, timeout=30)
            assert out.returncode == 0, out.stderr
            assert out.stdout.strip() == "s3cret-token"
        finally:
            git_ops._cleanup_askpass(env)
        assert not os.path.exists(path)

    @pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
    def test_script_is_executable_on_posix(self, monkeypatch):
        monkeypatch.setenv(git_ops.token_env_var("github.com"), "tok")
        env = git_ops._askpass_env("github.com")
        try:
            mode = os.stat(env["GIT_ASKPASS"]).st_mode
            assert mode & stat.S_IXUSR, "git cannot invoke a non-executable GIT_ASKPASS"
            assert not (mode & (stat.S_IRWXG | stat.S_IRWXO)), "must not be group/world readable"
        finally:
            git_ops._cleanup_askpass(env)

    def test_cleanup_is_safe_when_no_script_was_written(self, monkeypatch):
        monkeypatch.delenv(git_ops.token_env_var("github.com"), raising=False)
        with patch("app.services.codebase.git_ops.keyring.get_password", return_value=None):
            env = git_ops._askpass_env("github.com")
        git_ops._cleanup_askpass(env)  # must not raise
