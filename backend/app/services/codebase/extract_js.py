"""TypeScript/TSX/JavaScript symbol + import extraction, built against grammar
node shapes verified directly against tree-sitter-typescript/-javascript.

Known, deliberate gap: dynamic `import(...)` is never extracted as an edge,
even when the argument is a literal string -- its callee is an `import` node,
not an `identifier`, so the require() check below simply never matches it.
This keeps "resolved" a crisp, honest concept rather than a partial one.

Class name and default-import local-name nodes differ between grammars: plain
JavaScript uses `identifier` where TypeScript/TSX use `type_identifier` for a
class name -- both are checked directly (verified empirically, not assumed).
"""
from dataclasses import dataclass, field
from typing import Optional

from app.services.codebase.languages import parser_for_language

CLASS_NAME_TYPES = ("type_identifier", "identifier")


@dataclass
class RawSymbol:
    name: str
    kind: str  # function|class|method
    signature: str
    docstring: Optional[str]
    line_start: int
    line_end: int
    parent_name: Optional[str] = None


@dataclass
class RawImport:
    raw_specifier: str
    imported_names: list = field(default_factory=list)  # original/exported names -- used for resolution, unchanged behavior
    # Parallel to imported_names: the identifier actually bound in THIS
    # file's own body. Equal to imported_names[i] unless aliased (`as`), in
    # which case it's the alias; for a default import the entry is the real
    # local identifier (imported_names keeps the "default" sentinel for
    # resolution). None where there's no trackable local binding at all
    # (namespace/wildcard re-exports, bare require()). Phase F1's edge-weight
    # classifier reads this for occurrence counting; resolution never does.
    local_names: list = field(default_factory=list)
    line_number: int = 0
    is_reexport: bool = False  # `export ... from "..."` -- forwarded, not used in this file's own body


