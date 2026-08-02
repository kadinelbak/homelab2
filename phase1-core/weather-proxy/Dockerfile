FROM python:3.11-alpine
WORKDIR /app
COPY app.py .
RUN adduser -D appuser && mkdir -p /data && chown -R appuser:appuser /app /data
USER appuser
CMD ["python", "app.py"]
