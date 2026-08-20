"""Phase E4: entry-point detection. Real files on disk (tmp_path), no DB --
detection reads config files and source text directly, independent of
ingest/CodeFile rows except for the final id-matching step.
"""
from pathlib import Path
from types import SimpleNamespace

from app.services.codebase.entry_detection import (
    detect_entry_points,
    find_js_authoritative_entry_paths,
    find_python_authoritative_entry_modules,
    is_js_fallback_entry,
    is_python_fallback_entry,
    load_entry_detection_config,
)


def _write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _file(id_, path, language):
    return SimpleNamespace(id=id_, path=path, language=language)


def _methods(detected: dict) -> dict:
    """detect_entry_points returns {file_id: {"method": ..., "seed_eligible": ...}};
    most tests only care about which method matched -- seed_eligible is
    covered separately in TestSeedEligibility."""
    return {fid: info["method"] for fid, info in detected.items()}


class TestPythonAuthoritativeSources:
    def test_dockerfile_cmd_uvicorn(self, tmp_path):
        _write(tmp_path / "Dockerfile", 'FROM python:3.11\nCMD ["uvicorn", "app.main:app", "--host", "0.0.0.0"]\n')
        modules = find_python_authoritative_entry_modules(tmp_path)
        assert "app.main" in modules

    def test_dockerfile_python_dash_m(self, tmp_path):
        _write(tmp_path / "Dockerfile", "FROM python:3.11\nCMD python -m worker.run\n")
        modules = find_python_authoritative_entry_modules(tmp_path)
        assert "worker.run" in modules

    def test_procfile(self, tmp_path):
        _write(tmp_path / "Procfile", "web: uvicorn app.main:app\n")
        modules = find_python_authoritative_entry_modules(tmp_path)
        assert "app.main" in modules

    def test_render_yaml_start_command(self, tmp_path):
        _write(
            tmp_path / "render.yaml",
            "services:\n  - type: web\n    name: api\n    startCommand: uvicorn app.main:app\n",
        )
        modules = find_python_authoritative_entry_modules(tmp_path)
        assert "app.main" in modules

    def test_pyproject_project_scripts(self, tmp_path):
        _write(
            tmp_path / "pyproject.toml",
            '[project]\nname = "x"\n\n[project.scripts]\nmycli = "package.module:main"\n',
        )
        modules = find_python_authoritative_entry_modules(tmp_path)
        assert "package.module" in modules

    def test_setup_py_console_scripts(self, tmp_path):
        """Apache Superset's exact shape: pyproject defers via `dynamic`, and
        the real entry point is only declared in setup.py."""
        _write(
            tmp_path / "pyproject.toml",
            '[project]\nname = "x"\ndynamic = ["version", "scripts", "entry-points"]\n',
        )
        _write(
            tmp_path / "setup.py",
            'setup(\n    name="x",\n    entry_points={\n'
            '        "console_scripts": ["superset=superset.cli.main:superset"],\n'
            '        "sqlalchemy.dialects": [\n'
            '            "postgres = sqlalchemy.dialects.postgresql:dialect",\n'
            '        ],\n    },\n)\n',
        )
        modules = find_python_authoritative_entry_modules(tmp_path)
        assert "superset.cli.main" in modules
        # The sibling entry-point group is not a CLI entry point -- scoping
        # to the console_scripts region is what excludes it.
        assert "sqlalchemy.dialects.postgresql" not in modules

    def test_setup_py_multiple_console_scripts(self, tmp_path):
        _write(
            tmp_path / "setup.py",
            'setup(entry_points={"console_scripts": [\n'
            '    "one=pkg.first:main",\n'
            '    "two=pkg.second:main",\n'
            ']})\n',
        )
        modules = find_python_authoritative_entry_modules(tmp_path)
        assert "pkg.first" in modules and "pkg.second" in modules

    def test_setup_py_without_entry_points_yields_nothing(self, tmp_path):
        _write(tmp_path / "setup.py", 'setup(name="x", packages=find_packages())\n')
        assert find_python_authoritative_entry_modules(tmp_path) == []

    def test_no_config_files_returns_empty(self, tmp_path):
        assert find_python_authoritative_entry_modules(tmp_path) == []