def _text(node, src: bytes) -> str:
    return src[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _string_literal_text(string_node, src: bytes) -> Optional[str]:
    fragments = [c for c in string_node.children if c.type == "string_fragment"]
    if not fragments:
        return None
    return "".join(_text(c, src) for c in fragments)


def _param_and_return(node, src: bytes) -> tuple:
    params, ret = "", None
    for child in node.children:
        if child.type == "formal_parameters":
            params = _text(child, src)
        elif child.type == "type_annotation":
            ret = _text(child, src).lstrip(":").strip()
    return params, ret


# ---------------- symbols ----------------


def _extract_symbols(root, src: bytes) -> list:
    symbols = []

    def handle(node):
        if node.type == "export_statement":
            for child in node.children:
                if child.type in ("function_declaration", "class_declaration", "lexical_declaration"):
                    handle(child)
            return

        if node.type == "function_declaration":
            name_node = next((c for c in node.children if c.type == "identifier"), None)
            name = _text(name_node, src) if name_node else ""
            params, ret = _param_and_return(node, src)
            sig = f"function {name}{params}" + (f": {ret}" if ret else "")
            symbols.append(RawSymbol(name, "function", sig, None, node.start_point[0] + 1, node.end_point[0] + 1))

        elif node.type == "class_declaration":
            name_node = next((c for c in node.children if c.type in CLASS_NAME_TYPES), None)
            class_name = _text(name_node, src) if name_node else ""
            symbols.append(RawSymbol(class_name, "class", f"class {class_name}", None,
                                      node.start_point[0] + 1, node.end_point[0] + 1))
            body = next((c for c in node.children if c.type == "class_body"), None)
            if body is not None:
                for member in body.children:
                    if member.type == "method_definition":
                        mname_node = next((c for c in member.children if c.type == "property_identifier"), None)
                        mname = _text(mname_node, src) if mname_node else ""
                        params, ret = _param_and_return(member, src)
                        sig = f"{mname}{params}" + (f": {ret}" if ret else "")
                        symbols.append(RawSymbol(mname, "method", sig, None,
                                                  member.start_point[0] + 1, member.end_point[0] + 1,
                                                  parent_name=class_name))

        elif node.type == "lexical_declaration":
            for decl in node.children:
                if decl.type != "variable_declarator":
                    continue
                ident_node = next((c for c in decl.children if c.type == "identifier"), None)
                arrow_node = next((c for c in decl.children if c.type == "arrow_function"), None)
                if ident_node is not None and arrow_node is not None:
                    name = _text(ident_node, src)
                    params, ret = _param_and_return(arrow_node, src)
                    sig = f"const {name} = {params}" + (f": {ret}" if ret else "") + " =>"
                    symbols.append(RawSymbol(name, "function", sig, None,
                                              node.start_point[0] + 1, node.end_point[0] + 1))

    for top_level in root.children:
        handle(top_level)
    return symbols


# ---------------- imports ----------------


def _names_and_locals_from_import_clause(clause, src: bytes) -> tuple:
    """(imported_names, local_names), parallel lists."""
    names, locals_ = [], []
    for c in clause.children:
        if c.type == "identifier":
            names.append("default")
            locals_.append(_text(c, src))
        elif c.type == "named_imports":
            for spec in c.children:
                if spec.type == "import_specifier":
                    idents = [g for g in spec.children if g.type == "identifier"]
                    if idents:
                        original = _text(idents[0], src)
                        local = _text(idents[1], src) if len(idents) > 1 else original
                        names.append(original)
                        locals_.append(local)
        elif c.type == "namespace_import":
            ident = next((g for g in c.children if g.type == "identifier"), None)
            names.append("*")
            locals_.append(_text(ident, src) if ident else None)
    return names, locals_


def _extract_imports(root, src: bytes) -> list:
    imports = []

    def handle(node):
        if node.type == "import_statement":
            string_node = next((c for c in node.children if c.type == "string"), None)
            if string_node is not None:
                spec = _string_literal_text(string_node, src) or ""
                clause = next((c for c in node.children if c.type == "import_clause"), None)
                names, locals_ = _names_and_locals_from_import_clause(clause, src) if clause is not None else ([], [])
                imports.append(RawImport(spec, names, locals_, node.start_point[0] + 1))

        elif node.type == "export_statement":
            string_node = next((c for c in node.children if c.type == "string"), None)
            if string_node is not None:
                spec = _string_literal_text(string_node, src) or ""
                export_clause = next((c for c in node.children if c.type == "export_clause"), None)
                namespace_export = next((c for c in node.children if c.type == "namespace_export"), None)
                if export_clause is not None:
                    names = []
                    for spec_node in export_clause.children:
                        if spec_node.type == "export_specifier":
                            idents = [g for g in spec_node.children if g.type == "identifier"]
                            if idents:
                                names.append(_text(idents[0], src))
                elif namespace_export is not None:
                    names = ["*"]
                else:
                    names = ["*"]  # bare `export * from "..."`
                # A re-export is forwarded, never used in this file's own body --
                # no local binding applies, regardless of what names/locals a
                # non-reexport import of the same shape would have.
                imports.append(RawImport(spec, names, [None] * len(names), node.start_point[0] + 1, is_reexport=True))

        elif node.type == "call_expression":
            children = node.children
            callee = children[0] if children else None
            if callee is not None and callee.type == "identifier" and _text(callee, src) == "require":
                args = next((c for c in children if c.type == "arguments"), None)
                if args is not None:
                    str_node = next((c for c in args.children if c.type == "string"), None)
                    if str_node is not None:
                        spec = _string_literal_text(str_node, src) or ""
                        # No local binding captured (e.g. `const mod = require(...)`
                        # isn't traced back to `mod`) -- unresolvable_binding at
                        # classification time, same as a wildcard import.
                        imports.append(RawImport(spec, [], [], node.start_point[0] + 1))

        for child in node.children:
            handle(child)

    handle(root)
    return imports


def extract(source_bytes: bytes, language: str) -> tuple:
    """Returns (symbols: list[RawSymbol], imports: list[RawImport])."""
    parser = parser_for_language(language)
    tree = parser.parse(source_bytes)
    root = tree.root_node
    return _extract_symbols(root, source_bytes), _extract_imports(root, source_bytes)
