# Docker Compose для AI Gigaschool

Этот файл `docker-compose.yml` позволяет запустить все сервисы проекта в контейнерах Docker.

## Сервисы

### 1. Model API (model-api)
FastAPI сервис для работы с LLM моделями.

- **Порт**: 8000
- **URL**: http://localhost:8000
- **Документация**: http://localhost:8000/docs
- **Зависимости**: tavily-adapter

### 2. Telegram Bot (telegram-bot)
Telegram бот для профориентации.

- **Зависимости**: model-api
- **Переменные окружения**: `TELEGRAM_BOT_TOKEN` (обязательно)

### 3. SearXNG (searxng)
Поисковая система с открытым исходным кодом.

- **Порт**: 8999
- **URL**: http://localhost:8999
- **Используется**: tavily-adapter для выполнения поисковых запросов

### 4. Tavily Adapter (tavily-adapter)
Адаптер, предоставляющий Tavily-совместимый API на основе SearXNG.

- **Порт**: 1000
- **URL**: http://localhost:1000
- **Healthcheck**: http://localhost:1000/health
- **Зависимости**: searxng
- **Используется**: model-api для веб-поиска

## Быстрый старт

### 1. Создайте файл `.env` в корне проекта:

```env
# Yandex Cloud (по умолчанию)
YANDEX_CLOUD_FOLDER=your_folder_id
YANDEX_CLOUD_API_KEY=your_api_key
LLM_PROVIDER=yandex

# Или используйте другой провайдер:
# LLM_PROVIDER=openai
# OPENAI_API_KEY=your_openai_key

# Для Telegram бота (если используется)
# TELEGRAM_BOT_TOKEN=your_telegram_bot_token
```

### 2. Создайте конфигурационный файл для SearXNG (если еще не создан):

```bash
# Скопируйте пример конфигурации
cp web_search/config.yaml web_search/config.yaml
# Отредактируйте secret_key в файле web_search/config.yaml
```

### 3. Запустите сервисы:

```bash
# Запуск всех сервисов
docker-compose up -d

# Запуск только model-api
docker-compose up -d model-api

# Запуск без telegram-bot (если не нужен)
docker-compose up -d model-api searxng tavily-adapter

# Просмотр логов
docker-compose logs -f model-api
```

### 4. Проверьте работу:

```bash
# Проверка healthcheck
docker-compose ps

# Проверка Model API
curl http://localhost:8000/

# Проверка Tavily Adapter
curl http://localhost:1000/health

# Проверка SearXNG
curl http://localhost:8999/
```

## Остановка сервисов

```bash
# Остановка всех сервисов
docker-compose down

# Остановка с удалением volumes
docker-compose down -v
```

## Переменные окружения

### Model API

- `YANDEX_CLOUD_FOLDER` - ID папки Yandex Cloud (для Yandex провайдера)
- `YANDEX_CLOUD_API_KEY` - API ключ Yandex Cloud (для Yandex провайдера)
- `LLM_PROVIDER` - Провайдер LLM: `yandex`, `openai`, `anthropic`, `google` (по умолчанию: `yandex`)
- `OPENAI_API_KEY` - API ключ OpenAI (для OpenAI провайдера)
- `ANTHROPIC_API_KEY` - API ключ Anthropic (для Anthropic провайдера)
- `GOOGLE_API_KEY` - API ключ Google (для Google провайдера)

### Telegram Bot

- `TELEGRAM_BOT_TOKEN` - Токен Telegram бота от @BotFather (обязательно)
- `LLM_BASE_URL` - URL API модели (автоматически устанавливается в `http://model-api:8000`)
- `LLM_API_URL` - URL для `/start_talk/` эндпоинта (автоматически устанавливается)
- `LLM_PROFESSION_API_URL` - URL для `/get_profession_info/` эндпоинта (автоматически устанавливается)

### Model API (дополнительно)

- `WEB_SEARCH_API_URL` - URL для Tavily adapter (автоматически устанавливается в `http://tavily-adapter:1000`)

## Volumes

- `./data:/app/data:ro` - Данные проекта (векторные индексы, образовательные данные) - только для чтения
- `./logs:/app/logs` - Логи приложения
- `searxng-data` - Кэш данных SearXNG

## Сеть

Все сервисы находятся в одной сети `ai-gigaschool-network` и могут обращаться друг к другу по имени сервиса.

Примеры:
- `telegram-bot` → `http://model-api:8000`
- `model-api` → `http://tavily-adapter:1000`
- `tavily-adapter` → `http://searxng:8080`

## Healthcheck

- **Model API**: Проверяет доступность каждые 30 секунд
- **Tavily Adapter**: Проверяет `/health` эндпоинт каждые 30 секунд

## Примеры использования

### Запуск только Model API

```bash
docker-compose up -d model-api
```

### Пересборка образа

```bash
docker-compose build model-api
docker-compose up -d model-api
```

### Просмотр логов

```bash
# Все логи
docker-compose logs -f

# Только model-api
docker-compose logs -f model-api

# Последние 100 строк
docker-compose logs --tail=100 model-api
```

### Выполнение команд в контейнере

```bash
# Войти в контейнер
docker-compose exec model-api bash

# Выполнить команду
docker-compose exec model-api python -c "print('Hello')"
```

## Troubleshooting

### Проблема: Контейнер не запускается

1. Проверьте логи: `docker-compose logs model-api`
2. Проверьте переменные окружения в `.env`
3. Убедитесь, что порт 8000 свободен

### Проблема: Healthcheck не проходит

1. Проверьте, что приложение запустилось: `docker-compose exec model-api ps aux`
2. Проверьте логи на наличие ошибок
3. Увеличьте `start_period` в healthcheck, если приложению нужно больше времени на запуск

### Проблема: Нет доступа к данным

1. Убедитесь, что директория `data/` существует
2. Проверьте права доступа к файлам
3. Убедитесь, что volume правильно смонтирован


