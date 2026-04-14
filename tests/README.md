# Тесты API эндпоинтов

Эта папка содержит тесты для всех эндпоинтов API из `model/main.py`.

## Файлы

- `test_api_endpoints.ipynb` - Jupyter Notebook с интерактивными тестами
- `test_api_endpoints.py` - Unittest тесты для автоматизированного тестирования

## Запуск тестов

### Unittest (рекомендуется для CI/CD)

```bash
# Запуск всех тестов
python -m unittest tests.test_api_endpoints

# Запуск с подробным выводом
python -m unittest tests.test_api_endpoints -v

# Запуск конкретного теста
python -m unittest tests.test_api_endpoints.TestAPIRootEndpoint

# Запуск через pytest (если установлен)
pytest tests/test_api_endpoints.py -v
```

### Jupyter Notebook

Откройте `test_api_endpoints.ipynb` в Jupyter и запустите ячейки последовательно.

## Требования

Перед запуском тестов убедитесь, что:

1. API сервер запущен на `http://localhost:8000`
2. Установлены необходимые зависимости:
   - `requests`
   - `unittest` (встроен в Python)

## Тестируемые эндпоинты

1. `GET /` - приветственный эндпоинт
2. `POST /start_talk/` - начало диалога с LLM
3. `POST /get_user_info/` - получение информации о пользователе
4. `POST /get_profession_info/` - получение информации о профессии через RAG

## Структура тестов

### TestAPIRootEndpoint
- Проверка статус кода
- Проверка структуры ответа

### TestAPIStartTalkEndpoint
- Проверка статус кода
- Проверка структуры ответа
- Тесты с разными промптами

### TestAPIGetUserInfoEndpoint
- Проверка статус кода
- Проверка структуры ответа

### TestAPIGetProfessionInfoEndpoint
- Проверка статус кода
- Проверка структуры ответа
- Тесты с разными профессиями

### TestAPIDocumentation
- Проверка доступности Swagger UI
- Проверка доступности ReDoc
- Проверка доступности OpenAPI Schema

### TestAPIComprehensive
- Комплексное тестирование полного сценария использования API


