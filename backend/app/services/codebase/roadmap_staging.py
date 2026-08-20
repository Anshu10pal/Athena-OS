"""Config for how a repo-roadmap's stages are derived (Phase 4).

Its own module rather than a function inside module_mapping.py because that
module's stated contract is "pure: no DB, no IO" -- the staging logic itself
lives there and takes the threshold as an argument, and this is the one piece
that has to touch the filesystem. The decision is pure; the lookup is not.
"""
from pathlib import Path

import yaml

from app.core.config import BACKEND_DIR, settings
from app.services.codebase.module_mapping import DEFAULT_LAYER_COVERAGE_THRESHOLD

# Same 0.50 as subsystems.py's custom_label carry-over, deliberately: one
# notion of "this is the same cluster as before" for the whole codebase side.
DEFAULT_MODULE_IDENTITY_MIN_OVERLAP = 0.50

DEFAULT_ROADMAP_STAGING_CONFIG = {
    "layer_coverage_threshold": DEFAULT_LAYER_COVERAGE_THRESHOLD,
    "module_identity_min_overlap": DEFAULT_MODULE_IDENTITY_MIN_OVERLAP,
}


def _roadmap_staging_config_path() -> Path:
    p = Path(settings.ROADMAP_STAGING_CONFIG_PATH)
    return p if p.is_absolute() else BACKEND_DIR / p


def load_roadmap_staging_config() -> dict:
    path = _roadmap_staging_config_path()
    if not path.is_file():
        return dict(DEFAULT_ROADMAP_STAGING_CONFIG)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {**DEFAULT_ROADMAP_STAGING_CONFIG, **data}
