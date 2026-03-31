# C4 Container-диаграмма

```mermaid
flowchart TB
    subgraph Клиент
      TG[tg-module / Telegram transport]
    end

    subgraph Система[AI Assistant PoC]
      API[Core API]
      ORCH[Orchestrator Graph]
      RET[Retriever-слой]
      TOOLS[Tool/API Adapters]
      MEM[Менеджер контекста и памяти]
      OUT[Выходной guard]
    end

    subgraph Данные[Хранилище]
      CRUD[crud-service + SQLite]
      VEC[Vector Store]
      CFG[Config / Env / Secrets]
    end

    subgraph Внешние_сервисы
      LLM[llm-service / model backend]
      WEB[Web Search API]
      OBS[Логи / Метрики / Трейсы]
    end

    TG --> API
    API --> ORCH
    ORCH --> MEM
    ORCH --> RET
    ORCH --> TOOLS
    ORCH --> LLM
    RET --> VEC
    TOOLS --> WEB
    MEM --> CRUD
    ORCH --> OUT
    API --> OBS
    ORCH --> OBS
    LLM --> OBS
    CFG -.-> API
    CFG -.-> ORCH
```

## Пояснения

- `core` владеет всей логикой переходов и quality gates.
- Retrieval и tool-вызовы являются явными контейнерами исполнения, а не скрытыми деталями реализации.
