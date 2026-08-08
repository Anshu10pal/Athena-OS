"""Phase E2.2: TypeScript/JS root + alias discovery. Pure-function tests --
real files on disk (tmp_path), no DB.
"""
from pathlib import Path

from app.services.codebase.js_root_discovery import (
    config_for_file,
    find_package_json_workspace_dirs,
    find_ts_configs,
    load_js_root_discovery_config,
    workspace_of,
)
from app.services.codebase.resolve_imports import resolve_js_module


def _write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


class TestFindTsConfigs:
    def test_single_root_tsconfig_discovered(self, tmp_path):
        _write(tmp_path / "tsconfig.json", '{"compilerOptions": {"baseUrl": ".", "paths": {"@/*": ["./src/*"]}}}')
        configs = find_ts_configs(tmp_path)
        assert len(configs) == 1
        assert configs[0]["dir"] == ""
        assert configs[0]["base_url"] == "."
        # targets are anchored (repo-root-relative) at discovery time -- "./src/*"
        # normalizes to "src/*" when the config's own dir is the repo root.
        assert configs[0]["paths"] == {"@/*": ["src/*"]}

    def test_jsconfig_json_also_discovered(self, tmp_path):
        _write(tmp_path / "jsconfig.json", '{"compilerOptions": {"baseUrl": "."}}')
        configs = find_ts_configs(tmp_path)
        assert len(configs) == 1

    def test_multiple_configs_at_different_levels_all_discovered(self, tmp_path):
        _write(tmp_path / "tsconfig.json", '{"compilerOptions": {}}')
        _write(tmp_path / "packages" / "ui" / "tsconfig.json", '{"compilerOptions": {}}')
        configs = find_ts_configs(tmp_path)
        dirs = {c["dir"] for c in configs}
        assert dirs == {"", "packages/ui"}

    def test_node_modules_configs_ignored(self, tmp_path):
        _write(tmp_path / "node_modules" / "somepkg" / "tsconfig.json", '{"compilerOptions": {}}')
        assert find_ts_configs(tmp_path) == []

    def test_comments_in_tsconfig_stripped(self, tmp_path):
        _write(tmp_path / "tsconfig.json", '{\n  // a comment\n  "compilerOptions": {"baseUrl": "."}\n}')
        configs = find_ts_configs(tmp_path)
        assert len(configs) == 1
        assert configs[0]["base_url"] == "."

    def test_malformed_json_skipped_not_raised(self, tmp_path):
        _write(tmp_path / "tsconfig.json", "{not valid json")
        assert find_ts_configs(tmp_path) == []

    def test_single_string_paths_target_coerced_to_list(self, tmp_path):
        # malformed relative to the real tsconfig.json spec (paths values
        # are always arrays), but must not silently break discovery.
        _write(tmp_path / "tsconfig.json", '{"compilerOptions": {"paths": {"@lib/*": "./lib/*"}}}')
        configs = find_ts_configs(tmp_path)
        assert configs[0]["paths"] == {"@lib/*": ["lib/*"]}

    def test_module_resolution_captured(self, tmp_path):
        _write(tmp_path / "tsconfig.json", '{"compilerOptions": {"moduleResolution": "bundler"}}')
        configs = find_ts_configs(tmp_path)
        assert configs[0]["module_resolution"] == "bundler"

    def test_config_search_root_defaults_to_repo_root_unchanged(self, tmp_path):
        _write(tmp_path / "tsconfig.json", '{"compilerOptions": {}}')
        assert find_ts_configs(tmp_path) == find_ts_configs(tmp_path, config_search_root=tmp_path)

    def test_config_above_repo_root_is_discarded_not_mismapped(self, tmp_path):
        # tsconfig.json lives ABOVE repo_root (config_search_root/frontend)
        # -- the exact source_root-scoped miss confirmed in
        # docs/external-validation-eslint.md's Round 2. Its config_dir has
        # no valid representation relative to repo_root, so it must be
        # dropped entirely, not reported at some wrong/negative path.
        _write(tmp_path / "tsconfig.json", '{"compilerOptions": {"baseUrl": "."}}')
        repo_root = tmp_path / "frontend"
        repo_root.mkdir()
        configs = find_ts_configs(repo_root, config_search_root=tmp_path)
        assert configs == []

    def test_config_inside_repo_root_still_found_when_widened(self, tmp_path):
        _write(tmp_path / "tsconfig.json", '{"compilerOptions": {}}')  # above -- discarded
        repo_root = tmp_path / "frontend"
        _write(repo_root / "src" / "tsconfig.json", '{"compilerOptions": {}}')  # inside -- kept
        configs = find_ts_configs(repo_root, config_search_root=tmp_path)
        assert [c["dir"] for c in configs] == ["src"]


