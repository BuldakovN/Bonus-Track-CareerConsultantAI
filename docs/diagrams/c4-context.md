# C4 Context-диаграмма

```mermaid
flowchart LR
    U[Пользователь]
    TG[Telegram]
    SYS[PoC-система AI Assistant]
    LLM[LLM Provider / llm-service]
    CRUD[CRUD-сервис]
    VS[Хранилище векторного индекса]
    WS[Web Search API]
    OBS[Стек наблюдаемости]

    U --> TG
    TG --> SYS
    SYS --> LLM
    SYS --> CRUD
    SYS --> VS
    SYS --> WS
    SYS --> OBS
```

## Пояснения

- Граница системы включает оркестрацию, retrieval, policy-проверки и формирование ответа.
- Внешние зависимости изолированы API-адаптерами и защищены timeout/retry-политиками.
