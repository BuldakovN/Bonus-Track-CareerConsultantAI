"""
ИСПОЛЬЗОВАНИЕ:
- Для сбора большего количества профессий увеличьте MAX_PAGES и VACANCIES_PER_PAGE
- API лимиты: до 2000 страниц, до 100 вакансий на страницу
- Парсер собирает вакансии ТОЛЬКО из России (area=113)

НАСТРОЙКИ:
- MAX_PAGES: количество страниц для обработки
- VACANCIES_PER_PAGE: вакансий на страницу
- MAX_PROFESSIONS: максимальное количество профессий
- MIN_VACANCIES_PER_PROFESSION: минимум вакансий на профессию
- FUZZY_MATCH_THRESHOLD: порог схожести для группировки

"""

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import json
import re
import os
import time
from datetime import datetime
from typing import List, Dict
from fuzzywuzzy import fuzz
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np
from dotenv import load_dotenv
from parsers.embedding_matcher import EmbeddingProfessionMatcher

# Настройки парсера
FUZZY_MATCH_THRESHOLD = 65          # Порог схожести для fuzzy matching
EMBEDDING_THRESHOLD = 0.77          # Порог схожести для эмбеддингов (0.0-1.0)
USE_EMBEDDINGS = True               # Использовать эмбеддинги вместо fuzzy matching
MAX_PROFESSIONS = 400               # Топ количество профессий для вывода
MIN_VACANCIES_PER_PROFESSION = 5    # Минимум вакансий на профессию для ранней остановки
VERBOSE_LOGGING = False             # Подробные логи сопоставления (для отладки)

# Настройки обработки
MAX_PAGES = 1000                       # Максимальное количество страниц для обработки (с OAuth лимиты выше)
VACANCIES_PER_PAGE = 50            # Вакансий на страницу

# Настройки TF-IDF
USE_TFIDF = True                    # Использовать TF-IDF для улучшения сравнения
TFIDF_MAX_FEATURES = 20000          # Максимальное количество признаков TF-IDF
TOP_SKILLS = 15                     # Количество топ навыков для TF-IDF

# Настройки региона
RUSSIA_AREA_ID = 113                # ID России в системе HeadHunter

# Конфигурация OAuth2 через переменные окружения
# Загружаем .env, если он есть рядом с проектом
load_dotenv()
CLIENT_ID = os.getenv("HH_CLIENT_ID")
CLIENT_SECRET = os.getenv("HH_CLIENT_SECRET")
REDIRECT_URI = os.getenv("HH_REDIRECT_URI")

# Глобальные переменные для TF-IDF кэширования
tfidf_vectorizer = None
profession_tfidf_vectors = {}
profession_texts = []



def format_time(seconds: float) -> str:
    """
    Форматировать время в читаемый вид.
    """
    if seconds < 60:
        return f"{seconds:.1f} секунд"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        secs = seconds % 60
        return f"{minutes} мин {secs:.1f} сек"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = seconds % 60
        return f"{hours} ч {minutes} мин {secs:.1f} сек"


def create_profession_text(title: str, skills: List[str]) -> str:
    """
    Создать текстовое представление профессии для TF-IDF.
    normalized_title + top-N skills
    """
    normalized_title = normalize_profession_title(title)
    
    # Берем топ навыков
    top_skills = skills[:TOP_SKILLS] if skills else []
    skills_text = " ".join(top_skills)
    
    return f"{normalized_title} {skills_text}".strip()


def initialize_tfidf(professions: Dict[str, Dict]) -> None:
    """
    Инициализировать TF-IDF векторizer и построить векторы для существующих профессий.
    """
    global tfidf_vectorizer, profession_tfidf_vectors, profession_texts
    
    if not USE_TFIDF or not professions:
        return
    
    # Собираем тексты всех профессий
    profession_texts = []
    profession_keys = []
    
    for prof_key, prof_data in professions.items():
        title = prof_data.get('title', prof_key)
        skills = prof_data.get('skills', [])
        text = create_profession_text(title, skills)
        profession_texts.append(text)
        profession_keys.append(prof_key)
    
    if not profession_texts:
        return
    
    # Создаем TF-IDF векторizer
    tfidf_vectorizer = TfidfVectorizer(
        max_features=TFIDF_MAX_FEATURES,
        stop_words=None,  # Не используем стоп-слова, так как у нас уже нормализованные тексты
        lowercase=True,
        ngram_range=(1, 2)  # Униграммы и биграммы
    )
    
    # Обучаем на текстах профессий
    tfidf_matrix = tfidf_vectorizer.fit_transform(profession_texts)
    
    # Сохраняем векторы для каждой профессии
    for i, prof_key in enumerate(profession_keys):
        profession_tfidf_vectors[prof_key] = tfidf_matrix[i]
    


