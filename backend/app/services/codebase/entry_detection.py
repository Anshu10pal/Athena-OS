"""Phase E4: entry-point detection.

Build/deployment config is authoritative; code patterns are the fallback,
checked only for files no authoritative source names. This replaces the old
fan_in==0-or-basename heuristic (ranking.ENTRY_POINT_BASENAMES, still kept
as a dormant safety net -- see ranking._write_back_entry_priors) as the
thing that actually decides whether a file is an entry point. That old
heuristic treated absence of fan-in as evidence of importance; it isn't --
plenty of dead code and orphaned scripts also have fan_in == 0. A real
entry point is invoked by a build tool or a container CMD, not imported by
other source files, so detection here is expected to return a SMALL set
(2-6 files on a typical repo). Returning many is a sign detection is wrong,
not a sign of thoroughness.

    Language   Authoritative                                          Fallback
    Python     Dockerfile CMD/ENTRYPOINT, Procfile, render.yaml        if __name__ == "__main__",
               start command, [project.scripts]                       module-level FastAPI(/Flask( assignment
    TS/JS      index.html script src, package.json main/module/bin,   createRoot(...).render(,
               vite.config rollupOptions.input                        ReactDOM.render(

Route modules mounted into an app (api/roadmap.py-style) are NOT entry
points under this definition, however central they are in the import
graph -- they're mounted, not entered. Only a real runtime execution start
counts.
"""
import json
import os
import re
from pathlib import Path
from typing import Optional

import yaml
from app.services.codebase import discovery

JS_LANGUAGES = {"javascript", "typescript", "tsx"}

DEFAULT_FAN_IN_CONTRADICTION_THRESHOLD = 0

# Generic, ecosystem-wide conventions for "auxiliary, not the primary
# surface" -- NOT repo-1-specific overrides (e.g. this deliberately does not
# list "voice_listener/", which is a judgment call for this one repo, not a
# convention any repo follows). A path under one of these markers can still
# have a genuine __main__ guard and run standalone; it just shouldn't be
# where PageRank's teleport mass originates.
DEFAULT_SEED_INELIGIBLE_PATH_MARKERS = ["scripts/", "tools/", "tests/", "test/"]


# --- Python: authoritative sources -----------------------------------------

_DOCKERFILE_NAMES = ("Dockerfile", "dockerfile")

# Matches "python -m package.module", "uvicorn module.path:attr", and
# "gunicorn ... module.path:attr" -- the three conventional ways a container
# CMD/ENTRYPOINT or a Procfile line names a Python entry module.
_PYTHON_ENTRY_CMD_RE = re.compile(
    r"python3?\s+-m\s+([\w.]+)"
    r"|uvicorn\s+([\w.]+):(\w+)"
    r"|gunicorn\s+.*?([\w.]+):(\w+)"
)

# Dockerfile CMD/ENTRYPOINT is commonly JSON exec form (["uvicorn", "app.main:app"])
# rather than shell form (uvicorn app.main:app) -- stripping JSON syntax
# characters first lets one regex handle both without a JSON/shell parser.
_JSON_EXEC_FORM_CHARS_RE = re.compile(r'[\[\]",]')


def _scan_text_for_python_entry_modules(text: str) -> list:
    normalized = _JSON_EXEC_FORM_CHARS_RE.sub(" ", text)
    modules = []
    for m in _PYTHON_ENTRY_CMD_RE.finditer(normalized):
        module = m.group(1) or m.group(2) or m.group(4)
        if module:
            modules.append(module)
    return modules


def _module_path_to_candidate_file_paths(module_path: str) -> list:
    """"app.main" -> ["app/main.py", "app/main/__init__.py"] -- either is a
    valid resolution for a dotted module path; the caller checks which (if
    either) exists among the repo's real CodeFile paths."""
    base = "/".join(module_path.split("."))
    return [f"{base}.py", f"{base}/__init__.py"]


