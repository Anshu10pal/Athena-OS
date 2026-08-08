"""Phase B: parse + import graph.

Extraction is tested directly against tree-sitter output (the failure mode to
guard against is silently-empty extraction that looks like success). Ingest
is tested end-to-end against small real repos written to tmp_path -- no
mocking of tree-sitter, the filesystem walk, or the DB.
"""
from pathlib import Path

import pytest

from app.db.models import CodeFile, CodeImport, CodeSymbol, Repo
from app.services.codebase import extract_js, extract_python, resolve_imports
from app.services.codebase.discovery import TooManyFilesError, discover_files
from app.services.codebase.ingest import RootPromotionCollapseError, ingest_repo
from app.services.codebase.registry import register_from_path
from app.services.codebase.repo_lock import RepoBusyError, repo_lock


# ---------------- extraction: Python ----------------


class TestExtractPython:
    def test_functions_classes_methods_and_docstrings(self):
        src = b'''
def foo(a: int, b: str = "x") -> bool:
    """docstring here."""
    return True


class Foo:
    """class doc."""

    def method(self, x):
        pass
'''
        symbols, _ = extract_python.extract(src)
        by_name = {s.name: s for s in symbols}
        assert by_name["foo"].kind == "function"
        assert by_name["foo"].docstring == "docstring here."
        assert "def foo(a: int, b: str = \"x\") -> bool" == by_name["foo"].signature
        assert by_name["Foo"].kind == "class"
        assert by_name["Foo"].docstring == "class doc."
        assert by_name["method"].kind == "method"
        assert by_name["method"].parent_name == "Foo"

    def test_no_docstring_is_none(self):
        symbols, _ = extract_python.extract(b"def foo():\n    return 1\n")
        assert symbols[0].docstring is None

    def test_import_forms(self):
        src = b'''
import os
import os.path as p
from . import sibling
from .utils import helper
from ..pkg.mod import thing as t
from typing import Optional, List
from a.b import (c, d)
from x import *
'''
        _, imports = extract_python.extract(src)
        specs = {(i.raw_specifier, tuple(i.imported_names)) for i in imports}
        assert ("os", ()) in specs
        assert ("os.path", ()) in specs
        assert (".", ("sibling",)) in specs
        assert (".utils", ("helper",)) in specs
        assert ("..pkg.mod", ("thing",)) in specs
        assert ("typing", ("Optional", "List")) in specs
        assert ("a.b", ("c", "d")) in specs
        assert ("x", ("*",)) in specs


# ---------------- extraction: TypeScript/JS ----------------


class TestExtractJs:
    def test_import_forms(self):
        src = b'''
import Foo from "./foo";
import { bar, baz } from "../utils/bar";
import { original as alias } from "./renamed";
import * as ns from "lib";
import type { OnlyType } from "./types";
import "./side-effect";
export { x } from "./x";
export * from "./y";
export * as nsRe from "./z";
const mod = require("./req");
import("./dynamic").then(() => {});
'''
        _, imports = extract_js.extract(src, "typescript")
        specs = {(i.raw_specifier, tuple(i.imported_names)) for i in imports}
        assert ("./foo", ("default",)) in specs
        # extract_js returns one RawImport per statement with all names combined;
        # fan-out into one CodeImport row per name happens later, at persist time.
        assert ("../utils/bar", ("bar", "baz")) in specs
        assert ("./renamed", ("original",)) in specs  # original name, not the local alias
        assert ("lib", ("*",)) in specs
        assert ("./types", ("OnlyType",)) in specs
        assert ("./side-effect", ()) in specs
        assert ("./x", ("x",)) in specs
        assert ("./y", ("*",)) in specs
        assert ("./z", ("*",)) in specs
        assert ("./req", ()) in specs
        # dynamic import() is deliberately never extracted as an edge
        assert not any(spec == "./dynamic" for spec, _ in specs)

    def test_functions_classes_methods_and_arrow_functions(self):
        src = b'''
export function greet(name: string): string {
  return "hi " + name;
}

export class Widget {
  render(x: number): void {}
  static create(): Widget { return new Widget(); }
}

const add = (a: number, b: number): number => a + b;
export const Named = () => 1;
export default function Main() {}
'''
        symbols, _ = extract_js.extract(src, "typescript")
        by_name = {s.name: s for s in symbols}
        assert by_name["greet"].kind == "function"
        assert by_name["Widget"].kind == "class"
        assert by_name["render"].kind == "method"
        assert by_name["render"].parent_name == "Widget"
        assert by_name["create"].kind == "method"
        assert by_name["add"].kind == "function"
        assert by_name["Named"].kind == "function"
        assert by_name["Main"].kind == "function"

    def test_tsx_component_structure_matches_ts(self):
        src = b'''
import React from "react";

export default function App() {
  return <div className="x">hi</div>;
}

export const Card = ({ title }: { title: string }) => {
  return <div>{title}</div>;
};
'''
        symbols, imports = extract_js.extract(src, "tsx")
        assert {s.name for s in symbols} == {"App", "Card"}
        assert any(i.raw_specifier == "react" for i in imports)

    def test_plain_javascript_class_name_uses_identifier_node(self):
        # Plain JS (not TS) grammar names a class with `identifier`, not
        # `type_identifier` -- verified directly against tree-sitter-javascript.
        src = b"class Widget {\n  render(x) {}\n}\n"
        symbols, _ = extract_js.extract(src, "javascript")
        assert {s.name for s in symbols} == {"Widget", "render"}


