# Архитектура PoC-системы (LLM-first)

## 1) Область и цели

Документ фиксирует архитектуру PoC AI-ассистента так, чтобы можно было переходить к реализации без существенных архитектурных пробелов.

Ключевые цели:
- стабильный пользовательский диалог с оркестрацией по фазам;
- надежный retrieval-augmented generation для запросов о профессиях и роадмапах;
- безопасная работа с tools/API с контролем побочных эффектов;
- измеримое качество через явные точки контроля и fallback-механизмы.

Вне scope PoC:
- жесткие real-time гарантии;
- отказоустойчивость multi-region уровня enterprise;
- автономные высокорисковые действия без подтверждения пользователя.

## 2) Ключевые архитектурные решения

1. **Оркестрация вынесена из модели.** LLM — компонент рассуждения, но не владелец workflow; все переходы контролирует граф `core`.
2. **Единый источник истины по состоянию сессии — CRUD-сервис.** In-memory кэши допустимы только как ускорители.
3. **Retrieval — явный этап, а не скрытый prompt-трюк.** Построение запроса, поиск, rerank и упаковка контекста — отдельные контрольные точки.
4. **Защитные механизмы многоуровневые.** Входной guard, guard политик tools, выходной guard и guard надежности независимы.
5. **Для каждой внешней зависимости определены timeout + retry budget + fallback путь.**
6. **Observability по умолчанию.** Каждый turn оставляет структурированный след с решениями и причинами деградации.

## 3) Состав модулей и роли

- `tg-module` (transport/UI): Telegram updates, кнопки, форматирование, без предметной логики.
- `core` (orchestrator): нормализация запроса, выполнение графа, policy checks, переходы состояния, сборка ответа.
- `llm-service`: chat completions и опциональный endpoint для tool-call planning.
- `retrieval layer` (внутри `core` на PoC): query builder, vector search, lexical fallback, reranker, context packer.
- `crud-service`: чтение/запись session snapshot, metadata, conversation history.
- `tool/API layer`: web search и доменные API через типизированные адаптеры с policy enforcement.
- `storage`: SQLite (session + history), vector index (знания по профессиям), config/env.
- `observability`: logs, metrics, traces, quality counters, eval hooks.

## 4) Основной execution flow (happy path)

1. Сообщение клиента приходит в `core` через API.
2. `core` загружает снимок сессии из `crud-service`.
3. Входной guard проверяет prompt-injection/jailbreak/content policy.
4. Router выбирает ветку: dialog / profession-info / roadmap / clean.
5. Для retrieval-веток:
   - формируется retrieval query из намерения пользователя и профиля сессии;
   - извлекаются top-k чанки (vector; при необходимости lexical fallback);
   - выполняется rerank и упаковка контекста в token budget.
6. Orchestrator формирует вход модели (system + policy + context + history window).
7. Вызов `llm-service` выполняется с timeout и ограниченной температурой.
8. Выходной guard проверяет формат, safety-флаги и критерии confidence.
9. `core` сохраняет обновленное состояние и decision metadata.
10. Ответ возвращается клиенту, quality-сигналы публикуются в observability.

## 5) State / memory / context handling

### 5.1 Модель состояния

Персистентные поля (authoritative):
- `user_state` (who/about/test/recommendation/talk/inject_attempt);
- `user_type`, `test_results`, рекомендованные профессии;
- компактная история диалога и metadata по turn.

Эфемерные поля (только в рамках запроса):
- retrieved chunks;
- кандидаты tool-вызовов;
- guard decisions и risk score.

### 5.2 Политика памяти

- Долговременная память: только структурированные поля в CRUD.
- Краткосрочная память: последние `N` turn с role-aware усечением.
- Запрещено слепое включение всей истории в prompt.
- Любое обновление памяти от модели проходит schema validation до persist.

### 5.3 Политика context budget

- Бюджет резервируется под: system policy, user message, retrieved context, response.
- Для каждого сегмента есть hard cap; сначала режется retrieval, затем history, policy не режется.
- Если переполнение сохраняется — включается concise-mode prompt с ограниченным ответом.

## 6) Retrieval-контур