def find_python_authoritative_entry_modules(repo_root: Path) -> list:
    """Dotted-module-path candidates found in Dockerfile CMD/ENTRYPOINT,
    Procfile, render.yaml's start command, pyproject.toml's [project.scripts]
    and setup.py's entry_points console_scripts -- resolved to file paths by
    the caller."""
    modules = []

    for name in _DOCKERFILE_NAMES:
        p = repo_root / name
        if p.is_file():
            modules.extend(_scan_text_for_python_entry_modules(_read_text(p)))

    procfile = repo_root / "Procfile"
    if procfile.is_file():
        modules.extend(_scan_text_for_python_entry_modules(_read_text(procfile)))

    render_yaml = repo_root / "render.yaml"
    if render_yaml.is_file():
        try:
            data = yaml.safe_load(_read_text(render_yaml)) or {}
        except yaml.YAMLError:
            data = {}
        for service in (data.get("services") or []):
            if isinstance(service, dict):
                modules.extend(_scan_text_for_python_entry_modules(service.get("startCommand") or ""))

    pyproject = repo_root / "pyproject.toml"
    if pyproject.is_file():
        modules.extend(_scan_pyproject_scripts(_read_text(pyproject)))

    setup_py = repo_root / "setup.py"
    if setup_py.is_file():
        modules.extend(_scan_setup_py_console_scripts(_read_text(setup_py)))

    return modules


_CONSOLE_SCRIPTS_KEY_RE = re.compile(r"[\"']?(?:console_scripts|gui_scripts)[\"']?\s*[:=]")
# setuptools' entry-point spec: "name=package.module:function", the only
# shape a console_scripts value takes (it is a list of these strings; the
# dict-of-name-to-spec form some projects assume does not exist).
_ENTRY_POINT_SPEC_RE = re.compile(r"[\w.\-]+\s*=\s*([\w.]+)\s*:\s*\w+")


def _scan_setup_py_console_scripts(text: str) -> list:
    """setup.py's entry_points={"console_scripts": ["name=pkg.mod:fn"]}.

    Exists because [project.scripts] is not where every project declares its
    CLI. A pyproject.toml may declare `dynamic = ["scripts", "entry-points"]`
    and defer entirely to setup.py -- Apache Superset does exactly this, so
    `superset.cli.main`, its real console entry point, was invisible to
    detection that read only pyproject.

    Text-scanned, not imported or AST-parsed: setup.py is arbitrary
    executable code, and running a downloaded repo's build script to find its
    entry points is not a trade this is willing to make. Regex over a bounded
    region is the same line-based compromise _scan_pyproject_scripts already
    makes for TOML, and for the same reason (this backend pins Python 3.10,
    which has no stdlib tomllib).

    Scoped to the region after a console_scripts/gui_scripts key so that the
    many other `name=module:attr` strings in a real setup.py -- Superset
    declares a whole block of `sqlalchemy.dialects` in the same dict -- are
    not mistaken for CLI entry points.
    """
    modules = []
    for key_match in _CONSOLE_SCRIPTS_KEY_RE.finditer(text):
        region = text[key_match.end():]
        # Stop at the close of this key's own list/dict. Finding the first
        # closing bracket is imprecise for a nested value, but a
        # console_scripts value is a flat sequence of strings by definition,
        # so the first close is its own -- and over-reading would pull in the
        # sibling entry-point groups this scoping exists to exclude.
        end = min((i for i in (region.find("]"), region.find("}")) if i != -1), default=len(region))
        for spec in _ENTRY_POINT_SPEC_RE.finditer(region[:end]):
            modules.append(spec.group(1))
    return modules


def _scan_pyproject_scripts(text: str) -> list:
    """[project.scripts]\\nname = "package.module:function" -- simple
    line-based extraction, not a full TOML parser (avoids a TOML dependency
    for one narrow field)."""
    modules = []
    in_scripts_section = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            in_scripts_section = stripped == "[project.scripts]"
            continue
        if in_scripts_section and "=" in stripped:
            _, _, value = stripped.partition("=")
            value = value.strip().strip('"').strip("'")
            module_path, _, _attr = value.partition(":")
            if module_path:
                modules.append(module_path)
    return modules


# --- Python: fallback code patterns -----------------------------------------

_PY_MAIN_GUARD_RE = re.compile(r'^\s*if\s+__name__\s*==\s*["\']__main__["\']\s*:', re.MULTILINE)
_PY_APP_ASSIGNMENT_RE = re.compile(r'^\w+\s*=\s*(?:FastAPI|Flask)\s*\(', re.MULTILINE)


def is_python_fallback_entry(source_text: str) -> bool:
    return bool(_PY_MAIN_GUARD_RE.search(source_text) or _PY_APP_ASSIGNMENT_RE.search(source_text))


# --- JS/TS: authoritative sources -------------------------------------------

_SCRIPT_SRC_RE = re.compile(r'<script[^>]*\ssrc=["\']([^"\']+)["\']', re.IGNORECASE)
_VITE_INPUT_RE = re.compile(r'input\s*:\s*[\'"]([^\'"]+)[\'"]')