# ---------------- discovery ----------------


class TestDiscovery:
    def test_default_excludes_and_extension_filter(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("x = 1\n")
        (tmp_path / "src" / "readme.md").write_text("not code\n")
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "lib.js").write_text("x\n")
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "__pycache__" / "main.cpython-311.pyc").write_text("x\n")

        found = discover_files(tmp_path, max_files=100)
        assert found == [Path("src/main.py")]

    def test_gitignore_respected(self, tmp_path):
        (tmp_path / ".gitignore").write_text("ignored/\n")
        (tmp_path / "ignored").mkdir()
        (tmp_path / "ignored" / "a.py").write_text("x = 1\n")
        (tmp_path / "kept.py").write_text("x = 1\n")

        found = discover_files(tmp_path, max_files=100)
        assert found == [Path("kept.py")]

    def test_file_cap_raises_without_truncating(self, tmp_path):
        for i in range(5):
            (tmp_path / f"f{i}.py").write_text("x = 1\n")
        with pytest.raises(TooManyFilesError):
            discover_files(tmp_path, max_files=3)

    def test_extra_excludes_apply_independent_of_gitignore(self, tmp_path):
        # No .gitignore at all -- extra_excludes must still work. This is the
        # exact shape of a registered `local` repo that isn't a git repo, or
        # whose .gitignore doesn't happen to cover the clone cache.
        (tmp_path / "cache").mkdir()
        (tmp_path / "cache" / "hidden.py").write_text("x = 1\n")
        (tmp_path / "kept.py").write_text("x = 1\n")

        found = discover_files(tmp_path, max_files=100, extra_excludes=["cache/"])
        assert found == [Path("kept.py")]


# ---------------- resolution ----------------


class TestResolvePython:
    def test_absolute_import(self):
        files = {"pkg/a.py", "pkg/__init__.py"}
        path, is_sub = resolve_imports.resolve_python_import("pkg.a", None, "main.py", files)
        assert path == "pkg/a.py"

    def test_relative_module_import(self):
        files = {"pkg/a.py", "pkg/b.py"}
        path, is_sub = resolve_imports.resolve_python_import(".a", "foo", "pkg/b.py", files)
        assert path == "pkg/a.py"

    def test_bare_dot_import_treats_name_as_submodule(self):
        files = {"pkg/sibling.py", "pkg/b.py"}
        path, is_sub = resolve_imports.resolve_python_import(".", "sibling", "pkg/b.py", files)
        assert path == "pkg/sibling.py"
        assert is_sub is True

    def test_unresolvable_external_import(self):
        path, _ = resolve_imports.resolve_python_import("numpy", None, "main.py", {"main.py"})
        assert path is None


class TestResolveJs:
    def test_relative_with_extension_resolution(self):
        files = {"src/utils.ts", "src/main.ts"}
        path = resolve_imports.resolve_js_module("./utils", "src/main.ts", files)
        assert path == "src/utils.ts"

    def test_relative_index_resolution(self):
        files = {"src/lib/index.ts", "src/main.ts"}
        path = resolve_imports.resolve_js_module("./lib", "src/main.ts", files)
        assert path == "src/lib/index.ts"

    def test_tsconfig_alias(self):
        files = {"src/components/Button.tsx", "src/main.tsx"}
        aliases = {"@components/*": ["src/components/*"]}
        path = resolve_imports.resolve_js_module("@components/Button", "src/main.tsx", files, aliases)
        assert path == "src/components/Button.tsx"

    def test_external_package_unresolved(self):
        path = resolve_imports.resolve_js_module("react", "src/main.tsx", {"src/main.tsx"})
        assert path is None


# ---------------- ingest: end to end ----------------


def _write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