Конвейер:
1. Intent classifier решает, нужен ли retrieval и какой профиль корпуса использовать.
2. Query constructor строит:
   - semantic query (dense);
   - keyword query (sparse fallback).
3. Основной retrieval из vector index (top-k).
4. Lexical fallback при низком recall или miss индекса.
5. Reranking (cross-encoder или эвристический score blend).
6. Context packer:
   - удаляет дубликаты;
   - сохраняет source IDs;
   - соблюдает token budget.
7. Grounded generation prompt с набором evidence, пригодным для ссылок.

Контроль качества:
- минимальный порог релевантности;
- ограничение на устаревание источников (где применимо);
- правило abstain при confidence ниже порога.

## 7) Tool/API интеграции

Интеграционный контракт (для всех tools):
- детерминированные JSON input/output схемы;
- явные timeout и retry policy;
- класс идемпотентности (`read-only` / `write-confirmed`);
- декларация side effects и аудит;
- нормализованный error surface для LLM/orchestrator.

Политика выполнения:
- tools никогда не вызываются напрямую из transport-слоя;
- orchestrator разрешает вызов по allowlist и текущему состоянию;
- высокорисковые вызовы требуют явного confirmation flag от пользователя;
- при отказе tool: bounded retry -> alternate tool -> текстовый graceful fallback.

## 8) Failure modes, fallback и guardrails

Основные failure modes:
- LLM timeout или 5xx;
- retrieval miss / низкая релевантность;
- недоступность CRUD;
- tool timeout или некорректный ответ;
- prompt-injection попытки и unsafe output.

Fallback-стратегия:
- сбой модели -> retry с укороченным prompt -> fallback-профиль модели -> безопасный ответ + следующий шаг;
- сбой retrieval -> lexical fallback -> негрунтованный ответ с маркером неопределенности;
- сбой CRUD -> stateless mode + warning metric + запрет деструктивных обновлений;
- сбой tool -> подавление результата tool и продолжение базовым ответом.

Guardrails:
- input guard (injection/jailbreak паттерны, unsafe intents);
- усиление policy prompt (непереопределяемые правила);
- output validator (schema + safety classes + запрещенные директивы);
- rate limit и cooldown для повторных злоупотреблений.

## 9) Технические и операционные ограничения (PoC baseline)

- **Latency target (p95):**
  - стандартный turn: <= 4.0s;
  - retrieval turn: <= 6.0s.
- **Cost target:**
  - средняя стоимость <= $0.01 за turn;
  - hard cap <= $0.03 за turn с truncation/degradation.
- **Reliability target:**
  - доля успешных ответов >= 99.0%;
  - доля деградированных, но полезных ответов >= 99.7%.
- **Timeout по умолчанию:**
  - LLM call 8s;
  - retrieval stage 1.5s;
  - CRUD stage 1.0s;
  - tool call 2.0s.
- **Retries:**
  - максимум 1 retry для LLM/tool, exponential backoff, jitter включен.
- **Базовая безопасность:**
  - без секретов в prompts/logs;
  - секреты только через env;
  - редактирование PII в диагностических логах.

## 10) Точки контроля (quality gates)

Контрольные точки на каждый turn:
1. `CP1 Input Validation` - проверка схемы, авторизации и размера.
2. `CP2 Guard Decision` - классификация abuse/injection.
3. `CP3 Retrieval Quality Gate` - порог релевантности и confidence.
4. `CP4 Tool Safety Gate` - allowlist + политика побочных эффектов.
5. `CP5 Output Validation` - проверка схемы, безопасности и groundedness-маркера.
6. `CP6 Persistence Integrity` - атомарное обновление состояния в CRUD.
7. `CP7 Telemetry Completeness` - обязательная эмиссия logs/metrics/traces.

Ответ считается валидным для эксплуатации, только если пройдены CP1..CP7 или зафиксирован допустимый деградированный путь.
# фСистемный дизайн

## 1) Цель и границы PoC

PoC-система реализует профориентационный диалоговый ассистент с управляемым состоянием, retrieval-поддержкой и контролем качества ответов LLM. Дизайн ориентирован на безопасную и воспроизводимую оркестрацию запроса от пользователя до ответа, с явными fallback-путями при деградации внешних зависимостей.

