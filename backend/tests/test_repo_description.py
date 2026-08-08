"""Phase K1: repo self-description extraction.

Pure string tests -- the parsing half never touches a filesystem, so it is
tested with literals. The thin filesystem half (extract_description) gets a
few tmp_path tests for precedence, which is the only behaviour that needs
real files to be meaningful.
"""
from app.services.codebase.repo_description import (
    MAX_DESCRIPTION_CHARS,
    description_from_package_json,
    description_from_pyproject,
    description_from_readme,
    description_from_setup_cfg,
    extract_description,
)


class TestPackageJson:
    def test_reads_the_description_field(self):
        assert description_from_package_json('{"description": "A fast linter."}') == "A fast linter."

    def test_none_for_missing_field(self):
        assert description_from_package_json('{"name": "x"}') is None

    def test_none_for_blank_description(self):
        assert description_from_package_json('{"description": "   "}') is None

    def test_none_for_malformed_json_rather_than_raising(self):
        # A broken package.json must fall through to the next source, not
        # take down the whole ingest.
        assert description_from_package_json("{not json") is None

    def test_none_for_json_that_is_not_an_object(self):
        assert description_from_package_json('["a", "b"]') is None


class TestPyproject:
    def test_reads_double_quoted_description(self):
        assert description_from_pyproject('[project]\ndescription = "Does a thing."\n') == "Does a thing."

    def test_reads_single_quoted_description(self):
        assert description_from_pyproject("[project]\ndescription = 'Does a thing.'\n") == "Does a thing."

    def test_none_when_absent(self):
        assert description_from_pyproject('[project]\nname = "x"\n') is None


class TestSetupCfg:
    def test_reads_unquoted_description(self):
        assert description_from_setup_cfg("[metadata]\ndescription = A small tool\n") == "A small tool"


class TestReadme:
    def test_skips_the_title_and_takes_the_first_prose_paragraph(self):
        readme = "# My Project\n\nThis project does a specific thing.\n\nMore detail here.\n"
        assert description_from_readme(readme) == "This project does a specific thing."

    def test_skips_badge_rows(self):
        readme = (
            "# Project\n\n"
            "[![build](https://img.shields.io/x)](https://ci.example)\n"
            "![coverage](https://img.shields.io/y)\n\n"
            "The actual description.\n"
        )
        assert description_from_readme(readme) == "The actual description."

    def test_skips_raw_html_blocks(self):
        readme = '<p align="center">\n<img src="logo.png">\n</p>\n\nReal text here.\n'
        assert description_from_readme(readme) == "Real text here."

    def test_joins_a_multi_line_paragraph(self):
        readme = "# T\n\nLine one\nline two.\n\nNext para.\n"
        assert description_from_readme(readme) == "Line one line two."

    def test_strips_markdown_links_and_emphasis_to_plain_text(self):
        readme = "# T\n\nA **fast** [linter](https://example.com) for `code`.\n"
        assert description_from_readme(readme) == "A fast linter for code."

    def test_decodes_html_entities_rather_than_showing_them_literally(self):
        # Real READMEs use &nbsp;/&amp; freely; showing them raw on the
        # overview page would look like a rendering bug.
        readme = "# T\n\nBatch: X &nbsp;|&nbsp; Tools &amp; Systems.\n"
        assert description_from_readme(readme) == "Batch: X | Tools & Systems."

    def test_none_when_there_is_no_prose_at_all(self):
        assert description_from_readme("# Only A Title\n\n- a list item\n- another\n") is None

    def test_truncates_a_very_long_paragraph_at_a_word_boundary(self):
        readme = "# T\n\n" + ("word " * 400) + "\n"
        result = description_from_readme(readme)
        assert result is not None
        assert len(result) <= MAX_DESCRIPTION_CHARS + 1  # +1 for the ellipsis
        assert result.endswith("…")


class TestExtractDescriptionPrecedence:
    def test_prefers_package_json(self, tmp_path):
        (tmp_path / "package.json").write_text('{"description": "From package.json"}')
        (tmp_path / "README.md").write_text("# T\n\nFrom the readme.\n")
        assert extract_description(tmp_path) == ("From package.json", "package.json")

    def test_falls_back_to_readme_when_packaging_metadata_has_no_description(self, tmp_path):
        (tmp_path / "package.json").write_text('{"name": "x"}')
        (tmp_path / "README.md").write_text("# T\n\nFrom the readme.\n")
        assert extract_description(tmp_path) == ("From the readme.", "README")

    def test_falls_back_to_pyproject_before_readme(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text('[project]\ndescription = "From pyproject"\n')
        (tmp_path / "README.md").write_text("# T\n\nFrom the readme.\n")
        assert extract_description(tmp_path) == ("From pyproject", "pyproject.toml")

    def test_returns_none_none_for_a_repo_that_says_nothing_about_itself(self, tmp_path):
        # A legitimate outcome, not an error -- the UI says "no description
        # found" rather than synthesising one.
        (tmp_path / "main.py").write_text("print('hi')\n")
        assert extract_description(tmp_path) == (None, None)

    def test_does_not_recurse_into_subdirectories(self, tmp_path):
        # A description found in a vendored subpackage would describe that
        # dependency, not this repo.
        nested = tmp_path / "vendor" / "somelib"
        nested.mkdir(parents=True)
        (nested / "package.json").write_text('{"description": "Some vendored library"}')
        assert extract_description(tmp_path) == (None, None)