class TestPythonFallbackPatterns:
    def test_main_guard_detected(self):
        assert is_python_fallback_entry("def f():\n    pass\n\nif __name__ == '__main__':\n    f()\n")

    def test_fastapi_assignment_detected(self):
        assert is_python_fallback_entry("from fastapi import FastAPI\napp = FastAPI()\n")

    def test_flask_assignment_detected(self):
        assert is_python_fallback_entry("from flask import Flask\napp = Flask(__name__)\n")

    def test_plain_module_not_detected(self):
        assert not is_python_fallback_entry("def helper():\n    return 1\n")

    def test_fastapi_mention_without_assignment_not_detected(self):
        # a route module that imports FastAPI's APIRouter, say -- not an entry
        assert not is_python_fallback_entry("from fastapi import APIRouter\nrouter = APIRouter()\n")


class TestJsAuthoritativeSources:
    def test_index_html_script_src(self, tmp_path):
        _write(tmp_path / "index.html", '<html><body><script type="module" src="/src/main.tsx"></script></body></html>\n')
        _write(tmp_path / "src" / "main.tsx", "export {}\n")
        candidates = find_js_authoritative_entry_paths(tmp_path)
        assert str((tmp_path / "src" / "main.tsx").resolve()) in candidates

    def test_index_html_external_script_ignored(self, tmp_path):
        _write(tmp_path / "index.html", '<script src="https://cdn.example.com/x.js"></script>\n')
        assert find_js_authoritative_entry_paths(tmp_path) == []

    def test_package_json_main(self, tmp_path):
        _write(tmp_path / "package.json", '{"main": "index.js"}')
        candidates = find_js_authoritative_entry_paths(tmp_path)
        assert str((tmp_path / "index.js").resolve()) in candidates

    def test_package_json_bin_dict(self, tmp_path):
        _write(tmp_path / "package.json", '{"bin": {"mycli": "bin/cli.js"}}')
        candidates = find_js_authoritative_entry_paths(tmp_path)
        assert str((tmp_path / "bin" / "cli.js").resolve()) in candidates

    def test_vite_config_rollup_input(self, tmp_path):
        _write(tmp_path / "vite.config.ts", "export default { build: { rollupOptions: { input: 'src/main.tsx' } } }\n")
        candidates = find_js_authoritative_entry_paths(tmp_path)
        assert str((tmp_path / "src" / "main.tsx").resolve()) in candidates

    def test_node_modules_index_html_ignored(self, tmp_path):
        _write(tmp_path / "node_modules" / "pkg" / "index.html", '<script src="./x.js"></script>\n')
        assert find_js_authoritative_entry_paths(tmp_path) == []


class TestIgnoredDirsArePrunedDuringTheWalk:
    """Phase H1.5: the ignored-directory filter used to run AFTER
    Path.rglob had already walked into node_modules/.git/venv/etc. --
    the filter hid the cost, it never avoided it. Measured on this
    project's own repo (frontend/node_modules, ~300+ nested package.json
    files; backend/venv, ~1700 subdirectories): that unpruned walk was
    the entire 15-20s cost of a live entry-detection call. The result-only
    test above (test_node_modules_index_html_ignored) can't tell a pruned
    walk from a filtered one -- both return the same empty list -- so this
    spies on os.walk itself to prove the walk never DESCENDS into an
    ignored directory, not just that matches from inside one get dropped."""

    def test_never_descends_into_node_modules(self, tmp_path, monkeypatch):
        import os

        import app.services.codebase.entry_detection as ed

        _write(tmp_path / "package.json", "{}")
        _write(tmp_path / "node_modules" / "some_pkg" / "package.json", "{}")

        visited = []
        real_walk = os.walk

        def spy_walk(top, *args, **kwargs):
            for dirpath, dirnames, filenames in real_walk(top, *args, **kwargs):
                visited.append(dirpath)
                yield dirpath, dirnames, filenames

        monkeypatch.setattr(ed.os, "walk", spy_walk)

        results = list(ed._iter_files_named(tmp_path, "package.json"))

        assert len(results) == 1
        assert results[0] == tmp_path / "package.json"
        assert not any("node_modules" in Path(d).parts for d in visited)

    def test_never_descends_into_a_python_virtualenv(self, tmp_path, monkeypatch):
        import os

        import app.services.codebase.entry_detection as ed

        _write(tmp_path / "index.html", "<html></html>")
        _write(tmp_path / "venv" / "lib" / "site-packages" / "index.html", "<html></html>")

        visited = []
        real_walk = os.walk

        def spy_walk(top, *args, **kwargs):
            for dirpath, dirnames, filenames in real_walk(top, *args, **kwargs):
                visited.append(dirpath)
                yield dirpath, dirnames, filenames

        monkeypatch.setattr(ed.os, "walk", spy_walk)

        results = list(ed._iter_files_named(tmp_path, "index.html"))

        assert len(results) == 1
        assert not any("venv" in Path(d).parts for d in visited)


