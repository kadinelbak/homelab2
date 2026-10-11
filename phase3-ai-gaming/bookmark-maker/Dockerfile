FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends openscad potrace librsvg2-bin fonts-dejavu-core fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir pillow==11.0.0

RUN adduser --disabled-password --gecos '' appuser

COPY *.py page.html ./

USER appuser

EXPOSE 8105

CMD ["python", "app.py"]
