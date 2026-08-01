FROM python:3.11-slim

WORKDIR /app

RUN adduser --disabled-password --gecos '' appuser

COPY app.py .

RUN chown -R appuser:appuser /app

USER appuser

EXPOSE 8095

CMD ["python", "app.py"]
