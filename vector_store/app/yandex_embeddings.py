from typing import Optional

from langchain_core.embeddings import Embeddings

from app.rag_embeddings import get_rag_embeddings


def get_yandex_embeddings(api_key: Optional[str] = None, folder_id: Optional[str] = None) -> Embeddings:
    """
    Обёртка для обратной совместимости: ``get_rag_embeddings`` с учётом
    ``RAG_EMBEDDING_PROVIDER`` / ``LLM_PROVIDER`` (не только Yandex).
    """
    return get_rag_embeddings(api_key=api_key, folder_id=folder_id)
