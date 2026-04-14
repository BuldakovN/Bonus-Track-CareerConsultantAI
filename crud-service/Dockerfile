FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir fastapi "uvicorn[standard]" pydantic "sqlalchemy>=2.0.0"

COPY repo/ ./repo/
COPY crud-service/main.py ./main.py

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

RUN mkdir -p /app/db

EXPOSE 8010

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8010"]
