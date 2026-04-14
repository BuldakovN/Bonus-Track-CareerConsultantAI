from __future__ import annotations

from dataclasses import dataclass, asdict, field as dc_field
from typing import List, Optional, Literal, Dict, Any


ProgramType = Literal[
    "bachelor",
    "master",
    "specialist",
    "spo",
    "course",
    "dpo",
]


@dataclass
class EducationProgram:
    """Единая модель образовательной программы.

    Одна программа = один документ.
    Все провайдеры приводятся к этому формату.
    """

    id: str
    title: str
    type: ProgramType
    provider: str
    link: str = ""
    source: str = ""  # например, "stepik"
    description: Optional[str] = None

    # остальные поля убраны для унификации

    def to_json(self) -> Dict[str, Any]:
        data = asdict(self)
        # Оставляем только утверждённые поля
        keys = ["id", "title", "type", "provider", "link", "source", "description"]
        filtered = {k: data.get(k) for k in keys if data.get(k) not in (None, "")}
        return filtered


