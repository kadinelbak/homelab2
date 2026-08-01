FROM node:22-bookworm-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends git python3 ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g @openai/codex

RUN adduser --disabled-password --gecos '' appuser

COPY app.py .

RUN chown -R appuser:appuser /app

USER appuser

EXPOSE 18300

CMD ["python3", "app.py"]
