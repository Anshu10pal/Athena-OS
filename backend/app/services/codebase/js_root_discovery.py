"""Phase E2.2: TypeScript/JS root + alias discovery.

Config presence is authoritative, not evidence to be scored -- the
opposite of Python's root_discovery.py, and deliberately so. Python got a
clean three-bucket denominator (stdlib is a free, zero-design-surface
exclusion via sys.stdlib_module_names). TS/JS has no equivalent: `react`,
`axios`, and `three` are indistinguishable from a real internal bare
specifier until Phase E3's package.json-dependency parsing lands, so a
percentage-of-unresolved-specifiers score would be dominated by npm
packages and could never be a meaningful promotion gate. A tsconfig.json or
jsconfig.json with baseUrl/paths is a real, declared fact about how this
project resolves modules -- same argument as Phase E4's build-config-first
hierarchy: config beats a guess, and there is nothing to verify a config
file's own authority against.

This module only DISCOVERS configs and workspace boundaries; it does not
wire them into ingest.py's actual resolution pass (Phase E2.3's job, same
boundary as Python's root_discovery.py).
"""
import json
import posixpath
from pathlib import Path
from typing import Optional

import yaml

CONFIG_FILENAMES = ("tsconfig.json", "jsconfig.json")
_IGNORED_DIR_NAMES = {"node_modules", "dist", "build", ".git"}

DEFAULT_EXTENSION_PROBE_ORDER = [".ts", ".tsx", ".js", ".jsx"]
DEFAULT_TRY_INDEX_RESOLUTION = True


def _strip_json_comments(raw: str) -> str:
    """tsconfig.json conventionally allows // line comments, which plain
    json.loads rejects -- same minimal stripping load_tsconfig_paths uses."""
    return "\n".join(line for line in raw.splitlines() if not line.strip().startswith("//"))


def _iter_files_named(search_root: Path, *names: str):
    for name in names:
        for p in search_root.rglob(name):
            if not any(part in _IGNORED_DIR_NAMES for part in p.parts):
                yield p


def _rel_dir_within_root(path: Path, repo_root: Path) -> Optional[str]:
    """Same as _rel_dir, but for a `path` that may have come from a WIDER
    config_search_root scan -- returns None (discard) if `path` isn't
    actually a descendant of repo_root, instead of raising. Resolves both
    sides first, same robustness step as entry_detection's
    `repo_root.resolve()`. See find_ts_configs/find_package_json_
    workspace_dirs' docstrings for why this can't just report the wider
    match as-is: their return values are used downstream as paths
    relative to repo_root, not matched against an absolute CodeFile path
    the way entry_detection's widened search is."""
    try:
        rel = path.parent.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return None
    return "" if rel == "." else rel


def find_ts_configs(repo_root: Path, config_search_root: Optional[Path] = None) -> list:
    """Every tsconfig.json/jsconfig.json in the tree (not the single fixed
    repo-root lookup Phase E1 shipped with), each contributing its own
    scoped resolution context. Returns a list of
    {"dir": repo-relative POSIX dir ("" for repo root), "base_url": str,
    "paths": {alias: [targets]}, "module_resolution": str|None}, sorted by
    dir depth ascending (shallowest first) -- config_for_file relies on
    this order only as a tiebreak convenience, not correctness (it always
    picks the deepest matching one explicitly).

    config_search_root: same parameter/reasoning as
    find_marker_candidate_roots' -- defaults to repo_root (identical
    behavior to before). A config found while scanning a wider
    config_search_root is discarded (via _rel_dir_within_root) unless it's
    actually a descendant of repo_root: config_dir is used downstream as a
    path relative to repo_root (config_for_file's ancestor matching,
    resolve_js_module's target paths), not matched against an absolute
    CodeFile path, so a config outside repo_root's subtree has no valid
    representation here -- see find_marker_candidate_roots' docstring for
    the full reasoning and its "confirmed no observed behavior change on
    any registered repo, closes a correctness gap not an observed bug"
    caveat, which applies identically here."""
    search_root = config_search_root if config_search_root is not None else repo_root
    configs = []
    for config_path in _iter_files_named(search_root, *CONFIG_FILENAMES):
        config_dir = _rel_dir_within_root(config_path, repo_root)
        if config_dir is None:
            continue
        try:
            data = json.loads(_strip_json_comments(config_path.read_text(encoding="utf-8", errors="ignore")))
        except (json.JSONDecodeError, OSError):
            continue
        opts = data.get("compilerOptions", {}) or {}
        base_url = opts.get("baseUrl", ".")
        raw_paths = opts.get("paths", {}) or {}
        # targets in tsconfig.json are relative to THIS config's own
        # directory + its baseUrl, not to the repo root -- a nested
        # package's tsconfig (e.g. packages/ui/tsconfig.json) with
        # baseUrl "." and paths {"@ui/*": ["./src/*"]} means
        # packages/ui/src/*, not src/* at the repo root. Anchored here, at
        # discovery time, so callers (resolve_js_module) get repo-root-
        # relative targets directly, the same contract load_tsconfig_paths
        # already had for the single-repo-root-only case.
        paths = {
            alias: [
                posixpath.normpath(posixpath.join(config_dir, base_url, t))
                for t in ([targets] if isinstance(targets, str) else targets)
            ]
            for alias, targets in raw_paths.items()
        }
        configs.append({
            "dir": config_dir,
            "base_url": base_url,
            "paths": paths,
            "module_resolution": opts.get("moduleResolution"),
        })
    configs.sort(key=lambda c: c["dir"].count("/"))
    return configs


