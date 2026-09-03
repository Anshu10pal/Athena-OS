import os
from pathlib import Path

import platformdirs
from pydantic_settings import BaseSettings

BACKEND_DIR = Path(__file__).resolve().parents[2]

# All runtime-generated state (repo clone cache, uploaded resource files, the
# local vector DB) lives under one app-data root OUTSIDE any tree a user
# might register and ingest -- platformdirs picks the right convention per
# OS (XDG on Linux, where this deploys via Render; %LOCALAPPDATA% on
# Windows). An earlier default put the clone cache at "./data/repos"
# resolved relative to BACKEND_DIR, i.e. inside this very repo's own
# backend/ directory -- a registered `local` repo at the monorepo root would
# have the cache nested inside its own analysable tree. That was only saved
# from contaminating ingest by this repo's own .gitignore happening to list
# backend/data/ -- incidental, not a guarantee (a registered local path may
# not be a git repo at all, or its .gitignore may not cover wherever these
# settings point). See app/services/codebase/registry.py for the real,
# gitignore-independent guard (protected_data_exclusion_patterns) and the
# startup check (check_clone_root_safety) that refuses to serve rather than
# merely working around a misconfiguration.
#
# `os.path.expandvars("%LOCALAPPDATA%")` -- an earlier, wrong approach --
# does not resolve %VAR% syntax on POSIX; it returns the string unchanged,
# which on Render (Linux) would have created a literal directory named
# `%LOCALAPPDATA%` relative to the working directory, possibly right back
# inside an analysable tree. platformdirs handles this correctly per-OS.
APP_DATA_ROOT = Path(platformdirs.user_data_dir("athena-codebase-agent", appauthor=False))


# ALL model weights live HERE, inside the repo directory, and that location is
# not a preference -- it is what Render's filesystem semantics allow.
#
# Verified against Render's own docs rather than assumed (the assumption that
# this project ships in a Docker image was carried across four filed items
# before anyone checked; see decisions.md, the unresolved-premise class):
#
#   * The build command's filesystem DOES carry into the runtime -- it must,
#     since `pip install -r requirements.txt` at build and `uvicorn` at start
#     is the documented shape.
#   * Persistent disks are NOT accessible during the build command ("these
#     commands run on separate compute").
#   * The runtime filesystem is otherwise EPHEMERAL: "any changes you make to a
#     service's local files are lost every time the service redeploys or
#     restarts."
#
# What the docs do NOT say is whether build-time writes OUTSIDE the project
# directory (~/.cache, /tmp) reach the runtime. Betting the closure of KI-2 and
# VKI-4 on an undocumented behaviour would be the same class of defect those
# items describe, so weights go somewhere documented to exist at runtime: the
# service's own source directory.
#
# This also matters more than "one download" on the free tier: a RUNTIME fetch
# is re-paid on every cold start after a spin-down, because the ephemeral
# filesystem is restored to its post-build state. A build-time fetch is paid
# once per deploy.
MODELS_DIR = Path(os.environ.get("MODELS_DIR", str(BACKEND_DIR / "models")))

# When true (the default), every model loader is told it may NOT reach the
# network -- `local_files_only` / offline flags rather than a warm cache we hope
# for. That is the difference between "it did not download this time" and "it
# cannot download", and only the second is testable.
#
# KI-2's decision was that the app "either boots working or fails at build,
# never at a user's first request". Defaulting this to true is what implements
# that: a checkout that skipped scripts/fetch_models.sh fails loudly and
# actionably instead of silently fetching 316 MB on someone's first click.
MODELS_OFFLINE = os.environ.get("MODELS_OFFLINE", "1") not in ("0", "false", "False")


class Settings(BaseSettings):
    GEMINI_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    SECRET_KEY: str = "dev-secret-change-me"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 43200  # 30 days (feedback phase)
    DATABASE_URL: str = "sqlite:///./athena.db"
    QDRANT_PATH: str = str(APP_DATA_ROOT / "qdrant_data")

    # Every logged-in user currently has full write access to the content library --
    # there's no role model yet. This flag is the seam: flip it off (and implement
    # real role checks in app.core.security.require_write_access) once there's more
    # than one user who shouldn't have admin rights over the library.
    SINGLE_USER_MODE: bool = True

    # Uploaded topic resource files (POST /api/topics/{id}/resources/upload).
    # Render's default web service filesystem is ephemeral -- this directory
    # (like the clone cache and Qdrant's) needs a persistent disk attached in
    # production, or uploads/cache are lost on every redeploy. See README.md.
    RESOURCES_DIR: str = str(APP_DATA_ROOT / "resources")

    # Codebase agent: where repo clones and blocklist policy live.
    ATHENA_GIT_PATH: str = ""  # explicit override, checked before PATH -- see app/services/codebase/git_ops.py
    REPO_CLONE_ROOT: str = str(APP_DATA_ROOT / "repos")
    REPO_CLONE_CACHE_MAX_BYTES: int = 5 * 1024 * 1024 * 1024  # 5 GB
    REPO_POLICY_PATH: str = "./config/repo_policy.yaml"
    REPO_MAX_FILES: int = 20000  # ingest refuses outright above this, no silent truncation
    RANKING_WEIGHTS_PATH: str = "./config/ranking_weights.yaml"
    EDGE_WEIGHTS_PATH: str = "./config/edge_weights.yaml"
    NODE_PRIORS_PATH: str = "./config/node_priors.yaml"
    WEIGHTED_PAGERANK_CONFIG_PATH: str = "./config/weighted_pagerank.yaml"
    RRF_CONFIG_PATH: str = "./config/rrf.yaml"
    ENTRY_DETECTION_CONFIG_PATH: str = "./config/entry_detection.yaml"
    ROOT_DISCOVERY_CONFIG_PATH: str = "./config/root_discovery.yaml"
    JS_ROOT_DISCOVERY_CONFIG_PATH: str = "./config/js_root_discovery.yaml"
    RESOLUTION_TRIPWIRE_CONFIG_PATH: str = "./config/resolution_tripwire.yaml"
    SUBSYSTEM_CLUSTERING_CONFIG_PATH: str = "./config/subsystem_clustering.yaml"
    ROADMAP_STAGING_CONFIG_PATH: str = "./config/roadmap_staging.yaml"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"  # avoids the UTF-16 .env trap on Windows


settings = Settings()
