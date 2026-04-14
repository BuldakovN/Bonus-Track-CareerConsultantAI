import re
import time
from dataclasses import dataclass
from typing import Generator, Iterable, List, Optional, Any, Dict

import requests
from bs4 import BeautifulSoup

from .config import config
from .schema import EducationProgram


BASE_DOMAINS = {
    "msk": "https://msk.postupi.online",
    "spb": "https://spb.postupi.online",
    "kazan": "https://kazan.postupi.online",
    # "nnov": "https://nnov.postupi.online",
    # "tomsk": "https://tomsk.postupi.online",
}


@dataclass
class HtmlClient:
    base_url: str

    def __post_init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": config.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
            }
        )

    def get(self, path_or_url: str) -> str:
        url = path_or_url
        if path_or_url.startswith("/"):
            url = f"{self.base_url}{path_or_url}"
        resp = self.session.get(url, timeout=60)
        resp.raise_for_status()
        # Улучшаем детекцию кодировки (на сайте встречается windows-1251)
        try:
            if not resp.encoding:
                resp.encoding = resp.apparent_encoding or "utf-8"
        except Exception:
            resp.encoding = resp.encoding or "utf-8"
        text = resp.text
        return text


def iterate_postupi_programs(
    cities: Optional[List[str]] = None,
    throttle_sec: float = 0.7,
) -> Generator[EducationProgram, None, None]:
    """Итерирует по программам выбранных городов и выдает объекты EducationProgram."""
    if not cities:
        cities = list(BASE_DOMAINS.keys())

    seen_program_ids: set[str] = set()
    for city in cities:
        base = BASE_DOMAINS.get(city)
        if not base:
            continue
        client = HtmlClient(base)

        # Список вузов в городе
        university_pages: List[str] = []
        try:
            # Сначала пробуем явный список /vuzi/
            university_pages = list_university_pages_from_vuzi(client)
        except Exception:
            university_pages = []

        # Fallback: список /vuz/ с пагинацией, затем лёгкий краулер
        if not university_pages:
            try:
                university_pages = list_university_pages(client)
                if not university_pages:
                    university_pages = crawl_city_for_universities(client)
            except Exception:
                university_pages = []

        for uni_url in university_pages:
            # Ссылки на все варианты программ в рамках вуза
            try:
                prog_links = list_program_links_on_university(client, uni_url)
            except Exception:
                prog_links = []

            for prog_url in prog_links:
                try:
                    program = parse_program_page(client, prog_url)
                    if program:
                        if program.id in seen_program_ids:
                            continue
                        seen_program_ids.add(program.id)
                        yield program
                except Exception:
                    # Игнорируем единичные ошибки страниц
                    pass
                time.sleep(throttle_sec)


def _abs(client: HtmlClient, href: str) -> str:
    if href.startswith("http://") or href.startswith("https://"):
        return href
    if not href.startswith("/"):
        href = "/" + href
    return f"{client.base_url}{href}"


def _extract_text(el) -> str:
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)) if el else ""


def list_university_pages(client: HtmlClient, max_pages: int = 200) -> List[str]:
    """Возвращает ссылки на страницы вузов города, обходя пагинацию на /vuz/"""
    pages: List[str] = []
    page_num = 1
    max_page_detected = None
    while True:
        path = "/vuz/" if page_num == 1 else f"/vuz/?page={page_num}"
        html = client.get(path)
        soup = BeautifulSoup(html, "lxml")

        # Карточки вузов с ссылками вида /vuz/<slug>/
        new_links: List[str] = []
        # Несколько вариантов селекторов: карточки, заголовки, списки; также data-href/onclick
        candidates = soup.select('a, div, article, li')
        for a in candidates:
            href = a.get("href") or a.get("data-href") or ""
            if not href and a.get("onclick"):
                m_on = re.search(r"'(\/vuz\/[^']+)'", a.get("onclick") or "")
                if m_on:
                    href = m_on.group(1)
            # отфильтровываем служебные ссылки типа /vuz/?page=2
            if not href.startswith("/vuz/"):
                continue
            if href.startswith("/vuz/?"):
                continue
            if any(sub in href for sub in ["variant-programmi", "variant-programmi-magistr", "?", "#"]):
                continue
            # оставляем страницы вузов вида /vuz/<slug>/ или более глубокие /vuz/<slug>/.../
            # (иногда профиль вуза может иметь поддиректории)
            if not href.endswith("/"):
                href += "/"
            url = _abs(client, href)
            new_links.append(url)

        # Уникализируем в рамках страницы
        unique = []
        seen = set()
        for u in new_links:
            if u not in seen:
                unique.append(u)
                seen.add(u)

        if not unique:
            break

        pages.extend(unique)

        # Пытаемся понять, есть ли следующая страница
        # Переход на следующую страницу (разные варианты пагинации)
        # Находим максимальный номер страницы
        if max_page_detected is None:
            pages_nums = []
            for a in soup.select('a[href*="/vuz/?page="]'):
                m = re.search(r"page=(\d+)", a.get("href") or "")
                if m:
                    try:
                        pages_nums.append(int(m.group(1)))
                    except Exception:
                        pass
            if pages_nums:
                max_page_detected = max(pages_nums)

        if (max_page_detected is not None and page_num >= max_page_detected) or page_num >= max_pages:
            break
        page_num += 1
        time.sleep(0.5)

    # Финальная уникализация
    final: List[str] = []
    seen_final = set()
    for u in pages:
        if u not in seen_final:
            final.append(u)
            seen_final.add(u)
    return final


