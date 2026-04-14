import os
import json
import asyncio
import aiohttp
import argparse
import re
from pathlib import Path
from typing import Dict, Any, Optional, List
import requests
from dotenv import load_dotenv

load_dotenv()  # Подхватываем .env из корня
DEFAULT_API_URL = os.getenv('LLM_API_URL', 'http://localhost:8000/start_talk/')
DEFAULT_USER_ID = os.getenv('LLM_SUMMARIZER_USER_ID', 'summarizer')
YANDEX_FOLDER_ID = os.getenv('YANDEX_CLOUD_FOLDER', '')
YANDEX_API_KEY = os.getenv('YANDEX_CLOUD_API_KEY', '')
YANDEX_MODEL = os.getenv('YANDEX_MODEL', 'yandexgpt')  # или yandexgpt-lite

PROMPT_TEMPLATE = """Ты — эксперт по рынку труда и карьерному ориентированию. На основе предоставленного агрегированного текста о профессии составь структурированное, универсальное и нейтральное описание профессии.
Важно:
- Избегай узко-специфичных, единичных навыков и редких технологий. Обобщай.
- Пиши чётко и кратко. Не упоминай вакансии и компании.
- Используй только информацию, логично вытекающую из текста. Ничего не выдумывай.
- Зарплату указывай ТОЛЬКО если в тексте явно есть упоминания сумм/диапазонов. В таком случае приведи ЕДИНЫЙ агрегированный диапазон в рублях в месячном выражении.
  - Нормализуй все встречающиеся значения: распознай форматы «от/до», «≈», диапазоны (X–Y), обозначения «тыс.», «k» и т.п.
  - Если встречаются разные цифры в тексте, вычисли общий диапазон: минимальная из всех нижних границ и максимальная из всех верхних границ. Если есть только одиночные значения, считай их и нижней, и верхней границей.
  - Валюта по умолчанию — рубли. Если указана иная валюта, конвертацию не выполняй, просто пропусти такие значения.
  - Формат вывода: "X–Y ₽/мес" (например, "80 000–150 000 ₽/мес"). Используй неразрывные пробелы для разделения тысяч (можно тонкий пробел). Если данных нет — "не указано".
- Верни строго валидный JSON по заданной схеме. Никаких пояснений до/после JSON.

Схема JSON:
{{
  "title": "string",                       // Название профессии (обобщённо)
  "description": "string",                 // Общее описание (3-6 предложений)
  "responsibilities": ["string", ...],     // Ключевые задачи (обобщённые)
  "skills_general": ["string", ...],       // Базовые и переносимые навыки (без редких/частных)
  "areas": ["string", ...],                // Типичные области/домены применения
  "typical_roles": ["string", ...],        // Типичные роли/позиции
  "education": ["string", ...],            // Типичное образование/подготовка
  "growth_paths": ["string", ...],         // Векторы развития/карьеры
  "salary_range": "string"                 // Диапазон в рублях за месяц: "X–Y ₽/мес" или "не указано"
}}

Текст по профессии:
\"\"\"{text}\"\"\""""

JSON_BLOCK_RE = re.compile(r"\{[\s\S]*\}\s*$")

def ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)

def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path: Path, data: Any):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def extract_json(text: str) -> Optional[Dict[str, Any]]:
    # Пробуем взять последний JSON-блок
    m = JSON_BLOCK_RE.search(text.strip())
    raw = m.group(0) if m else text.strip()
    try:
        return json.loads(raw)
    except Exception:
        # fallback: попытка найти первую и последнюю скобку
        try:
            start = raw.find("{")
            end = raw.rfind("}")
            if start != -1 and end != -1 and end > start:
                return json.loads(raw[start:end+1])
        except Exception:
            return None
    return None

async def call_llm_api(session: aiohttp.ClientSession, api_url: str, prompt: str, user_id: str) -> str:
    payload = {"user_id": str(user_id), "prompt": prompt, "parameters": {}}
    async with session.post(api_url, json=payload) as resp:
        if resp.status != 200:
            text = await resp.text()
            raise RuntimeError(f"HTTP {resp.status}: {text[:200]}")
        data = await resp.json()
        return data.get("msg", "")

def call_llm_direct(prompt: str) -> str:
    url = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {YANDEX_API_KEY}",
        "x-folder-id": YANDEX_FOLDER_ID,
    }
    payload = {
        "modelUri": f"gpt://{YANDEX_FOLDER_ID}/{YANDEX_MODEL}/latest",
        "completionOptions": {"temperature": 0.6, "maxTokens": 2000},
        "messages": [
            {"role": "user", "text": prompt}
        ],
    }
    r = requests.post(url, headers=headers, json=payload, timeout=60)
    r.raise_for_status()
    data = r.json()
    return (
        data.get("result", {})
        .get("alternatives", [{}])[0]
        .get("message", {})
        .get("text", "")
    )

