"""Repository registration and acquisition (Phase A).

Two ways in: a git URL (cloned into the local cache) or a path to an existing
checkout (used in place, never modified -- no fetch, no checkout, no write of
any kind ever touches a `local` repo).

The clone cache is exactly that -- a cache. Eviction deletes the DB row and the
on-disk directory together; re-adding by URL is the recovery path, nothing is
lost that a re-clone can't reproduce.
"""
import os
import shutil
import stat
from pathlib import Path
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import APP_DATA_ROOT, BACKEND_DIR, settings
from app.db.models import Repo
from app.services.codebase import git_ops
from app.services.codebase.git_ops import GitBinaryUnavailable  # noqa: F401  (re-exported for callers)
from app.services.codebase.policy import check_policy


def clone_cache_root() -> Path:
    p = Path(settings.REPO_CLONE_ROOT)
    return p if p.is_absolute() else BACKEND_DIR / p


def _resources_dir() -> Path:
    p = Path(settings.RESOURCES_DIR)
    return p if p.is_absolute() else BACKEND_DIR / p


def _qdrant_dir() -> Path:
    p = Path(settings.QDRANT_PATH)
    return p if p.is_absolute() else BACKEND_DIR / p


def _protected_data_dirs() -> list[Path]:
    """Every runtime-generated directory that must never be treated as part
    of an ingested repo's own source, regardless of that repo's .gitignore
    (or the complete absence of one -- a registered `local` path may not be
    a git repo at all)."""
    return [clone_cache_root(), _resources_dir(), _qdrant_dir(), APP_DATA_ROOT]


def protected_data_exclusion_patterns(ingest_root: Path) -> list[str]:
    """gitignore-style patterns (POSIX, trailing slash) excluding every
    configured runtime-data directory that happens to live inside
    ingest_root. Independent of ingest_root's own .gitignore. Also includes
    a literal "data/" pattern as a defense-in-depth fallback specific to
    this project's own history -- both the old clone cache and resources
    dir defaults lived at backend/data/{repos,resources} before being
    relocated, so a stray leftover or future misconfiguration under
    backend/data/ is still caught even if it no longer matches any
    currently-configured path exactly."""
    root = ingest_root.resolve()
    patterns: list[str] = []
    for p in _protected_data_dirs():
        try:
            rel = p.resolve().relative_to(root)
        except ValueError:
            continue
        pattern = rel.as_posix() + "/"
        if pattern not in patterns:
            patterns.append(pattern)
    if (root / "data").is_dir() and "data/" not in patterns:
        patterns.append("data/")
    return patterns


def check_clone_root_safety(db: Session) -> None:
    """Refuse to start (raises RuntimeError, not logged-and-ignored) if the
    resolved clone cache root sits inside any registered repo's local_path.
    This is the guard that makes the class of bug impossible rather than
    merely worked around: ingest-time exclusion (protected_data_exclusion_patterns)
    only helps if someone remembers it exists; this fails loudly at boot,
    the same "fail loudly, never mid-ingest" principle as git binary
    resolution in git_ops.py."""
    cache_root = clone_cache_root().resolve()
    for repo in db.query(Repo).all():
        repo_root = Path(repo.local_path).resolve()
        try:
            cache_root.relative_to(repo_root)
        except ValueError:
            continue
        raise RuntimeError(
            f"Refusing to start: the configured clone cache root ({cache_root}) is inside "
            f"registered repo '{repo.host}/{repo.owner}/{repo.name}' at ({repo_root}). "
            "Set REPO_CLONE_ROOT to a path outside every registered repo's tree -- otherwise "
            "the clone cache would be ingested as part of that repo's own code."
        )


def register_from_url(db: Session, url: str, source_root: Optional[str] = None) -> Repo:
    host, owner, name = git_ops.parse_git_url(url)
    check_policy(host, owner)

    existing = db.query(Repo).filter(Repo.host == host, Repo.owner == owner, Repo.name == name).first()
    if existing:
        return existing  # already registered -- caller should resync, not re-add

    dest = clone_cache_root() / host / owner / name
    git_ops.clone_repo(url, str(dest))
    branch = git_ops.get_current_branch(str(dest))

    repo = Repo(
        host=host,
        owner=owner,
        name=name,
        url=url,
        local_path=str(dest),
        source_kind="clone",
        default_branch=branch,
        visibility="unknown",
        source_root=source_root,
        allow_external_llm=False,
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)
    evict_lru_if_needed(db)
    return repo