def list_university_pages_from_vuzi(client: HtmlClient, max_pages: int = 200) -> List[str]:
    """Собирает страницы вузов с раздела /vuzi/ с учётом пагинации."""
    pages: List[str] = []
    seen = set()
    page_num = 1
    while page_num <= max_pages:
        path = "/vuzi/" if page_num == 1 else f"/vuzi/?page={page_num}"
        try:
            html = client.get(path)
        except Exception:
            break
        soup = BeautifulSoup(html, "lxml")

        # Карточки вузов часто имеют ссылки формата /vuz/<slug>/
        new_links: List[str] = []
        for a in soup.select('a, div, article, li'):
            href = a.get("href") or a.get("data-href") or ""
            if not href and a.get("onclick"):
                m_on = re.search(r"'(\/vuz\/[^']+)'", a.get("onclick") or "")
                if m_on:
                    href = m_on.group(1)
            if not href.startswith("/vuz/"):
                continue
            if any(x in href for x in ["?", "#", "variant-programmi"]):
                continue
            # Нормализуем до /vuz/<slug>/
            m = re.match(r"^/vuz/[a-z0-9\-]+/?$", href, re.IGNORECASE)
            if not m:
                # если глубже, берем первый сегмент
                m2 = re.match(r"^/vuz/([a-z0-9\-]+)/", href, re.IGNORECASE)
                if m2:
                    href = f"/vuz/{m2.group(1)}/"
                else:
                    continue
            url = _abs(client, href if href.endswith("/") else href + "/")
            new_links.append(url)

        # Дополнительно — извлекаем /vuz/<slug>/ из всего HTML (могут быть в JSON/скриптах)
        for m in re.findall(r"(?:https?://[^\s\"']+)?(/vuz/[a-z0-9\-]+/)", html, flags=re.IGNORECASE):
            url = _abs(client, m)
            new_links.append(url)

        for u in new_links:
            if u not in seen:
                pages.append(u)
                seen.add(u)

        # Определяем наличие следующей страницы
        has_next = False
        # rel=next
        if soup.select_one('a[rel="next"]'):
            has_next = True
        # page=
        if not has_next:
            for a in soup.select('a[href*="/vuzi/?page="]'):
                m = re.search(r"page=(\d+)", a.get("href") or "")
                if m and int(m.group(1)) > page_num:
                    has_next = True
                    break
        # Bitrix PAGEN_* формат
        if not has_next:
            for a in soup.select('a[href*="/vuzi/?"]'):
                href = a.get("href") or ""
                if "PAGEN_" in href:
                    has_next = True
                    break
        if not has_next:
            break
        page_num += 1
        time.sleep(0.3)

    return pages


