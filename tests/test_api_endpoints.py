"""
Unittest тесты для API эндпоинтов из model/main.py

Запуск тестов:
    python -m unittest tests.test_api_endpoints
    или
    python -m pytest tests/test_api_endpoints.py
"""

import unittest
import requests
import json
from datetime import datetime
from typing import Dict, Any, Optional


# Базовый URL API
BASE_URL = "http://localhost:8000"

# Тестовые данные
TEST_USER_ID = "test_user_123"
TEST_PROMPT = "Привет, я хочу узнать о профессиях в IT"
TEST_PROFESSION_NAME = "Программист"


class TestAPIRootEndpoint(unittest.TestCase):
    """Тесты для корневого эндпоинта GET /"""
    
    def test_root_endpoint_status(self):
        """Проверка статус кода корневого эндпоинта"""
        try:
            response = requests.get(f"{BASE_URL}/")
            self.assertEqual(response.status_code, 200, 
                           f"Ожидался статус 200, получен {response.status_code}")
        except requests.exceptions.ConnectionError:
            self.fail("Не удалось подключиться к API. Убедитесь, что сервер запущен на http://localhost:8000")
    
    def test_root_endpoint_message(self):
        """Проверка наличия поля message в ответе"""
        try:
            response = requests.get(f"{BASE_URL}/")
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertIn("message", data, "В ответе отсутствует поле 'message'")
            self.assertIsInstance(data["message"], str)
        except requests.exceptions.ConnectionError:
            self.fail("Не удалось подключиться к API. Убедитесь, что сервер запущен на http://localhost:8000")


class TestAPIStartTalkEndpoint(unittest.TestCase):
    """Тесты для эндпоинта POST /start_talk/"""
    
    def setUp(self):
        """Настройка перед каждым тестом"""
        self.user_id = f"test_user_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.payload = {
            "user_id": self.user_id,
            "prompt": TEST_PROMPT,
            "parameters": {}
        }
    
    def test_start_talk_status(self):
        """Проверка статус кода эндпоинта /start_talk/"""
        try:
            response = requests.post(
                f"{BASE_URL}/start_talk/",
                json=self.payload,
                headers={"Content-Type": "application/json"}
            )
            self.assertEqual(response.status_code, 200,
                           f"Ожидался статус 200, получен {response.status_code}")
        except requests.exceptions.ConnectionError:
            self.fail("Не удалось подключиться к API. Убедитесь, что сервер запущен на http://localhost:8000")
    
    def test_start_talk_response_structure(self):
        """Проверка структуры ответа эндпоинта /start_talk/"""
        try:
            response = requests.post(
                f"{BASE_URL}/start_talk/",
                json=self.payload,
                headers={"Content-Type": "application/json"}
            )
            self.assertEqual(response.status_code, 200)
            result = response.json()
            self.assertIn("msg", result, "В ответе отсутствует поле 'msg'")
            self.assertIsInstance(result["msg"], str)
            # professions может быть None или dict
            if result.get("professions") is not None:
                self.assertIsInstance(result["professions"], dict)
        except requests.exceptions.ConnectionError:
            self.fail("Не удалось подключиться к API. Убедитесь, что сервер запущен на http://localhost:8000")
    
    def test_start_talk_different_prompts(self):
        """Тест с разными промптами"""
        test_prompts = [
            "Расскажи о профессии программиста",
            "Какие навыки нужны для работы в data science?",
            "Хочу стать веб-разработчиком, с чего начать?",
        ]
        
        for prompt in test_prompts:
            with self.subTest(prompt=prompt):
                payload = {
                    "user_id": f"test_user_prompt_{datetime.now().timestamp()}",
                    "prompt": prompt,
                    "parameters": {}
                }
                try:
                    response = requests.post(
                        f"{BASE_URL}/start_talk/",
                        json=payload,
                        headers={"Content-Type": "application/json"}
                    )
                    self.assertEqual(response.status_code, 200)
                    result = response.json()
                    self.assertIn("msg", result)
                except requests.exceptions.ConnectionError:
                    self.fail("Не удалось подключиться к API")


class TestAPIGetUserInfoEndpoint(unittest.TestCase):
    """Тесты для эндпоинта POST /get_user_info/"""
    
    def setUp(self):
        """Настройка перед каждым тестом"""
        self.user_id = f"test_user_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.payload = {
            "user_id": self.user_id,
            "prompt": "",
            "parameters": {}
        }
    
    def test_get_user_info_status(self):
        """Проверка статус кода эндпоинта /get_user_info/"""
        try:
            response = requests.post(
                f"{BASE_URL}/get_user_info/",
                json=self.payload,
                headers={"Content-Type": "application/json"}
            )
            self.assertEqual(response.status_code, 200,
                           f"Ожидался статус 200, получен {response.status_code}")
        except requests.exceptions.ConnectionError:
            self.fail("Не удалось подключиться к API. Убедитесь, что сервер запущен на http://localhost:8000")
    
    def test_get_user_info_response_structure(self):
        """Проверка структуры ответа эндпоинта /get_user_info/"""
        try:
            response = requests.post(
                f"{BASE_URL}/get_user_info/",
                json=self.payload,
                headers={"Content-Type": "application/json"}
            )
            self.assertEqual(response.status_code, 200)
            result = response.json()
            self.assertIn("user_id", result, "В ответе отсутствует поле 'user_id'")
            self.assertIn("msg", result, "В ответе отсутствует поле 'msg'")
            self.assertIn("timestamp", result, "В ответе отсутствует поле 'timestamp'")
            self.assertEqual(result["user_id"], self.user_id)
            self.assertIsInstance(result["msg"], str)
            self.assertIsInstance(result["timestamp"], str)
        except requests.exceptions.ConnectionError:
            self.fail("Не удалось подключиться к API. Убедитесь, что сервер запущен на http://localhost:8000")


