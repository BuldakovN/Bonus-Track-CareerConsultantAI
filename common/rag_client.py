"""
HTTP-клиент к микросервису vector_store (FAISS / RAG).
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

import httpx


def _vector_store_base_url() -> str:
    return (os.getenv("VECTOR_STORE_SERVICE_URL") or "http://localhost:8030").rstrip("/")


class RagDocument:
    __slots__ = ("page_content", "metadata")

    def __init__(self, page_content: str, metadata: Dict[str, Any]) -> None:
        self.page_content = page_content
        self.metadata = metadata


async def rag_search(
    *,
    query: str,
    k: int = 5,
    api_key: Optional[str] = None,
    folder_id: Optional[str] = None,
    index_dir: str = "INDEX_DIR",
    client: Optional[httpx.AsyncClient] = None,
) -> List[Tuple[RagDocument, float]]:
    """
    Аналог ``professions_vector_index.search_professions.rag_search``: список пар (документ, score).

    ``index_dir`` — ``INDEX_DIR`` (профессии) или ``COURSES_DIR`` (курсы), как в старом API.
    """
    base = _vector_store_base_url()
    index = "courses" if index_dir == "COURSES_DIR" else "professions"
    payload: Dict[str, Any] = {
        "query": query,
        "k": k,
        "index": index,
        "threshold": 0.75,
    }
    if api_key is not None:
        payload["api_key"] = api_key
    if folder_id is not None:
        payload["folder_id"] = folder_id

    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=120.0)
    assert client is not None
    try:
        r = await client.post(f"{base}/v1/search", json=payload)
        r.raise_for_status()
        data = r.json()
        out: List[Tuple[RagDocument, float]] = []
        for h in data.get("hits", []):
            doc = RagDocument(
                str(h.get("page_content") or ""),
                dict(h.get("metadata") or {}),
            )
            out.append((doc, float(h.get("score", 0.0))))
        return out
    finally:
        if own_client:
            await client.aclose()
