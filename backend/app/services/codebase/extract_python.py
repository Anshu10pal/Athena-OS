"""Python symbol + import extraction, built against the grammar node shapes
verified directly against tree-sitter-python (see Phase B report): imports
via import_statement/import_from_statement/relative_import/wildcard_import,
symbols via function_definition/class_definition with nested
function_definitions inside a class's block captured as methods, docstrings
as the first expression_statement>string child of a block.
"""
from dataclasses import dataclass, field
from typing import Optional

from app.services.codebase.languages import parser_for_language


@dataclass
class RawSymbol:
    name: str
    kind: str  # function|class|method
    signature: str
    docstring: Optional[str]
    line_start: int  # 1-indexed, inclusive
    line_end: int  # 1-indexed, inclusive
    parent_name: Optional[str] = None


@dataclass
class RawImport:
    raw_specifier: str
    imported_names: list = field(default_factory=list)  # original/exported names -- used for resolution, unchanged behavior
    # Parallel to imported_names (same index = same import); the identifier
    # actually bound in THIS file's own body -- equal to imported_names[i]
    # unless aliased (`as`), in which case it's the alias. For a bare/whole-
    # module import (imported_names == []), this has exactly one entry: the
    # single local name the import statement introduces. None where there's
    # no trackable local binding at all (wildcard imports) -- Phase F1's
    # edge-weight classifier reads this for occurrence counting; resolution
    # (Phase B) never uses it.
    local_names: list = field(default_factory=list)
    line_number: int = 0
    is_reexport: bool = False  # never true for Python -- no `export ... from` equivalent


def _text(node, src: bytes) -> str:
    return src[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _docstring_of(block_node, src: bytes) -> Optional[str]:
    if block_node is None:
        return None
    for child in block_node.children:
        if child.type != "expression_statement":
            break  # first statement isn't a bare expression -- no docstring
        for gc in child.children:
            if gc.type == "string":
                return _strip_string_quotes(_text(gc, src))
        break
    return None


def _strip_string_quotes(text: str) -> str:
    text = text.strip()
    for quote in ('"""', "'''", '"', "'"):
        if text.startswith(quote) and text.endswith(quote) and len(text) >= 2 * len(quote):
            return text[len(quote):-len(quote)].strip()
    return text


def _relative_import_specifier(node, src: bytes) -> str:
    dots, module = "", ""
    for child in node.children:
        if child.type == "import_prefix":
            dots = _text(child, src)
        elif child.type == "dotted_name":
            module = _text(child, src)
    return dots + module


def _names_and_locals_from_import_from(node, src: bytes) -> tuple:
    """(imported_names, local_names), parallel lists. A wildcard contributes
    ("*", None) -- no local binding is introduced by name, so nothing to
    occurrence-count; the edge classifier treats original_name == "*" as its
    own unresolvable_binding case regardless of local_names."""
    names, locals_ = [], []
    past_import_kw = False
    for child in node.children:
        if child.type == "import":
            past_import_kw = True
            continue
        if not past_import_kw:
            continue
        if child.type == "dotted_name":
            text = _text(child, src)
            names.append(text)
            locals_.append(text)
        elif child.type == "aliased_import":
            original, alias = None, None
            for gc in child.children:
                if gc.type == "dotted_name" and original is None:
                    original = _text(gc, src)
                elif gc.type == "identifier":
                    alias = _text(gc, src)
            if original is not None:
                names.append(original)
                locals_.append(alias or original)
        elif child.type == "wildcard_import":
            names.append("*")
            locals_.append(None)
    return names, locals_


def _function_signature(node, src: bytes) -> str:
    name, params, ret = "", "", None
    for child in node.children:
        if child.type == "identifier" and not name:
            name = _text(child, src)
        elif child.type == "parameters":
            params = _text(child, src)
        elif child.type == "type":
            ret = _text(child, src)
    sig = f"def {name}{params}"
    if ret:
        sig += f" -> {ret}"
    return sig


def _extract_symbols(root, src: bytes, parent_name: Optional[str] = None) -> list:
    symbols = []
    for node in root.children:
        if node.type == "function_definition":
            name_node = next((c for c in node.children if c.type == "identifier"), None)
            block_node = next((c for c in node.children if c.type == "block"), None)
            symbols.append(RawSymbol(
                name=_text(name_node, src) if name_node else "",
                kind="method" if parent_name else "function",
                signature=_function_signature(node, src),
                docstring=_docstring_of(block_node, src),
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                parent_name=parent_name,
            ))
        elif node.type == "class_definition":
            name_node = next((c for c in node.children if c.type == "identifier"), None)
            block_node = next((c for c in node.children if c.type == "block"), None)
            class_name = _text(name_node, src) if name_node else ""
            symbols.append(RawSymbol(
                name=class_name,
                kind="class",
                signature=f"class {class_name}",
                docstring=_docstring_of(block_node, src),
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                parent_name=parent_name,
            ))
            if block_node is not None:
                symbols.extend(_extract_symbols(block_node, src, parent_name=class_name))
    return symbols


def _extract_imports(root, src: bytes) -> list:
    imports = []

    def walk(node):
        if node.type == "import_statement":
            for child in node.children:
                if child.type == "dotted_name":
                    text = _text(child, src)
                    local = text.split(".")[0]  # `import a.b.c` binds the name `a`, not `a.b.c`
                    imports.append(RawImport(text, [], [local], child.start_point[0] + 1))
                elif child.type == "aliased_import":
                    original, alias = None, None
                    for gc in child.children:
                        if gc.type == "dotted_name" and original is None:
                            original = _text(gc, src)
                        elif gc.type == "identifier":
                            alias = _text(gc, src)
                    if original is not None:
                        local = alias or original.split(".")[0]
                        imports.append(RawImport(original, [], [local], node.start_point[0] + 1))
        elif node.type == "import_from_statement":
            module_node = next((c for c in node.children if c.type in ("relative_import", "dotted_name")), None)
            if module_node is not None:
                spec = _relative_import_specifier(module_node, src) if module_node.type == "relative_import" else _text(module_node, src)
                names, locals_ = _names_and_locals_from_import_from(node, src)
                imports.append(RawImport(spec, names, locals_, node.start_point[0] + 1))
        for child in node.children:
            walk(child)

    walk(root)
    return imports


def extract(source_bytes: bytes) -> tuple:
    """Returns (symbols: list[RawSymbol], imports: list[RawImport])."""
    parser = parser_for_language("python")
    tree = parser.parse(source_bytes)
    root = tree.root_node
    return _extract_symbols(root, source_bytes), _extract_imports(root, source_bytes)