class TestIngestPythonRepo:
    def _make_repo(self, tmp_path) -> Path:
        root = tmp_path / "repo"
        _write(root / "pkg" / "__init__.py", "")
        _write(root / "pkg" / "a.py", "def foo():\n    return 1\n")
        _write(root / "pkg" / "b.py", "from .a import foo\n\n\ndef bar():\n    return foo()\n")
        _write(root / "main.py", "from pkg.a import foo\nfrom pkg import b\n")
        return root

    def test_symbols_and_cross_file_resolution(self, db_session, tmp_path):
        root = self._make_repo(tmp_path)
        repo = register_from_path(db_session, str(root))
        report = ingest_repo(db_session, repo)

        assert report.files_total == 4
        assert report.files_parsed == 4
        assert report.files_skipped_unchanged == 0

        files = {f.path: f for f in db_session.query(CodeFile).filter(CodeFile.repo_id == repo.id).all()}
        assert set(files) == {"pkg/__init__.py", "pkg/a.py", "pkg/b.py", "main.py"}

        foo_symbol = db_session.query(CodeSymbol).filter(
            CodeSymbol.file_id == files["pkg/a.py"].id, CodeSymbol.name == "foo"
        ).one()

        b_import = db_session.query(CodeImport).filter(
            CodeImport.from_file_id == files["pkg/b.py"].id
        ).one()
        assert b_import.resolved is True
        assert b_import.to_file_id == files["pkg/a.py"].id
        assert b_import.to_symbol_id == foo_symbol.id

        main_imports = db_session.query(CodeImport).filter(CodeImport.from_file_id == files["main.py"].id).all()
        by_spec = {(i.raw_specifier, tuple(i.imported_names)): i for i in main_imports}
        assert by_spec[("pkg.a", ("foo",))].to_file_id == files["pkg/a.py"].id
        assert by_spec[("pkg.a", ("foo",))].to_symbol_id == foo_symbol.id
        # `from pkg import b` -- b is a submodule, not a symbol inside pkg/__init__.py
        assert by_spec[("pkg", ("b",))].to_file_id == files["pkg/b.py"].id
        assert by_spec[("pkg", ("b",))].to_symbol_id is None

    def test_reingest_unchanged_repo_reparses_nothing(self, db_session, tmp_path):
        root = self._make_repo(tmp_path)
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)

        report2 = ingest_repo(db_session, repo)
        assert report2.files_parsed == 0
        assert report2.files_skipped_unchanged == report2.files_total

    def test_reingest_after_edit_reparses_only_changed_file(self, db_session, tmp_path):
        root = self._make_repo(tmp_path)
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)

        (root / "pkg" / "a.py").write_text("def foo():\n    return 2\n\n\ndef new_func():\n    pass\n")
        report2 = ingest_repo(db_session, repo)
        assert report2.files_parsed == 1
        assert report2.files_skipped_unchanged == report2.files_total - 1

        a_file = db_session.query(CodeFile).filter(CodeFile.repo_id == repo.id, CodeFile.path == "pkg/a.py").one()
        names = {s.name for s in db_session.query(CodeSymbol).filter(CodeSymbol.file_id == a_file.id).all()}
        assert names == {"foo", "new_func"}

    def test_deleted_file_is_removed_on_reingest(self, db_session, tmp_path):
        root = self._make_repo(tmp_path)
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)

        (root / "pkg" / "b.py").unlink()
        report2 = ingest_repo(db_session, repo)
        assert report2.files_deleted == 1
        remaining = {f.path for f in db_session.query(CodeFile).filter(CodeFile.repo_id == repo.id).all()}
        assert "pkg/b.py" not in remaining

    def test_new_file_resolves_previously_unresolved_import(self, db_session, tmp_path):
        root = self._make_repo(tmp_path)
        (root / "main.py").write_text("from pkg.missing import thing\n")
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)

        main_file = db_session.query(CodeFile).filter(CodeFile.repo_id == repo.id, CodeFile.path == "main.py").one()
        row = db_session.query(CodeImport).filter(CodeImport.from_file_id == main_file.id).one()
        assert row.resolved is False

        _write(root / "pkg" / "missing.py", "def thing():\n    pass\n")
        report2 = ingest_repo(db_session, repo)
        assert report2.files_parsed == 1  # only the new file -- main.py's hash didn't change

        db_session.refresh(row)
        assert row.resolved is True

    def test_zero_llm_calls_during_ingest(self, db_session, tmp_path, monkeypatch):
        root = self._make_repo(tmp_path)
        repo = register_from_path(db_session, str(root))

        def _boom(*a, **kw):
            raise AssertionError("LLM was called during a codebase-agent ingest")

        monkeypatch.setattr("app.core.llm.chat", _boom)
        monkeypatch.setattr("app.core.llm.chat_json", _boom)
        monkeypatch.setattr("app.core.llm.chat_stream", _boom)

        ingest_repo(db_session, repo)  # must complete without touching app.core.llm


class TestIngestTsRepo:
    def test_ts_cross_file_resolution(self, db_session, tmp_path):
        root = tmp_path / "repo"
        _write(root / "src" / "utils.ts", "export function helper(): number {\n  return 1;\n}\n")
        _write(root / "src" / "main.ts", 'import { helper } from "./utils";\n\nhelper();\n')
        repo = register_from_path(db_session, str(root))
        report = ingest_repo(db_session, repo)

        assert report.files_total == 2
        files = {f.path: f for f in db_session.query(CodeFile).filter(CodeFile.repo_id == repo.id).all()}
        helper_symbol = db_session.query(CodeSymbol).filter(
            CodeSymbol.file_id == files["src/utils.ts"].id, CodeSymbol.name == "helper"
        ).one()
        row = db_session.query(CodeImport).filter(CodeImport.from_file_id == files["src/main.ts"].id).one()
        assert row.to_file_id == files["src/utils.ts"].id
        assert row.to_symbol_id == helper_symbol.id


