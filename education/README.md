# Education Parsers & Vector Base

Единый формат хранения и обработки образовательных программ. Поддерживаются провайдеры Stepik и Поступи. Реализованы парсеры, объединяющий скрипт и построение векторной базы знаний для семантического поиска.

## Формат данных (одна программа = один JSON-документ)


### Структура JSON-документа образовательной программы


| Поле         | Тип     | Описание |
|--------------|---------|----------|
| `id`         | string  | Уникальный идентификатор программы (например, `stepik:12345`) |
| `title`      | string  | Название программы |
| `type`       | string  | Тип программы: `bachelor`, `master`, `specialist`, `spo`, `course`, `dpo` |
| `provider`   | string  | Источник/провайдер данных (например, `Stepik`, `Postupi`) |
| `link`       | string  | Ссылка на страницу программы |
| `source`     | string  | Название источника (например, `stepik`) |
| `description`| string/ null | Краткое описание (если есть) |

Пример:
```json
{
  "id": "stepik:12345",
  "title": "Алгоритмы и структуры данных",
  "type": "course",
  "provider": "Stepik",
  "link": "https://stepik.org/course/12345",
  "source": "stepik",
  "description": "Базовый курс по алгоритмам и структурам данных."
}
```

---

## Переменные окружения

- `STEPIK_CLIENT_ID`, `STEPIK_CLIENT_SECRET`, `STEPIK_ACCESS_TOKEN` — для Stepik
- `EDU_USER_AGENT` — для парсеров
- (для векторной базы) `YANDEX_CLOUD_API_KEY`, `YANDEX_CLOUD_FOLDER`

---

## Парсеры образовательных программ

### Stepik

Собрать данные с Stepik и сохранить в файл:

```bash
python -m education stepik --pages 1 --page-size 20 --language ru
```
Результат: `data/education/stepik.ndjson`

### Поступи (postupi)

Собрать данные с Поступи:

```bash
python -m education postupi --cities msk --out data/education/postupi_msk.ndjson
python -m education postupi --out data/education/postupi_msk.ndjson
```
Результат: `data/education/postupi_msk.ndjson`

---

## Объединяющий скрипт

Для объединения и агрегации данных из разных источников используйте:

```bash
python -m education.build_education_json
```
Результат: агрегированные файлы в `data/education/education_comparison.json` и др.

---

## Построение векторной базы знаний

Для построения FAISS-векторной базы по агрегированному файлу:

```bash
python -m education.build_education_faiss_index
```
Результат: индекс и метаданные сохраняются в `data/education/education_vector/<провайдер>/` (slug из `RAG_EMBEDDING_PROVIDER` или `LLM_PROVIDER`, см. `professions_vector_index.store_paths`).

