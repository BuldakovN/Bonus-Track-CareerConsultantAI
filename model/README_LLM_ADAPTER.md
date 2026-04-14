# LLM Adapter - Поддержка различных провайдеров LLM

Модуль `llm_adapter.py` предоставляет абстракцию для работы с различными LLM провайдерами через единый интерфейс.

## Поддерживаемые провайдеры

- **Yandex Cloud** (по умолчанию) - через Yandex Cloud ML SDK
- **OpenAI** - через Langchain
- **OpenRouter** - через Langchain (`ChatOpenAI` + OpenRouter API base URL)
- **Anthropic (Claude)** - через Langchain
- **Google (Gemini)** - через Langchain

## Использование

### Настройка через переменные окружения

По умолчанию используется Yandex Cloud. Для использования другого провайдера установите переменную окружения:

```bash
# Для OpenAI
export LLM_PROVIDER=openai
export OPENAI_API_KEY=your_api_key

# Для OpenRouter
export LLM_PROVIDER=openrouter
export OPENROUTER_API_KEY=your_api_key
# Опционально:
# export OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
# export OPENROUTER_HTTP_REFERER=https://your-app-url.example
# export OPENROUTER_X_TITLE=AI-Gigaschool

# Для Anthropic
export LLM_PROVIDER=anthropic
export ANTHROPIC_API_KEY=your_api_key

# Для Google
export LLM_PROVIDER=google
export GOOGLE_API_KEY=your_api_key

# Для Yandex (по умолчанию)
export LLM_PROVIDER=yandex
export YANDEX_CLOUD_FOLDER=your_folder_id
export YANDEX_CLOUD_API_KEY=your_api_key
```

### Программная настройка

Вы можете указать провайдер при создании экземпляра `Model`:

```python
from start_llm import Model

# Использование OpenAI
model = Model(
    llm_provider="openai",
    api_key="your_openai_api_key",
    model_name="gpt-4o-mini"  # опционально
)

# Использование OpenRouter
model = Model(
    llm_provider="openrouter",
    api_key="your_openrouter_api_key",
    model_name="openai/gpt-4o-mini"  # опционально
)

# Использование Anthropic
model = Model(
    llm_provider="anthropic",
    api_key="your_anthropic_api_key",
    model_name="claude-3-5-sonnet-20241022"  # опционально
)

# Использование Google
model = Model(
    llm_provider="google",
    api_key="your_google_api_key",
    model_name="gemini-pro"  # опционально
)
```

## Архитектура

Модуль использует паттерн Adapter для абстракции различных LLM провайдеров:

1. **LLMAdapter** - абстрактный базовый класс с методами:
   - `chat()` - асинхронный чат
   - `chat_sync()` - синхронный чат
   - `tool_call()` - вызов функций (function calling)

2. **YandexAdapter** - реализация для Yandex Cloud ML SDK

3. **LangchainAdapter** - реализация для Langchain провайдеров (OpenAI, OpenRouter, Anthropic, Google, Mistral)

4. **create_llm_adapter()** - фабрика для создания нужного адаптера

## Обратная совместимость

Код полностью обратно совместим. Если не указан провайдер, используется Yandex Cloud как раньше.

## Установка зависимостей

Для использования Langchain провайдеров установите соответствующие пакеты:

```bash
# Для OpenAI
pip install langchain-openai

# Для Anthropic
pip install langchain-anthropic

# Для Google
pip install langchain-google-genai
```

## Примечания

- Tool calling (function calling) поддерживается для всех провайдеров
- Формат сообщений унифицирован: `[{"role": "system|user|assistant", "text": "..."}]`
- Все провайдеры автоматически конвертируют сообщения в нужный формат


