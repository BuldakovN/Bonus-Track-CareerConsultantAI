import re
import time
from dataclasses import dataclass
from typing import Generator, Iterable, List, Optional, Any, Dict

import requests
from bs4 import BeautifulSoup

from .config import config
from .schema import EducationProgram


BASE_URL = "https://netology.ru"


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


def list_program_pages(client: HtmlClient, max_pages: int = 50) -> List[str]:
    program_links: List[str] = []
    seen = set()
    
    try:
        print("Парсим каталог курсов с /navigation...")
        html = client.get("/navigation")
        soup = BeautifulSoup(html, "lxml")
        
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            if not href:
                continue
            
            href = _abs_url(href)
            
            if "netology.ru" in href and any(pattern in href for pattern in ["/programs/", "/courses/", "/course/"]):
                if any(exclude in href for exclude in ["#", "?page=", "javascript:", "mailto:", "/navigation"]):
                    continue
                excluded_sections = [
                    "/programs/ai-courses",
                    "/programs/psychology", 
                    "/programs/b2b",
                    "/programs/discipliny-i-moduli",
                    "/programs/b2c2b",
                ]
                if any(excluded in href for excluded in excluded_sections):
                    continue
                
                match = re.search(r'netology\.ru/(?:programs|courses|course)/([^/?]+)', href)
                if match:
                    slug = match.group(1)
                    if len(slug) > 3 and slug not in ["programs", "courses", "course"]:
                        if href not in seen:
                            program_links.append(href)
                            seen.add(href)
        
        print(f"Найдено {len(program_links)} уникальных курсов на /navigation")
    except Exception as e:
        print(f"Ошибка при парсинге /navigation: {e}")
    
    try:
        html = client.get("/")
        soup = BeautifulSoup(html, "lxml")
        
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            if not href:
                continue
            
            href = _abs_url(href)
            
            if "netology.ru" in href and any(pattern in href for pattern in ["/programs/", "/courses/", "/course/"]):
                if any(exclude in href for exclude in ["#", "?", "javascript:", "mailto:"]):
                    continue
                match = re.search(r'netology\.ru/(?:programs|courses|course)/([^/?]+)', href)
                if match:
                    slug = match.group(1)
                    if len(slug) > 3 and slug not in ["programs", "courses", "course", "ai-courses", "psychology", "b2b"]:
                        if href not in seen:
                            program_links.append(href)
                            seen.add(href)
    except Exception as e:
        print(f"Ошибка при парсинге главной страницы: {e}")
    
    return program_links


def parse_program_page(client: HtmlClient, program_url: str) -> Optional[EducationProgram]:
    try:
        html = client.get(program_url)
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
        
        if not title:
            title = "Программа Нетологии"
        
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
        url_lower = program_url.lower()
        if "program" in url_lower:
            program_type = "dpo"
        
        slug_match = re.search(r"/(?:programs|courses|course)/([^/?]+)", program_url)
        if slug_match:
            program_id = f"netology:{slug_match.group(1)}"
        else:
            program_id = f"netology:{abs(hash(program_url))}"
        
        program = EducationProgram(
            id=program_id,
            title=title,
            type=program_type,
            provider="Нетология",
            link=program_url,
            source="netology",
            description=description,
        )
        
        return program
        
    except Exception as e:
        print(f"Ошибка при парсинге {program_url}: {e}")
        return None


def iterate_netology_programs(
    throttle_sec: float = 0.7,
    max_programs: Optional[int] = None,
) -> Generator[EducationProgram, None, None]:
    client = HtmlClient(BASE_URL)
    program_links = list_program_pages(client)
    print(f"Найдено ссылок на программы: {len(program_links)}")
    
    seen_ids: set[str] = set()
    processed = 0
    
    for program_url in program_links:
        if max_programs and processed >= max_programs:
            break
            
        try:
            program = parse_program_page(client, program_url)
            if program and program.id not in seen_ids:
                seen_ids.add(program.id)
                yield program
                processed += 1
        except Exception as e:
            print(f"Ошибка при обработке {program_url}: {e}")
            continue
        
        time.sleep(throttle_sec)


def iterate_netology_programs_from_urls(
    urls: List[str], 
    throttle_sec: float = 0.5
) -> Generator[EducationProgram, None, None]:
    client = HtmlClient(BASE_URL)
    
    for url in urls:
        try:
            program = parse_program_page(client, url)
            if program:
                yield program
        except Exception as e:
            print(f"Ошибка при парсинге {url}: {e}")
        time.sleep(throttle_sec)

