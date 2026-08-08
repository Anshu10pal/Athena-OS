"""Host/organisation blocklist -- a hard refusal, independent of allow_external_llm
or any other per-repo setting. Re-read from disk on every check rather than cached
at import time, so an edit to the policy file takes effect without a restart.
"""
from pathlib import Path

import yaml

from app.core.config import BACKEND_DIR, settings


class RepoBlocked(PermissionError):
    pass


def _policy_path() -> Path:
    p = Path(settings.REPO_POLICY_PATH)
    return p if p.is_absolute() else BACKEND_DIR / p


def _load_policy() -> dict:
    path = _policy_path()
    if not path.is_file():
        return {"blocked_hosts": [], "blocked_orgs": []}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {
        "blocked_hosts": [h.lower() for h in (data.get("blocked_hosts") or [])],
        "blocked_orgs": [o.lower() for o in (data.get("blocked_orgs") or [])],
    }


def check_policy(host: str, owner: str) -> None:
    policy = _load_policy()
    if host.lower() in policy["blocked_hosts"]:
        raise RepoBlocked(f"Host '{host}' is blocked by repo policy ({_policy_path()}).")
    if owner and owner.lower() in policy["blocked_orgs"]:
        raise RepoBlocked(f"Organisation '{owner}' is blocked by repo policy ({_policy_path()}).")