class TestJsFallbackPatterns:
    def test_create_root_detected(self):
        assert is_js_fallback_entry("createRoot(document.getElementById('root')).render(<App />)")

    def test_react_dom_render_detected(self):
        assert is_js_fallback_entry("ReactDOM.render(<App />, document.getElementById('root'))")

    def test_plain_component_not_detected(self):
        assert not is_js_fallback_entry("export function App() { return <div /> }")


class TestDetectEntryPoints:
    def test_authoritative_wins_over_fallback_for_same_file(self, tmp_path):
        # main.tsx both matches index.html's script src AND contains createRoot --
        # must be counted once, as authoritative.
        _write(tmp_path / "index.html", '<script type="module" src="/src/main.tsx"></script>\n')
        _write(tmp_path / "src" / "main.tsx", "createRoot(document.getElementById('root')).render(<App />)\n")
        files = [_file(1, "src/main.tsx", "tsx")]
        detected = detect_entry_points(tmp_path, files)
        assert _methods(detected) == {1: "authoritative"}

    def test_fallback_used_when_no_authoritative_source_names_the_file(self, tmp_path):
        _write(tmp_path / "src" / "main.tsx", "createRoot(document.getElementById('root')).render(<App />)\n")
        files = [_file(1, "src/main.tsx", "tsx")]
        detected = detect_entry_points(tmp_path, files)
        assert _methods(detected) == {1: "fallback"}

    def test_mounted_route_module_not_detected_as_entry(self, tmp_path):
        _write(tmp_path / "Dockerfile", 'CMD ["uvicorn", "app.main:app"]\n')
        _write(tmp_path / "app" / "main.py", "from fastapi import FastAPI\napp = FastAPI()\n")
        _write(tmp_path / "app" / "api" / "roadmap.py", "from fastapi import APIRouter\nrouter = APIRouter()\n")
        files = [_file(1, "app/main.py", "python"), _file(2, "app/api/roadmap.py", "python")]
        detected = detect_entry_points(tmp_path, files)
        assert _methods(detected) == {1: "authoritative"}

    def test_no_entries_detected_returns_empty_dict(self, tmp_path):
        _write(tmp_path / "src" / "helper.ts", "export function helper() { return 1 }\n")
        files = [_file(1, "src/helper.ts", "typescript")]
        assert detect_entry_points(tmp_path, files) == {}

    def test_two_language_repo_detects_one_entry_per_language(self, tmp_path):
        _write(tmp_path / "Dockerfile", 'CMD ["uvicorn", "backend.main:app"]\n')
        _write(tmp_path / "backend" / "main.py", "from fastapi import FastAPI\napp = FastAPI()\n")
        _write(tmp_path / "index.html", '<script type="module" src="/frontend/main.tsx"></script>\n')
        _write(tmp_path / "frontend" / "main.tsx", "createRoot(document.getElementById('root')).render(<App />)\n")
        files = [_file(1, "backend/main.py", "python"), _file(2, "frontend/main.tsx", "tsx")]
        detected = detect_entry_points(tmp_path, files)
        assert _methods(detected) == {1: "authoritative", 2: "authoritative"}


