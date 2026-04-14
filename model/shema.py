from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from enum import Enum


class Message(BaseModel):
    user_id: str
    msg: str
    timestamp: str


class LLMResponse(BaseModel):
    """Ответ от LLM с типом сообщения и дополнительными данными"""
    msg: str
    professions: Optional[Dict[str, str]] = None  # Словарь профессий: название -> описание
    test_info: Optional[Dict] = None # Словарь с информацией о тесте


class Context(BaseModel):
    user_id: str
    prompt: str
    parameters: dict = {}


class ProfessionRequest(BaseModel):
    """Запрос информации о профессии"""
    user_id: str
    profession_name: str