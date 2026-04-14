import re
import time
from dataclasses import dataclass
from typing import Generator, Iterable, List, Optional, Any, Dict

import requests
from bs4 import BeautifulSoup

from .config import config
from .schema import EducationProgram


BASE_URL = "https://skillfactory.ru"


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
        elif not path_or_url.startswith("http"):
            url = f"{self.base_url}/{path_or_url}"
        resp = self.session.get(url, timeout=60)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or "utf-8"
        return resp.text


def _extract_text(el) -> str:
    if not el:
        return ""
    text = el.get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text)


def _abs_url(href: str, base_url: str = BASE_URL) -> str:
    if href.startswith("http://") or href.startswith("https://"):
        return href
    if not href.startswith("/"):
        href = "/" + href
    return f"{base_url}{href}"


def list_course_pages(client: HtmlClient) -> List[str]:
    course_links: List[str] = []
    seen = set()
    
    try:
        print("Парсим каталог курсов с /courses...")
        html = client.get("/courses")
        soup = BeautifulSoup(html, "lxml")
        
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            if not href:
                continue
            
            href = _abs_url(href)
            
            if "skillfactory.ru" in href and any(pattern in href for pattern in ["/courses/", "/course/"]):
                if any(exclude in href for exclude in ["#", "?page=", "javascript:", "mailto:"]):
                    continue
                
                excluded_sections = [
                    "/courses/courses",
                    "/courses/course",
                    "/courses/catalog",
                    "/courses/all",
                ]
                if any(excluded in href for excluded in excluded_sections):
                    continue
                
                match = re.search(r'skillfactory\.ru/(?:courses|course)/([^/?]+)', href)
                if match:
                    slug = match.group(1)
                    if len(slug) > 3:
                        if href not in seen:
                            course_links.append(href)
                            seen.add(href)
        
        print(f"Найдено {len(course_links)} ссылок на /courses")
    except Exception as e:
        print(f"Ошибка при парсинге /courses: {e}")
    
    catalog_sections = [
        "/courses/programmirovanie",
        "/courses/data-science",
        "/courses/analitika-dannyh",
        "/courses/marketing",
        "/courses/design",
        "/courses/testirovanie",
        "/courses/kiberbezopasnost",
        "/courses/razrabotka-igr",
        "/courses/web-razrabotka",
        "/courses/backend-razrabotka",
        "/courses/python",
    ]
    
    for section in catalog_sections:
        try:
            print(f"Парсим раздел {section}...")
            html = client.get(section)
            soup = BeautifulSoup(html, "lxml")
            
            for a in soup.find_all("a", href=True):
                href = a.get("href", "")
                if not href:
                    continue
                
                href = _abs_url(href)
                
                if "skillfactory.ru" in href and any(pattern in href for pattern in ["/courses/", "/course/"]):
                    if any(exclude in href for exclude in ["#", "?", "javascript:", "mailto:"]):
                        continue
                    
                    match = re.search(r'skillfactory\.ru/(?:courses|course)/([^/?]+)', href)
                    if match:
                        slug = match.group(1)
                        excluded_categories = [
                            "programmirovanie", "data-science", "analitika-dannyh", "marketing", 
                            "design", "testirovanie", "kiberbezopasnost", "razrabotka-igr",
                            "web-razrabotka", "backend-razrabotka", "python", "courses", "course"
                        ]
                        if slug not in excluded_categories and len(slug) > 5:
                            if href not in seen:
                                course_links.append(href)
                                seen.add(href)
            
            time.sleep(0.5)
        except Exception as e:
            print(f"Ошибка при парсинге раздела {section}: {e}")
            continue
    
    try:
        html = client.get("/")
        soup = BeautifulSoup(html, "lxml")
        
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            if not href:
                continue
            
            href = _abs_url(href)
            
            if "skillfactory.ru" in href and any(pattern in href for pattern in ["/courses/", "/course/"]):
                if any(exclude in href for exclude in ["#", "?", "javascript:", "mailto:"]):
                    continue
                match = re.search(r'skillfactory\.ru/(?:courses|course)/([^/?]+)', href)
                if match:
                    slug = match.group(1)
                    excluded = ["programmirovanie", "data-science", "analitika-dannyh", "marketing", "design", "courses", "course"]
                    if slug not in excluded and len(slug) > 5:
                        if href not in seen:
                            course_links.append(href)
                            seen.add(href)
    except Exception as e:
        print(f"Ошибка при парсинге главной страницы: {e}")
    
    print(f"Всего найдено {len(course_links)} уникальных курсов")
    return course_links


