"""Phase I6: pure text-building tests for the HDBSCAN embedding input.

embed_texts itself (real FastEmbed/ONNX model, CPU inference) is
deliberately NOT unit-tested here -- same reasoning as this project never
hitting a real LLM in a fast test, it would make the suite depend on a
model download and a real inference pass. subsystems.py's HDBSCAN
integration tests monkeypatch embed_texts instead (see test_subsystems.py).
"""
from app.db.models import CodeSymbol
from app.services.codebase.embeddings import build_file_embedding_text


def _symbol(**kwargs) -> CodeSymbol:
    defaults = dict(
        file_id=1, name="f", kind="function", signature="()",
        docstring=None, line_start=1, line_end=2,
    )
    defaults.update(kwargs)
    return CodeSymbol(**defaults)


class TestBuildFileEmbeddingText:
    def test_path_only_when_no_symbols(self):
        # A config file or an empty __init__.py still needs a non-empty,
        # comparable text -- silently skipping it from clustering would
        # mean HDBSCAN's file coverage is a strict subset of modularity/
        # Louvain's, which report every file (unclustered or not).
        text = build_file_embedding_text("app/api/repos.py", [])
        assert text == "app/api/repos.py"

    def test_includes_kind_name_signature(self):
        sym = _symbol(name="rank_repo", kind="function", signature="(db, repo)")
        text = build_file_embedding_text("app/services/ranking.py", [sym])
        lines = text.split("\n")
        assert lines[0] == "app/services/ranking.py"
        assert lines[1] == "function rank_repo(db, repo)"

    def test_includes_stripped_docstring_when_present(self):
        sym = _symbol(name="f", signature="()", docstring="  Does a thing.  ")
        text = build_file_embedding_text("a.py", [sym])
        assert "Does a thing." in text
        assert "  Does a thing.  " not in text

    def test_omits_docstring_separator_when_none(self):
        sym = _symbol(name="f", signature="()", docstring=None)
        text = build_file_embedding_text("a.py", [sym])
        assert "--" not in text.split("\n")[1]

    def test_multiple_symbols_each_get_their_own_line(self):
        syms = [_symbol(name="a", signature="()"), _symbol(name="b", signature="(x)")]
        text = build_file_embedding_text("a.py", syms)
        lines = text.split("\n")
        assert len(lines) == 3  # path + 2 symbols
        assert lines[1] == "function a()"
        assert lines[2] == "function b(x)"
