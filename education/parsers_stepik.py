from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from .clients import StepikClient
from .schema import EducationProgram


def normalize_stepik_course(course: Dict[str, Any]) -> EducationProgram:
    title = course.get("title") or course.get("slug") or ""
    description = course.get("summary")
    if not description:
        # fallback: первые 300 символов title или slug
        description = (title or "")[:300]
    link = f"https://stepik.org/course/{course.get('id')}"
    return EducationProgram(
        id=f"stepik:{course.get('id')}",
        title=title,
        type="course",
        provider="Stepik",
        link=link,
        source="stepik",
        description=description,
    )


def iterate_stepik_courses(pages: int = 2, page_size: int = 50, language: str | None = None) -> Iterable[EducationProgram]:
    client = StepikClient()
    for page in range(1, pages + 1):
        data = client.list_courses(page=page, page_size=page_size, language=language)
        courses = data.get("courses", [])
        for course in courses:
            # Фильтрация: только курсы, где записалось больше 15 человек
            if course.get("learners_count", 0) > 15:
                yield normalize_stepik_course(course)