def update_tfidf_with_new_profession(prof_key: str, title: str, skills: List[str]) -> None:
    """
    Добавить новую профессию в TF-IDF кэш.
    """
    global tfidf_vectorizer, profession_tfidf_vectors, profession_texts
    
    if not USE_TFIDF or not tfidf_vectorizer:
        return
    
    # Создаем текст для новой профессии
    new_text = create_profession_text(title, skills)
    
    # Добавляем в список текстов
    profession_texts.append(new_text)
    
    # Создаем вектор для новой профессии
    new_vector = tfidf_vectorizer.transform([new_text])
    profession_tfidf_vectors[prof_key] = new_vector[0]
    


def calculate_tfidf_similarity(vacancy_title: str, vacancy_skills: List[str], prof_key: str) -> float:
    """
    Вычислить TF-IDF similarity между вакансией и профессией.
    Возвращает значение от 0 до 100.
    """
    global tfidf_vectorizer, profession_tfidf_vectors
    
    if not USE_TFIDF or not tfidf_vectorizer or prof_key not in profession_tfidf_vectors:
        return 0.0
    
    # Создаем текст для вакансии
    vacancy_text = create_profession_text(vacancy_title, vacancy_skills)
    
    # Создаем вектор для вакансии
    vacancy_vector = tfidf_vectorizer.transform([vacancy_text])
    
    # Вычисляем cosine similarity
    similarity = cosine_similarity(vacancy_vector, profession_tfidf_vectors[prof_key].reshape(1, -1))[0][0]
    
    # Преобразуем в проценты
    return similarity * 100


def clean_html_tags(text: str) -> str:
    """
    Очистить HTML теги из текста.
    """
    if not text:
        return ""
    
    # Убираем HTML теги
    clean_text = re.sub(r'<[^>]+>', '', text)
    
    # Убираем лишние пробелы и переносы строк
    clean_text = re.sub(r'\s+', ' ', clean_text)
    clean_text = clean_text.strip()
    
    return clean_text


def extract_core_profession(title: str) -> str:
    """
    Извлечь основную профессию из длинного названия вакансии.
    Убирает специфические детали места работы, компании, сферы И технологии.
    """
    # Приводим к нижнему регистру
    core = title.lower().strip()
    
    # Убираем специфические детали места работы
    location_patterns = [
        r'в\s+\w+\s+центр\w*',           # "в бизнес центр", "в торговый центр"
        r'в\s+дом\w*',                   # "в дом", "в жилой дом"
        r'в\s+\w+\s+компани\w*',         # "в производственную компанию"
        r'в\s+сфере\s+\w+',              # "в сфере металлургии"
        r'в\s+\w+\s+сфере',              # "в IT сфере"
        r'в\s+\w+\s+области',            # "в области продаж"
        r'в\s+\w+\s+направлении',        # "в направлении маркетинга"
        r'\([^)]*\)',                    # (строительная компания), (Middle/Middle+)
        r'\[[^\]]*\]',                   # [React/Next.js]
        r'—.*$',                         # — React / Next.js
    ]
    
    for pattern in location_patterns:
        core = re.sub(pattern, '', core)
    
    # Убираем лишние слова и символы
    stop_words = ['senior', 'junior', 'middle', 'lead', 'principal', 'staff', 'sr', 'jr', 'mid', 'стажёр', 'ведущий', 'zarina']
    for word in stop_words:
        core = core.replace(word, '')
    
    # Убираем технологии для объединения похожих профессий
    tech_words = [
        'vue', 'vue.js', 'vuejs',
        'react', 'react.js', 'reactjs', 
        'angular', 'angular.js',
        'next.js', 'nextjs',
        'node.js', 'nodejs',
        'typescript', 'ts',
        'javascript', 'js',
        'py', 'spring',
        'csharp', 'cpp',
        'php', 'laravel',
        'django', 'flask', 'fastapi',
        'html', 'css', 'sass', 'scss',
        'webpack', 'gulp', 'vite'
    ]
    
    for tech in tech_words:
        core = core.replace(tech, '')
    
    # Убираем лишние пробелы и знаки препинания
    core = re.sub(r'[^\w\s]', ' ', core)
    core = re.sub(r'\s+', ' ', core).strip()
    
    return core