class TestIngestConfigSearchRootAboveSourceRoot:
    """Closes the confirmed-but-not-yet-fixed config-discovery bug class
    (docs/external-validation-eslint.md's Round 2): find_marker_candidate_
    roots/find_ts_configs/find_package_json_workspace_dirs all searched
    only from `_repo_root(repo)` (source_root-scoped), missing config
    files that live above it. Fixed via a config_search_root parameter,
    same shape as entry_detection's.

    find_package_json_workspace_dirs is the one function where this
    produces an ACTUALLY OBSERVABLE difference at the ingest level (proven
    below) -- find_marker_candidate_roots and find_ts_configs discard any
    match outside repo_root's own subtree by construction (their return
    values are used as repo_root-relative paths), so widening never adds
    a new usable candidate for those two; only proven not to regress/crash
    here, honestly, not claimed to change behavior."""

    def test_workspace_declared_above_source_root_is_found_and_flags_cross_root(self, db_session, tmp_path):
        # True repo root: package.json declares a workspace glob that
        # resolves to a directory INSIDE source_root -- the declaring
        # file's own location (above source_root) doesn't matter, only
        # where the boundary it names lands (see find_package_json_
        # workspace_dirs' own docstring for why this discards at a
        # different point than find_ts_configs).
        root = tmp_path / "repo"
        _write(root / "package.json", '{"workspaces": ["app/packages/*"]}')
        _write(root / "app" / "packages" / "ui" / "package.json", '{"name": "ui"}')
        _write(root / "app" / "packages" / "ui" / "index.ts", 'import { x } from "../../main";\n')
        _write(root / "app" / "main.ts", "export const x = 1;\n")

        repo = register_from_path(db_session, str(root), source_root="app")
        report = ingest_repo(db_session, repo)

        assert report.files_total == 2
        files = {f.path: f for f in db_session.query(CodeFile).filter(CodeFile.repo_id == repo.id).all()}
        row = db_session.query(CodeImport).filter(
            CodeImport.from_file_id == files["packages/ui/index.ts"].id
        ).one()
        assert row.to_file_id == files["main.ts"].id
        assert row.cross_root_kind == "workspace_boundary"
        assert report.js_cross_root_edges == 1

    def test_marker_and_config_above_source_root_do_not_crash_or_regress(self, db_session, tmp_path):
        # Python marker + tsconfig.json both live above source_root.
        # Neither can ever nominate a usable candidate from outside
        # repo_root's own subtree (see the class docstring) -- this test
        # proves the widened scan doesn't crash and doesn't corrupt the
        # in-scope resolution that already worked before this fix.
        root = tmp_path / "repo"
        _write(root / "pyproject.toml", "[project]\nname = \"x\"\n")
        _write(root / "tsconfig.json", '{"compilerOptions": {"baseUrl": "."}}')
        _write(root / "backend" / "app" / "__init__.py", "")
        _write(root / "backend" / "app" / "utils.py", "def helper():\n    return 1\n")
        _write(root / "backend" / "app" / "main.py", "from app.utils import helper\n")

        repo = register_from_path(db_session, str(root), source_root="backend")
        report = ingest_repo(db_session, repo)

        files = {f.path: f for f in db_session.query(CodeFile).filter(CodeFile.repo_id == repo.id).all()}
        row = db_session.query(CodeImport).filter(CodeImport.from_file_id == files["app/main.py"].id).one()
        assert row.to_file_id == files["app/utils.py"].id  # in-scope resolution unaffected


class TestIngestPythonStage2RootDiscovery:
    """Phase E2.3: rows stage 1 (default "", "src") can't resolve get a
    second attempt using Phase E2.1's evidence-based root discovery. Needs
    at least 3 unresolved specifiers resolving under the same root to clear
    the default absolute floor (3) -- a single resolving specifier is not
    enough evidence to promote anything."""

    def _make_repo(self, tmp_path) -> Path:
        root = tmp_path / "repo"
        _write(root / "backend" / "requirements.txt", "fastapi\n")
        _write(root / "backend" / "app" / "__init__.py", "")
        _write(
            root / "backend" / "app" / "main.py",
            "from app.db import get_db\nfrom app.models import Model\nfrom app.utils import helper\n"
            "import json\nimport os\n",
        )
        _write(root / "backend" / "app" / "db.py", "def get_db():\n    return None\n")
        _write(root / "backend" / "app" / "models.py", "class Model:\n    pass\n")
        _write(root / "backend" / "app" / "utils.py", "def helper():\n    return 1\n")
        return root

    def test_stage2_resolves_via_promoted_root_and_reports_it(self, db_session, tmp_path):
        root = self._make_repo(tmp_path)
        repo = register_from_path(db_session, str(root))
        report = ingest_repo(db_session, repo)

        assert report.promoted_python_roots == ["backend"]

        files = {f.path: f for f in db_session.query(CodeFile).filter(CodeFile.repo_id == repo.id).all()}
        rows = db_session.query(CodeImport).filter(CodeImport.from_file_id == files["backend/app/main.py"].id).all()
        by_spec = {r.raw_specifier: r for r in rows}

        assert by_spec["app.db"].resolved is True
        assert by_spec["app.db"].to_file_id == files["backend/app/db.py"].id
        assert by_spec["app.models"].resolved is True
        assert by_spec["app.utils"].resolved is True

    def test_stdlib_specifiers_never_resolved_and_do_not_dilute_promotion(self, db_session, tmp_path):
        root = self._make_repo(tmp_path)
        repo = register_from_path(db_session, str(root))
        report = ingest_repo(db_session, repo)

        # json/os are real, unresolved, non-relative specifiers alongside the
        # 3 that DO resolve -- if the stdlib short-circuit weren't excluding
        # them from the scoring denominator, "backend" would still clear the
        # floors here (3/5 = 60%), but the point is they must never resolve
        # AND must never carry a cross_root_kind (never even probed).
        assert report.promoted_python_roots == ["backend"]

        files = {f.path: f for f in db_session.query(CodeFile).filter(CodeFile.repo_id == repo.id).all()}
        rows = db_session.query(CodeImport).filter(CodeImport.from_file_id == files["backend/app/main.py"].id).all()
        by_spec = {r.raw_specifier: r for r in rows}

        assert by_spec["json"].resolved is False
        assert by_spec["json"].cross_root_kind is None
        assert by_spec["os"].resolved is False
        assert by_spec["os"].cross_root_kind is None

    def test_no_cross_root_kind_when_nearest_promoted_root_resolves_directly(self, db_session, tmp_path):
        root = self._make_repo(tmp_path)
        repo = register_from_path(db_session, str(root))
        report = ingest_repo(db_session, repo)
        assert report.python_cross_root_edges == 0

        files = {f.path: f for f in db_session.query(CodeFile).filter(CodeFile.repo_id == repo.id).all()}
        row = db_session.query(CodeImport).filter(
            CodeImport.from_file_id == files["backend/app/main.py"].id, CodeImport.raw_specifier == "app.db"
        ).one()
        assert row.cross_root_kind is None


