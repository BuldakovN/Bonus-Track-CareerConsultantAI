# Используем официальный Python образ
FROM python:3.11-slim

# CA для исходящего HTTPS (api.telegram.org и др.)
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем общий модуль логирования и код бота
COPY common/ ./common/
COPY tg-module/ ./tg-module/

RUN mkdir -p /app/logs

# Копируем файл зависимостей
#COPY tg-module/requirements.txt ./requirements.txt

# Устанавливаем Python зависимости
RUN pip install --no-cache-dir -r tg-module/requirements.txt


# Устанавливаем переменные окружения
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Команда для запуска бота
CMD ["python", "tg-module/run_bot.py"]