def crawl_city_for_universities(client: HtmlClient, max_pages: int = 300, max_depth: int = 2) -> List[str]:
    """Fallback: поверхностный краулер по домену города в поисках страниц вузов.
    Собираем все ссылки вида /vuz/<slug>/, обход ограничен по количеству страниц и глубине.
    """
    from collections import deque

    queue = deque([("/", 0), ("/vuz/", 0)])
    visited_pages = set()
    universities: List[str] = []
    seen_universities = set()

    def collect_unis_from_html(soup: BeautifulSoup) -> None:
        for a in soup.select('a[href^="/vuz/"]'):
            href = a.get("href") or ""
            if not href.startswith("/vuz/"):
                continue
            if any(sub in href for sub in ["variant-programmi", "variant-programmi-magistr", "?", "#"]):
                continue
            m = re.match(r"^/vuz/[a-z0-9\-]+/?$", href, re.IGNORECASE)
            if not m:
                continue
            url = _abs(client, href if href.endswith("/") else href + "/")
            if url not in seen_universities:
                universities.append(url)
                seen_universities.add(url)

    pages_processed = 0
    while queue and pages_processed < max_pages:
        path, depth = queue.popleft()
        if depth > max_depth:
            continue
        if path in visited_pages:
            continue
        visited_pages.add(path)
        try:
            html = client.get(path)
        except Exception:
            continue
        soup = BeautifulSoup(html, "lxml")
        pages_processed += 1

        collect_unis_from_html(soup)

        # Добавляем в очередь ссылки более общего характера, чтобы углубиться умеренно
        if depth < max_depth:
            for a in soup.select('a[href^="/"]'):
                href = a.get("href") or ""
                if not href.startswith("/"):
                    continue
                if any(sub in href for sub in ["#", "?", "tel:", "mailto:"]):
                    continue
                # ограничим только ключевыми разделами, чтобы не уехать далеко
                if not (href.startswith("/vuz/") or href in ("/", "/vuz/", "/universitet/", "/universitety/", "/vysshee-obrazovanie/")):
                    continue
                queue.append((href, depth + 1))
        time.sleep(0.2)

    return universities