def normalize_profession_title(title: str) -> str:
    """
    Нормализовать название профессии для лучшего сопоставления.
    Извлекает основную суть профессии.
    """
    # Извлекаем основную профессию (технологии уже удалены в extract_core_profession)
    normalized = extract_core_profession(title)
    
    return normalized


def enrich_profession_data(profession: Dict, new_vacancy: Dict) -> Dict:
    """
    Обогатить данные профессии новой вакансией.
    Обновляет описание, навыки, индустрию, зарплату и другие поля.
    """
    # Объединяем описания (очищаем от HTML тегов)
    current_desc = clean_html_tags(profession.get('description', ''))
    new_desc = clean_html_tags(new_vacancy.get('description', ''))
    if new_desc and new_desc not in current_desc:
        profession['description'] = f"{current_desc}\n\n{new_desc}".strip()
    
    # Объединяем навыки
    current_skills = set(profession.get('skills', []))
    new_skills = set(new_vacancy.get('skills', []))
    profession['skills'] = list(current_skills.union(new_skills))
    
    # Объединяем индустрии
    current_industry = profession.get('industry', '')
    new_industry = new_vacancy.get('industry', '')
    if new_industry and new_industry not in current_industry:
        if current_industry:
            profession['industry'] = f"{current_industry}, {new_industry}"
        else:
            profession['industry'] = new_industry
    
    # Обновляем зарплату (берем максимальную или добавляем диапазон)
    current_salary = profession.get('salary', '')
    new_salary = new_vacancy.get('salary', '')
    if new_salary:
        if not current_salary:
            profession['salary'] = new_salary
        else:
            # Если зарплаты разные, объединяем их
            if new_salary != current_salary:
                profession['salary'] = f"{current_salary}, {new_salary}"
    
    # Обновляем опыт (собираем все варианты)
    current_exp = profession.get('experience', '')
    new_exp = new_vacancy.get('experience', '')
    if new_exp:
        if not current_exp:
            profession['experience'] = new_exp
        elif new_exp not in current_exp:
            profession['experience'] = f"{current_exp}, {new_exp}"
    
    # Обновляем тип занятости (собираем все варианты)
    current_emp = profession.get('employment', '')
    new_emp = new_vacancy.get('employment', '')
    if new_emp:
        if not current_emp:
            profession['employment'] = new_emp
        elif new_emp not in current_emp:
            profession['employment'] = f"{current_emp}, {new_emp}"
    
    # Добавляем вакансию в список
    profession['vacancies'].append(new_vacancy)
    
    return profession


