"""Git binary resolution and every git invocation this feature makes.

Resolution order (checked once, at import time -- never mid-ingest, per spec):
1. ATHENA_GIT_PATH setting/env var
2. PATH (shutil.which)
3. Known Windows locations (per-user, Program Files x2, GitHub Desktop bundle)
4. pygit2 -- used for every git operation (clone/fetch/checkout/log), not just
   as a last resort for one call. History-based ranking is marked
   reduced-confidence whenever this backend is active (see app/services/codebase
   ranking, Phase C), because pygit2's clone has no blob-filter equivalent and
   its behavior through this machine's SSL-intercepting proxy hasn't been
   verified the way `git clone --filter=blob:none` has.

If NEITHER a git binary NOR pygit2 is usable, boot fails loudly listing every
path tried -- that is the only case that raises here. A resolved-but-missing
git binary with pygit2 available is a supported degraded mode, not a failure.
"""
import glob
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import keyring

from app.core.config import settings

logger = logging.getLogger("athena.codebase.git")

KEYRING_SERVICE = "athena-codebase-agent"


class GitBinaryUnavailable(RuntimeError):
    pass


def _candidate_paths() -> list[str]:
    candidates = []
    if settings.ATHENA_GIT_PATH:
        candidates.append(settings.ATHENA_GIT_PATH)
    which = shutil.which("git")
    if which:
        candidates.append(which)
    localappdata = os.environ.get("LOCALAPPDATA", "")
    known = [
        rf"{localappdata}\Programs\Git\cmd\git.exe",
        r"C:\Program Files\Git\cmd\git.exe",
        r"C:\Program Files (x86)\Git\cmd\git.exe",
    ]
    # GitHub Desktop bundles git under a version-specific app-* directory.
    known.extend(glob.glob(rf"{localappdata}\GitHubDesktop\app-*\resources\app\git\cmd\git.exe"))
    candidates.extend(known)
    return candidates


def _resolve_git_binary() -> Optional[str]:
    tried = []
    for path in _candidate_paths():
        tried.append(path)
        if path and Path(path).is_file():
            logger.info("Resolved git binary: %s", path)
            return path
    logger.warning(
        "No git binary found (tried: %s). Falling back to pygit2 -- history-based "
        "ranking will run in reduced-confidence mode.",
        tried,
    )
    return None


GIT_BINARY = _resolve_git_binary()
GIT_AVAILABLE = GIT_BINARY is not None

if not GIT_AVAILABLE:
    try:
        import pygit2  # noqa: F401
    except ImportError as e:
        raise GitBinaryUnavailable(
            "No git binary found on this machine, and pygit2 is not installed either -- "
            f"the codebase agent cannot perform any git operation. Tried: {_candidate_paths()}. "
            "Install Git for Windows, set ATHENA_GIT_PATH, or `pip install pygit2`."
        ) from e


# ---------------- credentials: keyring only, never a URL, never a config file ----------------


def set_credential(host: str, token: str) -> None:
    keyring.set_password(KEYRING_SERVICE, host, token)


def get_credential(host: str) -> Optional[str]:
    return keyring.get_password(KEYRING_SERVICE, host)


def _askpass_env(host: str) -> dict:
    """Env for a git subprocess that supplies a stored credential without ever
    putting it in the URL, the command line, or a file that outlives this call."""
    env = os.environ.copy()
    token = get_credential(host)
    if not token:
        return env
    fd, script_path = tempfile.mkstemp(suffix=".cmd")
    try:
        with os.fdopen(fd, "w") as f:
            # %ATHENA_GIT_TOKEN% is read from the environment, never written into
            # this script file itself.
            f.write("@echo off\r\necho %ATHENA_GIT_TOKEN%\r\n")
        env["ATHENA_GIT_TOKEN"] = token
        env["GIT_ASKPASS"] = script_path
        env["GIT_TERMINAL_PROMPT"] = "0"
        env["_ATHENA_ASKPASS_SCRIPT"] = script_path  # so the caller can clean it up
    except Exception:
        os.unlink(script_path)
        raise
    return env


def _cleanup_askpass(env: dict) -> None:
    script_path = env.get("_ATHENA_ASKPASS_SCRIPT")
    if script_path and os.path.exists(script_path):
        try:
            os.unlink(script_path)
        except OSError:
            pass


# ---------------- URL parsing ----------------


