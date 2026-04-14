FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

COPY core/requirements.txt ./core/requirements.txt
RUN pip install --no-cache-dir -r core/requirements.txt

COPY common/ ./common/
COPY core/ ./core/
COPY model/config.yaml ./model/config.yaml
COPY model/prof_tests.yaml ./model/prof_tests.yaml
COPY data/ ./data/

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV CORE_CONFIG_DIR=/app/model
ENV EDUCATION_JSON_PATH=/app/data/education/education_detailed.json

RUN mkdir -p /app/logs

EXPOSE 8020

CMD ["python", "-m", "uvicorn", "core.main:app", "--host", "0.0.0.0", "--port", "8020"]
