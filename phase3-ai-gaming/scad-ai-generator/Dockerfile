FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends openscad xvfb xauth ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir cadquery==2.5.2

RUN adduser --disabled-password --gecos '' appuser

COPY app.py .

RUN chown -R appuser:appuser /app

USER appuser

EXPOSE 8102

CMD ["python", "app.py"]
