"""Static import resolution against the repo's own file set.

Python: absolute imports checked against source_root (repo root) with a
src/ fallback (there's no live interpreter to consult sys.path per repo, so
an unconventional layout under-resolves -- a documented blind spot, not a
bug); relative imports resolved by dot-count against the importing file's
directory.

TypeScript/JavaScript: relative specifiers resolved with the usual
extension-less / index resolution; bare specifiers checked against
tsconfig.json `compilerOptions.paths` aliases if present, otherwise left
unresolved as external packages.

A specifier that doesn't resolve to a file inside this repo is not an error
-- most imports are of external packages/stdlib, and this tool only maps
edges within the repo.
"""
import json
import posixpath
from pathlib import Path
from typing import Optional

JS_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx")


# ---------------- Python ----------------


def _try_python_file_candidates(base: str, files: set) -> Optional[str]:
    for candidate in (f"{base}.py", f"{base}/__init__.py"):
        norm = posixpath.normpath(candidate)
        if norm in files:
            return norm
    return None


def _python_base_dir(raw_specifier: str, from_file: str) -> str:
    """The path implied by raw_specifier alone (before any imported name is
    appended) -- not checked for existence, just computed. Relative specifiers
    are walked by dot-count from the importing file's directory; absolute
    specifiers are dotted-path-to-slash-path."""
    if raw_specifier.startswith("."):
        dot_count = len(raw_specifier) - len(raw_specifier.lstrip("."))
        module_part = raw_specifier[dot_count:]
        base_dir = posixpath.dirname(from_file)
        for _ in range(dot_count - 1):
            base_dir = posixpath.dirname(base_dir)
        if module_part:
            base_dir = posixpath.normpath(posixpath.join(base_dir, module_part.replace(".", "/")))
        return base_dir
    return raw_specifier.replace(".", "/")


def resolve_python_import(
    raw_specifier: str, name: Optional[str], from_file: str, files: set, roots: Optional[list] = None,
) -> tuple:
    """Returns (resolved_path_or_None, is_submodule). Tries, in order:
    1. `<specifier>.<name>` as a submodule file -- covers both `from pkg import
       submodule` and `from . import sibling`, which are the same shape;
    2. the specifier itself as a module/package file, so `name` can be matched
       as a symbol inside it instead (handled by the caller).

    roots: candidate root prefixes to try IN ORDER for an ABSOLUTE specifier
    (ignored for relative specifiers, which are resolved purely by dot-count
    from from_file's own directory regardless of root -- root choice can't
    affect them). Defaults to ["", "src"] -- the pre-root-discovery (Phase
    E1) behavior: no prefix, then a src/ fallback, since there was no live
    interpreter to consult sys.path per repo and no real root-discovery
    mechanism yet. Phase E2's root_discovery.py passes an explicit
    single-element list to verify one candidate root in isolation, and
    (once wired into ingest.py's real resolution pass) the discovered
    roots in nearest-ancestor-first order."""
    base_dir = _python_base_dir(raw_specifier, from_file)
    is_relative = raw_specifier.startswith(".")
    if is_relative:
        bases = [base_dir]
    else:
        prefixes = roots if roots is not None else ["", "src"]
        bases = [posixpath.normpath(posixpath.join(prefix, base_dir)) if prefix else base_dir for prefix in prefixes]

    if name and name != "*":
        for base in bases:
            hit = _try_python_file_candidates(posixpath.normpath(posixpath.join(base, name)), files)
            if hit:
                return hit, True

    for base in bases:
        hit = _try_python_file_candidates(base, files)
        if hit:
            return hit, False

    return None, False


# ---------------- TypeScript / JavaScript ----------------


def _try_js_file_candidates(
    base: str, files: set, extension_probe_order: Optional[list] = None, try_index_resolution: bool = True,
) -> Optional[str]:
    """Probe order: the exact base path, then base+extension for each
    extension IN ORDER, then base/index+extension for each extension in
    order. Order matters -- when both `utils.ts` and `utils/index.ts`
    exist, whichever this list tries first silently becomes THE resolution,
    not a tie. extension_probe_order defaults to JS_EXTENSIONS (Phase E1's
    original fixed order) for callers that don't have a config-driven
    probe order yet (Phase E2.2's js_root_discovery.py does)."""
    extensions = extension_probe_order if extension_probe_order is not None else JS_EXTENSIONS
    norm = posixpath.normpath(base)
    if norm in files:
        return norm
    for ext in extensions:
        candidate = posixpath.normpath(base + ext)
        if candidate in files:
            return candidate
    if try_index_resolution:
        for ext in extensions:
            candidate = posixpath.normpath(posixpath.join(base, "index" + ext))
            if candidate in files:
                return candidate
    return None


def _sorted_alias_patterns(path_aliases: dict) -> list:
    """Longest-prefix-wins: when two patterns could both match a specifier
    (e.g. "@/*" and "@/components/*"), TypeScript's own resolution algorithm
    tries the more specific one first. Dict iteration order reflects
    whatever order tsconfig.json's `paths` happened to list them in, which
    is not the same thing -- sorted here rather than relying on it."""
    return sorted(path_aliases.items(), key=lambda item: len(item[0].rstrip("*")), reverse=True)


def resolve_js_module(
    raw_specifier: str, from_file: str, files: set, path_aliases: Optional[dict] = None,
    extension_probe_order: Optional[list] = None, try_index_resolution: bool = True,
) -> Optional[str]:
    if raw_specifier.startswith("."):
        base_dir = posixpath.dirname(from_file)
        base = posixpath.normpath(posixpath.join(base_dir, raw_specifier))
        return _try_js_file_candidates(base, files, extension_probe_order, try_index_resolution)

    for alias_pattern, targets in _sorted_alias_patterns(path_aliases or {}):
        prefix = alias_pattern.rstrip("*")
        if raw_specifier.startswith(prefix):
            remainder = raw_specifier[len(prefix):]
            # real tsconfig.json `paths` values are always arrays, even for
            # one target -- but a malformed single-string value must not
            # silently iterate over characters instead of being treated as
            # one target.
            target_list = [targets] if isinstance(targets, str) else targets
            for target in target_list:
                target_base = target.rstrip("*") + remainder
                resolved = _try_js_file_candidates(
                    posixpath.normpath(target_base), files, extension_probe_order, try_index_resolution
                )
                if resolved:
                    return resolved
    return None


def load_tsconfig_paths(repo_root: Path) -> dict:
    """{alias_pattern: [target_patterns]}, targets already joined with baseUrl.
    Missing, malformed, or comment-laden tsconfig.json -> {} (no aliases) --
    this is enrichment, not a requirement for resolution to function."""
    tsconfig_path = repo_root / "tsconfig.json"
    if not tsconfig_path.is_file():
        return {}
    try:
        raw = tsconfig_path.read_text(encoding="utf-8", errors="ignore")
        stripped = "\n".join(line for line in raw.splitlines() if not line.strip().startswith("//"))
        data = json.loads(stripped)
    except (json.JSONDecodeError, OSError):
        return {}
    opts = data.get("compilerOptions", {}) or {}
    base_url = opts.get("baseUrl", ".")
    paths = opts.get("paths", {}) or {}
    return {alias: [posixpath.normpath(posixpath.join(base_url, t)) for t in targets] for alias, targets in paths.items()}
