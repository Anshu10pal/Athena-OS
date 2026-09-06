"""Phase K1: a short description of what a repo IS, for the overview page.

Extracted from the repo's OWN metadata, in a fixed precedence order, and
never invented: packaging metadata first (it is written to be a one-line
description, which is exactly what this needs), then the README's first
real paragraph as a fallback. Zero LLM calls, consistent with this
feature's standing non-negotiable -- no summarisation, no rewriting, just
quoting what the repo already says about itself.

Returning None is a legitimate, expected result. A repo with no packaging
metadata and no README genuinely has no self-description, and the honest
UI response is to say so rather than to synthesise a sentence from file
counts and present it as if the maintainers had written it.

Split into a pure text-parsing half (testable with string literals) and a
thin filesystem half, the same split as every other module here.
"""
import html
import json
import re
from pathlib import Path
from typing import Optional, Tuple

# Ordered by how likely the text is to be a real, intentional one-line
# description of the project. Packaging metadata wins over README prose
# because it was written to BE a description; a README's opening paragraph
# is a reasonable fallback but is often a badge wall or a tagline fragment.
DESCRIPTION_SOURCES = ("package.json", "pyproject.toml", "setup.cfg", "README")

MAX_DESCRIPTION_CHARS = 400

# Lines that are never prose: markdown headings, badge/image lines, HTML,
# blockquotes, list bullets, code fences, and link-reference definitions.
_SKIP_LINE = re.compile(
    r"""^\s*(
        \#             |   # heading
        <              |   # raw HTML (badge tables, <p align=center>, ...)
        \[!\[          |   # linked badge
        !\[            |   # bare image/badge
        >              |   # blockquote
        [-*+]\s        |   # list bullet
        \d+\.\s        |   # ordered list
        ```            |   # code fence
        \[[^\]]+\]:        # link reference definition
    )""",
    re.VERBOSE,
)

_MD_INLINE = re.compile(r"\[([^\]]+)\]\([^)]*\)")  # [text](url) -> text
_MD_EMPHASIS = re.compile(r"[*_`]{1,3}")


def _clean(text: str) -> str:
    # READMEs routinely contain HTML entities (&nbsp;, &amp;, &mdash;) that
    # would otherwise render literally on the overview page. unescape turns
    # &nbsp; into U+00A0, which str.split() treats as whitespace, so the
    # normalisation below collapses it away in the same pass.
    text = html.unescape(text)
    text = " ".join(text.split())
    if len(text) > MAX_DESCRIPTION_CHARS:
        # Cut at a word boundary rather than mid-word, and mark the cut so
        # a truncated sentence never reads as the author's own full stop.
        text = text[:MAX_DESCRIPTION_CHARS].rsplit(" ", 1)[0] + "…"
    return text.strip()


def description_from_package_json(content: str) -> Optional[str]:
    try:
        data = json.loads(content)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    value = data.get("description")
    if not isinstance(value, str) or not value.strip():
        return None
    return _clean(value)


def description_from_pyproject(content: str) -> Optional[str]:
    """Deliberately a narrow regex, not a TOML parser. Python 3.10 has no
    tomllib in the stdlib (that arrived in 3.11) and this backend pins
    3.10, so a real parse would mean a new dependency for one optional
    string on one page. `description = "..."` under [project] or
    [tool.poetry] is a stable, conventional shape; anything more exotic
    correctly falls through to the next source rather than being guessed
    at."""
    match = re.search(
        r'^\s*description\s*=\s*(["\'])(?P<value>.*?)\1',
        content,
        re.MULTILINE,
    )
    if not match:
        return None
    value = match.group("value").strip()
    return _clean(value) if value else None


def description_from_setup_cfg(content: str) -> Optional[str]:
    match = re.search(r"^\s*description\s*=\s*(?P<value>.+)$", content, re.MULTILINE)
    if not match:
        return None
    value = match.group("value").strip()
    return _clean(value) if value else None


def description_from_readme(content: str) -> Optional[str]:
    """The first paragraph that is actually prose -- skipping the title,
    badge rows, HTML blocks, and lists that open most READMEs. Paragraphs
    are blank-line separated; the first one whose lines all survive
    _SKIP_LINE wins."""
    paragraph: list = []
    for raw_line in content.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            if paragraph:
                break  # paragraph ended and it had content -- take it
            continue
        if _SKIP_LINE.match(line):
            # A skippable line INSIDE an otherwise-good paragraph ends it;
            # a skippable line before any content just gets stepped over.
            if paragraph:
                break
            continue
        paragraph.append(line.strip())

    if not paragraph:
        return None
    text = " ".join(paragraph)
    text = _MD_INLINE.sub(r"\1", text)
    text = _MD_EMPHASIS.sub("", text)
    cleaned = _clean(text)
    return cleaned or None


def _read(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeError):
        return None


def extract_description(repo_root: Path) -> Tuple[Optional[str], Optional[str]]:
    """Returns (description, source) -- source is one of
    DESCRIPTION_SOURCES, or (None, None) when the repo says nothing about
    itself. Searched at the repo root only, not recursively: a description
    found in some vendored subpackage's package.json would describe that
    dependency, not this repo.

    Note this takes the TRUE repo root, not a source_root-scoped path --
    packaging metadata and READMEs conventionally live at the real root,
    which is the same reasoning (and the same bug class) as
    entry_detection's config_search_root fix in Phase E4.
    """
    package_json = repo_root / "package.json"
    if package_json.is_file():
        content = _read(package_json)
        if content:
            value = description_from_package_json(content)
            if value:
                return value, "package.json"

    pyproject = repo_root / "pyproject.toml"
    if pyproject.is_file():
        content = _read(pyproject)
        if content:
            value = description_from_pyproject(content)
            if value:
                return value, "pyproject.toml"

    setup_cfg = repo_root / "setup.cfg"
    if setup_cfg.is_file():
        content = _read(setup_cfg)
        if content:
            value = description_from_setup_cfg(content)
            if value:
                return value, "setup.cfg"

    for name in ("README.md", "README.rst", "README.txt", "README"):
        readme = repo_root / name
        if readme.is_file():
            content = _read(readme)
            if content:
                value = description_from_readme(content)
                if value:
                    return value, "README"

    return None, None