class TestIngestPythonRootPromotionCollapseTripwire:
    """Phase F7's second, better-grounded hypothesis for the Phase E2.3
    incident: root_discovery.promote_roots silently returning empty
    (evidence pool empty, thresholds not cleared, whatever the trigger)
    collapses stage 2 resolution to the bare ["", "src"] fallback for every
    unresolved absolute import, with no exception anywhere in the loop --
    deterministic, but invisible to a rank-time-only check (which can only
    ever see the aftermath). This is the ingest-time guard: fail before the
    commit that would persist the collapsed state."""

    def _make_repo(self, tmp_path) -> Path:
        return TestIngestPythonStage2RootDiscovery()._make_repo(tmp_path)

    def test_promotion_collapsing_to_empty_raises_before_commit(self, db_session, tmp_path, monkeypatch):
        root = self._make_repo(tmp_path)
        repo = register_from_path(db_session, str(root))
        report = ingest_repo(db_session, repo)
        assert report.promoted_python_roots == ["backend"]
        db_session.refresh(repo)
        assert repo.last_promoted_python_roots == ["backend"]

        from app.services.codebase import root_discovery
        monkeypatch.setattr(root_discovery, "promote_roots", lambda scores: set())

        with pytest.raises(RootPromotionCollapseError, match=r"backend"):
            ingest_repo(db_session, repo)

        # The collapsed state must never have been committed.
        db_session.rollback()
        db_session.refresh(repo)
        assert repo.last_promoted_python_roots == ["backend"]

    def test_promotion_staying_nonempty_across_reingest_does_not_raise(self, db_session, tmp_path):
        root = self._make_repo(tmp_path)
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)
        ingest_repo(db_session, repo)  # must not raise -- stable promotion across re-ingests

    def test_first_ever_ingest_never_raises_even_if_promotion_finds_nothing(self, db_session, tmp_path, monkeypatch):
        root = self._make_repo(tmp_path)
        repo = register_from_path(db_session, str(root))

        from app.services.codebase import root_discovery
        monkeypatch.setattr(root_discovery, "promote_roots", lambda scores: set())

        ingest_repo(db_session, repo)  # must not raise -- nothing promoted before, so nothing "collapsed"
        db_session.refresh(repo)
        assert repo.last_promoted_python_roots == []

    def test_successful_ingest_records_the_promoted_set(self, db_session, tmp_path):
        root = self._make_repo(tmp_path)
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)
        db_session.refresh(repo)
        assert repo.last_promoted_python_roots == ["backend"]

    def test_no_unresolved_python_rows_records_empty_without_raising(self, db_session, tmp_path):
        # Stage 2 never runs (stage 1 resolved everything) -- promotion was
        # never attempted, which is not the same thing as "collapsed", and
        # must never raise regardless of prior promotion history.
        root = tmp_path / "repo"
        _write(root / "a.py", "x = 1\n")
        _write(root / "b.py", "from a import x\n")  # resolves in stage 1 (relative-style, same dir)
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)
        db_session.refresh(repo)
        assert repo.last_promoted_python_roots == []


