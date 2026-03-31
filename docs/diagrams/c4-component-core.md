# C4 Component-диаграмма (`core`)

```mermaid
flowchart LR
    IN[Нормализатор запроса]
    GUARD[Входной guard]
    ROUTER[Маршрутизатор intent/state]
    PLAN[Планировщик исполнения]
    RET[Retrieval Pipeline]
    TP[Движок tool-политик]
    LLMI[LLM-клиент]
    OVAL[Валидатор ответа]
    STATE[Обновление состояния]
    RESP[Сборка ответа]
    TEL[Эмиттер телеметрии]

    IN --> GUARD --> ROUTER --> PLAN
    PLAN --> RET
    PLAN --> TP
    PLAN --> LLMI
    RET --> LLMI
    TP --> LLMI
    LLMI --> OVAL --> STATE --> RESP
    OVAL --> TEL
    STATE --> TEL
    RESP --> TEL
```

## Пояснения

- Планировщик может пропускать retrieval/tool-ноды для простых turn диалога.
- Валидатор ответа обязателен до persistence и выдачи ответа пользователю.