def register_from_path(db: Session, local_path: str, source_root: Optional[str] = None) -> Repo:
    p = Path(local_path).resolve()
    if not p.is_dir():
        raise ValueError(f"Path does not exist or is not a directory: {local_path}")

    existing = db.query(Repo).filter(Repo.local_path == str(p)).first()
    if existing:
        return existing

    host, owner, name, url, branch = "local", "", p.name, None, ""
    origin = git_ops.get_remote_url(str(p))  # read-only -- never fetches, never writes
    if origin:
        try:
            host, owner, name = git_ops.parse_git_url(origin)
            url = origin
        except ValueError:
            pass
    branch = git_ops.get_current_branch(str(p)) or ""

    check_policy(host, owner)

    if host != "local":
        # Two different local_paths (e.g. a checkout root and one of its own
        # subdirectories) can derive the identical (host, owner, name) from a
        # shared git origin -- the repos table's unique constraint on that
        # triple would otherwise surface as a raw IntegrityError/500. Caught
        # here as a clear error instead: found via a live end-to-end check
        # against this repo's own real git remote, not a hypothetical.
        conflict = db.query(Repo).filter(Repo.host == host, Repo.owner == owner, Repo.name == name).first()
        if conflict:
            raise ValueError(
                f"{host}/{owner}/{name} is already registered (at {conflict.local_path}). Registering the "
                "same git remote at a second local path isn't supported -- set source_root on the existing "
                "registration instead to scope ingestion to a subdirectory."
            )

    repo = Repo(
        host=host,
        owner=owner,
        name=name,
        url=url,
        local_path=str(p),
        source_kind="local",
        default_branch=branch,
        visibility="unknown",
        source_root=source_root,
        allow_external_llm=False,
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)
    return repo


def resync(db: Session, repo: Repo) -> Repo:
    """git fetch + checkout. Never a fresh clone. Never called on a `local` repo."""
    if repo.source_kind != "clone":
        raise ValueError("Only 'clone' repos can be resynced -- 'local' repos are used in place and never modified.")
    git_ops.fetch_repo(repo.local_path)
    git_ops.checkout_branch(repo.local_path, repo.default_branch)
    db.commit()
    return repo


def _dir_size_bytes(path: Path) -> int:
    if not path.is_dir():
        return 0
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def _clear_readonly_and_retry(func, path, exc_info) -> None:
    """shutil.rmtree onerror hook: git leaves some objects (e.g. commit-graph-chain)
    read-only on Windows, which trips a bare PermissionError on delete. This is not
    an edge case -- it reproduces on every eviction of a real clone -- so it's
    handled here rather than papered over with ignore_errors=True, which would
    silently leave the directory on disk while the DB row (and the space budget
    it was supposed to represent) is already gone."""
    os.chmod(path, stat.S_IWRITE)
    func(path)


def _remove_repo_dir(path: str) -> None:
    shutil.rmtree(path, onerror=_clear_readonly_and_retry)


def evict_lru_if_needed(db: Session) -> list[str]:
    """Evicts the least-recently-ingested `clone` repos (falling back to added_at
    for ones never ingested, so a freshly-cloned repo isn't evicted before Phase B
    even gets to it) until the cache is back under the configured byte cap.
    """
    cap = settings.REPO_CLONE_CACHE_MAX_BYTES
    order_col = func.coalesce(Repo.last_ingested_at, Repo.added_at)
    clones = db.query(Repo).filter(Repo.source_kind == "clone").order_by(order_col.asc()).all()

    sizes = {r.id: _dir_size_bytes(Path(r.local_path)) for r in clones}
    total = sum(sizes.values())

    evicted = []
    for r in clones:
        if total <= cap:
            break
        _remove_repo_dir(r.local_path)
        total -= sizes[r.id]
        evicted.append(f"{r.host}/{r.owner}/{r.name}")
        db.delete(r)
    if evicted:
        db.commit()
    return evicted
