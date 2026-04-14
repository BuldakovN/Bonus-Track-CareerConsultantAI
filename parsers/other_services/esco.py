import requests
import json
import os
import time

BASE_URL = "https://ec.europa.eu/esco/api/resource/occupation"
DATA_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'esco_occupations.json')

def get_text_in_lang(field, lang="ru", fallback="en"):
    if not isinstance(field, dict):
        return ""
    return field.get(lang, {}).get("literal") or field.get(fallback, {}).get("literal") or ""

def fetch_all_professions(limit=50):
    professions = []
    offset = 0

    scheme_uri = "http://data.europa.eu/esco/occupation"

    while True:
        url = f"{BASE_URL}?isInScheme={scheme_uri}&limit={limit}&offset={offset}"
        resp = requests.get(url)
        if resp.status_code != 200:
            print("Ошибка запроса:", resp.status_code, resp.text)
            break

        data = resp.json()
        results = data.get("_embedded", {}).get("resource", [])

        if not results:
            break  # данных больше нет

        for occ in results:
            title = get_text_in_lang(occ.get("title", {}))
            desc = get_text_in_lang(occ.get("description", {}))
            uri = occ.get("uri")

            professions.append({
                "title": title,
                "description": desc,
                "uri": uri
            })

        print(f"Собрано профессий: {len(professions)}")
        offset += limit
        time.sleep(0.2)

    return professions

if __name__ == "__main__":
    data = fetch_all_professions(limit=50)
    os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"✅ Сохранено {len(data)} профессий в {DATA_PATH}")