В рамках текущего этапа система покрывает:

- диалоговые сценарии профориентации (сбор контекста, тестовый блок, рекомендации, follow-up);
- retrieval по локальной базе профессий/образовательных треков (через векторный контур);
- ограниченный веб-поиск (через adapter) как дополнительный инструмент;
- персистентное состояние сессии и метаданные качества;
- базовую наблюдаемость и контроль эксплуатационных рисков.

---

## 2) Ключевые архитектурные решения

1. **LLM-модуль отделен от оркестрации**: `core` (окрекстратор) управляет обworkflow, а `llm-service` выполняет только модельные вызовы и tool-calls.
2. **State как источник логики переходов**: шаги диалога и правила переходов определяются `user_state`, а не эвристиками в UI.
3. **CRUD, подключенный к БД пользователей, как источник истины по сессии**: состояние, метаданные и история хранятся централизованно в SQLite базе.
4. **Retrieval изолирован в отдельном контуре**: векторный поиск и индексы обслуживаются `vector-store`.
5. **Guardrails до генерации ответа**: проверка prompt-injection/jailbreak применяется до передачи в LLM-контур.
6. **Явные fallback-пути**: для ошибок LLM/retrieval/tool предусмотрены деградационные ответы без silent failure.
7. **Наблюдаемость по всему пути запроса**: логи + метрики + технические KPI качества ответа.

---

## 3) Модули и роли

### Пользовательский контур

- `telegram-bot`  
Транспортный слой: принимает сообщения и кнопки, проксирует в `core`, рендерит ответ.

### Прикладное ядро

- `core`  
Оркестратор сценария: гидратация state, guardrails, вызов LLM/retrieval/tools, persist и возврат ответа.

### ML/Knowledge контур

- `llm-service`  
Унифицированный API к выбранному LLM provider (чат и tool call).
- `vector-store`  
Индексация/поиск по доменным источникам (профессии, курсы), выдача релевантных фрагментов.
- `tavily-adapter` + `searxng`  
Ограниченный внешний веб-поиск через безопасный прокси.

### Состояние и данные

- `crud-service` + SQLite  
Хранение `user_state`, profile metadata, истории сообщений и технических полей контроля.

---

## 4) Основной flow

1. Пользователь отправляет сообщение в `telegram-bot`.
2. Бот формирует запрос (user id, prompt, параметры UI-контекста) в `core`.
3. `core.prepare` загружает актуальную сессию из `crud-service`.
4. `core.guard` проверяет запрос на инъекции/нарушения policy.
5. При успешной проверке guard переход в `core.dialog`:
  - определяет активный `user_state`;
  - при необходимости вызывает `vector-store` (для извлечения профессий и курсов);
  - формирует промпт к LLM;
  - вызывает `llm-service`.
6. `core.persist` сохраняет новый state, метаданные, историю и quality-сигналы в БД через `crud-service`.
7. Ответ возвращается в `telegram-bot`пользователю.
8. При ошибках на шаге 5/6 запускается fallback-ветка (safe response + лог причины + retry policy при допустимости).

---

## 5) State, memory и context handling

### Session state

- Ключевой автомат: `who -> about -> test -> recommendation -> talk` (идентифицировать пользователя, узнать подробности проблемы, провести тест, дать рекомендации).
- Состояние хранится per-user в `crud-service`; `core` не является источником истины.
- Для security-событий используется служебный state/flag (например, `inject_attempt`), после фиксации состояние возвращается в рабочую фазу.

### Memory policy

- **Short-term memory**: недавние сообщения текущей сессии (окно контекста).
- **Structured memory**: извлеченные слоты пользователя (тип, интересы, результаты теста, shortlist профессий).
- **No raw over-retention**: не хранить в long-term память весь промпт без нормализации и минимизации.

### Context budget

- Контекст LLM собирается в фиксированном бюджете токенов:
  - system + policy + текущий intent: высокий приоритет;
  - релевантная история: ограниченное окно;
  - retrieval snippets: top-k с дедупликацией;
  - низкоприоритетные хвосты истории отбрасываются первыми.

---

## 6) Retrieval-контур

