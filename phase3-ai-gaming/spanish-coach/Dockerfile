FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1

RUN adduser --disabled-password --gecos '' appuser

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY static ./static

RUN chown -R appuser:appuser /app

USER appuser

EXPOSE 8120

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8120"]
