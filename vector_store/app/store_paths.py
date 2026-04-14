"""
Каталоги FAISS относительно рабочей директории процесса (корень репозитория или /app в Docker).

По умолчанию индексы лежат в подкаталогах **по провайдеру эмбеддинга** (как ``RAG_EMBEDDING_PROVIDER`` / ``LLM_PROVIDER``),
чтобы параллельно хранить версии для yandex, openai, google, mistral:

- профессии: ``{FAISS_PROFESSION_VECTOR_ROOT}/{provider}/`` (корень по умолчанию ``data/profession/profession_vector``)
- курсы: ``{FAISS_COURSES_VECTOR_ROOT}/{provider}/`` (корень по умолчанию ``data/education/education_vector``)

Переопределение:

- ``FAISS_PROFESSION_INDEX_DIR`` — если задан, используется **как полный путь** к индексу профессий (без добавления slug провайдера).
- ``FAISS_COURSES_INDEX_DIR`` — то же для курсов.
- ``FAISS_PROFESSION_VECTOR_ROOT`` — родительский каталог перед slug (если не задан ``FAISS_PROFESSION_INDEX_DIR``).
- ``FAISS_COURSES_VECTOR_ROOT`` — то же для курсов (если не задан ``FAISS_COURSES_INDEX_DIR``).
"""
from __future__ import annotations

import os
import re


def rag_provider_slug() -> str:
    """
    Имя подкаталога для текущего провайдера эмбеддингов (совпадает с логикой ``create_rag_embeddings``).
    """
    explicit = (os.getenv("RAG_EMBEDDING_PROVIDER") or "").strip().lower()
    raw = explicit if explicit else (os.getenv("LLM_PROVIDER") or "yandex").strip().lower()
    raw = raw or "yandex"
    slug = re.sub(r"[^a-z0-9._-]+", "_", raw).strip("._-") or "yandex"
    return slug


def profession_index_dir() -> str:
    override = (os.getenv("FAISS_PROFESSION_INDEX_DIR") or "").strip()
    if override:
        return override
    root = (os.getenv("FAISS_PROFESSION_VECTOR_ROOT") or "").strip() or os.path.join(
        "data", "profession", "profession_vector"
    )
    return os.path.join(root, rag_provider_slug())


def courses_index_dir() -> str:
    override = (os.getenv("FAISS_COURSES_INDEX_DIR") or "").strip()
    if override:
        return override
    root = (os.getenv("FAISS_COURSES_VECTOR_ROOT") or "").strip() or os.path.join(
        "data", "education", "education_vector"
    )
    return os.path.join(root, rag_provider_slug())