def list_program_links_on_university(client: HtmlClient, university_url: str) -> List[str]:
    """Возвращает ссылки на страницы ВАРИАНТОВ программ (с числовым id в URL)."""
    links: List[str] = []

    def collect_variant_links_from(url: str) -> None:
        """Собирает ссылки вариантов программ с поддержкой пагинации на списках."""
        visited_pages = set()
        to_visit = [url]
        while to_visit:
            cur = to_visit.pop(0)
            if cur in visited_pages:
                continue
            visited_pages.add(cur)
            try:
                html = client.get(cur)
                soup = BeautifulSoup(html, "lxml")
            except Exception:
                continue

            # Ссылки на программы бакалавриата и магистратуры
            for a in soup.select('a, div, article, li'):
                href = a.get("href") or a.get("data-href") or ""
                if not href and a.get("onclick"):
                    m_on = re.search(r"'(\/vuz\/[^']+)'", a.get("onclick") or "")
                    if m_on:
                        href = m_on.group(1)
                if not href:
                    continue
                # Варианты программ бакалавриата
                m_b = re.search(r"/(variant-programmi)/(\d+)/?", href)
                if m_b:
                    links.append(_abs(client, href))
                # Варианты программ магистратуры
                m_m = re.search(r"/(variant-programmi-magistr)/(\d+)/?", href)
                if m_m:
                    links.append(_abs(client, href))

            # Также выдернем возможные variant-ссылки напрямую из HTML (если они в скриптах)
            for m in re.findall(r"(?:https?://[^\s\"']+)?(/vuz/[a-z0-9\-\./]*/(variant-programmi(?:-magistr)?)/\d+/)", html, flags=re.IGNORECASE):
                abs_url = _abs(client, m[0])
                links.append(abs_url)

            # Пагинация: rel=next, ?page=, PAGEN_*
            next_candidates = []
            a_next = soup.select_one('a[rel="next"]')
            if a_next and a_next.get('href'):
                next_candidates.append(a_next.get('href'))
            for a in soup.select('a[href*="?page="]'):
                next_candidates.append(a.get('href') or '')
            for a in soup.select('a[href*="PAGEN_"]'):
                next_candidates.append(a.get('href') or '')

            for nhref in next_candidates:
                if not nhref:
                    continue
                # Оставляем только страницы с программами
                if not any(x in nhref for x in ['programmy-obucheniya', 'variant-programmi']):
                    continue
                to_visit.append(_abs(client, nhref))

    # 1) С главной страницы вуза собираем прямые ссылки, если есть
    try:
        html = client.get(university_url)
        soup = BeautifulSoup(html, "lxml")
        for a in soup.select('a, div, article, li'):
            href = a.get("href") or a.get("data-href") or ""
            if not href and a.get("onclick"):
                m_on = re.search(r"'(\/vuz\/[^']+)'", a.get("onclick") or "")
                if m_on:
                    href = m_on.group(1)
            m_b = re.search(r"/(variant-programmi)/(\d+)/?", href)
            if m_b:
                links.append(_abs(client, href))
            m_m = re.search(r"/(variant-programmi-magistr)/(\d+)/?", href)
            if m_m:
                links.append(_abs(client, href))
    except Exception:
        pass

    # 2) Явно переходим на страницы списков программ бакалавриата/магистратуры (новая структура)
    base = university_url.rstrip("/")
    # Новый список программ находится по /programmy-obucheniya/{bakalavr|magistratura}/
    for postfix in [
        "programmy-obucheniya/bakalavr",
        "programmy-obucheniya/magistratura",
    ]:
        list_url = f"{base}/{postfix}/"
        # Собираем все программы на странице
        visited_prog_pages = set()
        to_visit_prog = [list_url]
        while to_visit_prog:
            cur_prog_url = to_visit_prog.pop(0)
            if cur_prog_url in visited_prog_pages:
                continue
            visited_prog_pages.add(cur_prog_url)
            try:
                html_prog = client.get(cur_prog_url)
                soup_prog = BeautifulSoup(html_prog, "lxml")
            except Exception:
                continue
            # Ссылки на страницы программ (бакалавр/магистр)
            for a in soup_prog.select('a, div, article, li'):
                href = a.get("href") or a.get("data-href") or ""
                if not href and a.get("onclick"):
                    m_on = re.search(r"'(\/vuz\/[^']+)'", a.get("onclick") or "")
                    if m_on:
                        href = m_on.group(1)
                # Программа бакалавриата
                m_b = re.search(r"/programma/(\d+)/varianti/?", href)
                if m_b:
                    # Переходим на страницу вариантов
                    collect_variant_links_from(_abs(client, href))
                # Программа магистратуры
                m_m = re.search(r"/programma-magistr/(\d+)/varianti/?", href)
                if m_m:
                    collect_variant_links_from(_abs(client, href))
            # Пагинация программ
            next_candidates = []
            a_next = soup_prog.select_one('a[rel="next"]')
            if a_next and a_next.get('href'):
                next_candidates.append(a_next.get('href'))
            for a in soup_prog.select('a[href*="?page="]'):
                next_candidates.append(a.get('href') or '')
            for a in soup_prog.select('a[href*="PAGEN_"]'):
                next_candidates.append(a.get('href') or '')
            for nhref in next_candidates:
                if not nhref:
                    continue
                if not any(x in nhref for x in ['programmy-obucheniya']):
                    continue
                to_visit_prog.append(_abs(client, nhref))

    # Уникализация
    unique: List[str] = []
    seen = set()
    for u in links:
        if u not in seen:
            unique.append(u)
            seen.add(u)
    return unique


def detect_program_type(url_or_text: str) -> str:
    text = url_or_text.lower()
    if "magistr" in text or "магистр" in text:
        return "master"
    # Страницы бакалавр-специалитет: определяем по ключевым словам
    if "специалитет" in text:
        # В единую схему кладем как bachelor для совместной категории
        return "bachelor"
    return "bachelor"


