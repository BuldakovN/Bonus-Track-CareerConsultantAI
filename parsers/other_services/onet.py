import requests
from requests.auth import HTTPBasicAuth
import json
import os
import time
import xml.etree.ElementTree as ET

USERNAME = "mybigprofile"
PASSWORD = "2337wyt"
BASE_URL = "https://services.onetcenter.org/ws/online/occupations/"
DATA_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'onet_occupations.json')

# Диапазон кодов профессий
START_INDEX = 1
END_INDEX = 2000

def get_occupations_range(start, end):
    """Получаем список профессий в указанном диапазоне"""
    url = f"{BASE_URL}?format=xml&start={start}&end={end}"
    r = requests.get(url, auth=HTTPBasicAuth(USERNAME, PASSWORD))
    if r.status_code != 200:
        print(f"Ошибка запроса: {r.status_code}\nОтвет: {r.text}")
        return []
    try:
        root = ET.fromstring(r.text)
        occupations = []
        for occ in root.findall("occupation"):
            code = occ.findtext("code")
            title = occ.findtext("title")
            occupation_data = {"code": code, "title": title}
            description = occ.findtext("description")
            if description:
                occupation_data["description"] = description
            occupations.append(occupation_data)
        return occupations
    except Exception as e:
        print(f"Ошибка парсинга XML: {e}\nОтвет: {r.text}")
        return []

def get_occupation_details(code):
    """Получаем все доступные детали по профессии и сохраняем только непустые поля"""
    url = f"{BASE_URL}{code}?format=xml"
    r = requests.get(url, auth=HTTPBasicAuth(USERNAME, PASSWORD))
    if r.status_code != 200:
        print(f"Ошибка при получении {code}: {r.status_code}\nОтвет: {r.text}")
        return {}
    try:
        root = ET.fromstring(r.text)
        details = {}

        # Перебираем все элементы внутри occupation
        for child in root:
            tag = child.tag.lower()
            if child.text and child.text.strip():
                details[tag] = child.text.strip()
            else:
                # если есть несколько одноимённых элементов (tasks, skills, abilities и т.д.)
                repeated = [el.text.strip() for el in root.findall(child.tag) if el.text and el.text.strip()]
                if repeated:
                    details[tag] = repeated

        return details
    except Exception as e:
        print(f"Ошибка парсинга XML для {code}: {e}\nОтвет: {r.text}")
        return {}

def save_occupations_range(start, end):
    """Собираем профессии из диапазона и сохраняем в JSON"""
    all_occ = get_occupations_range(start, end)
    print(f"Найдено профессий: {len(all_occ)}")
    
    result = []
    for i, occ in enumerate(all_occ, 1):
        code = occ["code"]
        print(f"[{i}/{len(all_occ)}] Обработка {code}: {occ['title']}")
        details = get_occupation_details(code)
        occupation_data = occ.copy()
        occupation_data.update(details)  # добавляем только существующие поля
        result.append(occupation_data)

        time.sleep(0.2)  # чтобы не перегружать API

    os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"✅ Сохранено {len(result)} профессий в {DATA_PATH}")

if __name__ == "__main__":
    save_occupations_range(START_INDEX, END_INDEX)

