#!/usr/bin/env bash
set -euo pipefail

NEXTCLOUD_CONTAINER="${NEXTCLOUD_CONTAINER:-nextcloud}"
NEXTCLOUD_USER="${NEXTCLOUD_USER:-www-data}"
LOG_PREFIX="[nextcloud-nightly-sync]"

if ! docker inspect "$NEXTCLOUD_CONTAINER" >/dev/null 2>&1; then
  echo "$LOG_PREFIX container not found: $NEXTCLOUD_CONTAINER" >&2
  exit 1
fi

status="$(docker inspect -f '{{.State.Running}}' "$NEXTCLOUD_CONTAINER")"
if [[ "$status" != "true" ]]; then
  echo "$LOG_PREFIX container is not running; skipping"
  exit 0
fi

echo "$LOG_PREFIX starting cron.php"
docker exec -u "$NEXTCLOUD_USER" "$NEXTCLOUD_CONTAINER" php -f /var/www/html/cron.php

echo "$LOG_PREFIX starting files:scan --all"
docker exec -u "$NEXTCLOUD_USER" "$NEXTCLOUD_CONTAINER" php occ files:scan --all --quiet

echo "$LOG_PREFIX completed"
