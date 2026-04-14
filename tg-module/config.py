"""
Конфигурация для Telegram бота
"""
import os
from typing import Optional
from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла
load_dotenv()

class BotConfig:
    """Класс для хранения конфигурации бота"""
    
    def __init__(self):
        # Токен бота - должен быть установлен в переменных окружения
        self.bot_token: str = os.getenv('TELEGRAM_BOT_TOKEN', '')
        
        # Настройки для работы с LLM (API из папки model)
        self.llm_base_url: str = os.getenv('LLM_BASE_URL', 'http://localhost:8000')
        
        # Настройки бота
        self.max_message_length: int = 4096  # Максимальная длина сообщения в Telegram
        self.message_delay: float = 0.8  # Задержка между отправкой сообщений (секунды)
        
        # Тексты для команд
        self.start_text: str = "Я бот для профориентации и я создан, чтобы помочь тебе с выбором профессии."
        self.help_text: str = """
Доступные команды:
/start - Начать работу с ботом
/help - Показать эту справку
/clean_history - очистить историю сообщений

Просто напиши мне сообщение, и я отвечу!""".strip()
        self.cancel_text: str = "Операция отменена. Можете начать заново с команды /start"
        
    def validate(self) -> bool:
        """Проверяет корректность конфигурации"""
        if not self.bot_token:
            print("ОШИБКА: TELEGRAM_BOT_TOKEN не установлен в переменных окружения")
            return False
        return True

# Глобальный экземпляр конфигурации
config = BotConfig()
