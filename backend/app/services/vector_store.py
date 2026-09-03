"""Vector memory on embedded Qdrant + FastEmbed (ONNX, CPU-only, no torch).

First call downloads a small embedding model (~80 MB) automatically.
"""
import uuid
from typing import Optional

from qdrant_client import QdrantClient

from app.core.config import MODELS_DIR, MODELS_OFFLINE, settings

COLLECTION = "athena_memory"
MODULES_COLLECTION = "athena_modules"
_client: Optional[QdrantClient] = None


def client() -> QdrantClient:
    global _client
    if _client is None:
        _client = QdrantClient(path=settings.QDRANT_PATH)
        # cache_dir is PROJECT-RELATIVE, and it has to be passed here because
        # FastEmbed honours no environment variable for it -- not
        # FASTEMBED_CACHE_PATH, not HF_HOME, not XDG_CACHE_HOME. Only this
        # constructor argument. That is why KI-2 could not be closed by
        # configuration and needed a code change.
        #
        # Its default was WORSE than the ~80 MB runtime download KI-2 records:
        # measured, it cached to /tmp/fastembed_cache, and /tmp is not merely
        # ephemeral across deploys but plausibly cleared under the running
        # service -- so bge-small-en-v1.5 was being re-fetched on cold starts
        # rather than once.
        _client.set_model("BAAI/bge-small-en-v1.5",
                          cache_dir=str(MODELS_DIR / "fastembed"),
                          local_files_only=MODELS_OFFLINE)
    return _client


def add_memory(user_id: int, text: str, kind: str, title: str = "") -> str:
    doc_id = str(uuid.uuid4())
    client().add(
        collection_name=COLLECTION,
        documents=[text],
        metadata=[{"user_id": user_id, "kind": kind, "title": title}],
        ids=[doc_id],
    )
    return doc_id


def search_memory(user_id: int, query: str, limit: int = 5) -> list[dict]:
    try:
        results = client().query(
            collection_name=COLLECTION,
            query_text=query,
            query_filter={"must": [{"key": "user_id", "match": {"value": user_id}}]},
            limit=limit,
        )
    except Exception:
        return []  # collection may not exist yet
    return [
        {"text": r.document, "score": r.score, **(r.metadata or {})}
        for r in results
    ]


def _module_point_id(slug: str) -> str:
    # Deterministic from the slug so re-indexing on every re-seed upserts the
    # same point instead of accumulating duplicates.
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"athena-module:{slug}"))


def index_module(module_id: int, slug: str, title: str, summary: str, aliases: list[str]) -> None:
    text = f"{title}. {summary}"
    if aliases:
        text += f" Also known as: {', '.join(aliases)}."
    client().add(
        collection_name=MODULES_COLLECTION,
        documents=[text],
        metadata=[{"module_id": module_id, "slug": slug}],
        ids=[_module_point_id(slug)],
    )


def find_similar_module(query_text: str, threshold: float = 0.82) -> Optional[dict]:
    """Top module match by embedding similarity, or None if nothing clears the threshold."""
    try:
        results = client().query(collection_name=MODULES_COLLECTION, query_text=query_text, limit=1)
    except Exception:
        return None  # collection may not exist yet
    if not results or results[0].score < threshold:
        return None
    meta = results[0].metadata or {}
    return {"module_id": meta.get("module_id"), "slug": meta.get("slug"), "score": results[0].score}