def _iter_files_named(repo_root: Path, *names: str):
    """Delegates to discovery.iter_files_named.

    Phase H1.5 fixed this function -- it was `rglob(name)` filtered AFTER the
    fact, which still walks INTO node_modules/.git/dist/build before discarding
    what it finds, so the filter hid the cost without avoiding it. That one
    function was the entire 15-20s cost of a /graph request.

    The pruning logic then lived here, and two OTHER modules kept their own
    near-identical copies of the ignored-name list. All three disagreed, and
    none contained a virtualenv marker, so a repo with a committed `venv310`
    was walked in full from three separate code paths. The walk now has one
    implementation and one list, which is also the only way the `pyvenv.cfg`
    structural rule reaches all three callers."""
    return discovery.iter_files_named(repo_root, *names)


def find_js_authoritative_entry_paths(repo_root: Path) -> list:
    """Absolute, resolved file paths (candidates -- not yet checked against
    real CodeFile paths) found in index.html <script src>, package.json
    main/module/bin, and vite.config.*'s rollupOptions.input."""
    candidates = []

    for html_path in _iter_files_named(repo_root, "index.html"):
        for m in _SCRIPT_SRC_RE.finditer(_read_text(html_path)):
            src = m.group(1)
            if src.startswith(("http://", "https://", "//")):
                continue
            candidates.append(_resolve_relative(html_path.parent, src.lstrip("/")))

    for pkg_path in _iter_files_named(repo_root, "package.json"):
        try:
            data = json.loads(_read_text(pkg_path))
        except ValueError:
            continue
        for key in ("main", "module"):
            value = data.get(key)
            if isinstance(value, str):
                candidates.append(_resolve_relative(pkg_path.parent, value))
        bin_value = data.get("bin")
        if isinstance(bin_value, str):
            candidates.append(_resolve_relative(pkg_path.parent, bin_value))
        elif isinstance(bin_value, dict):
            for value in bin_value.values():
                if isinstance(value, str):
                    candidates.append(_resolve_relative(pkg_path.parent, value))

    for vite_path in _iter_files_named(repo_root, "vite.config.ts", "vite.config.js"):
        for m in _VITE_INPUT_RE.finditer(_read_text(vite_path)):
            candidates.append(_resolve_relative(vite_path.parent, m.group(1)))

    return candidates


def _resolve_relative(base_dir: Path, rel: str) -> str:
    return str((base_dir / rel).resolve())


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


# --- JS/TS: fallback code patterns -------------------------------------------

# Two independent existence checks, not one regex spanning createRoot(...)'s
# argument: that argument is itself a call (e.g. document.getElementById('root'))
# containing its own closing paren, which a single non-nesting regex can't
# skip over correctly.
_CREATE_ROOT_RE = re.compile(r'createRoot\s*\(')
_RENDER_CALL_RE = re.compile(r'\.render\s*\(')
_REACT_DOM_RENDER_RE = re.compile(r'ReactDOM\.render\s*\(')


def is_js_fallback_entry(source_text: str) -> bool:
    if _REACT_DOM_RENDER_RE.search(source_text):
        return True
    return bool(_CREATE_ROOT_RE.search(source_text) and _RENDER_CALL_RE.search(source_text))


# --- orchestration -----------------------------------------------------------


def _is_seed_eligible(path: str, method: str, seed_ineligible_path_markers: list, repo_seed_exclude_paths: list) -> bool:
    """Being an executable entry and being where a newcomer starts reading
    a codebase are different properties. An authoritative detection is
    always seed-eligible -- named by real deployment/build config, the
    strongest signal available that this is where execution truly starts.
    A fallback detection (a code pattern found inside the file itself) is
    seed-eligible UNLESS the file's path sits under a conventionally
    auxiliary directory (scripts/, tools/, tests/): a validation script or
    a standalone side-utility genuinely has a __main__ guard and genuinely
    runs standalone, but seeding PageRank from it injects real teleport
    mass at the wrong origin -- the same 20% share as the application
    itself, if there are five equally-weighted seeds. It still earns the
    entry prior (see _migrate_entry_priors) -- only seed mass is withheld.

    repo_seed_exclude_paths: the repo's OWN override (Repo.seed_exclude_paths,
    prefix-matched), for auxiliary surfaces no ecosystem-wide marker catches
    (a worker, a cron script, a dev harness -- every repo has some). This is
    checked FIRST and overrides even an authoritative detection: it's an
    explicit, repo-specific admin decision, stronger than any automated
    detection method."""
    if any(path.startswith(prefix) for prefix in repo_seed_exclude_paths):
        return False
    if method == "authoritative":
        return True
    return not any(marker in path for marker in seed_ineligible_path_markers)


