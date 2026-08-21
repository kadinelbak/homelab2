FROM python:3.12-slim

WORKDIR /app

RUN adduser --disabled-password --gecos '' appuser

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini .
COPY migrations ./migrations
ARG JARVIS_CORE_SOURCE_VERSION=local
COPY jarvis_core ./jarvis_core

RUN chown -R appuser:appuser /app

USER appuser

EXPOSE 8097

CMD ["sh", "-c", "alembic upgrade head && uvicorn jarvis_core.main:app --host 0.0.0.0 --port 8097"]