def _build_hh_session() -> requests.Session:
    """
    Создать requests.Session с User-Agent, OAuth авторизацией и политикой повторов для hh.ru.
    """
    session = requests.Session()
    headers = {
        "User-Agent": "itmo-hackathon-bot/1.0"
    }
    
    # Добавляем OAuth авторизацию если токены доступны
    if CLIENT_ID and CLIENT_SECRET:
        # Получаем access token
        token_url = "https://hh.ru/oauth/token"
        token_data = {
            "grant_type": "client_credentials",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET
        }
        try:
            token_resp = session.post(token_url, data=token_data)
            if token_resp.status_code == 200:
                access_token = token_resp.json().get("access_token")
                if access_token:
                    headers["Authorization"] = f"Bearer {access_token}"
                    print("✅ OAuth авторизация успешна")
                else:
                    print("⚠️  Не удалось получить access token")
            else:
                print(f"⚠️  Ошибка получения токена: {token_resp.status_code}")
        except Exception as e:
            print(f"⚠️  Ошибка OAuth: {e}")
    else:
        print("⚠️  OAuth токены не настроены, используем анонимный доступ")
    
    session.headers.update(headers)
    retries = Retry(
        total=5,
        backoff_factor=0.8,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def _get_with_retry(session: requests.Session, url: str, params: Dict = None, timeout: int = 15) -> requests.Response:
    """
    GET-запрос с ручными повторными попытками и экспоненциальной паузой в дополнение к внутренним ретраям.
    """
    attempts = 5
    for i in range(attempts):
        try:
            resp = session.get(url, params=params, timeout=timeout)
            if resp.status_code == 429:
                # ручной бэкофф при rate limit
                time.sleep(2 + i)
                continue
            resp.raise_for_status()
            return resp
        except requests.RequestException:
            if i == attempts - 1:
                raise
            time.sleep(1.2 * (i + 1))
    # теоретически недостижимо
    raise RuntimeError("Не удалось выполнить запрос после повторов")


def process_vacancies_sequentially(pages: int = 5, per_page: int = 50, 
                                 max_professions: int = 10, 
                                 threshold: int = 80, start_page: int = 0,
                                 use_embeddings: bool = None) -> Dict[str, Dict]:
    """
    Последовательно обрабатывать вакансии, группируя их по профессиям в реальном времени.
    Возвращает топ профессий по количеству вакансий.
    """
    
    # Определяем, использовать ли эмбеддинги
    if use_embeddings is None:
        use_embeddings = USE_EMBEDDINGS
    
    # Запускаем таймер
    start_time = time.time()
    
    professions = {}  # Словарь профессий: {title: profession_data}
    processed_count = 0
    profession_matcher = None  # Матчер эмбеддингов
    stop_early = False  # Флаг для ранней остановки при достижении цели
    
    print(f"Начинаем последовательную обработку вакансий...")
    print(f"Цель: собрать топ {max_professions} профессий по количеству вакансий")
    print(f"🔍 Режим сопоставления: {'Эмбеддинги' if use_embeddings else 'Fuzzy Matching'}")
    
    # Подготавливаем HTTP-сессию
    http = _build_hh_session()
    
    for page in range(pages):
        page_start_time = time.time()
        actual_page = start_page + page
        print(f"Обрабатываем страницу {actual_page + 1} (пакет {page + 1}/{pages})...")
        
        # Получаем вакансии со страницы (только из России)
        url = "https://api.hh.ru/vacancies"
        params = {
            "per_page": per_page,
            "page": actual_page,
            "area": RUSSIA_AREA_ID,  # ID России в системе HeadHunter
            "date_from": "2022-01-01",  # Фильтр по дате - вакансии не позже 2022 года
            "order_by": "publication_time"  # Сортировка по времени публикации
        }
        try:
            response = _get_with_retry(http, url, params=params, timeout=15)
            if response.status_code == 400:
                print(f"⚠️  API лимит достигнут на странице {actual_page + 1}. Останавливаем сбор.")
                break
        except Exception as e:
            print(f"Ошибка запроса списка вакансий на странице {page + 1}: {e}")
            time.sleep(0.7)
            continue
        # небольшая задержка между страницами
        time.sleep(0.35)
            
        vacancies = response.json().get("items", [])
        
        for vacancy_data in vacancies:
            processed_count += 1
            vacancy_id = vacancy_data.get("id")
            
            # Получаем детальную информацию о вакансии
            detail_url = f"https://api.hh.ru/vacancies/{vacancy_id}"
            try:
                detail_resp = _get_with_retry(http, detail_url, timeout=20)
            except Exception as e:
                print(f"⚠️  Пропускаем вакансию {vacancy_id}: {e}")
                time.sleep(0.4)
                continue
            # небольшая задержка между детальными запросами
            time.sleep(0.35)
                
            detail = detail_resp.json()
            
            # Формируем структуру вакансии
            salary = detail.get("salary")
            salary_str = None
            if salary:
                salary_from = salary.get("from")
                salary_to = salary.get("to")
                currency = salary.get("currency")
                salary_str = f"{salary_from or ''}-{salary_to or ''} {currency}" if salary_from or salary_to else None
            
            # Получаем индустрию только из реальных данных API
            industry = None
            if detail.get("employer", {}).get("industries"):
                industry = ", ".join([ind.get("name","") for ind in detail["employer"]["industries"]])
            
            vacancy = {
                "id": vacancy_id,
                "name": detail.get("name",""),
                "salary": salary_str,
                "industry": industry,
                "description": clean_html_tags(detail.get("description", "")),
                "skills": [skill.get("name") for skill in detail.get("key_skills",[])],
                "experience": detail.get("experience",{}).get("name",""),
                "employment": detail.get("employment",{}).get("name","")
            }
            
            # Ищем подходящую профессию с улучшенным fuzzy matching + TF-IDF
            name = vacancy.get("name", "").strip()
            description = vacancy.get("description", "").strip()
            skills = vacancy.get("skills", [])
            
            # Извлекаем основную профессию и нормализуем
            core_profession = extract_core_profession(name)
            normalized_name = normalize_profession_title(name)
            
            matched_profession = None
            similarity_score = 0
            
            if use_embeddings and professions:
                # НОВЫЙ ПОДХОД: Используем эмбеддинги для сопоставления
                try:
                    # Инициализируем матчер при первом использовании
                    if profession_matcher is None:
                        if VERBOSE_LOGGING:
                            print("🔍 Инициализация векторного сопоставления профессий...")
                        profession_matcher = EmbeddingProfessionMatcher(professions, threshold=EMBEDDING_THRESHOLD)
                        if VERBOSE_LOGGING:
                            print("✅ Векторный матчер готов")
                    
                    # Ищем лучшее совпадение
                    match_result = profession_matcher.find_best_match(
                        vacancy_title=name,
                        vacancy_description=description,
                        vacancy_skills=skills
                    )
                    
                    if match_result:
                        matched_profession, similarity_score = match_result
                        # Доп. защита: если профессия водительская, отсекаем офисные роли
                        try:
                            mp_low = (matched_profession or "").lower()
                            is_driver_prof = ("водител" in mp_low) or ("driver" in mp_low)
                            if is_driver_prof:
                                if profession_matcher._is_blacklisted_for_driver(name, description, skills) and not profession_matcher._has_driver_signals(name, description, skills):
                                    print(f"🚫 Отклонено доменным правилом: '{name}' не водитель (ембеддинг предлагал '{matched_profession}')")
                                    matched_profession = None
                                    similarity_score = 0
                        except Exception:
                            pass
                        if matched_profession and VERBOSE_LOGGING:
                            print(f"🎯 Найдено совпадение: '{name}' -> '{matched_profession}' (схожесть: {similarity_score:.1f}%)")
                    
                except Exception as e:
                    print(f"❌ Ошибка векторного сопоставления: {e}")
                    print("🔄 Переключаемся на fuzzy matching...")
                    use_embeddings = False
                    profession_matcher = None
            
            if not use_embeddings or not matched_profession:
                # СТАРЫЙ ПОДХОД: Fuzzy matching
                skills_text = " ".join(skills) if skills else ""
                # Ограничиваем длину описания вакансии для экономии памяти
                if len(description) > 1000:
                    description = description[:1000] + "..."
                full_text = f"{normalized_name} {description} {skills_text}".lower()
                
                best_score = 0
                
                for prof_title, prof_data in professions.items():
                    prof_description = prof_data.get('description', '')
                    # Ограничиваем длину описания для экономии памяти при сравнении
                    if len(prof_description) > 1000:
                        prof_description = prof_description[:1000] + "..."
                    
                    prof_skills = prof_data.get('skills', [])
                    prof_skills_text = " ".join(prof_skills) if prof_skills else ""
                    prof_full_text = f"{prof_title} {prof_description} {prof_skills_text}".lower()
                    
                    # Извлекаем основную профессию из существующей профессии
                    prof_core = extract_core_profession(prof_title)
                    normalized_prof_title = normalize_profession_title(prof_title)
                    
                    # Используем комбинацию разных алгоритмов fuzzy matching
                    score1 = fuzz.token_set_ratio(full_text, prof_full_text)  # Сравнение по полному тексту
                    score2 = fuzz.partial_ratio(normalized_name, normalized_prof_title)  # Частичное сравнение нормализованных названий
                    score3 = fuzz.ratio(normalized_name, normalized_prof_title)  # Точное сравнение нормализованных названий
                    score4 = fuzz.token_sort_ratio(normalized_name, normalized_prof_title)  # Сравнение по отсортированным токенам
                    
                    # НОВОЕ: Сравнение основных профессий (без специфических деталей)
                    score5 = fuzz.ratio(core_profession, prof_core)  # Сравнение основных профессий
                    score6 = fuzz.partial_ratio(core_profession, prof_core)  # Частичное сравнение основных профессий
                    
                    # TF-IDF similarity (если включен)
                    score7 = calculate_tfidf_similarity(name, skills, prof_title) if USE_TFIDF else 0
                    
                    # Взвешенная оценка с приоритетом на основные профессии
                    if USE_TFIDF:
                        combined_score = (score1 * 0.2) + (score2 * 0.15) + (score3 * 0.1) + (score4 * 0.1) + (score5 * 0.25) + (score6 * 0.1) + (score7 * 0.1)
                    else:
                        combined_score = (score1 * 0.25) + (score2 * 0.2) + (score3 * 0.15) + (score4 * 0.1) + (score5 * 0.2) + (score6 * 0.1)
                    
                    if combined_score >= threshold and combined_score > best_score:
                        best_score = combined_score
                        matched_profession = prof_title
                        similarity_score = best_score
            
            if matched_profession:
                # Обогащаем существующую профессию
                professions[matched_profession] = enrich_profession_data(
                    professions[matched_profession], vacancy
                )
                
                # Обновляем матчер эмбеддингов с новой информацией
                if use_embeddings and profession_matcher:
                    try:
                        profession_matcher.add_new_profession(matched_profession, professions[matched_profession])
                    except Exception as e:
                        print(f"⚠️  Не удалось обновить векторный индекс: {e}")
            else:
                # Создаем новую профессию с ключом на основе основной профессии
                profession_key = core_profession if core_profession else normalized_name
                
                professions[profession_key] = {
                    'title': profession_key,  # Используем чистый ключ профессии
                    'description': description,
                    'skills': vacancy.get('skills', []),
                    'industry': industry,
                    'salary': salary_str,
                    'experience': vacancy.get('experience', ''),
                    'employment': vacancy.get('employment', ''),
                    'vacancies': [vacancy]
                }
                
                # Обновляем TF-IDF кэш для новой профессии
                if USE_TFIDF:
                    update_tfidf_with_new_profession(profession_key, name, vacancy.get('skills', []))
                
                # Добавляем новую профессию в матчер эмбеддингов
                if use_embeddings and profession_matcher:
                    try:
                        profession_matcher.add_new_profession(profession_key, professions[profession_key])
                    except Exception as e:
                        print(f"⚠️  Не удалось добавить профессию в векторный индекс: {e}")
            
            # Проверяем условие ранней остановки: есть ли как минимум max_professions
            # профессий, у которых набралось не меньше MIN_VACANCIES_PER_PROFESSION вакансий
            try:
                ready_professions = sum(1 for p in professions.values() if len(p.get('vacancies', [])) >= MIN_VACANCIES_PER_PROFESSION)
                if ready_professions >= max_professions:
                    print(f"✅ Достигнута цель: {ready_professions} профессий имеют не меньше {MIN_VACANCIES_PER_PROFESSION} вакансий. Останавливаем сбор.")
                    stop_early = True
                    break
            except Exception:
                pass
            
            # Продолжаем обработку всех страниц для сбора максимального количества данных
            
            # Не удаляем профессии во время обработки - даем им шанс набрать вакансии
        
        # Инициализируем TF-IDF после первой страницы (когда есть первые профессии)
        if page == 0 and USE_TFIDF and professions:
            initialize_tfidf(professions)
        
        # Выводим время обработки страницы и общую статистику
        page_end_time = time.time()
        page_time = page_end_time - page_start_time
        total_elapsed = page_end_time - start_time
        print(f"  ⏱️  Страница {actual_page + 1} обработана за {format_time(page_time)}")
        print(f"  📊 Создано профессий: {len(professions)}")
        print(f"  ⏱️  Общее время: {format_time(total_elapsed)}")
        
        # Сохраняем резервную копию после каждой страницы
        if professions:  # Сохраняем только если есть профессии
            save_backup_professions(professions, actual_page + 1, pages)
            print(f"  💾 Резервная копия обновлена")
        
        # Ранняя остановка после обработки текущей страницы
        if stop_early:
            break
        
        # Обрабатываем все страницы для максимального сбора данных
    
    # Сортируем все профессии по количеству вакансий (больше вакансий = лучше)
    all_professions = list(professions.items())
    all_professions.sort(key=lambda x: len(x[1]['vacancies']), reverse=True)
    
    # Берем топ профессии (до max_professions)
    result = {}
    for title, prof_data in all_professions[:max_professions]:
        result[title] = prof_data
    
    # Вычисляем время работы
    end_time = time.time()
    total_time = end_time - start_time
    
    print(f"\n=== СТАТИСТИКА ОБРАБОТКИ ===")
    print(f"Обработано вакансий: {processed_count}")
    print(f"Создано профессий: {len(professions)}")
    print(f"Топ профессий для вывода: {len(result)}")
    print(f"Максимум вакансий для обработки: {pages * per_page}")
    print(f"Процент обработанных вакансий: {(processed_count / (pages * per_page)) * 100:.1f}%")
    print(f"⏱️  Время работы: {format_time(total_time)}")
    
    return result






def create_detailed_professions_file(professions: Dict[str, Dict]) -> Dict[str, Dict]:
    """
    Создать детальный файл с профессиями, где каждая профессия содержит:
    - описание, навыки, индустрия, зарплата, опыт, занятость
    - список всех вакансий этой профессии
    """
    detailed_professions = {}
    
    for title, prof_data in professions.items():
        vacancies = prof_data.get('vacancies', [])
        if not vacancies:
            continue
            
        # Создаем структуру профессии
        profession = {
            "title": title,
            "description": prof_data.get('description', ''),
            "skills": prof_data.get('skills', []),
            "industry": prof_data.get('industry', ''),
            "salary": prof_data.get('salary', ''),
            "experience": prof_data.get('experience', ''),
            "employment": prof_data.get('employment', ''),
            "vacancy_count": len(vacancies),
            "vacancies": vacancies
        }
        
        detailed_professions[title] = profession
    
    return detailed_professions


def create_comparison_text_file(professions: Dict[str, Dict]) -> Dict[str, str]:
    """
    Создать файл для сравнения, где каждая профессия представлена как текст:
    "описание: текст; навыки: список; зарплата: диапазон; индустрия: список; опыт: уровень; занятость: тип"
    """
    comparison_texts = {}
    
    for title, prof_data in professions.items():
        # Формируем текстовое представление профессии
        parts = []
        
        # Описание
        description = prof_data.get('description', '')
        if description and isinstance(description, str):
            description = description.strip()
            if description:
                parts.append(f"описание: {description}")
        
        # Навыки
        skills = prof_data.get('skills', [])
        if skills:
            # Фильтруем None значения
            valid_skills = [skill for skill in skills if skill is not None]
            if valid_skills:
                skills_text = ", ".join(valid_skills)
                parts.append(f"навыки: {skills_text}")
        
        # Зарплата
        salary = prof_data.get('salary', '')
        if salary and isinstance(salary, str):
            salary = salary.strip()
            if salary:
                parts.append(f"зарплата: {salary}")
        
        # Индустрия
        industry = prof_data.get('industry', '')
        if industry and isinstance(industry, str):
            industry = industry.strip()
            if industry:
                parts.append(f"индустрия: {industry}")
        
        # Опыт
        experience = prof_data.get('experience', '')
        if experience and isinstance(experience, str):
            experience = experience.strip()
            if experience:
                parts.append(f"опыт: {experience}")
        
        # Занятость
        employment = prof_data.get('employment', '')
        if employment and isinstance(employment, str):
            employment = employment.strip()
            if employment:
                parts.append(f"занятость: {employment}")
        
        # Объединяем все части через точку с запятой
        full_text = "; ".join(parts)
        comparison_texts[title] = full_text
    
    return comparison_texts


def create_profession_knowledge_base(professions: Dict[str, Dict]) -> Dict[str, Dict]:
    """
    Создать обогащенную базу знаний по профессиям на основе собранных вакансий.
    Извлекает ключевую информацию: требования, навыки, зарплаты, индустрии и т.д.
    """
    knowledge_base = {}
    
    for title, prof_data in professions.items():
        vacancies = prof_data.get('vacancies', [])
        if not vacancies:
            continue
            
        # Анализируем все вакансии профессии
        all_skills = []
        all_industries = []
        salary_ranges = []
        experience_levels = []
        employment_types = []
        
        for vacancy in vacancies:
            # Собираем навыки
            all_skills.extend(vacancy.get('skills', []))
            
            # Собираем индустрии
            if vacancy.get('industry'):
                all_industries.append(vacancy.get('industry'))
            
            # Собираем зарплаты
            if vacancy.get('salary'):
                salary_ranges.append(vacancy.get('salary'))
            
            # Собираем уровни опыта
            if vacancy.get('experience'):
                experience_levels.append(vacancy.get('experience'))
            
            # Собираем типы занятости
            if vacancy.get('employment'):
                employment_types.append(vacancy.get('employment'))
        
        # Создаем обогащенную запись профессии
        knowledge_base[title] = {
            'title': title,
            'description': prof_data.get('description', ''),
            'key_skills': list(set(all_skills)),  # Уникальные навыки
            'industries': list(set(all_industries)),  # Уникальные индустрии
            'salary_info': {
                'ranges': salary_ranges,
                'count': len(salary_ranges)
            },
            'experience_requirements': list(set(experience_levels)),
            'employment_types': list(set(employment_types)),
            'vacancy_count': len(vacancies),
            'sample_vacancies': vacancies[:3],  # Первые 3 вакансии как примеры
            'statistics': {
                'total_skills': len(set(all_skills)),
                'total_industries': len(set(all_industries)),
                'avg_salary_mentions': len(salary_ranges) / len(vacancies) if vacancies else 0
            }
        }
    
    return knowledge_base


def save_to_json(data: Dict, filename: str):
    """Сохранить данные в JSON, создать папку если нужно"""
    folder = os.path.dirname(filename)
    if folder and not os.path.exists(folder):
        os.makedirs(folder)
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_backup_filename() -> str:
    """
    Получить имя файла для резервной копии (один файл, перезаписывается).
    """
    return "data/backup_hh_professions_current.json"


def save_backup_professions(professions: Dict[str, Dict], page_num: int, total_pages: int) -> str:
    """
    Сохранить резервную копию профессий после обработки страницы.
    Перезаписывает один и тот же файл.
    Возвращает путь к сохраненному файлу.
    """
    backup_filename = get_backup_filename()
    
    # Создаем детальную структуру для резервной копии
    detailed_professions = create_detailed_professions_file(professions)
    
    # Добавляем метаданные о резервной копии
    backup_data = {
        "backup_info": {
            "page_number": page_num,
            "total_pages": total_pages,
            "updated_at": datetime.now().isoformat(),
            "professions_count": len(professions),
            "total_vacancies": sum(len(prof.get('vacancies', [])) for prof in professions.values())
        },
        "professions": detailed_professions
    }
    
    save_to_json(backup_data, backup_filename)
    return backup_filename

if __name__ == "__main__":
    # Запускаем общий таймер программы
    program_start_time = time.time()
    
    print(f"🚀 Сбор вакансий с hh.ru...")
    print(f"Настройки: MAX_PROFESSIONS={MAX_PROFESSIONS}")
    if USE_EMBEDDINGS:
        print(f"🔍 Эмбеддинги: ВКЛЮЧЕНЫ (порог: {EMBEDDING_THRESHOLD})")
    else:
        print(f"🔍 Fuzzy Matching: ВКЛЮЧЕН (порог: {FUZZY_MATCH_THRESHOLD})")
    print(f"Максимум вакансий для обработки: {MAX_PAGES * VACANCIES_PER_PAGE:,}")
    print("📅 Фильтр по дате: вакансии с 2022 года")
    if CLIENT_ID and CLIENT_SECRET:
        print("🔐 OAuth авторизация: ВКЛЮЧЕНА (повышенные лимиты)")
    else:
        print("⚠️  OAuth авторизация: ОТКЛЮЧЕНА (ограниченные лимиты)")
    
    # Используем последовательную обработку
    grouped = process_vacancies_sequentially(
        pages=MAX_PAGES, 
        per_page=VACANCIES_PER_PAGE,
        max_professions=MAX_PROFESSIONS,
        threshold=FUZZY_MATCH_THRESHOLD,
        use_embeddings=USE_EMBEDDINGS
    )
    
    print(f"Выбрано профессий: {len(grouped)}")
    
    # Создаем детальный файл с профессиями и вакансиями
    print("\nСоздание детального файла профессий...")
    detailed_professions = create_detailed_professions_file(grouped)
    save_to_json(detailed_professions, "data/hh_detailed_professions.json")
    print("Детальные данные профессий сохранены в data/hh_detailed_professions.json")
    
    # Создаем файл для сравнения (текстовое представление)
    print("\nСоздание файла для сравнения...")
    comparison_texts = create_comparison_text_file(grouped)
    save_to_json(comparison_texts, "data/hh_professions_comparison.json")
    print("Файл для сравнения сохранен в data/hh_professions_comparison.json")
    
    # Вычисляем общее время работы программы
    program_end_time = time.time()
    total_program_time = program_end_time - program_start_time
    
    # Выводим статистику
    print(f"\n=== ФИНАЛЬНАЯ СТАТИСТИКА ===")
    print(f"Всего профессий: {len(detailed_professions)}")
    for title, data in detailed_professions.items():
        print(f"  {title}: {data['vacancy_count']} вакансий, {len(data['skills'])} навыков")
    
    print(f"\n⏱️  ОБЩЕЕ ВРЕМЯ РАБОТЫ ПРОГРАММЫ: {format_time(total_program_time)}")
    print(f"✅ Программа завершена успешно!")