def parse_git_url(url: str) -> tuple[str, str, str]:
    """(host, owner, name) from an https or ssh git URL."""
    url = url.strip()
    if "@" in url and not url.startswith(("http://", "https://")):
        # scp-like ssh form: git@github.com:owner/name.git
        host_part, _, path_part = url.partition(":")
        host = host_part.split("@")[-1]
        path = path_part
    else:
        parsed = urlparse(url)
        host = parsed.netloc.split("@")[-1]  # strip any embedded user@ (should never carry a token, but strip regardless)
        path = parsed.path
    path = path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    parts = [p for p in path.split("/") if p]
    if len(parts) < 2 or not host:
        raise ValueError(f"Could not parse owner/name from URL: {url}")
    owner, name = parts[-2], parts[-1]
    return host, owner, name


# ---------------- git.exe backend ----------------


def run_git(args: list[str], cwd: Optional[str] = None, env: Optional[dict] = None, timeout: int = 600) -> subprocess.CompletedProcess:
    """Every git.exe invocation goes through here: always --no-pager, never shell=True."""
    if not GIT_BINARY:
        raise GitBinaryUnavailable("git binary not resolved; this call should have used the pygit2 backend")
    cmd = [GIT_BINARY, "--no-pager", *args]
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env, shell=False)


def _clone_git_exe(url: str, dest: str) -> None:
    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    host, _, _ = parse_git_url(url)
    env = _askpass_env(host)
    try:
        result = run_git(
            [
                "clone",
                "--filter=blob:none",
                "--config", "core.autocrlf=false",
                "--config", "core.longpaths=true",
                url,
                dest,
            ],
            env=env,
        )
    finally:
        _cleanup_askpass(env)
    if result.returncode != 0:
        raise RuntimeError(f"git clone failed ({result.returncode}): {result.stderr.strip()}")


def _clone_pygit2(url: str, dest: str) -> None:
    import pygit2

    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    # pygit2's public clone_repository() has no blob-filter parameter (checked against
    # 1.18.2) -- this is a full clone, not a partial one. Deliberately not shallow
    # (depth=1) either: shallow would leave only one commit, destroying the history
    # signals Phase C computes, which defeats the point of falling back at all.
    host, _, _ = parse_git_url(url)
    token = get_credential(host)
    callbacks = None
    if token:
        callbacks = pygit2.RemoteCallbacks(credentials=pygit2.UserPass(token, "x-oauth-basic"))
    pygit2.clone_repository(url, dest, callbacks=callbacks)


def clone_repo(url: str, dest: str) -> None:
    if GIT_AVAILABLE:
        _clone_git_exe(url, dest)
    else:
        _clone_pygit2(url, dest)


def _fetch_git_exe(local_path: str) -> None:
    result = run_git(["fetch", "origin"], cwd=local_path)
    if result.returncode != 0:
        raise RuntimeError(f"git fetch failed ({result.returncode}): {result.stderr.strip()}")


def _fetch_pygit2(local_path: str) -> None:
    import pygit2

    repo = pygit2.Repository(local_path)
    repo.remotes["origin"].fetch()


def fetch_repo(local_path: str) -> None:
    if GIT_AVAILABLE:
        _fetch_git_exe(local_path)
    else:
        _fetch_pygit2(local_path)


def checkout_branch(local_path: str, branch: str) -> None:
    if not branch:
        return
    if GIT_AVAILABLE:
        result = run_git(["checkout", branch], cwd=local_path)
        if result.returncode != 0:
            raise RuntimeError(f"git checkout failed ({result.returncode}): {result.stderr.strip()}")
        result = run_git(["reset", "--hard", f"origin/{branch}"], cwd=local_path)
        if result.returncode != 0:
            raise RuntimeError(f"git reset failed ({result.returncode}): {result.stderr.strip()}")
    else:
        import pygit2

        repo = pygit2.Repository(local_path)
        ref = repo.lookup_reference(f"refs/remotes/origin/{branch}")
        repo.checkout(ref, strategy=pygit2.GIT_CHECKOUT_FORCE)
        repo.set_head(ref.target)


def get_head_sha(local_path: str) -> Optional[str]:
    if GIT_AVAILABLE:
        result = run_git(["rev-parse", "HEAD"], cwd=local_path)
        return result.stdout.strip() if result.returncode == 0 else None
    import pygit2

    try:
        return str(pygit2.Repository(local_path).head.target)
    except Exception:
        return None


def get_current_branch(local_path: str) -> str:
    if GIT_AVAILABLE:
        result = run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=local_path)
        return result.stdout.strip() if result.returncode == 0 else ""
    import pygit2

    try:
        repo = pygit2.Repository(local_path)
        return repo.head.shorthand if not repo.head_is_detached else ""
    except Exception:
        return ""


def get_remote_url(local_path: str) -> Optional[str]:
    if GIT_AVAILABLE:
        result = run_git(["remote", "get-url", "origin"], cwd=local_path)
        return result.stdout.strip() if result.returncode == 0 else None
    import pygit2

    try:
        return pygit2.Repository(local_path).remotes["origin"].url
    except Exception:
        return None
