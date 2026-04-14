import os
import time
import json
import argparse
from typing import List, Dict, Any
from pathlib import Path
from collections import Counter

import requests
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import re

# -----------------------
# Конфиг (можно менять / передавать через CLI)
# -----------------------
# По умолчанию берём API key из переменной окружения SUPERJOB_X_API_APP_ID,
# если не задана — можно подставить явно (но безопаснее хранить в env).
DEFAULT_CLIENT_SECRET = os.environ.get(
    "SUPERJOB_X_API_APP_ID",
    "v3.r.139276124.1265899fb7dead5c420cf7191e23ce4b6a1220f0.86d87b71ddd30916350ea14a13eaaddba6b280cb"
)
API_URL = "https://api.superjob.ru/2.0/vacancies/"

# Параметры агрегации
DEFAULT_TARGET_PROFESSIONS = 50
DEFAULT_SIM_THRESHOLD = 0.62
DEFAULT_TITLE_BOOST = 3
DEFAULT_PER_PAGE = 100  # max per-request (обычно 100)
DEFAULT_MAX_PAGES = 20  # если нужно ограничить время запроса
DEFAULT_MAX_VACANCIES = None  # можно ограничить общее число вакансий (None = не ограничивать)
REQUEST_SLEEP = 0.5  # пауза между запросами (сек)
BACKOFF_BASE = 2.0

# Параметры сохранения
DEFAULT_OUT_VACANCIES = "data/superjob_vacancies.json"
DEFAULT_OUT_PROFESSIONS = "data/professions_aggregated.json"

# -----------------------
# Вспомогательные функции
# -----------------------
def extract_title_and_description(obj: Dict[str, Any]) -> Dict[str, str]:
    """
    Пытаемся аккуратно извлечь заголовок и текст-описание вакансии.
    SuperJob возвращает поля с разными именами, поэтому делаем набор fallback-полей.
    """
    # Возможные поля для названия
    title_keys = ["profession", "profession_ru", "title", "name", "vacancy", "position"]
    # Возможные поля для описания / обязанностей / условия
    desc_keys = [
        "vacancyRichText", "vacancy", "candidat", "description", "work", "responsibility",
        "requirements", "conditions", "description_raw", "notice", "snippet"
    ]

    title = None
    for k in title_keys:
        if k in obj and obj.get(k):
            title = obj.get(k)
            break
    # Иногда "profession" присутствует as str, else fallback
    if title is None:
        # try nested 'profession' object (if any)
        if isinstance(obj.get("profession"), dict):
            title = obj["profession"].get("title")
    if title is None:
        # try to assemble from 'town' + 'company' if nothing else
        title = obj.get("vacancy") or obj.get("name") or obj.get("title") or ""

    # Compose description from multiple possible fields: join available text-like fields
    desc_parts = []
    for k in desc_keys:
        v = obj.get(k)
        if isinstance(v, str) and v.strip():
            desc_parts.append(v.strip())
    # Additionally include big text-like fields (safety fallback)
    # take any string fields longer than 80 chars
    for k, v in obj.items():
        if isinstance(v, str) and len(v) > 80 and k not in desc_keys:
            desc_parts.append(v.strip())

    description = "\n\n".join(dict.fromkeys(desc_parts))  # убираем дублируемые подряд
    # final fallback: short summary fields like 'snippet' might be dicts
    if not description:
        # try some nested fields that sometimes contain 'text' or 'snippet'
        if isinstance(obj.get("snippet"), dict):
            s = obj["snippet"].get("requirement") or obj["snippet"].get("responsibility")
            if s:
                description = s
    return {"title": title or "", "description": description or ""}

# Нормализация и подготовка текста для TF-IDF
def normalize_title(title: str) -> str:
    if not isinstance(title, str):
        return ""
    t = title.lower()
    t = re.sub(r"\(.*?\)", " ", t)
    t = re.sub(r"\bг\.?\s*\w+\b", " ", t)
    t = re.sub(r"\b(санкт[- ]?петербург|москва|спб|питер|пермь|екатеринбург|новосибирск|сочи|казань|нижний)\b", " ", t)
    t = re.sub(r"[^0-9a-zа-яё\- ]+", " ", t, flags=re.IGNORECASE)
    t = re.sub(r"\s+", " ", t).strip()
    return t

def vacancy_text_for_vector(vac: Dict[str, str], title_boost: int = DEFAULT_TITLE_BOOST, max_desc_chars: int = 4000) -> str:
    title = vac.get("title", "") or ""
    desc = vac.get("description", "") or ""
    desc_cut = desc.strip()[:max_desc_chars]
    return (" " + title + " ") * title_boost + " " + desc_cut

