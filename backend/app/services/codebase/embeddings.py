"""Phase I6: per-file text embeddings for HDBSCAN clustering (subsystems.py).

Deliberately embeds symbol signatures + docstrings, not full file content --
this is meant to answer "what does this file's code SAY it does," a
different question than modularity/Louvain's import-graph coupling. Full
file content would mostly re-encode import lines and formatting, the same
signal the graph algorithms already use; embedding what CodeSymbol already
extracted at parse time (name/kind/signature/docstring, Phase B) is both a
better-targeted signal and free of new parsing work.

Uses FastEmbed directly (the `fastembed` package, not qdrant_client's
add()/query() wrapper) -- the app's existing vector_store.py wraps FastEmbed
behind Qdrant because it needs similarity SEARCH; HDBSCAN needs the raw
vector matrix for every file at once, which is what TextEmbedding.embed()
returns without the indirection of writing to and reading back from a
Qdrant collection. Same model as vector_store.py (BAAI/bge-small-en-v1.5) on
purpose -- it's already downloaded and cached locally from the roadmap
module-search feature, so this feature doesn't trigger a second ~80MB
download for a different model.

Entirely local: ONNX runtime, CPU-only, no torch, no network egress, no API
key, no data leaving this machine. This directly replaces an earlier design
that would have sent code to a hosted embeddings API behind an explicit
user-confirmation gate -- with FastEmbed there is nothing to confirm, since
nothing is sent anywhere.
"""
from typing import Optional

import numpy as np
from fastembed import TextEmbedding

from app.core.config import MODELS_DIR, MODELS_OFFLINE
from app.db.models import CodeSymbol

EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"

_model: Optional[TextEmbedding] = None


def _get_model() -> TextEmbedding:
    global _model
    if _model is None:
        # Same project-relative cache as vector_store.py, and passed for the
        # same reason: FastEmbed reads no env var for it. Two call sites, one
        # cache directory -- the alternative is two copies of an 80 MB model in
        # two locations, neither of which survives a Render restart.
        _model = TextEmbedding(model_name=EMBEDDING_MODEL,
                               cache_dir=str(MODELS_DIR / "fastembed"),
                               local_files_only=MODELS_OFFLINE)
    return _model


def build_file_embedding_text(path: str, symbols: list) -> str:
    """One embedding-ready text blob per file. Always includes the file's
    own path (so a file with zero extracted symbols -- a config file, an
    empty __init__.py -- still gets a non-empty, comparable text rather
    than being silently skipped from clustering); each symbol contributes
    its kind, name, signature, and docstring when present."""
    parts = [path]
    for sym in symbols:
        line = f"{sym.kind} {sym.name}{sym.signature}"
        if sym.docstring:
            line += f" -- {sym.docstring.strip()}"
        parts.append(line)
    return "\n".join(parts)


def embed_texts(texts: list) -> np.ndarray:
    """Raw embedding vectors, one row per input text, same order. First
    call in a process may download the model (~80MB) if it isn't already
    cached from vector_store.py's prior use."""
    return np.array(list(_get_model().embed(texts)))
