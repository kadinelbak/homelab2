FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends espeak-ng ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY app.py /app/app.py

EXPOSE 8101
CMD ["python", "/app/app.py"]
