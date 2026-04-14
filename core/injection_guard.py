"""
Эвристическая проверка пользовательского ввода на попытки jailbreak / извлечения системного промпта.
Срабатывает на уровне графа до вызова LLM.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

# Явные паттерны (регистронезависимо)
_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions",
    r"disregard\s+(all\s+)?(previous|instructions|the\s+rules)",
    r"system\s+prompt",
    r"internal\s+prompt",
    r"reveal\s+(your\s+)?(prompt|instructions|system)",
    r"show\s+(me\s+)?(your\s+)?(prompt|instructions|system)",
    r"what\s+(are|is)\s+your\s+(instructions|prompt|rules)",
    r"jailbreak",
    r"\bdan\s+mode\b",
    r"pretend\s+(you\s+are|to\s+be)",
    r"you\s+are\s+now\s+(a|an|the)\s+",
    r"developer\s+mode",
    r"override\s+(your\s+)?(instructions|rules)",
    r"repeat\s+(the\s+)?(text|words)\s+above",
    r"\[INST\]",
    r"<\|im_start\|>",
    r"<\|system\|>",
    # RU
    r"системн(ый|ого|ую)\s+промпт",
    r"покажи\s+(мне\s+)?(системн|внутренн)",
    r"выведи\s+(мне\s+)?(промпт|инструкци)",
    r"игнорируй\s+(все\s+)?(предыдущ|инструкц|правил)",
    r"забудь\s+(все\s+)?(инструкц|правил)",
    r"раскрой\s+(секретн|скрыт)",
    r"какие\s+у\s+тебя\s+инструкц",
    r"промпт\s+разработчик",
]

_COMPILED = [re.compile(p, re.IGNORECASE | re.DOTALL) for p in _INJECTION_PATTERNS]


def detect_prompt_injection(user_text: str, parameters: Optional[Dict[str, Any]] = None) -> bool:
    """
    True, если ввод похож на попытку обойти политику или вытащить системный контекст.
    Пустой текст не считается инъекцией (например, запрос только с test_results).
    """
    parameters = parameters or {}
    text = (user_text or "").strip()
    if not text:
        return False
    # Очень короткие тех. вставки
    if re.fullmatch(r"[\s\W_]{1,6}", text):
        return False

    for rx in _COMPILED:
        if rx.search(text):
            return True
    return False