class TestConfigForFile:
    def _config(self, dir_: str) -> dict:
        return {"dir": dir_, "base_url": ".", "paths": {}, "module_resolution": None}

    def test_nearest_ancestor_config_wins_over_shallower_one(self):
        configs = [self._config(""), self._config("packages/ui")]
        governing = config_for_file("packages/ui/src/index.ts", configs)
        assert governing["dir"] == "packages/ui"

    def test_repo_root_config_used_when_no_nested_config_matches(self):
        configs = [self._config(""), self._config("packages/ui")]
        governing = config_for_file("apps/web/src/index.ts", configs)
        assert governing["dir"] == ""

    def test_none_when_no_configs_at_all(self):
        assert config_for_file("src/index.ts", []) is None

    def test_sibling_directory_with_similar_name_not_treated_as_ancestor(self):
        # "packages/ui-extra" must not be treated as governed by a config
        # at "packages/ui" just because the string "packages/ui" is a
        # prefix of the path -- it isn't an ancestor DIRECTORY.
        configs = [self._config(""), self._config("packages/ui")]
        governing = config_for_file("packages/ui-extra/src/index.ts", configs)
        assert governing["dir"] == ""

    def test_file_directly_at_config_dir_is_governed_by_it(self):
        configs = [self._config(""), self._config("packages/ui")]
        governing = config_for_file("packages/ui/index.ts", configs)
        assert governing["dir"] == "packages/ui"


class TestFindPackageJsonWorkspaceDirs:
    def _make_package(self, path: Path, name: str):
        _write(path / "package.json", f'{{"name": "{name}"}}')

    def test_array_form_workspace_discovered(self, tmp_path):
        _write(tmp_path / "package.json", '{"workspaces": ["packages/ui", "packages/api"]}')
        self._make_package(tmp_path / "packages" / "ui", "ui")
        self._make_package(tmp_path / "packages" / "api", "api")
        dirs = find_package_json_workspace_dirs(tmp_path)
        assert dirs == {"packages/ui", "packages/api"}

    def test_glob_wildcard_form_discovered(self, tmp_path):
        _write(tmp_path / "package.json", '{"workspaces": ["packages/*"]}')
        self._make_package(tmp_path / "packages" / "ui", "ui")
        self._make_package(tmp_path / "packages" / "api", "api")
        dirs = find_package_json_workspace_dirs(tmp_path)
        assert dirs == {"packages/ui", "packages/api"}

    def test_yarn_object_form_discovered(self, tmp_path):
        _write(tmp_path / "package.json", '{"workspaces": {"packages": ["packages/*"]}}')
        self._make_package(tmp_path / "packages" / "ui", "ui")
        dirs = find_package_json_workspace_dirs(tmp_path)
        assert dirs == {"packages/ui"}

    def test_entry_without_own_package_json_not_counted_as_workspace(self, tmp_path):
        _write(tmp_path / "package.json", '{"workspaces": ["packages/ui"]}')
        (tmp_path / "packages" / "ui").mkdir(parents=True)  # dir exists, but no package.json inside
        assert find_package_json_workspace_dirs(tmp_path) == set()

    def test_no_workspaces_field_gives_empty_set(self, tmp_path):
        _write(tmp_path / "package.json", '{"name": "solo-package"}')
        assert find_package_json_workspace_dirs(tmp_path) == set()

    def test_config_search_root_defaults_to_repo_root_unchanged(self, tmp_path):
        _write(tmp_path / "package.json", '{"workspaces": ["packages/ui"]}')
        self._make_package(tmp_path / "packages" / "ui", "ui")
        assert find_package_json_workspace_dirs(tmp_path) == find_package_json_workspace_dirs(tmp_path, config_search_root=tmp_path)

    def test_declaring_package_json_above_repo_root_is_a_legitimate_shape_not_discarded(self, tmp_path):
        # Deliberately different from find_ts_configs' test: the
        # DECLARING package.json lives above repo_root, but the workspace
        # boundary it names resolves INSIDE repo_root -- a real root
        # monorepo package.json declaring `workspaces: ["backend/*"]` for
        # a source_root-scoped ingest of `backend/`. The declaring file's
        # own location doesn't matter; only where the resulting boundary
        # lands does.
        _write(tmp_path / "package.json", '{"workspaces": ["backend/packages/*"]}')
        repo_root = tmp_path / "backend"
        self._make_package(repo_root / "packages" / "ui", "ui")
        dirs = find_package_json_workspace_dirs(repo_root, config_search_root=tmp_path)
        assert dirs == {"packages/ui"}

    def test_boundary_resolving_outside_repo_root_is_discarded(self, tmp_path):
        # Same declaring package.json above repo_root, but this time the
        # named workspace resolves to a directory OUTSIDE repo_root's own
        # subtree -- has no valid repo_root-relative representation, must
        # be dropped rather than raise or mis-map.
        _write(tmp_path / "package.json", '{"workspaces": ["other/*"]}')
        self._make_package(tmp_path / "other" / "ui", "ui")
        repo_root = tmp_path / "backend"
        repo_root.mkdir()
        dirs = find_package_json_workspace_dirs(repo_root, config_search_root=tmp_path)
        assert dirs == set()