def parse_course_page(client: HtmlClient, course_url: str) -> Optional[EducationProgram]:
    try:
        html = client.get(course_url)
        soup = BeautifulSoup(html, "lxml")
        
        title = ""
        title_el = (
            soup.find("h1") 
            or soup.find("h2", class_=re.compile("title|name", re.I))
            or soup.find("title")
        )
        if title_el:
            title = _extract_text(title_el)
            if "|" in title:
                title = title.split("|")[0].strip()
            if "—" in title:
                title = title.split("—")[0].strip()
            if "Skillfactory" in title:
                title = title.replace("Skillfactory", "").strip()
        
        if not title or len(title) < 3:
            title = "Курс Skillfactory"
        
        description = None
        
        meta_desc = soup.find("meta", {"name": "description"})
        if meta_desc and meta_desc.get("content"):
            description = meta_desc.get("content").strip()
        
        if not description:
            desc_el = (
                soup.find("div", class_=re.compile("description|about|intro", re.I))
                or soup.find("p", class_=re.compile("description|about", re.I))
            )
            if desc_el:
                description = _extract_text(desc_el)
        
        if not description:
            first_p = soup.find("p")
            if first_p:
                description = _extract_text(first_p)
                if len(description) > 500:
                    description = description[:500] + "..."
        
        program_type = "course"
        url_lower = course_url.lower()
        if "program" in url_lower or "profession" in url_lower:
            program_type = "dpo"
        
        slug_match = re.search(r"/(?:courses|course)/([^/?]+)", course_url)
        if slug_match:
            program_id = f"skillfactory:{slug_match.group(1)}"
        else:
            program_id = f"skillfactory:{abs(hash(course_url))}"
        
        program = EducationProgram(
            id=program_id,
            title=title,
            type=program_type,
            provider="Skillfactory",
            link=course_url,
            source="skillfactory",
            description=description,
        )
        
        return program
        
    except Exception as e:
        print(f"Ошибка при парсинге {course_url}: {e}")
        return None


def iterate_skillfactory_courses(
    throttle_sec: float = 0.7,
    max_courses: Optional[int] = None,
) -> Generator[EducationProgram, None, None]:
    client = HtmlClient(BASE_URL)
    course_links = list_course_pages(client)
    print(f"Найдено ссылок на курсы: {len(course_links)}")
    
    seen_ids: set[str] = set()
    processed = 0
    
    for course_url in course_links:
        if max_courses and processed >= max_courses:
            break
            
        try:
            course = parse_course_page(client, course_url)
            if course and course.id not in seen_ids:
                seen_ids.add(course.id)
                yield course
                processed += 1
        except Exception as e:
            print(f"Ошибка при обработке {course_url}: {e}")
            continue
        
        time.sleep(throttle_sec)


def iterate_skillfactory_courses_from_urls(
    urls: List[str], 
    throttle_sec: float = 0.5
) -> Generator[EducationProgram, None, None]:
    client = HtmlClient(BASE_URL)
    
    for url in urls:
        try:
            course = parse_course_page(client, url)
            if course:
                yield course
        except Exception as e:
            print(f"Ошибка при парсинге {url}: {e}")
        time.sleep(throttle_sec)

