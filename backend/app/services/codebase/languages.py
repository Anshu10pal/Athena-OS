"""tree-sitter parser setup, one per supported language.

Uses the per-language packages (tree-sitter-python/javascript/typescript), not
tree-sitter-languages -- that package is compiled against an old tree-sitter
ABI and raises TypeError on parser construction against tree-sitter>=0.22.
"""
from pathlib import Path
from typing import Optional

import tree_sitter_javascript
import tree_sitter_python
import tree_sitter_typescript
from tree_sitter import Language, Parser

EXTENSION_LANGUAGE = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript",
    ".jsx": "javascript",
}

_PARSERS: dict[str, Parser] = {
    "python": Parser(Language(tree_sitter_python.language())),
    "javascript": Parser(Language(tree_sitter_javascript.language())),
    "typescript": Parser(Language(tree_sitter_typescript.language_typescript())),
    "tsx": Parser(Language(tree_sitter_typescript.language_tsx())),
}


def language_for_path(path: Path) -> Optional[str]:
    return EXTENSION_LANGUAGE.get(path.suffix.lower())


def parser_for_language(language: str) -> Parser:
    return _PARSERS[language]