class TestConfigSearchRoot:
    """Real bug, found by external validation on eslint/eslint: a repo
    registered with source_root scopes ingestion (and every CodeFile.path)
    to a subdirectory, but authoritative config conventionally lives at the
    TRUE repo root, above source_root -- even when the entry point it names
    lives inside the ingested subtree. Searching only from repo_root (as
    every caller did before config_search_root existed) silently finds
    nothing in that case, not because there's no authoritative source, but
    because the search started in the wrong directory."""

    def test_config_above_source_root_still_detects_target_inside_it(self, tmp_path):
        # True root has package.json; the ingested subtree is "lib/", and
        # package.json's "main" points at a file INSIDE that subtree --
        # exactly eslint/eslint's real "main": "./lib/api.js" shape.
        _write(tmp_path / "package.json", '{"main": "./lib/api.js"}')
        _write(tmp_path / "lib" / "api.js", "export {}\n")
        files = [_file(1, "api.js", "javascript")]  # path relative to lib/, per CodeFile convention
        detected = detect_entry_points(tmp_path / "lib", files, config_search_root=tmp_path)
        assert _methods(detected) == {1: "authoritative"}

    def test_config_above_source_root_naming_a_target_outside_it_is_not_a_false_positive(self, tmp_path):
        # package.json's "bin" points OUTSIDE the ingested subtree (like
        # eslint/eslint's real "bin": "./bin/eslint.js", outside
        # source_root="lib") -- widening the search must not manufacture a
        # match for a file that was never ingested.
        _write(tmp_path / "package.json", '{"bin": "./bin/cli.js"}')
        _write(tmp_path / "bin" / "cli.js", "#!/usr/bin/env node\n")
        _write(tmp_path / "lib" / "index.js", "export {}\n")
        files = [_file(1, "index.js", "javascript")]
        detected = detect_entry_points(tmp_path / "lib", files, config_search_root=tmp_path)
        assert detected == {}

    def test_omitting_config_search_root_defaults_to_repo_root_unchanged_behavior(self, tmp_path):
        # No source_root case (the common one): config_search_root omitted
        # entirely must behave exactly as before this parameter existed.
        _write(tmp_path / "package.json", '{"main": "index.js"}')
        _write(tmp_path / "index.js", "export {}\n")
        files = [_file(1, "index.js", "javascript")]
        assert _methods(detect_entry_points(tmp_path, files)) == {1: "authoritative"}

    def test_explicit_config_search_root_equal_to_repo_root_matches_omitted(self, tmp_path):
        _write(tmp_path / "package.json", '{"main": "index.js"}')
        _write(tmp_path / "index.js", "export {}\n")
        files = [_file(1, "index.js", "javascript")]
        with_default = detect_entry_points(tmp_path, files)
        with_explicit = detect_entry_points(tmp_path, files, config_search_root=tmp_path)
        assert with_default == with_explicit