class TestIngestPythonStage2CrossRootFallback:
    """A second, nested promoted root (backend/legacy/) whose own file
    resolves an absolute specifier only via the SHALLOWER promoted root
    (backend/) -- the real "fallback occurred" case cross_root_kind exists
    to flag."""

    def _make_repo(self, tmp_path) -> Path:
        root = tmp_path / "repo"
        _write(root / "backend" / "requirements.txt", "fastapi\n")
        _write(root / "backend" / "app" / "__init__.py", "")
        _write(
            root / "backend" / "app" / "main.py",
            "from app.db import get_db\nfrom app.models import Model\nfrom app.utils import helper\n",
        )
        _write(root / "backend" / "app" / "db.py", "def get_db():\n    return None\n")
        _write(root / "backend" / "app" / "models.py", "class Model:\n    pass\n")
        _write(root / "backend" / "app" / "utils.py", "def helper():\n    return 1\n")

        _write(root / "backend" / "legacy" / "requirements.txt", "flask\n")
        _write(
            root / "backend" / "legacy" / "consumer.py",
            "from helpers import a\nfrom tools import b\nfrom extratool import c\n",
        )
        _write(root / "backend" / "legacy" / "helpers.py", "a = 1\n")
        _write(root / "backend" / "legacy" / "tools.py", "b = 1\n")
        _write(root / "backend" / "legacy" / "extratool.py", "c = 1\n")
        # old.py's own nearest promoted root is backend/legacy -- but "app.db"
        # only resolves under the SHALLOWER backend/ root.
        _write(root / "backend" / "legacy" / "old.py", "from app.db import get_db\n")
        return root

    def test_both_roots_promoted(self, db_session, tmp_path):
        root = self._make_repo(tmp_path)
        repo = register_from_path(db_session, str(root))
        report = ingest_repo(db_session, repo)
        assert set(report.promoted_python_roots) == {"backend", "backend/legacy"}

    def test_fallback_to_shallower_root_flagged_cross_root(self, db_session, tmp_path):
        root = self._make_repo(tmp_path)
        repo = register_from_path(db_session, str(root))
        report = ingest_repo(db_session, repo)

        files = {f.path: f for f in db_session.query(CodeFile).filter(CodeFile.repo_id == repo.id).all()}
        row = db_session.query(CodeImport).filter(CodeImport.from_file_id == files["backend/legacy/old.py"].id).one()
        assert row.resolved is True
        assert row.to_file_id == files["backend/app/db.py"].id
        assert row.cross_root_kind == "root_fallback"
        assert report.python_cross_root_edges == 1

    def test_consumer_resolving_via_its_own_nearest_root_is_not_flagged(self, db_session, tmp_path):
        root = self._make_repo(tmp_path)
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)

        files = {f.path: f for f in db_session.query(CodeFile).filter(CodeFile.repo_id == repo.id).all()}
        rows = db_session.query(CodeImport).filter(CodeImport.from_file_id == files["backend/legacy/consumer.py"].id).all()
        assert all(r.resolved for r in rows)
        assert all(r.cross_root_kind is None for r in rows)


class TestIngestJsWorkspaceBoundary:
    """Phase E2.2's exact synthetic fixture (nested tsconfig, overlapping
    aliases, index-vs-file ambiguity, package.json workspaces), this time
    driven through the real ingest_repo pipeline end to end, plus one
    relative cross-package import to exercise cross_root_kind."""

    def _make_repo(self, tmp_path) -> Path:
        root = tmp_path / "repo"
        _write(root / "package.json", '{"workspaces": ["packages/*"]}')
        _write(root / "tsconfig.json", '{"compilerOptions": {"baseUrl": ".", "paths": {"@/*": ["./src/*"]}}}')
        _write(root / "src" / "utils.ts", "export const util = 1;\n")
        _write(root / "src" / "components" / "button.ts", "export const Button = 1;\n")
        _write(
            root / "src" / "main.ts",
            'import { Button } from "@/components/button";\n'
            'import { Widget } from "../packages/ui/src/widget";\n',
        )

        _write(root / "packages" / "ui" / "package.json", '{"name": "ui"}')
        _write(
            root / "packages" / "ui" / "tsconfig.json",
            '{"compilerOptions": {"baseUrl": ".", "paths": '
            '{"@ui/*": ["./src/*"], "@ui/components/*": ["./src/components/*"]}}}',
        )
        _write(root / "packages" / "ui" / "src" / "widget.ts", "export const Widget = 1;\n")
        _write(root / "packages" / "ui" / "src" / "components" / "icon.ts", "export const Icon = 1;\n")
        _write(
            root / "packages" / "ui" / "src" / "main.ts",
            'import { Icon } from "@ui/components/icon";\n',
        )
        return root

    def test_root_config_alias_resolves(self, db_session, tmp_path):
        root = self._make_repo(tmp_path)
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)

        files = {f.path: f for f in db_session.query(CodeFile).filter(CodeFile.repo_id == repo.id).all()}
        row = db_session.query(CodeImport).filter(
            CodeImport.from_file_id == files["src/main.ts"].id, CodeImport.raw_specifier == "@/components/button"
        ).one()
        assert row.resolved is True
        assert row.to_file_id == files["src/components/button.ts"].id

    def test_nested_config_longest_prefix_alias_resolves(self, db_session, tmp_path):
        root = self._make_repo(tmp_path)
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)

        files = {f.path: f for f in db_session.query(CodeFile).filter(CodeFile.repo_id == repo.id).all()}
        row = db_session.query(CodeImport).filter(CodeImport.from_file_id == files["packages/ui/src/main.ts"].id).one()
        assert row.resolved is True
        assert row.to_file_id == files["packages/ui/src/components/icon.ts"].id
        assert row.cross_root_kind is None  # resolved inside its own workspace

    def test_relative_import_reaching_into_a_workspace_is_flagged(self, db_session, tmp_path):
        root = self._make_repo(tmp_path)
        repo = register_from_path(db_session, str(root))
        report = ingest_repo(db_session, repo)

        files = {f.path: f for f in db_session.query(CodeFile).filter(CodeFile.repo_id == repo.id).all()}
        row = db_session.query(CodeImport).filter(
            CodeImport.from_file_id == files["src/main.ts"].id,
            CodeImport.raw_specifier == "../packages/ui/src/widget",
        ).one()
        assert row.resolved is True
        assert row.to_file_id == files["packages/ui/src/widget.ts"].id
        assert row.cross_root_kind == "workspace_boundary"
        assert report.js_cross_root_edges == 1
        assert report.js_configs_found == 2


