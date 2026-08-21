#!/usr/bin/env sh
set -eu

ROOT_DIR="${1:-/home/kadin/homelab2}"
ENV_FILE="$ROOT_DIR/.env"

if [ ! -f "$ENV_FILE" ]; then
  echo "missing_env_file=$ENV_FILE" >&2
  exit 1
fi

cd "$ROOT_DIR"

if ! grep -q '^DOCMOST_APP_SECRET=' "$ENV_FILE"; then
  printf '\nDOCMOST_APP_SECRET=' >> "$ENV_FILE"
  openssl rand -hex 32 >> "$ENV_FILE"
fi

if ! grep -q '^DOCMOST_APP_URL=' "$ENV_FILE"; then
  printf 'DOCMOST_APP_URL=http://100.79.132.39:3004\n' >> "$ENV_FILE"
fi

docker exec homelab_postgres sh -eu -c '
  if ! psql -U "$POSTGRES_USER" -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '\''docmost'\''" | grep -q 1; then
    createdb -U "$POSTGRES_USER" docmost
  fi
'

grep -E '^(DOCMOST_APP_SECRET|DOCMOST_APP_URL)=' "$ENV_FILE" | sed -E 's/(DOCMOST_APP_SECRET=).*/\1[set]/'
echo "docmost_database=ready"