class TestSeedEligibility:
    """Phase E4 refinement: being an executable entry (earns the prior) and
    being where a newcomer starts reading (earns seed mass) are different
    properties. Authoritative detections are always seed-eligible; fallback
    detections are seed-eligible unless their path sits under a
    conventionally auxiliary directory (scripts/, tools/, tests/)."""

    def test_authoritative_entry_is_always_seed_eligible(self, tmp_path):
        _write(tmp_path / "index.html", '<script type="module" src="/src/main.tsx"></script>\n')
        _write(tmp_path / "src" / "main.tsx", "export {}\n")
        files = [_file(1, "src/main.tsx", "tsx")]
        detected = detect_entry_points(tmp_path, files)
        assert detected[1]["seed_eligible"] is True

    def test_fallback_entry_outside_auxiliary_dirs_is_seed_eligible(self, tmp_path):
        _write(tmp_path / "backend" / "main.py", "from fastapi import FastAPI\napp = FastAPI()\n")
        files = [_file(1, "backend/main.py", "python")]
        detected = detect_entry_points(tmp_path, files)
        assert detected[1]["seed_eligible"] is True

    def test_fallback_entry_under_scripts_is_not_seed_eligible(self, tmp_path):
        _write(tmp_path / "backend" / "scripts" / "validate_ranking.py", "import argparse\n\nif __name__ == '__main__':\n    pass\n")
        files = [_file(1, "backend/scripts/validate_ranking.py", "python")]
        detected = detect_entry_points(tmp_path, files)
        assert detected[1]["method"] == "fallback"
        assert detected[1]["seed_eligible"] is False

    def test_fallback_entry_under_tests_is_not_seed_eligible(self, tmp_path):
        _write(tmp_path / "tests" / "conftest_runner.py", "if __name__ == '__main__':\n    pass\n")
        files = [_file(1, "tests/conftest_runner.py", "python")]
        detected = detect_entry_points(tmp_path, files)
        assert detected[1]["seed_eligible"] is False

    def test_authoritative_entry_under_scripts_is_still_seed_eligible(self, tmp_path):
        # authoritative (named by real deployment/build config) always wins,
        # regardless of path -- if a container CMD really does point at a
        # file under scripts/, that's still where execution starts.
        _write(tmp_path / "Dockerfile", 'CMD ["python", "-m", "scripts.run"]\n')
        _write(tmp_path / "scripts" / "run.py", "pass\n")
        files = [_file(1, "scripts/run.py", "python")]
        detected = detect_entry_points(tmp_path, files)
        assert detected[1]["method"] == "authoritative"
        assert detected[1]["seed_eligible"] is True


class TestPerRepoSeedExcludePaths:
    """Repo.seed_exclude_paths: the escape hatch for auxiliary surfaces no
    ecosystem-wide marker catches (a worker, a cron script, a dev harness --
    every repo has one). Prefix-matched, unlike the global markers'
    substring matching, and overrides even an authoritative detection."""

    def test_fallback_entry_excluded_by_repo_override(self, tmp_path):
        _write(tmp_path / "voice_listener" / "wake_word.py", "if __name__ == '__main__':\n    pass\n")
        files = [_file(1, "voice_listener/wake_word.py", "python")]
        detected = detect_entry_points(tmp_path, files, seed_exclude_paths=["voice_listener/"])
        assert detected[1]["method"] == "fallback"
        assert detected[1]["seed_eligible"] is False

    def test_repo_override_does_not_affect_files_outside_the_prefix(self, tmp_path):
        _write(tmp_path / "backend" / "main.py", "if __name__ == '__main__':\n    pass\n")
        files = [_file(1, "backend/main.py", "python")]
        detected = detect_entry_points(tmp_path, files, seed_exclude_paths=["voice_listener/"])
        assert detected[1]["seed_eligible"] is True

    def test_repo_override_beats_authoritative_detection(self, tmp_path):
        # an explicit, repo-specific admin decision outranks even a real
        # deployment-config-named entry -- the strongest override available.
        _write(tmp_path / "Dockerfile", 'CMD ["uvicorn", "legacy.main:app"]\n')
        _write(tmp_path / "legacy" / "main.py", "from fastapi import FastAPI\napp = FastAPI()\n")
        files = [_file(1, "legacy/main.py", "python")]
        detected = detect_entry_points(tmp_path, files, seed_exclude_paths=["legacy/"])
        assert detected[1]["method"] == "authoritative"
        assert detected[1]["seed_eligible"] is False

    def test_no_override_defaults_to_normal_rules(self, tmp_path):
        _write(tmp_path / "backend" / "main.py", "if __name__ == '__main__':\n    pass\n")
        files = [_file(1, "backend/main.py", "python")]
        detected = detect_entry_points(tmp_path, files)  # seed_exclude_paths omitted
        assert detected[1]["seed_eligible"] is True


class TestLoadEntryDetectionConfig:
    def test_default_threshold_when_no_config_file(self):
        config = load_entry_detection_config()
        assert "fan_in_contradiction_threshold" in config

    def test_default_seed_ineligible_markers_when_no_config_file(self):
        config = load_entry_detection_config()
        assert "scripts/" in config["seed_ineligible_path_markers"]
