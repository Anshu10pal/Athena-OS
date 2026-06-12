"""Vector memory on embedded Qdrant + FastEmbed (ONNX, CPU-only, no torch).

First call downloads a small embedding model (~80 MB) automatically.
"""
import uuid
from typing import Optional

from qdrant_client import QdrantClient

from app.core.config import settings

COLLECTION = "athena_memory"
_client: Optional[QdrantClient] = None


def client() -> QdrantClient:
    global _client
    if _client is None:
        _client = QdrantClient(path=settings.QDRANT_PATH)
        _client.set_model("BAAI/bge-small-en-v1.5")
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