class TestWorkspaceOf:
    def test_file_inside_workspace_returns_that_workspace(self):
        workspaces = {"packages/ui", "packages/api"}
        assert workspace_of("packages/ui/src/widget.ts", workspaces) == "packages/ui"

    def test_file_outside_any_workspace_returns_none(self):
        workspaces = {"packages/ui"}
        assert workspace_of("apps/web/src/main.ts", workspaces) is None

    def test_deepest_workspace_wins_when_nested(self):
        workspaces = {"packages", "packages/ui"}
        assert workspace_of("packages/ui/src/widget.ts", workspaces) == "packages/ui"

    def test_no_workspaces_declared_returns_none(self):
        assert workspace_of("packages/ui/src/widget.ts", set()) is None

    def test_sibling_directory_with_similar_name_not_treated_as_inside(self):
        workspaces = {"packages/ui"}
        assert workspace_of("packages/ui-extra/src/widget.ts", workspaces) is None


class TestLoadJsRootDiscoveryConfig:
    def test_default_extension_probe_order_when_no_config_file(self):
        config = load_js_root_discovery_config()
        assert config["extension_probe_order"] == [".ts", ".tsx", ".js", ".jsx"]
        assert config["try_index_resolution"] is True


class TestSyntheticFixtureEndToEnd:
    """Neither real registered repo (repo 1's frontend, repo 2's frontend)
    uses tsconfig/jsconfig paths, a Vite resolve.alias, or package.json
    workspaces -- confirmed by direct inspection before writing this phase's
    plan. Validating against them alone would exercise none of
    find_ts_configs/config_for_file/find_package_json_workspace_dirs/the
    longest-prefix-wins fix/the index-vs-file probe order -- the same kind
    of silently-unexercised path that made the original single-tsconfig
    lookup's bug invisible. This fixture is built specifically to exercise
    all of it together, end to end: a monorepo with a root tsconfig, a
    nested package tsconfig with its OWN, more specific aliases (project
    boundary correctness -- no cascading to the root's paths), overlapping
    alias patterns (longest-prefix-wins), a file/index-both-exist ambiguity,
    and a package.json workspaces field."""

    def _build_fixture(self, root: Path):
        _write(root / "package.json", '{"workspaces": ["packages/*"]}')
        _write(root / "tsconfig.json", '{"compilerOptions": {"baseUrl": ".", "paths": {"@/*": ["./src/*"]}}}')
        _write(root / "src" / "utils.ts", "export const util = 1;\n")
        _write(root / "src" / "utils" / "index.ts", "export const utilIndex = 1;\n")  # file-vs-index ambiguity
        _write(root / "src" / "components" / "button.ts", "export const Button = 1;\n")
        _write(root / "src" / "main.ts", "export {};\n")

        _write(root / "packages" / "ui" / "package.json", '{"name": "ui"}')
        _write(
            root / "packages" / "ui" / "tsconfig.json",
            '{"compilerOptions": {"baseUrl": ".", "paths": '
            '{"@ui/*": ["./src/*"], "@ui/components/*": ["./src/components/*"]}}}',
        )
        _write(root / "packages" / "ui" / "src" / "widget.ts", "export const Widget = 1;\n")
        _write(root / "packages" / "ui" / "src" / "components" / "icon.ts", "export const Icon = 1;\n")
        _write(root / "packages" / "ui" / "src" / "main.ts", "export {};\n")

        all_paths = {
            "package.json", "tsconfig.json",
            "src/utils.ts", "src/utils/index.ts", "src/components/button.ts", "src/main.ts",
            "packages/ui/package.json", "packages/ui/tsconfig.json",
            "packages/ui/src/widget.ts", "packages/ui/src/components/icon.ts", "packages/ui/src/main.ts",
        }
        return all_paths

    def test_workspace_boundary_discovered(self, tmp_path):
        self._build_fixture(tmp_path)
        assert find_package_json_workspace_dirs(tmp_path) == {"packages/ui"}

    def test_both_configs_discovered(self, tmp_path):
        self._build_fixture(tmp_path)
        configs = find_ts_configs(tmp_path)
        assert {c["dir"] for c in configs} == {"", "packages/ui"}

    def test_root_file_governed_by_root_config_resolves_via_its_alias(self, tmp_path):
        all_paths = self._build_fixture(tmp_path)
        configs = find_ts_configs(tmp_path)
        governing = config_for_file("src/main.ts", configs)
        assert governing["dir"] == ""
        target = resolve_js_module("@/components/button", "src/main.ts", all_paths, path_aliases=governing["paths"])
        assert target == "src/components/button.ts"

    def test_file_form_wins_over_index_form_through_the_real_alias(self, tmp_path):
        all_paths = self._build_fixture(tmp_path)
        configs = find_ts_configs(tmp_path)
        governing = config_for_file("src/main.ts", configs)
        target = resolve_js_module("@/utils", "src/main.ts", all_paths, path_aliases=governing["paths"])
        assert target == "src/utils.ts"  # not src/utils/index.ts, despite both existing

    def test_nested_package_file_governed_by_its_own_config_not_root(self, tmp_path):
        all_paths = self._build_fixture(tmp_path)
        configs = find_ts_configs(tmp_path)
        governing = config_for_file("packages/ui/src/main.ts", configs)
        assert governing["dir"] == "packages/ui"
        # "@/*" (the ROOT's alias) must NOT resolve anything from inside
        # packages/ui -- it isn't even in the nested config's own paths.
        assert "@/*" not in governing["paths"]

    def test_nested_package_longest_prefix_wins_through_the_real_alias(self, tmp_path):
        all_paths = self._build_fixture(tmp_path)
        configs = find_ts_configs(tmp_path)
        governing = config_for_file("packages/ui/src/main.ts", configs)
        target = resolve_js_module("@ui/components/icon", "packages/ui/src/main.ts", all_paths, path_aliases=governing["paths"])
        assert target == "packages/ui/src/components/icon.ts"  # not packages/ui/src/icon.ts (the broader @ui/* pattern)

    def test_nested_package_broader_alias_still_works_for_its_own_files(self, tmp_path):
        all_paths = self._build_fixture(tmp_path)
        configs = find_ts_configs(tmp_path)
        governing = config_for_file("packages/ui/src/main.ts", configs)
        target = resolve_js_module("@ui/widget", "packages/ui/src/main.ts", all_paths, path_aliases=governing["paths"])
        assert target == "packages/ui/src/widget.ts"