def summarize_descriptions(descriptions: List[str], top_k: int = 3) -> str:
    sents = []
    for d in descriptions:
        if not d:
            continue
        parts = re.split(r'(?<=[\.\!\?])\s+|\n+', d.strip())
        for p in parts:
            p = p.strip()
            if len(p) >= 30:
                sents.append(p)
    if not sents:
        return ""
    if len(sents) <= top_k:
        return " ".join(list(dict.fromkeys(sents))[:top_k])
    max_df = 0.85
    if max_df * len(sents) < 1:
        max_df = 1.0
    vec = TfidfVectorizer(max_df=max_df, min_df=1, ngram_range=(1,2)).fit_transform(sents)
    centroid = np.asarray(vec.mean(axis=0)).ravel()
    sim = (vec @ centroid).ravel()
    top_idx = np.argsort(-sim)[:top_k]
    top_sents = [sents[i] for i in top_idx]
    return " ".join(top_sents)

# Кластеризация (агрегация вакансий в профессии) — последовательный online-like алгоритм
def aggregate_vacancies(
    vacancies: List[Dict[str, str]],
    target_num: int = DEFAULT_TARGET_PROFESSIONS,
    sim_threshold: float = DEFAULT_SIM_THRESHOLD,
    title_boost: int = DEFAULT_TITLE_BOOST
) -> Dict[str, Any]:
    corpus = [vacancy_text_for_vector(v, title_boost=title_boost) for v in vacancies]
    if not corpus:
        return {}

    vectorizer = TfidfVectorizer(max_df=0.85, min_df=1, ngram_range=(1,2))
    X_all = vectorizer.fit_transform(corpus)
    vectors_all = X_all.toarray()

    clusters = []
    for idx, vac in enumerate(vacancies):
        vec = vectors_all[idx].reshape(1, -1)
        best_sim = -1.0
        best_cluster = None

        for cluster in clusters:
            centroid = cluster['centroid'].reshape(1, -1)
            sim = cosine_similarity(vec, centroid)[0,0]
            if sim > best_sim:
                best_sim = sim
                best_cluster = cluster

        if best_sim >= sim_threshold and best_cluster is not None:
            best_cluster['texts_idx'].append(idx)
            best_cluster['titles'].append(vac.get('title',''))
            best_cluster['descriptions'].append(vac.get('description',''))
            if len(best_cluster['examples']) < 10:
                best_cluster['examples'].append(vac.get('title',''))
            members = vectors_all[best_cluster['texts_idx'], :]
            best_cluster['centroid'] = members.mean(axis=0)
        else:
            new_cluster = {
                'texts_idx': [idx],
                'centroid': vec.ravel(),
                'titles': [vac.get('title','')],
                'descriptions': [vac.get('description','')],
                'examples': [vac.get('title','')],
            }
            clusters.append(new_cluster)

        if len(clusters) >= target_num:
            break

    result = {}
    for c in clusters:
        norm_titles = [normalize_title(t) for t in c['titles'] if t]
        if norm_titles:
            most_common_norm = Counter(norm_titles).most_common(1)[0][0]
            candidates = [t for t in c['titles'] if normalize_title(t) == most_common_norm]
            canonical_title = max(candidates, key=len) if candidates else (c['titles'][0] if c['titles'] else most_common_norm)
        else:
            canonical_title = c['titles'][0] if c['titles'] else "Unknown"

        agg_desc = summarize_descriptions(c['descriptions'], top_k=3)
        result[canonical_title] = {
            "title": canonical_title,
            "description": agg_desc if agg_desc else " ".join(list({d for d in c['descriptions'] if d})[:3]),
            "vacancy_count": len(c['texts_idx']),
            "examples": c['examples'][:5]
        }
    return result