def _extract_variant_learning(soup: BeautifulSoup) -> Optional[str]:
    """
    Ищем секцию "Вариант обучения" и возвращаем её текст (все <p> в секции, кроме заголовка).
    """
    # На страницах встречаются блоки <section class="section-box"> и внутри <p class="h-large-nd ...">Вариант обучения</p>
    for section in soup.find_all("section", class_=lambda v: v and "section-box" in v):
        # Найдём заголовочный <p> внутри секции
        header = None
        # header может быть <p class="h-large-nd h-large-nd_inner">Вариант обучения</p>
        for p in section.find_all("p"):
            txt = (p.get_text(" ", strip=True) or "").lower()
            if "вариант обуч" in txt or "вариант обучения" in txt:
                header = p
                break
        if header:
            # Собираем все <p> внутри секции, кроме заголовочного
            paras = []
            for p in section.find_all("p"):
                if p is header:
                    continue
                t = p.get_text(" ", strip=True)
                if t:
                    paras.append(re.sub(r"\s+", " ", t))
            if paras:
                return " ".join(paras)
            # если параграфов нет, возьмём весь текст секции без заголовка
            sec_text = section.get_text(" ", strip=True)
            sec_text = re.sub(r"\s+", " ", sec_text)
            # удалим заголовочную фразу
            sec_text = re.sub(r"(?i)вариант обучения[:\s-]*", "", sec_text, count=1)
            sec_text = sec_text.strip()
            return sec_text or None
    # также возможен вариант, где блокы оформлены иначе — пробуем просто поиск по заголовкам в документе
    for p in soup.find_all(["p", "h2", "h3", "h4"]):
        txt = (p.get_text(" ", strip=True) or "").lower()
        if "вариант обуч" in txt:
            # берем следующий sibling <p> или следующий элемент с текстом
            nxt = p.find_next_sibling()
            texts = []
            steps = 0
            while nxt and steps < 5:  # ограничим число братьевых элементов
                if nxt.name == "p":
                    t = nxt.get_text(" ", strip=True)
                    if t:
                        texts.append(re.sub(r"\s+", " ", t))
                nxt = nxt.find_next_sibling()
                steps += 1
            if texts:
                return " ".join(texts)
    return None


def parse_program_page(client: HtmlClient, program_url: str) -> Optional[EducationProgram]:
    html = client.get(program_url)
    soup = BeautifulSoup(html, "lxml")

    # Заголовок программы
    title_el = soup.select_one("h1, .page-title h1, .title h1")
    title = _extract_text(title_el) or ""

    # Университет: берем из хлебных крошек или блоков с названием вуза
    uni = None
    for sel in [
        ".breadcrumbs a[href^='/vuz/']:last-child",
        ".breadcrumbs a[href^='/vuz/']",
        "a[href^='/vuz/'].link",
        ".vuz-title, .vuz-name",
    ]:
        el = soup.select_one(sel)
        uni = _extract_text(el)
        if uni:
            break

    # Сначала пробуем явно вытащить "Вариант обучения" — если есть, ставим его в description
    variant_text = _extract_variant_learning(soup)
    description = None
    if variant_text:
        description = variant_text

    # Если не нашли явный вариант обучения — fallback к предыдущей логике
    if not description:
        # Длительность/формат/язык/стоимость: извлекаем из таблиц характеристик, если есть
        desc_el = soup.select_one(".program-description, .description, .summary, p")
        if desc_el:
            description = _extract_text(desc_el)
        if not description:
            # fallback: первые 300 символов текста страницы
            description = soup.get_text(" ", strip=True)[:300]

    ptype = detect_program_type(program_url + " " + soup.get_text(" ", strip=True)[:200])

    # Идентификатор из URL: берем последний числовой сегмент, если есть
    prog_id = None
    m = re.search(r"/(variant-programmi(?:-magistr)?)/(\d+)/?", program_url)
    if m:
        prog_id = f"postupi:{m.group(1)}:{m.group(2)}"
    else:
        # fallback: хэш URL
        prog_id = f"postupi:{abs(hash(program_url))}"

    program = EducationProgram(
        id=prog_id,
        title=title or "Программа",
        type=ptype,  # bachelor|master
        provider="Postupi.online",
        link=program_url,
        source="postupi",
        description=description,
    )
    # Попробуем заполнить university если нашли
    if uni:
        # в нашей модели, если есть поле university, можно назначить
        try:
            program.university = uni  # если в dataclass есть такое поле
        except Exception:
            # если поля нет, просто проигнорируем
            pass

    return program


def iterate_postupi_programs_from_urls(urls: List[str], throttle_sec: float = 0.5) -> Generator[EducationProgram, None, None]:
    """Парсинг конкретных страниц программ (для отладки/быстрого запуска)."""
    # Выбираем клиента по домену каждой ссылки
    def client_for(url: str) -> HtmlClient:
        for base in BASE_DOMAINS.values():
            if url.startswith(base):
                return HtmlClient(base)
        # если домен не из списка, берём из URL
        m = re.match(r"^(https?://[^/]+)", url)
        base = m.group(1) if m else "https://postupi.online"
        return HtmlClient(base)

    for url in urls:
        try:
            client = client_for(url)
            program = parse_program_page(client, url)
            if program:
                yield program
        except Exception:
            pass
        time.sleep(throttle_sec)
