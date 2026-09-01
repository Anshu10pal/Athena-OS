"""Loader for config/arena_extraction.yaml.

Same shape as the codebase agent's config loaders (edge_weights.py,
subsystems.py): a DEFAULT_* dict in code, the YAML overlaid on top, and a bad
or missing file degrading to the defaults with a log line rather than taking
the API down at import time.

The defaults here are NOT a second source of truth to be kept in sync with the
YAML by hand -- they are the minimum needed for the module to import and for
tests to run without a config file present. The YAML is authoritative for every
number a human is expected to tune. Where the two disagree, the YAML wins, and
`load_config` says so by merging one level deep.
"""
import logging
from pathlib import Path
from typing import Any, Optional

import yaml

from app.core.config import BACKEND_DIR

logger = logging.getLogger("athena.arena.config")

CONFIG_PATH = BACKEND_DIR / "config" / "arena_extraction.yaml"

# Minimum viable defaults. Deliberately thin: enough to import and to run the
# deterministic unit tests, not a mirror of the YAML.
DEFAULT_CONFIG: dict[str, Any] = {
    "extractor_version": "a1",
    "canonicalisation": {
        # Shadow metric only -- withdrawn as a decision branch after measuring a
        # 92% false-merge rate under template phrasing. See canonicalise.py.
        "enriched_cosine_threshold": 0.76,
        "bare_cosine_threshold": 0.86,
        "review_band_low": 0.80,
        "containment_min_chars": 5,
        "aliases": {},
    },
    "clustering": {
        "coherence_threshold": 0.64,
        "min_coherent_parent_fraction": 0.80,
        "linkage": "average",
        "metric": "cosine",
    },
    "node_budget": [
        {"max_mentions": 7, "min_parents": 2, "max_parents": 4, "allow_flat": True},
        {"max_mentions": 14, "min_parents": 3, "max_parents": 5, "allow_flat": False},
        {"max_mentions": 29, "min_parents": 5, "max_parents": 7, "allow_flat": False},
        {"max_mentions": 100000, "min_parents": 6, "max_parents": 9, "allow_flat": False},
    ],
    "max_children_per_parent": 8,
    "weighting": {
        # Headroom below max_weight is load-bearing -- see the YAML's comment.
        # required == max_weight made signals 2-5 inert for required skills.
        "section_base": {
            "required": 0.60, "responsibilities": 0.42, "preferred": 0.24,
            "nice_to_have": 0.18, "boilerplate": 0.03, "unknown": 0.30,
        },
        "title_presence_bonus": 0.25,
        "repetition_bonus_per_log2": 0.09,
        "repetition_bonus_cap": 0.18,
        "position_bonus_max": 0.10,
        "qualifier_bonus": {
            "expert": 0.15, "proficient": 0.08, "working": 0.00, "awareness": -0.12,
        },
        "min_weight": 0.05,
        "max_weight": 1.00,
    },
    "tiers": {
        "order": ["expert", "proficient", "working", "awareness"],
        "default_tier": "working",
        "phrases": {"expert": [], "proficient": [], "working": [], "awareness": []},
    },
    "sections": {
        "required": [], "preferred": [], "nice_to_have": [],
        "responsibilities": [], "boilerplate": [],
    },
    "llm": {
        "max_calls_per_extraction": 2,
        "use_fast_lane": False,
        "max_jd_chars": 24000,
    },
}

_cache: Optional[dict] = None


def load_config(path: Optional[Path] = None, force: bool = False) -> dict:
    """Config with the YAML overlaid on DEFAULT_CONFIG, one level deep.

    Cached, because this is read once per extraction and the file does not
    change under a running process in any supported workflow. `force=True` is
    for tests that write a scratch config -- exposed rather than having tests
    reach into the module global, so the cache-busting path is itself tested.
    """
    global _cache
    if _cache is not None and not force and path is None:
        return _cache

    target = path or CONFIG_PATH
    merged: dict[str, Any] = {}
    for key, value in DEFAULT_CONFIG.items():
        merged[key] = dict(value) if isinstance(value, dict) else value

    try:
        raw = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        logger.warning("arena config not found at %s; using defaults", target)
        raw = {}
    except yaml.YAMLError:
        # Same posture as seed.py: a malformed config logs and degrades rather
        # than preventing the process from starting. A wrong threshold produces
        # a measurably worse graph; an unbootable API produces nothing.
        logger.exception("arena config at %s is not valid YAML; using defaults", target)
        raw = {}

    for key, value in raw.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value

    if path is None and not force:
        _cache = merged
    return merged


def extractor_version() -> str:
    """The value that participates in the graph idempotency key.

    Read through here rather than indexed inline at each call site so there is
    exactly one place that decides what "the current extractor" means.
    """
    return str(load_config()["extractor_version"])
