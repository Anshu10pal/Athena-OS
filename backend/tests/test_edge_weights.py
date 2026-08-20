"""Phase F1: edge kind classification.

Extraction-side local_names/is_reexport capture is tested directly (the
failure mode to guard against is silently discarding an alias and always
counting zero occurrences -- exactly what would have happened with
`import numpy as np` before this phase). classify_edge's precedence rules
are tested directly against the written-down design: test_edge/reexport/
unresolvable_binding short-circuit as provenance facts; inherits/calls/
heavy_use/light_use/type_only compete via a fixed priority order.
"""
from app.services.codebase import extract_js, extract_python
from app.services.codebase.edge_weights import (
    classify_edge,
    is_test_file,
    load_edge_weights,
    occurrence_count_after_line,
    resolve_weight,
)


class TestPythonLocalNameCapture:
    def test_bare_import_no_alias(self):
        _, imports = extract_python.extract(b"import os\n")
        assert imports[0].imported_names == []
        assert imports[0].local_names == ["os"]

    def test_bare_dotted_import_binds_first_component(self):
        # `import os.path` binds the name `os`, not `os.path`.
        _, imports = extract_python.extract(b"import os.path\n")
        assert imports[0].imported_names == []
        assert imports[0].local_names == ["os"]

    def test_bare_import_with_alias(self):
        _, imports = extract_python.extract(b"import numpy as np\n")
        assert imports[0].imported_names == []
        assert imports[0].local_names == ["np"]

    def test_from_import_no_alias(self):
        _, imports = extract_python.extract(b"from a.b import helper\n")
        assert imports[0].imported_names == ["helper"]
        assert imports[0].local_names == ["helper"]

    def test_from_import_with_alias(self):
        _, imports = extract_python.extract(b"from a.b import thing as t\n")
        assert imports[0].imported_names == ["thing"]
        assert imports[0].local_names == ["t"]

    def test_wildcard_import_has_no_local_name(self):
        _, imports = extract_python.extract(b"from x import *\n")
        assert imports[0].imported_names == ["*"]
        assert imports[0].local_names == [None]

    def test_never_marked_as_reexport(self):
        _, imports = extract_python.extract(b"from a import b\nimport c\n")
        assert all(not ri.is_reexport for ri in imports)


class TestJsLocalNameCapture:
    def test_default_import_local_name_is_real_identifier_not_sentinel(self):
        _, imports = extract_js.extract(b'import Foo from "./foo";\n', "typescript")
        assert imports[0].imported_names == ["default"]
        assert imports[0].local_names == ["Foo"]

    def test_named_import_no_alias(self):
        _, imports = extract_js.extract(b'import { bar } from "./bar";\n', "typescript")
        assert imports[0].imported_names == ["bar"]
        assert imports[0].local_names == ["bar"]

    def test_named_import_with_alias(self):
        _, imports = extract_js.extract(b'import { foo as f } from "./x";\n', "typescript")
        assert imports[0].imported_names == ["foo"]
        assert imports[0].local_names == ["f"]

    def test_namespace_import_local_name(self):
        _, imports = extract_js.extract(b'import * as ns from "lib";\n', "typescript")
        assert imports[0].imported_names == ["*"]
        assert imports[0].local_names == ["ns"]

    def test_reexport_is_flagged_with_no_local_names(self):
        _, imports = extract_js.extract(b'export { x } from "./x";\n', "typescript")
        assert imports[0].is_reexport is True
        assert imports[0].local_names == [None]

    def test_wildcard_reexport_is_flagged(self):
        _, imports = extract_js.extract(b'export * from "./y";\n', "typescript")
        assert imports[0].is_reexport is True

    def test_regular_import_never_flagged_as_reexport(self):
        _, imports = extract_js.extract(b'import { bar } from "./bar";\n', "typescript")
        assert imports[0].is_reexport is False

    def test_require_has_no_local_name(self):
        _, imports = extract_js.extract(b'const mod = require("./req");\n', "javascript")
        assert imports[0].local_names == []


class TestIsTestFile:
    def test_matches_common_patterns(self):
        for path in ("backend/tests/test_ingest.py", "src/foo_test.py", "src/foo.test.ts", "src/foo.spec.ts", "src/__tests__/foo.ts"):
            assert is_test_file(path), path

    def test_does_not_match_normal_source(self):
        for path in ("backend/app/main.py", "frontend/src/App.tsx", "backend/app/core/testing_utils.py"):
            assert not is_test_file(path), path

    def test_top_level_test_directory_matches(self):
        """The regression that motivated the structural rewrite: the old
        "/tests/" substring needed a leading slash, so a top-level tests/
        tree matched nothing. eslint/eslint has 963 such files and Superset
        443, all of them weighted as real coupling instead of test_edge."""
        for path in ("tests/lib/linter.js", "tests/conftest.py", "test/helpers/setup.js"):
            assert is_test_file(path), path

    def test_matches_python_and_js_naming_conventions(self):
        for path in ("superset/db_tests.py", "a/conftest.py", "src/foo-test.js", "spec/models/user.rb"):
            assert is_test_file(path), path

    def test_word_boundary_prevents_substring_false_positives(self):
        """A bare "test" substring would match all of these; the "_", "." or
        "-" boundary on at least one side is what keeps them out."""
        for path in ("src/latest_version.py", "src/contest.py", "app/protest_handler.py", "src/manifest.py"):
            assert not is_test_file(path), path

    def test_normalizes_windows_separators(self):
        assert is_test_file("backend\\tests\\test_ingest.py")