class TestIngestHoldsRepoLock:
    """Phase E2.3 incident follow-up: ingest_repo must refuse to run
    concurrently with another ingest/rank for the SAME repo -- see
    repo_lock.py."""

    def test_ingest_refuses_while_repo_lock_already_held(self, db_session, tmp_path):
        root = tmp_path / "repo"
        _write(root / "a.py", "def foo():\n    return 1\n")
        repo = register_from_path(db_session, str(root))

        with repo_lock(repo.id, "test"):
            with pytest.raises(RepoBusyError):
                ingest_repo(db_session, repo)

    def test_ingest_releases_lock_after_completing(self, db_session, tmp_path):
        root = tmp_path / "repo"
        _write(root / "a.py", "def foo():\n    return 1\n")
        repo = register_from_path(db_session, str(root))

        ingest_repo(db_session, repo)
        with repo_lock(repo.id, "test"):  # must succeed -- ingest released its own lock
            pass


class TestIngestFileCap:
    def test_refuses_above_cap(self, db_session, tmp_path, monkeypatch):
        from app.core.config import settings

        root = tmp_path / "repo"
        for i in range(5):
            _write(root / f"f{i}.py", "x = 1\n")
        repo = register_from_path(db_session, str(root))

        monkeypatch.setattr(settings, "REPO_MAX_FILES", 3)
        with pytest.raises(TooManyFilesError):
            ingest_repo(db_session, repo)


class TestIngestCloneCacheExclusion:
    def test_clone_cache_never_ingested_even_with_no_gitignore_at_all(self, db_session, tmp_path, monkeypatch):
        # Regression test for a real cross-repo contamination risk: a `local`
        # repo (which may not be a git repo at all, and here deliberately has
        # NO .gitignore) whose root happens to contain the clone cache
        # directory -- exactly the shape of this project's own dev setup
        # before the clone cache was relocated outside any analysable tree.
        # This must be excluded independent of .gitignore, not merely by luck.
        root = tmp_path / "monorepo"
        _write(root / "app" / "main.py", "def foo():\n    return 1\n")
        fake_cache = root / "backend" / "data" / "repos" / "github.com" / "someone" / "other-project"
        _write(fake_cache / "leaked.py", "def should_not_be_ingested():\n    pass\n")

        monkeypatch.setattr("app.services.codebase.registry.clone_cache_root", lambda: root / "backend" / "data" / "repos")

        repo = register_from_path(db_session, str(root))
        report = ingest_repo(db_session, repo)

        assert report.files_total == 1
        paths = {f.path for f in db_session.query(CodeFile).filter(CodeFile.repo_id == repo.id).all()}
        assert paths == {"app/main.py"}
        assert not any("leaked" in p for p in paths)


class TestDefaultCloneRootLocation:
    def test_app_data_root_is_outside_backend_dir(self):
        # Regression test: the app-data root must never resolve inside
        # BACKEND_DIR again -- that was the root condition that made
        # cross-repo contamination possible in the first place, saved only
        # by an incidental .gitignore entry.
        from app.core.config import APP_DATA_ROOT, BACKEND_DIR

        resolved = APP_DATA_ROOT.resolve()
        assert resolved.is_absolute()
        assert BACKEND_DIR.resolve() not in resolved.parents and resolved != BACKEND_DIR.resolve()

    def test_clone_resources_qdrant_defaults_all_live_under_app_data_root(self):
        from app.core.config import APP_DATA_ROOT, settings

        assert Path(settings.REPO_CLONE_ROOT).resolve() == (APP_DATA_ROOT / "repos").resolve()
        assert Path(settings.RESOURCES_DIR).resolve() == (APP_DATA_ROOT / "resources").resolve()
        assert Path(settings.QDRANT_PATH).resolve() == (APP_DATA_ROOT / "qdrant_data").resolve()


