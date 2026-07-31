FROM python:3.12-alpine

RUN apk add --no-cache docker-cli docker-cli-compose

WORKDIR /app
COPY app.py /app/app.py

ENV HOMELAB_REPO=/homelab \
    HOMELAB_CONTROL_HOST=0.0.0.0 \
    HOMELAB_CONTROL_PORT=5055

EXPOSE 5055
CMD ["python", "/app/app.py"]