- Источники: доменные JSON/структурированные данные о профессиях и обучении.
- Индексация: FAISS-индексы по профессиям и образовательным материалам.
- Поиск:
  1. embedding + vector search top-k,
  2. пост-фильтрация по доменным правилам,
  3. optional rerank.
- Выход retrieval в оркестратор.
- Правило генерации: ответы с фактами должны опираться на retrieval evidence; если evidence нет — explicit uncertainty и мягкий fallback.

---

## 7) Tool/API-интеграции

- `core -> crud-service`: чтение/запись сессии, очистка, разрешение identity.
- `core -> llm-service`: чат-генерация и tool-call endpoint.
- `core -> vector-store`: retrieval по профессиям/роадмапу, при необходимости trigger rebuild (ограниченный, с секретом).
- `core -> tavily-adapter`: внешнее уточнение через web-search (ограниченный allowlist/quotas).
- `telegram-bot -> core`: единая точка входа для пользовательского запроса.

Интеграционные правила:

- timeout и retry на каждый upstream вызов;
- circuit-breaker/деградация на нестабильных внешних инструментах;
- idempotent semantics для безопасных повторов;
- трассировка с correlation-id сквозь все сервисы.

---

## 8) Failure modes, fallback и guardrails

### Основные failure modes

1. `llm-service` timeout/5xx/provider error.
2. `vector-store` недоступен или возвращает нерелевантный/пустой контекст.
3. `crud-service` недоступен (невозможно гидратировать/зафиксировать state).
4. tool/web-search возвращает шум, неподходящие или небезопасные фрагменты.
5. prompt-injection/jailbreak в пользовательском вводе.
6. переполнение context budget и деградация качества ответа.

### Fallback-поведение

- LLM недоступен: ограниченный шаблонный ответ + просьба повторить + лог инцидента.
- Retrieval недоступен: ответ без фактологических утверждений, с дисклеймером и безопасной альтернативой.
- Persist ошибка: пользователю выдаётся ответ, но ставится флаг `persistence_error`; повторная попытка сохранения.
- Tool ошибка: пропуск tool branch, возврат к базовому диалогу.

### Guardrails

- pre-LLM injection detection (эвристики + сигнатуры jailbreak);
- policy-layer в system prompt (запрет на опасные/неэтичные рекомендации);
- ответ в безопасном тоне для образовательного домена;
- ограничение побочных эффектов tool-вызовов (read-only по умолчанию);
- фильтрация исходящего контента (PII/unsafe claims) перед отправкой пользователю.

---

## 9) Ограничения и SLO/SLA ориентиры PoC

### Технические ограничения

- Монолитный SQLite ограничивает горизонтальное масштабирование записи.
- Качество retrieval ограничено полнотой и актуальностью локальных источников.
- Провайдер LLM может иметь переменную latency/availability.

### Операционные ограничения

- Без гарантии 24/7 production-SLA (стадия PoC).
- Ограниченные бюджеты на токены и web-search запросы.
- Ручной контроль части quality gates на ранних этапах.

### Целевые ориентиры PoC

- **Latency**: p50 <= 3.0s, p95 <= 7.0s для обычного диалога без тяжелого tool chain.
- **Cost**: средняя стоимость 1 диалогового turn в пределах бюджетного лимита (настраивается по провайдеру и модели).
- **Reliability**: >= 99% успешных ответов без 5xx на уровне `core`, >= 95% успешных retrieval-запросов.
- **Safety/quality**: 0 критических policy-violations на контрольном eval-наборе.

---

## 10) Точки контроля качества (quality gates)

1. **Входной gate**: валидация запроса, sanity-check параметров, screening инъекций.
2. **Контекстный gate**: контроль состава контекста и trimming по budget.
3. **Генерационный gate**: проверка формата/структуры ответа и наличия обязательных полей.
4. **Safety gate**: фильтрация опасных/неэтичных/галлюцинаторных утверждений.
5. **Persist gate**: атомарная фиксация состояния и metadata.
6. **Observability gate**: запись метрик и trace-атрибутов по каждому turn.

Данный дизайн достаточен для старта реализации: модули, контракты, flow, ограничения, защитные механики и контроль качества зафиксированы с фокусом на LLM-контур и его отказоустойчивость.