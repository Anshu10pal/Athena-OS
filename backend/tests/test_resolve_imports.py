"""resolve_python_import's `roots` parameter (Phase E2.1) and
resolve_js_module's bug fixes + probe-order parameters (Phase E2.2).
Pure-function tests, no DB, no ingest -- files is a plain set of
repo-relative paths.
"""
from app.services.codebase.resolve_imports import resolve_js_module, resolve_python_import


class TestRootsParameterBackwardCompatibility:
    def test_default_roots_matches_pre_e2_behavior_no_prefix(self):
        files = {"app/db/models.py"}
        target, _ = resolve_python_import("app.db.models", None, "main.py", files)
        assert target == "app/db/models.py"

    def test_default_roots_matches_pre_e2_behavior_src_fallback(self):
        files = {"src/app/db/models.py"}
        target, _ = resolve_python_import("app.db.models", None, "main.py", files)
        assert target == "src/app/db/models.py"

    def test_default_roots_prefers_no_prefix_over_src_fallback(self):
        files = {"app/db/models.py", "src/app/db/models.py"}
        target, _ = resolve_python_import("app.db.models", None, "main.py", files)
        assert target == "app/db/models.py"


class TestExplicitRoots:
    def test_single_explicit_root_used_as_prefix(self):
        files = {"backend/app/db/models.py"}
        target, _ = resolve_python_import("app.db.models", None, "backend/app/main.py", files, roots=["backend"])
        assert target == "backend/app/db/models.py"

    def test_explicit_roots_does_not_fall_back_to_no_prefix_or_src(self):
        # roots=["backend"] means ONLY try that prefix -- verifying one
        # candidate root in isolation is the whole point (root_discovery.py's
        # scoring), so it must not silently also try "" or "src".
        files = {"app/db/models.py"}  # exists WITHOUT the backend/ prefix
        target, _ = resolve_python_import("app.db.models", None, "main.py", files, roots=["backend"])
        assert target is None

    def test_empty_string_root_means_no_prefix(self):
        files = {"app/db/models.py"}
        target, _ = resolve_python_import("app.db.models", None, "main.py", files, roots=[""])
        assert target == "app/db/models.py"

    def test_multiple_explicit_roots_tried_in_order(self):
        files = {"lib/app/db/models.py"}
        target, _ = resolve_python_import(
            "app.db.models", None, "main.py", files, roots=["backend", "lib"]
        )
        assert target == "lib/app/db/models.py"

    def test_relative_specifier_ignores_roots_entirely(self):
        files = {"pkg/sibling.py"}
        target, _ = resolve_python_import(".sibling", None, "pkg/main.py", files, roots=["irrelevant_root"])
        assert target == "pkg/sibling.py"

    def test_no_matching_root_returns_none(self):
        files = {"other/app/db/models.py"}
        target, _ = resolve_python_import("app.db.models", None, "main.py", files, roots=["backend"])
        assert target is None


class TestResolveJsModuleLongestPrefixWins:
    def test_more_specific_pattern_preferred_over_broader_one(self):
        files = {"src/components/button.ts", "src/other/button.ts"}
        # dict order deliberately puts the BROADER pattern first -- if
        # iteration order were trusted instead of prefix length, this would
        # wrongly resolve through "@/*" -> src/other/button.ts.
        aliases = {"@/*": ["src/other/*"], "@/components/*": ["src/components/*"]}
        target = resolve_js_module("@/components/button", "x.ts", files, path_aliases=aliases)
        assert target == "src/components/button.ts"

    def test_falls_back_to_broader_pattern_when_specific_one_does_not_resolve(self):
        files = {"src/other/components/button.ts"}
        aliases = {"@/*": ["src/other/*"], "@/components/*": ["src/components/*"]}
        target = resolve_js_module("@/components/button", "x.ts", files, path_aliases=aliases)
        assert target == "src/other/components/button.ts"


class TestResolveJsModuleArrayTargetCoercion:
    def test_malformed_single_string_target_treated_as_one_target_not_iterated_as_chars(self):
        files = {"src/lib/util.ts"}
        aliases = {"@lib/*": "src/lib/*"}  # malformed: should be a list per real tsconfig.json
        target = resolve_js_module("@lib/util", "x.ts", files, path_aliases=aliases)
        assert target == "src/lib/util.ts"

    def test_array_target_tried_in_order_first_hit_wins(self):
        files = {"vendor/util.ts"}
        aliases = {"@lib/*": ["src/lib/*", "vendor/*"]}
        target = resolve_js_module("@lib/util", "x.ts", files, path_aliases=aliases)
        assert target == "vendor/util.ts"


class TestResolveJsModuleProbeOrder:
    def test_default_probe_order_matches_pre_e2_2_behavior(self):
        files = {"utils.ts", "utils.js"}
        target = resolve_js_module("./utils", "main.ts", files)
        assert target == "utils.ts"  # .ts before .js, the default order

    def test_explicit_probe_order_changes_which_extension_wins(self):
        files = {"utils.ts", "utils.js"}
        target = resolve_js_module("./utils", "main.ts", files, extension_probe_order=[".js", ".ts"])
        assert target == "utils.js"

    def test_index_resolution_disabled_skips_directory_form(self):
        files = {"utils/index.ts"}
        target = resolve_js_module("./utils", "main.ts", files, try_index_resolution=False)
        assert target is None

    def test_index_resolution_enabled_by_default(self):
        files = {"utils/index.ts"}
        target = resolve_js_module("./utils", "main.ts", files)
        assert target == "utils/index.ts"

    def test_file_form_preferred_over_index_form_when_both_exist(self):
        files = {"utils.ts", "utils/index.ts"}
        target = resolve_js_module("./utils", "main.ts", files)
        assert target == "utils.ts"