class TestIngestEdgeKindClassification:
    def test_two_bindings_of_the_same_module_get_independently_correct_kinds(self, db_session, tmp_path):
        # `Base` is referenced in the class bases list; `B2` (a second,
        # differently-aliased import of the exact same name) is never
        # referenced at all. Each row must be classified independently and
        # correctly by its OWN local name, not conflated with the other.
        root = tmp_path / "repo"
        _write(root / "base.py", "class Base:\n    pass\n")
        _write(
            root / "consumer.py",
            "from base import Base\n"
            "from base import Base as B2\n"
            "\n\n"
            "class Child(Base):\n"
            "    pass\n",
        )
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)

        consumer = db_session.query(CodeFile).filter(CodeFile.repo_id == repo.id, CodeFile.path == "consumer.py").one()
        rows = db_session.query(CodeImport).filter(CodeImport.from_file_id == consumer.id).all()
        by_line = {r.line_number: r.kind for r in rows}
        assert by_line[1] == "inherits"   # `from base import Base` -- Base appears in Child(Base)
        assert by_line[2] == "type_only"  # `from base import Base as B2` -- B2 never appears in the body

    def test_test_file_edges_classified_as_test_edge(self, db_session, tmp_path):
        root = tmp_path / "repo"
        _write(root / "app" / "helper.py", "def do_thing():\n    return 1\n")
        _write(
            root / "tests" / "test_helper.py",
            "from app.helper import do_thing\n\n\ndef test_it():\n    assert do_thing() == 1\n",
        )
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)

        test_file = db_session.query(CodeFile).filter(CodeFile.repo_id == repo.id, CodeFile.path == "tests/test_helper.py").one()
        row = db_session.query(CodeImport).filter(CodeImport.from_file_id == test_file.id).one()
        assert row.kind == "test_edge"

    def test_wildcard_import_classified_as_unresolvable_binding(self, db_session, tmp_path):
        root = tmp_path / "repo"
        _write(root / "pkg" / "__init__.py", "")
        _write(root / "pkg" / "things.py", "THING = 1\n")
        _write(root / "main.py", "from pkg.things import *\nprint(THING)\n")
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)

        main_file = db_session.query(CodeFile).filter(CodeFile.repo_id == repo.id, CodeFile.path == "main.py").one()
        row = db_session.query(CodeImport).filter(CodeImport.from_file_id == main_file.id).one()
        assert row.kind == "unresolvable_binding"

    def test_reexport_classified_regardless_of_body_usage(self, db_session, tmp_path):
        root = tmp_path / "repo"
        _write(root / "src" / "inner.ts", "export function helper(): number { return 1; }\n")
        _write(root / "src" / "barrel.ts", 'export { helper } from "./inner";\n')
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)

        barrel = db_session.query(CodeFile).filter(CodeFile.repo_id == repo.id, CodeFile.path == "src/barrel.ts").one()
        row = db_session.query(CodeImport).filter(CodeImport.from_file_id == barrel.id).one()
        assert row.kind == "reexport"

    def test_aliased_import_occurrence_counted_under_the_alias_not_the_original(self, db_session, tmp_path):
        # The regression this whole extension exists to prevent: `import
        # numpy as np` with heavy `np.` usage must NOT be misclassified as
        # barely-used just because "numpy" itself never appears in the body.
        root = tmp_path / "repo"
        _write(
            root / "main.py",
            "import numpy as np\n"
            "a = np.array([1])\n"
            "b = np.array([2])\n"
            "c = np.array([3])\n"
            "d = np.array([4])\n"
            "e = np.array([5])\n",
        )
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)

        main_file = db_session.query(CodeFile).filter(CodeFile.repo_id == repo.id, CodeFile.path == "main.py").one()
        row = db_session.query(CodeImport).filter(CodeImport.from_file_id == main_file.id).one()
        assert row.kind == "heavy_use"  # would be "type_only" if the alias were discarded, per the bug this fixes


class TestIngestNodePriorClassification:
    def test_prior_category_and_source_persisted_on_real_rows(self, db_session, tmp_path):
        root = tmp_path / "repo"
        _write(root / "app" / "logic.py", "def do_thing():\n    return 1\n")  # plain source
        _write(root / "app" / "tailwind.config.js", "module.exports = {};\n")  # config pattern
        _write(root / "backend" / "alembic" / "versions" / "abc_add_thing.py", "def upgrade():\n    pass\n")  # migration
        _write(root / "gen" / "thing_pb2.py", "")  # generated (filename suffix)
        _write(root / "pkg" / "__init__.py", '"""Just a package marker."""\n')  # barrel (trivial init)
        repo = register_from_path(db_session, str(root))
        ingest_repo(db_session, repo)

        files = {f.path: f for f in db_session.query(CodeFile).filter(CodeFile.repo_id == repo.id).all()}

        assert (files["app/logic.py"].prior_category, files["app/logic.py"].prior_source) == ("source", "graph")
        assert (files["app/tailwind.config.js"].prior_category, files["app/tailwind.config.js"].prior_source) == ("config", "pattern")
        assert (files["backend/alembic/versions/abc_add_thing.py"].prior_category,
                files["backend/alembic/versions/abc_add_thing.py"].prior_source) == ("migration", "pattern")
        assert (files["gen/thing_pb2.py"].prior_category, files["gen/thing_pb2.py"].prior_source) == ("generated", "pattern")
        assert (files["pkg/__init__.py"].prior_category, files["pkg/__init__.py"].prior_source) == ("barrel", "structural")