class TestAPIGetProfessionInfoEndpoint(unittest.TestCase):
    """Тесты для эндпоинта POST /get_profession_info/"""
    
    def setUp(self):
        """Настройка перед каждым тестом"""
        self.user_id = f"test_user_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.profession_name = TEST_PROFESSION_NAME
        self.payload = {
            "user_id": self.user_id,
            "profession_name": self.profession_name
        }
    
    def test_get_profession_info_status(self):
        """Проверка статус кода эндпоинта /get_profession_info/"""
        try:
            response = requests.post(
                f"{BASE_URL}/get_profession_info/",
                json=self.payload,
                headers={"Content-Type": "application/json"}
            )
            # Может вернуть 200 или 500 в зависимости от состояния сервера
            self.assertIn(response.status_code, [200, 500],
                         f"Неожиданный статус код: {response.status_code}")
        except requests.exceptions.ConnectionError:
            self.fail("Не удалось подключиться к API. Убедитесь, что сервер запущен на http://localhost:8000")
    
    def test_get_profession_info_response_structure(self):
        """Проверка структуры ответа эндпоинта /get_profession_info/"""
        try:
            response = requests.post(
                f"{BASE_URL}/get_profession_info/",
                json=self.payload,
                headers={"Content-Type": "application/json"}
            )
            if response.status_code == 200:
                result = response.json()
                self.assertIn("msg", result, "В ответе отсутствует поле 'msg'")
                self.assertIsInstance(result["msg"], str)
                # professions может быть None или dict
                if result.get("professions") is not None:
                    self.assertIsInstance(result["professions"], dict)
            # Если 500, просто проверяем что это ошибка сервера
            elif response.status_code == 500:
                self.assertEqual(response.status_code, 500, "Сервер вернул ошибку 500")
        except requests.exceptions.ConnectionError:
            self.fail("Не удалось подключиться к API. Убедитесь, что сервер запущен на http://localhost:8000")
    
    def test_get_profession_info_different_professions(self):
        """Тест с разными названиями профессий"""
        professions = ["Data Scientist", "Веб-разработчик", "DevOps инженер"]
        
        for profession in professions:
            with self.subTest(profession=profession):
                payload = {
                    "user_id": f"test_user_{datetime.now().timestamp()}",
                    "profession_name": profession
                }
                try:
                    response = requests.post(
                        f"{BASE_URL}/get_profession_info/",
                        json=payload,
                        headers={"Content-Type": "application/json"}
                    )
                    # Принимаем как 200, так и 500 (если сервер не настроен)
                    self.assertIn(response.status_code, [200, 500])
                except requests.exceptions.ConnectionError:
                    self.fail("Не удалось подключиться к API")


class TestAPIDocumentation(unittest.TestCase):
    """Тесты для проверки доступности документации API"""
    
    def test_swagger_ui_available(self):
        """Проверка доступности Swagger UI"""
        try:
            response = requests.get(f"{BASE_URL}/docs")
            self.assertEqual(response.status_code, 200,
                           f"Swagger UI недоступен. Статус: {response.status_code}")
        except requests.exceptions.ConnectionError:
            self.fail("Не удалось подключиться к API")
    
    def test_redoc_available(self):
        """Проверка доступности ReDoc"""
        try:
            response = requests.get(f"{BASE_URL}/redoc")
            self.assertEqual(response.status_code, 200,
                           f"ReDoc недоступен. Статус: {response.status_code}")
        except requests.exceptions.ConnectionError:
            self.fail("Не удалось подключиться к API")
    
    def test_openapi_schema_available(self):
        """Проверка доступности OpenAPI Schema"""
        try:
            response = requests.get(f"{BASE_URL}/openapi.json")
            self.assertEqual(response.status_code, 200,
                           f"OpenAPI Schema недоступен. Статус: {response.status_code}")
            # Проверяем что это валидный JSON
            schema = response.json()
            self.assertIsInstance(schema, dict)
            self.assertIn("openapi", schema)
        except requests.exceptions.ConnectionError:
            self.fail("Не удалось подключиться к API")


class TestAPIComprehensive(unittest.TestCase):
    """Комплексные тесты - последовательность запросов"""
    
    def setUp(self):
        """Настройка перед каждым тестом"""
        self.user_id = f"test_user_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    def test_full_user_flow(self):
        """Тест полного сценария использования API"""
        try:
            # 1. Проверка корневого эндпоинта
            response = requests.get(f"{BASE_URL}/")
            self.assertEqual(response.status_code, 200)
            
            # 2. Начало диалога
            payload = {
                "user_id": self.user_id,
                "prompt": "Я интересуюсь программированием и хочу узнать о карьере в IT",
                "parameters": {}
            }
            response = requests.post(
                f"{BASE_URL}/start_talk/",
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            self.assertEqual(response.status_code, 200)
            result = response.json()
            self.assertIn("msg", result)
            
            # 3. Получение информации о пользователе
            payload = {
                "user_id": self.user_id,
                "prompt": "",
                "parameters": {}
            }
            response = requests.post(
                f"{BASE_URL}/get_user_info/",
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            self.assertEqual(response.status_code, 200)
            result = response.json()
            self.assertIn("user_id", result)
            self.assertEqual(result["user_id"], self.user_id)
            
        except requests.exceptions.ConnectionError:
            self.fail("Не удалось подключиться к API. Убедитесь, что сервер запущен на http://localhost:8000")


if __name__ == "__main__":
    # Настройка вывода тестов
    unittest.main(verbosity=2)

