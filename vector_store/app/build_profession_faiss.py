import os
import json
import time
from typing import Dict, List, Tuple

from dotenv import load_dotenv
from langchain_community.vectorstores import FAISS

from app.rag_embeddings import get_rag_embeddings
from app.store_paths import profession_index_dir


def profession_source_json_path() -> str:
    """JSON с агрегированными профессиями для индексации. Переопределение: FAISS_PROFESSION_SOURCE_JSON."""
    override = (os.getenv("FAISS_PROFESSION_SOURCE_JSON") or "").strip()
    if override:
        return override
    return os.path.join("data", "profession", "summary_hh_professions_comparison.json")


def load_professions(path: str) -> Dict[str, str]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def profession_to_text(key: str, combined_str: str) -> Tuple[str, Dict]:
    title = key
    combined_text = (combined_str or "").strip()
    text = combined_text if combined_text else title

    if len(text) > 2000:
        text = text[:2300] + "..."

    metadata = {"key": key, "title": title}
    return text, metadata


def build_index() -> None:
    load_dotenv()
    index_dir = profession_index_dir()
    docs_json = os.path.join(index_dir, "docs.json")
    os.makedirs(index_dir, exist_ok=True)

    data_path = profession_source_json_path()
    data = load_professions(data_path)

    texts: List[str] = []
    metadatas: List[Dict] = []
    for key, obj in data.items():
        text, meta = profession_to_text(key, obj)
        if text and len(text) > 10:
            texts.append(text)
            metadatas.append(meta)

    if not texts:
        raise RuntimeError("Не найдено валидных профессий для индексации")

    print(f"Найдено {len(texts)} профессий для индексации")
    print("Создание эмбеддингов с задержками для соблюдения лимитов API...")

    embeddings = get_rag_embeddings()

    BATCH_SIZE = 20
    all_embeddings = []

    for i in range(0, len(texts), BATCH_SIZE):
        batch_texts = texts[i : i + BATCH_SIZE]
        print(f"Обрабатываем batch {i // BATCH_SIZE + 1}/{(len(texts) + BATCH_SIZE - 1) // BATCH_SIZE}")

        batch_embeddings = embeddings.embed_documents(batch_texts)
        all_embeddings.extend(batch_embeddings)

        if i + BATCH_SIZE < len(texts):
            time.sleep(1.2)

    pairs = [
        (texts[i], list(map(float, all_embeddings[i]))) for i in range(len(texts))
    ]
    vs = FAISS.from_embeddings(text_embeddings=pairs, embedding=embeddings, metadatas=metadatas)

    vs.save_local(index_dir)
    with open(docs_json, "w", encoding="utf-8") as f:
        json.dump({i: m for i, m in enumerate(metadatas)}, f, ensure_ascii=False, indent=2)

    print(f"Индекс сохранён в: {index_dir}. Всего документов: {len(texts)}")


if __name__ == "__main__":
    build_index()