# -----------------------
# SuperJob fetcher
# -----------------------
def fetch_vacancies_from_superjob(
    client_secret: str,
    per_page: int = DEFAULT_PER_PAGE,
    max_pages: int = DEFAULT_MAX_PAGES,
    max_vacancies: int = DEFAULT_MAX_VACANCIES,
    sleep_between_requests: float = REQUEST_SLEEP,
) -> List[Dict[str, str]]:
    headers = {"X-Api-App-Id": client_secret}
    page = 0
    collected = []
    backoff = BACKOFF_BASE

    while True:
        if max_pages is not None and page >= max_pages:
            print(f"[fetch] reached max_pages={max_pages}, stopping")
            break
        params = {"page": page, "count": per_page}
        try:
            r = requests.get(API_URL, headers=headers, params=params, timeout=30)
        except Exception as e:
            print(f"[fetch] request exception page {page}: {e}. backoff {backoff}s")
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)
            continue

        if r.status_code != 200:
            print(f"[fetch] HTTP {r.status_code} on page {page}. Response: {r.text[:400]}")
            # при 429 / 5xx — делаем backoff
            if r.status_code in (429, 502, 503, 504):
                print(f"[fetch] backing off {backoff}s")
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)
                continue
            else:
                break

        try:
            data = r.json()
        except Exception as e:
            print(f"[fetch] JSON decode error page {page}: {e}")
            break

        items = data.get("objects") or data.get("items") or []
        if not items:
            print(f"[fetch] no items on page {page} — stopping")
            break

        for obj in items:
            try:
                rec = extract_title_and_description(obj)
                # skip entirely empty
                if not rec["title"] and not rec["description"]:
                    continue
                collected.append(rec)
            except Exception as e:
                print(f"[fetch] error extracting item: {e}")
            if max_vacancies is not None and len(collected) >= max_vacancies:
                print(f"[fetch] reached max_vacancies={max_vacancies}, stopping")
                break

        print(f"[fetch] page {page} fetched, got {len(items)} items, total collected {len(collected)}")
        # иногда API даёт флаг more
        more = data.get("more")
        page += 1
        if max_vacancies is not None and len(collected) >= max_vacancies:
            break
        if more is False:
            print("[fetch] API reports no more pages (more=False). Stopping.")
            break
        # if items length < per_page — possibly last page
        if len(items) < per_page:
            print("[fetch] last page (items < per_page). Stopping.")
            break

        time.sleep(sleep_between_requests)

    return collected

# -----------------------
# CLI и run
# -----------------------
def main():
    parser = argparse.ArgumentParser(description="Fetch SuperJob vacancies and aggregate into professions")
    parser.add_argument("--client-secret", "-k", default=DEFAULT_CLIENT_SECRET, help="X-Api-App-Id (SuperJob)")
    parser.add_argument("--per-page", type=int, default=DEFAULT_PER_PAGE)
    parser.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES)
    parser.add_argument("--max-vacancies", type=int, default=DEFAULT_MAX_VACANCIES)
    parser.add_argument("--out-vac", default=DEFAULT_OUT_VACANCIES)
    parser.add_argument("--out-prof", default=DEFAULT_OUT_PROFESSIONS)
    parser.add_argument("--target-professions", type=int, default=DEFAULT_TARGET_PROFESSIONS)
    parser.add_argument("--threshold", type=float, default=DEFAULT_SIM_THRESHOLD)
    parser.add_argument("--boost", type=int, default=DEFAULT_TITLE_BOOST)
    parser.add_argument("--permanently-save-raw", action="store_true", help="Save raw vacancies JSON even if empty")
    args = parser.parse_args()

    print("[main] fetching vacancies from SuperJob...")
    vacs = fetch_vacancies_from_superjob(
        client_secret=args.client_secret,
        per_page=args.per_page,
        max_pages=args.max_pages,
        max_vacancies=args.max_vacancies,
        sleep_between_requests=REQUEST_SLEEP,
    )

    out_vac_path = Path(args.out_vac)
    out_vac_path.parent.mkdir(parents=True, exist_ok=True)
    if vacs or args.permanently_save_raw:
        with out_vac_path.open("w", encoding="utf-8") as f:
            json.dump(vacs, f, ensure_ascii=False, indent=2)
        print(f"[main] saved {len(vacs)} raw vacancies to {out_vac_path}")
    else:
        print("[main] no vacancies fetched; raw file not saved")

    if not vacs:
        print("[main] nothing to aggregate, exiting.")
        return

    # aggregate
    print("[main] aggregating vacancies into professions...")
    professions = aggregate_vacancies(
        vacs,
        target_num=args.target_professions,
        sim_threshold=args.threshold,
        title_boost=args.boost
    )

    out_prof_path = Path(args.out_prof)
    out_prof_path.parent.mkdir(parents=True, exist_ok=True)
    with out_prof_path.open("w", encoding="utf-8") as f:
        json.dump(professions, f, ensure_ascii=False, indent=2)
    print(f"[main] saved {len(professions)} professions to {out_prof_path}")

if __name__ == "__main__":
    main()