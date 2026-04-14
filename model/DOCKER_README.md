# Docker для Model Module

## Сборка образа

Dockerfile должен собираться из **корневой директории проекта**, так как приложению нужны модули из корня (`professions_vector_index`, `data`).

```bash
# Из корневой директории проекта
docker build -f model/Dockerfile -t ai-gigaschool-model:latest .
```

## Запуск контейнера

```bash
docker run -d \
  --name model-api \
  -p 8000:8000 \
  -e YANDEX_CLOUD_FOLDER=your_folder_id \
  -e YANDEX_CLOUD_API_KEY=your_api_key \
  -e LLM_PROVIDER=yandex \
  ai-gigaschool-model:latest
```

### Использование с другими LLM провайдерами

**OpenAI:**
```bash
docker run -d \
  --name model-api \
  -p 8000:8000 \
  -e LLM_PROVIDER=openai \
  -e OPENAI_API_KEY=your_openai_key \
  ai-gigaschool-model:latest
```

**Anthropic:**
```bash
docker run -d \
  --name model-api \
  -p 8000:8000 \
  -e LLM_PROVIDER=anthropic \
  -e ANTHROPIC_API_KEY=your_anthropic_key \
  ai-gigaschool-model:latest
```

**Google:**
```bash
docker run -d \
  --name model-api \
  -p 8000:8000 \
  -e LLM_PROVIDER=google \
  -e GOOGLE_API_KEY=your_google_key \
  ai-gigaschool-model:latest
```

## Использование .env файла

Можно использовать файл `.env` из корня проекта:

```bash
docker run -d \
  --name model-api \
  -p 8000:8000 \
  --env-file ../.env \
  ai-gigaschool-model:latest
```

## Проверка работы

После запуска контейнера API будет доступен по адресу:
- API: http://localhost:8000
- Документация: http://localhost:8000/docs

## Просмотр логов

```bash
docker logs -f model-api
```

## Остановка и удаление

```bash
docker stop model-api
docker rm model-api
```

## Структура в контейнере

```
/app/
├── model/              # Код приложения
├── professions_vector_index/  # Модуль для векторного поиска
└── data/               # Данные (векторные индексы, образовательные данные)
```

## Переменные окружения

- `YANDEX_CLOUD_FOLDER` - ID папки Yandex Cloud (для Yandex провайдера)
- `YANDEX_CLOUD_API_KEY` - API ключ Yandex Cloud (для Yandex провайдера)
- `LLM_PROVIDER` - Провайдер LLM: `yandex`, `openai`, `anthropic`, `google` (по умолчанию: `yandex`)
- `OPENAI_API_KEY` - API ключ OpenAI (для OpenAI провайдера)
- `ANTHROPIC_API_KEY` - API ключ Anthropic (для Anthropic провайдера)
- `GOOGLE_API_KEY` - API ключ Google (для Google провайдера)