def config_for_file(from_file: str, configs: list) -> Optional[dict]:
    """Nearest-ancestor-config-wins: among configs whose `dir` is an
    ancestor of (or equal to) from_file's own directory, the DEEPEST one
    governs. No cascading fallback to a shallower config's paths if the
    nearest one doesn't resolve a specifier -- that's not how TypeScript's
    own project-boundary resolution behaves, and pretending otherwise would
    make a monorepo's inner package silently resolve against its parent's
    aliases."""
    from_dir = posixpath.dirname(from_file)
    governing = None
    for config in configs:
        config_dir = config["dir"]
        is_ancestor = config_dir == "" or from_dir == config_dir or from_dir.startswith(config_dir + "/")
        if not is_ancestor:
            continue
        if governing is None or config_dir.count("/") > governing["dir"].count("/") or len(config_dir) > len(governing["dir"]):
            governing = config
    return governing


def workspace_of(path: str, workspace_dirs: set) -> Optional[str]:
    """The deepest declared package.json workspace directory that is an
    ancestor of path, or None if path isn't inside any declared workspace.
    Used by Phase E2.3's ingest.py wiring to detect whether a resolved edge
    crosses a workspace boundary (importer and target under different
    workspace_of results, or one inside a workspace and the other not) --
    same ancestor-matching shape as config_for_file, different purpose
    (workspace membership, not which config's paths apply)."""
    file_dir = posixpath.dirname(path)
    best = None
    for ws in workspace_dirs:
        is_ancestor = file_dir == ws or file_dir.startswith(ws + "/")
        if not is_ancestor:
            continue
        if best is None or ws.count("/") > best.count("/"):
            best = ws
    return best


def _resolve_workspace_glob(repo_root: Path, pattern: str) -> list:
    """Minimal glob support for package.json `workspaces` entries: a
    literal directory, or a single trailing /* wildcard (one level only --
    "packages/*", not "packages/**"). Anything more elaborate is out of
    scope; a workspace entry this module can't resolve is simply skipped,
    not guessed at."""
    if pattern.endswith("/*"):
        parent = repo_root / pattern[:-2]
        if not parent.is_dir():
            return []
        return [child for child in parent.iterdir() if child.is_dir()]
    literal = repo_root / pattern
    return [literal] if literal.is_dir() else []


def find_package_json_workspace_dirs(repo_root: Path, config_search_root: Optional[Path] = None) -> set:
    """Directories (repo-relative POSIX) named by a package.json
    `workspaces` field -- either the array form or Yarn's
    {"packages": [...]} object form. Only entries that resolve to a real
    directory containing its OWN package.json count as a genuine workspace
    boundary, not just any directory a glob happened to match.

    config_search_root: same parameter as find_ts_configs', but discards
    at a DIFFERENT point, deliberately -- the declaring package.json
    itself doesn't need to be inside repo_root (a root package.json above
    a source_root-scoped ingest declaring `workspaces: ["backend/*"]` is
    a completely legitimate, real-world shape), only the resolved
    workspace BOUNDARY directories that come out of it do, since those
    are what get returned and used downstream as repo_root-relative
    paths. A boundary that resolves outside repo_root's subtree is
    dropped the same way an out-of-scope tsconfig is."""
    search_root = config_search_root if config_search_root is not None else repo_root
    resolved_repo_root = repo_root.resolve()
    boundaries = set()
    for pkg_path in _iter_files_named(search_root, "package.json"):
        try:
            data = json.loads(pkg_path.read_text(encoding="utf-8", errors="ignore"))
        except (json.JSONDecodeError, OSError):
            continue
        workspaces = data.get("workspaces")
        if isinstance(workspaces, dict):
            workspaces = workspaces.get("packages")
        if not isinstance(workspaces, list):
            continue
        base_dir = pkg_path.parent
        for pattern in workspaces:
            for candidate in _resolve_workspace_glob(base_dir, pattern):
                if not (candidate / "package.json").is_file():
                    continue
                try:
                    rel = candidate.resolve().relative_to(resolved_repo_root).as_posix()
                except ValueError:
                    continue  # workspace boundary resolves outside repo_root's own subtree
                boundaries.add(rel)
    return boundaries


def _config_path() -> Path:
    from app.core.config import BACKEND_DIR, settings
    p = Path(settings.JS_ROOT_DISCOVERY_CONFIG_PATH)
    return p if p.is_absolute() else BACKEND_DIR / p


def load_js_root_discovery_config() -> dict:
    defaults = {
        "extension_probe_order": list(DEFAULT_EXTENSION_PROBE_ORDER),
        "try_index_resolution": DEFAULT_TRY_INDEX_RESOLUTION,
    }
    path = _config_path()
    if not path.is_file():
        return defaults
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {**defaults, **data}