class TestOccurrenceCountAfterLine:
    def test_excludes_import_block_lines(self):
        text = "from x import helper\nhelper()\nhelper()\n"
        # boundary_line=1 -- everything after the one import line
        assert occurrence_count_after_line(text, "helper", 1) == 2

    def test_none_name_returns_zero(self):
        assert occurrence_count_after_line("anything", None, 0) == 0

    def test_dotted_attribute_access_counts_as_a_use(self):
        text = "import numpy as np\nx = np.array([1, 2])\ny = np.linalg.norm(x)\n"
        assert occurrence_count_after_line(text, "np", 1) == 2

    def test_substring_names_do_not_false_positive(self):
        text = "import numpy as np\nsnap = 1\nmynp = 2\n"
        assert occurrence_count_after_line(text, "np", 1) == 0


class TestClassifyEdge:
    def _classify(self, source_text, local_name="helper", original_name="helper", boundary=1, path="app/main.py", reexport=False):
        return classify_edge(
            source_text=source_text, local_name=local_name, original_name=original_name,
            import_block_end_line=boundary, from_file_path=path, is_reexport=reexport,
        )

    def test_test_file_short_circuits_to_test_edge(self):
        # Even though `helper` is used heavily, the source file is a test.
        source = "from x import helper\n" + "helper()\n" * 10
        kind = self._classify(source, path="backend/tests/test_foo.py")
        assert kind == "test_edge"

    def test_reexport_short_circuits_even_with_no_local_name(self):
        kind = self._classify("export { x } from './x';\n", local_name=None, original_name="x", reexport=True)
        assert kind == "reexport"

    def test_no_local_name_is_unresolvable_binding(self):
        kind = self._classify("const mod = require('./req');\n", local_name=None, original_name=None)
        assert kind == "unresolvable_binding"

    def test_wildcard_is_unresolvable_binding_even_with_a_local_name(self):
        # Shouldn't normally have a local_name when original is "*", but the
        # wildcard check must win regardless.
        kind = self._classify("from x import *\n", local_name="something", original_name="*")
        assert kind == "unresolvable_binding"

    def test_inherits_beats_heavy_use(self):
        source = "from x import Base\n" + "Base.thing\n" * 10 + "class Foo(Base):\n    pass\n"
        kind = self._classify(source, local_name="Base", original_name="Base")
        assert kind == "inherits"

    def test_calls_beats_light_use(self):
        source = "from x import helper\nhelper(1)\n"
        kind = self._classify(source, local_name="helper", original_name="helper")
        assert kind == "calls"

    def test_heavy_use_without_call_or_inherit(self):
        source = "from x import CONST\n" + "print(CONST)\n" * 5
        kind = self._classify(source, local_name="CONST", original_name="CONST")
        assert kind == "heavy_use"

    def test_light_use(self):
        source = "from x import CONST\nprint(CONST)\n"
        kind = self._classify(source, local_name="CONST", original_name="CONST")
        assert kind == "light_use"

    def test_type_only_when_zero_body_occurrences(self):
        source = "from x import Thing\n\ndef f(a):\n    pass\n"
        kind = self._classify(source, local_name="Thing", original_name="Thing")
        assert kind == "type_only"

    def test_test_edge_short_circuits_even_when_inherits_would_otherwise_apply(self):
        # Confirms the agreed precedence: test_edge is a provenance fact
        # checked before the usage-signal group, so it wins over inherits
        # even though inherits alone is the highest-priority usage signal.
        source = "from x import Base\nclass Foo(Base):\n    pass\n"
        kind = self._classify(source, local_name="Base", original_name="Base", path="backend/tests/test_foo.py")
        assert kind == "test_edge"


class TestEdgeWeightsConfig:
    def test_load_edge_weights_has_all_kinds(self):
        from app.services.codebase.edge_weights import ALL_KINDS

        weights = load_edge_weights()
        for kind in ALL_KINDS:
            assert kind in weights, kind

    def test_resolve_weight_uses_default_for_unknown_kind(self):
        assert resolve_weight("not_a_real_kind", weights={}) == 0.0

    def test_missing_config_file_falls_back_to_defaults(self, monkeypatch):
        from app.core import config as config_module

        monkeypatch.setattr(config_module.settings, "EDGE_WEIGHTS_PATH", "./nonexistent-file.yaml")
        weights = load_edge_weights()
        assert weights["inherits"] == 1.0
