# Диаграмма потоков данных

```mermaid
flowchart LR
    UIN[Ввод пользователя]
    NORM[Нормализованный запрос]
    HIST[Окно истории]
    RETQ[Retrieval query]
    CH[Retrieved chunks]
    PROMPT[Финальный prompt модели]
    MOUT[Выход модели]
    FOUT[Валидированный ответ]
    PERS[Персистентное состояние]
    LOG[Логи/метрики/трейсы]

    UIN --> NORM
    NORM --> HIST
    NORM --> RETQ
    RETQ --> CH
    HIST --> PROMPT
    CH --> PROMPT
    PROMPT --> MOUT
    MOUT --> FOUT
    FOUT --> PERS
    NORM --> LOG
    CH --> LOG
    MOUT --> LOG
    FOUT --> LOG
    PERS --> LOG
```

## Хранимые и временные данные

- Хранимые: фаза state machine, структурированные поля профиля, компактная история, metadata решений.
- Transient: артефакты сборки prompt, промежуточные payload tools, сырые retrieval-кандидаты.
- Logged (redacted): latency, token usage, решения по веткам, причина fallback, результат guard.