async def summarize_one(session: aiohttp.ClientSession, api_url: str, title: str, text: str, user_id: str, retries: int = 2, llm_mode: str = "api", fallback_direct: bool = True) -> Optional[Dict[str, Any]]:
    prompt = PROMPT_TEMPLATE.format(text=text[:12000])  # страховка по длине
    last_err = None
    for attempt in range(retries + 1):
        try:
            if llm_mode == "api":
                msg = await call_llm_api(session, api_url, prompt, user_id)
            else:
                msg = call_llm_direct(prompt)
            obj = extract_json(msg)
            if obj and isinstance(obj, dict) and obj.get("title"):
                return obj
            last_err = ValueError("Не удалось распарсить JSON/нет ключа title")
        except Exception as e:
            last_err = e
        await asyncio.sleep(1 + attempt)
    # Фоллбек на прямой вызов YC, если выбран API и включён fallback
    if llm_mode == "api" and fallback_direct:
        try:
            msg = call_llm_direct(prompt)
            obj = extract_json(msg)
            if obj and isinstance(obj, dict) and obj.get("title"):
                return obj
        except Exception:
            pass
    print(f"[WARN] {title}: {last_err}")
    return None

async def run(input_path: Path, output_path: Path, limit: Optional[int], concurrency: int, resume: bool, llm_mode: str, fallback_direct: bool) -> Dict[str, Any]:
    data: Dict[str, str] = load_json(input_path)
    existing: Dict[str, Any] = {}
    if resume and output_path.exists():
        try:
            existing = load_json(output_path)
        except Exception:
            existing = {}
    pending_items: List[tuple[str, str]] = []
    for k, v in data.items():
        if limit is not None and len(pending_items) >= limit:
            break
        if resume and k in existing:
            continue
        pending_items.append((k, v))

    ensure_dir(output_path.parent)
    api_url = os.getenv('LLM_API_URL', DEFAULT_API_URL)
    user_id = os.getenv('LLM_SUMMARIZER_USER_ID', DEFAULT_USER_ID)

    sem = asyncio.Semaphore(concurrency)
    results: Dict[str, Any] = dict(existing)

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as session:
        async def worker(title: str, text: str):
            async with sem:
                res = await summarize_one(session, api_url, title, text, user_id, llm_mode=llm_mode, fallback_direct=fallback_direct)
                if res:
                    results[title] = res

        tasks = [asyncio.create_task(worker(title, text)) for title, text in pending_items]
        for i in range(0, len(tasks), 20):
            chunk = tasks[i:i+20]
            await asyncio.gather(*chunk)
            save_json(output_path, results)  # чекпоинт

    save_json(output_path, results)
    print(f"Сохранено: {len(results)} профессий в {output_path}")
    return results

def render_summary_text(obj: Dict[str, Any]) -> str:
    parts: List[str] = []
    title = obj.get("title")
    if title:
        parts.append(f"Профессия: {title}")
    desc = obj.get("description")
    if desc:
        parts.append(desc)
    sr = obj.get("salary_range")
    if sr:
        parts.append(f"Диапазон зарплат: {sr}")
    resp = obj.get("responsibilities") or []
    if resp:
        parts.append("Задачи: " + ", ".join(resp))
    skills = obj.get("skills_general") or []
    if skills:
        parts.append("Навыки: " + ", ".join(skills))
    areas = obj.get("areas") or []
    if areas:
        parts.append("Области: " + ", ".join(areas))
    roles = obj.get("typical_roles") or []
    if roles:
        parts.append("Типичные роли: " + ", ".join(roles))
    edu = obj.get("education") or []
    if edu:
        parts.append("Образование: " + ", ".join(edu))
    growth = obj.get("growth_paths") or []
    if growth:
        parts.append("Пути развития: " + ", ".join(growth))
    related = obj.get("related_professions") or []
    if related:
        parts.append("Близкие профессии: " + ", ".join(related))
    nsf = obj.get("not_suitable_for") or []
    if nsf:
        parts.append("Не подойдёт: " + ", ".join(nsf))
    return " \n".join(parts)

def main():
    parser = argparse.ArgumentParser(description="Суммаризация профессий из hh_professions_comparison.json (структурно и плоский текст)")
    parser.add_argument("--input", type=str, default="data/hh_professions_comparison.json", help="Агрегированный текст по профессиям")
    parser.add_argument("--limit", type=int, default=None, help="Ограничить количество профессий для генерации")
    parser.add_argument("--concurrency", type=int, default=3, help="Параллельные запросы к LLM")
    parser.add_argument("--resume", action="store_true", help="Продолжить и дозаполнить существующий файл вывода")
    parser.add_argument("--llm-mode", choices=["api", "direct"], default="api", help="Куда слать запросы: локальный API (api) или напрямую в Яндекс (direct)")
    parser.add_argument("--no-fallback", action="store_true", help="Отключить фоллбек на прямой вызов при ошибке API")
    args = parser.parse_args()

    comparison_in = Path(args.input)
    if not comparison_in.exists():
        raise FileNotFoundError(f"Не найден входной файл: {comparison_in}")

    # 1) Генерация структурированного файла из comparison
    comparison_struct_out = Path("data/summary_hh_professions_detailed.json")
    results_comparison = asyncio.run(
        run(
            comparison_in,
            comparison_struct_out,
            args.limit,
            args.concurrency,
            args.resume,
            args.llm_mode,
            not args.no_fallback,
        )
    )

    # 2) Плоский текст в отдельный файл
    comparison_text_out = Path("data/summary_hh_professions_comparison.json")
    flattened: Dict[str, str] = {title: render_summary_text(obj) for title, obj in results_comparison.items()}
    save_json(comparison_text_out, flattened)
    print(f"Сохранён плоский текст: {comparison_text_out}")

if __name__ == "__main__":
    main()