"""
Файловое логирование ошибок (ERROR/CRITICAL) в каталог logs/<service_name>/errors.log.
Путь к корню логов: переменная окружения LOG_ROOT (в Docker: /app/logs).
"""
from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def _default_log_root() -> Path:
    return Path.cwd() / "logs"


def _resolved_log_root() -> Path:
    raw = (os.environ.get("LOG_ROOT") or "").strip()
    return Path(raw) if raw else _default_log_root()


_uncaught_excepthook_installed = False


def setup_service_error_logging(service_name: str) -> None:
    """
    Добавляет RotatingFileHandler на корневой логгер: только ERROR и выше.
    """
    log_root = _resolved_log_root()
    error_dir = log_root / service_name
    error_dir.mkdir(parents=True, exist_ok=True)
    log_file = error_dir / "errors.log"

    handler = RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    handler.setLevel(logging.ERROR)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    )

    root = logging.getLogger()
    # Избегаем дублирования при повторном импорте (reload / тесты)
    for h in root.handlers:
        if getattr(h, "_service_error_log", None) == service_name:
            return
    handler._service_error_log = service_name  # type: ignore[attr-defined]
    root.addHandler(handler)

    _install_uncaught_excepthook()


def _install_uncaught_excepthook() -> None:
    global _uncaught_excepthook_installed
    if _uncaught_excepthook_installed:
        return
    _uncaught_excepthook_installed = True

    previous = sys.excepthook
    log = logging.getLogger("uncaught")

    def excepthook(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            previous(exc_type, exc_value, exc_traceback)
            return
        log.error(
            "Необработанное исключение",
            exc_info=(exc_type, exc_value, exc_traceback),
        )
        previous(exc_type, exc_value, exc_traceback)

    sys.excepthook = excepthook
