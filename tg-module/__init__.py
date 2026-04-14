"""
Telegram Bot Module

Модуль для работы с Telegram ботом, использующий aiogram и LLM модель.
"""

from .bot import TelegramBot, main
from .config import config, BotConfig
from .llm_client import LLMClient

__version__ = "1.0.0"
__all__ = ["TelegramBot", "main", "config", "BotConfig", "LLMClient"]
