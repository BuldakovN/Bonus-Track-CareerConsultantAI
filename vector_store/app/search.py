import argparse
from typing import Any, Dict, List, Literal, Optional, Tuple

from dotenv import load_dotenv
from langchain_community.vectorstores import FAISS

from app.rag_embeddings import get_rag_embeddings
from app.store_paths import courses_index_dir, profession_index_dir

INTERNAL_CONTEXT = (
    """
    Мария, 34 года
    Работает кассиром в банке. Не нравится, что нет индексации зарплаты уже несколько лет, не нравится коллектив на работе. Есть образование педагога психолога, но получала его для того, чтобы трудоустроиться на работу, где требовалось высшее образование.
    Хотела бы сменить работу, но не знает, оставаться в этой же сфере или менять на другую.
    У Марии много интересов, спорт, участвует в акциях по разделению вторсырья. Нравится чувствовать свое причастность к улучшению окружающей среды.
    Хотела бы выйти на доход 60-80к. Чтобы у компании было ДМС, премирование сотрудников.
    """
).strip()

IndexKind = Literal["professions", "courses"]


def _index_directory(kind: IndexKind) -> str:
    return courses_index_dir() if kind == "courses" else profession_index_dir()


def similarity_search_hits(
    query: str,
    k: int = 5,
    *,
    api_key: Optional[str] = None,
    folder_id: Optional[str] = None,
    index: IndexKind = "professions",
    threshold: float = 0.75,
) -> List[Tuple[str, Dict[str, Any], float]]:
    """Возвращает список (page_content, metadata, score)."""
    load_dotenv()
    directory = _index_directory(index)
    embeddings = get_rag_embeddings(api_key=api_key, folder_id=folder_id)
    vs = FAISS.load_local(directory, embeddings, allow_dangerous_deserialization=True)
    docs = vs.similarity_search_with_score(query, k=k, threshold=threshold)
    out: List[Tuple[str, Dict[str, Any], float]] = []
    for d, score in docs:
        out.append((d.page_content, dict(d.metadata), float(score)))
    return out


def search_top_k(query: str, k: int = 5) -> List[str]:
    load_dotenv()
    embeddings = get_rag_embeddings()
    vs = FAISS.load_local(
        profession_index_dir(), embeddings, allow_dangerous_deserialization=True
    )
    docs = vs.similarity_search_with_score(query, k=k, threshold=0.75)
    results = []
    for d, _score in docs:
        title = d.metadata.get("title") or d.metadata.get("key") or "?"
        results.append(title)
    return results


def main_cli() -> None:
    parser = argparse.ArgumentParser(description="Поиск топ-k профессий по тексту пользователя")
    parser.add_argument(
        "--text",
        type=str,
        required=False,
        default=None,
        help="Текстовый контекст пользователя. Если не задан, используется INTERNAL_CONTEXT в коде",
    )
    parser.add_argument("--k", type=int, default=5, help="Сколько профессий вернуть")
    args = parser.parse_args()

    text = args.text or INTERNAL_CONTEXT
    if not text:
        print("Не задан текст (--text) и пустой INTERNAL_CONTEXT.")
        return

    titles = search_top_k(text, k=args.k)
    print("Топ профессий:")
    for i, t in enumerate(titles, 1):
        print(f"{i}. {t}")


if __name__ == "__main__":
    main_cli()
