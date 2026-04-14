# SearXNG Tavily Adapter

**Tavily-совместимая обертка для SearXNG** - используйте SearXNG с тем же API что и у Tavily!

## 🚀 Быстрая настройка

1. **Скопируйте пример конфигурации:**
   ```bash
   cp config.example.yaml config.yaml
   ```

2. **Отредактируйте config.yaml:**
   ```bash
   nano config.yaml
   # или
   code config.yaml
   ```

3. **Обязательно поменяйте:**
   - `server.secret_key` - секретный ключ для SearXNG (минимум 32 символа)
   
4. **Опционально настройте:**
   - `adapter.searxng_url` - URL для подключения к SearXNG
   - `adapter.scraper.user_agent` - User-Agent для скрапинга
   - `adapter.scraper.max_content_length` - максимальный размер raw_content

## 💡 Использование как замена Tavily

### Вариант 1: Python клиент (локальный)

```python
# Вместо: from tavily import TavilyClient
from simple_tavily_adapter.tavily_client import TavilyClient

# Используете точно так же как оригинальный Tavily!
client = TavilyClient()  # API ключ не нужен
response = client.search(
    query="цена bitcoin",
    max_results=5,
    include_raw_content=True
)
print(response)
```

### Вариант 2: Через HTTP API

```python
import requests

response = requests.post("http://localhost:1000/search", json={
    "query": "цена bitcoin",
    "max_results": 5,
    "include_raw_content": True
})
print(response.json())
```

### Вариант 3: Замена base_url в оригинальном Tavily

```python
# Установите оригинальный клиент
# pip install tavily-python

from tavily import TavilyClient

# Поменяйте только base_url!
client = TavilyClient(
    api_key="не_важно",  # Ключ игнорируется
    base_url="http://localhost:1000"  # Ваш адаптер
)

response = client.search(
    query="цена bitcoin",
    max_results=5,
    include_raw_content=True
)
```

## 🔄 Миграция с Tavily

Замените в своем коде:

```python
# Было:
# client = TavilyClient("tvly-xxxxxxx")

# Стало:
client = TavilyClient()  # Без API ключа
# ИЛИ
client = TavilyClient(base_url="http://localhost:1000")
```

Остальной код **остается без изменений**!

## Генерация секретного ключа

```bash
# Способ 1: Python
python3 -c "import secrets; print(secrets.token_hex(32))"

# Способ 2: OpenSSL
openssl rand -hex 32

# Способ 3: /dev/urandom
head -c 32 /dev/urandom | xxd -p -c 32
```

## Структура конфигурации

```yaml
# SearXNG настройки (корневой уровень)
use_default_settings: true
server:
  secret_key: "ВАШ_СЕКРЕТНЫЙ_КЛЮЧ"
search:
  formats: [html, json, csv, rss]

# Tavily Adapter настройки
adapter:
  searxng_url: "http://searxng:8080"
  server:
    port: 1000
  scraper:
    max_content_length: 2500
```

## Запуск

```bash
docker-compose up -d
```

## ✅ Проверка работы

```bash
# SearXNG
curl "http://localhost:8999/search?q=test&format=json"

# Tavily Adapter  
curl -X POST "http://localhost:1000/search" \
     -H "Content-Type: application/json" \
     -d '{"query": "test", "max_results": 3}'
```

## 📊 Формат ответа

Полностью совместим с Tavily API:

```json
{
  "query": "цена bitcoin",
  "follow_up_questions": null,
  "answer": null,
  "images": [],
  "results": [
    {
      "url": "https://example.com",
      "title": "Bitcoin Price",
      "content": "Bitcoin costs $50,000...",
      "score": 0.9,
      "raw_content": "Full page content..."
    }
  ],
  "response_time": 1.23,
  "request_id": "uuid-string"
}
```

## 🎯 Преимущества

- ✅ **Бесплатно** - без API ключей и лимитов
- ✅ **Приватность** - поиск через ваш SearXNG
- ✅ **Совместимость** - точно такой же API как у Tavily
- ✅ **Скорость** - локальное развертывание
- ✅ **Контроль** - настройте движки под себя
