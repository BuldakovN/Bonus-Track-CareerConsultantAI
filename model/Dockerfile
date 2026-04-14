# Используем официальный Python образ
FROM python:3.11-slim

# Устанавливаем рабочую директорию
WORKDIR /app

# Устанавливаем системные зависимости
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Копируем файл зависимостей из model
COPY model/requirements.txt ./model/requirements.txt

# Устанавливаем дополнительные зависимости для FastAPI и uvicorn
RUN pip install --no-cache-dir \
    fastapi>=0.100.0 \
    uvicorn[standard]>=0.23.0 \
    pydantic>=2.0.0 \
    pyyaml>=6.0

# Устанавливаем Python зависимости
RUN pip install --no-cache-dir -r model/requirements.txt

# Копируем код приложения из директории model
COPY model/ ./model/

COPY ./repo/ ./model/repo/

COPY common/ ./common/

# data нужна для образовательных JSON (роудмап и т.д.)
COPY data/ ./data/

# Создаем директорию для логов и временных файлов
RUN mkdir -p /app/logs

# Устанавливаем переменные окружения
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Открываем порт
EXPOSE 8000

# Переходим в директорию model для запуска
WORKDIR /app

# Команда для запуска приложения
CMD ["python", "model/app_run.py"]
#CMD ["ls"]