def detect_entry_points(
    repo_root: Path, files: list, seed_exclude_paths: Optional[list] = None,
    config_search_root: Optional[Path] = None,
) -> dict:
    """files: this repo's CodeFile rows (`.path` relative to repo_root,
    POSIX; `.language` one of languages.EXTENSION_LANGUAGE's values).
    seed_exclude_paths: this repo's own seed-eligibility override (see
    Repo.seed_exclude_paths / _is_seed_eligible) -- defaults to none.
    Returns {file_id: {"method": "authoritative"|"fallback", "seed_eligible": bool}}
    -- expected to be small. Fallback code-pattern scanning only considers
    files no authoritative source already claimed; a file matching BOTH
    counts once, as authoritative (the stronger claim wins, never
    both/neither).

    config_search_root: where to look for authoritative build/deploy config
    (Dockerfile, Procfile, render.yaml, pyproject.toml, index.html,
    package.json, vite.config) -- defaults to repo_root when omitted, which
    reproduces every prior caller's behavior exactly (repo_root and
    config_search_root coincide whenever a repo has no source_root, the
    common case). Distinct from repo_root because a repo registered with
    `source_root` scopes INGESTION -- and therefore every `files[i].path`
    -- to a subdirectory, but authoritative config conventionally lives at
    the true repository root, one or more levels above source_root, even
    when the entry point it names lives INSIDE the ingested subtree.
    Searching only from repo_root in that case finds nothing, not because
    no authoritative source exists, but because the search started in the
    wrong place. (Verified on eslint/eslint with source_root="lib":
    package.json's "main": "./lib/api.js" points inside the ingested
    subtree and was a real, confirmed miss without this parameter.)

    Widening the search root only helps find the config file itself -- a
    resolved candidate still has to match a real ingested file under
    repo_root to count, so an authoritative source naming a target OUTSIDE
    the ingested subtree (e.g. that same package.json's
    "bin": "./bin/eslint.js", outside source_root="lib") still correctly
    fails to match. No false positives from widening the search."""
    seed_exclude_paths = seed_exclude_paths or []
    config_search_root = config_search_root if config_search_root is not None else repo_root
    path_to_file = {f.path: f for f in files}
    detected_method: dict = {}

    for module_path in find_python_authoritative_entry_modules(config_search_root):
        for candidate_rel in _module_path_to_candidate_file_paths(module_path):
            f = path_to_file.get(candidate_rel)
            if f is not None:
                detected_method[f.id] = "authoritative"

    resolved_root = repo_root.resolve()
    for raw_candidate in find_js_authoritative_entry_paths(config_search_root):
        f = _match_absolute_path(raw_candidate, resolved_root, path_to_file)
        if f is not None:
            detected_method[f.id] = "authoritative"

    for f in files:
        if f.id in detected_method:
            continue
        source_path = repo_root / f.path
        if not source_path.is_file():
            continue
        text = _read_text(source_path)
        if f.language == "python" and is_python_fallback_entry(text):
            detected_method[f.id] = "fallback"
        elif f.language in JS_LANGUAGES and is_js_fallback_entry(text):
            detected_method[f.id] = "fallback"

    file_by_id = {f.id: f for f in files}
    markers = load_entry_detection_config()["seed_ineligible_path_markers"]
    return {
        fid: {
            "method": method,
            "seed_eligible": _is_seed_eligible(file_by_id[fid].path, method, markers, seed_exclude_paths),
        }
        for fid, method in detected_method.items()
    }


def _match_absolute_path(raw_candidate: str, resolved_root: Path, path_to_file: dict) -> Optional[object]:
    try:
        rel = Path(raw_candidate).relative_to(resolved_root)
    except ValueError:
        return None
    return path_to_file.get(rel.as_posix())


# --- config ------------------------------------------------------------------


def _config_path() -> Path:
    from app.core.config import BACKEND_DIR, settings
    p = Path(settings.ENTRY_DETECTION_CONFIG_PATH)
    return p if p.is_absolute() else BACKEND_DIR / p


def load_entry_detection_config() -> dict:
    defaults = {
        "fan_in_contradiction_threshold": DEFAULT_FAN_IN_CONTRADICTION_THRESHOLD,
        "seed_ineligible_path_markers": list(DEFAULT_SEED_INELIGIBLE_PATH_MARKERS),
    }
    path = _config_path()
    if not path.is_file():
        return defaults
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {**defaults, **data}
