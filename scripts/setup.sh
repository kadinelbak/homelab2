#!/usr/bin/env bash
# =============================================================================
# Homelab setup/bootstrap helper
#
# Safe to run repeatedly from any working directory:
#   bash scripts/setup.sh
#   bash scripts/setup.sh --validate-only
#   bash scripts/setup.sh --with-phase1
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_EXAMPLE="${REPO_ROOT}/.env.example"
ENV_FILE="${REPO_ROOT}/.env"

VALIDATE_ONLY=false
WITH_PHASE1=false

for arg in "$@"; do
  case "$arg" in
    --validate-only) VALIDATE_ONLY=true ;;
    --with-phase1) WITH_PHASE1=true ;;
    -h|--help)
      sed -n '1,12p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown argument: $arg" >&2
      exit 2
      ;;
  esac
done

log() {
  printf '%s\n' "$*"
}

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "Missing required command '$1'."
}

load_env() {
  [[ -f "$ENV_FILE" ]] || cp "$ENV_EXAMPLE" "$ENV_FILE"
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
}

validate_env_file() {
  [[ -f "$ENV_FILE" ]] || fail ".env not found. Copy .env.example to .env first."

  local missing=0
  while IFS='=' read -r key _; do
    [[ -z "$key" || "$key" =~ ^# ]] && continue
    if ! grep -q "^${key}=" "$ENV_FILE"; then
      printf 'MISSING: %s\n' "$key" >&2
      missing=1
    fi
  done < "$ENV_EXAMPLE"

  if grep -n 'CHANGE_ME' "$ENV_FILE"; then
    printf 'WARN: .env still contains CHANGE_ME placeholders.\n' >&2
  fi

  [[ "$missing" -eq 0 ]] || fail ".env is missing required keys."
}

ensure_host_values() {
  : "${TZ:?TZ is required}"
  : "${PUID:?PUID is required}"
  : "${PGID:?PGID is required}"
  : "${DATA_PATH:?DATA_PATH is required}"
  : "${DOMAIN:?DOMAIN is required}"
}

create_directories() {
  log "[1/5] Creating data directories under ${DATA_PATH}"

  local dirs=(
    "${DATA_PATH}/phase1-core/data/postgres"
    "${DATA_PATH}/phase1-core/data/redis"
    "${DATA_PATH}/phase1-core/data/portainer"
    "${DATA_PATH}/phase1-core/data/npm/data"
    "${DATA_PATH}/phase1-core/data/npm/letsencrypt"
    "${DATA_PATH}/phase1-core/data/authentik/media"
    "${DATA_PATH}/phase1-core/data/authentik/certs"
    "${DATA_PATH}/phase1-core/data/authentik/custom-templates"
    "${DATA_PATH}/phase1-core/data/homepage"
    "${DATA_PATH}/phase1-core/data/beszel/hub"
    "${DATA_PATH}/phase1-core/data/uptime-kuma"
    "${DATA_PATH}/phase1-core/data/scrutiny/config"
    "${DATA_PATH}/phase1-core/data/scrutiny/influxdb"
    "${DATA_PATH}/phase1-core/data/vaultwarden"
    "${DATA_PATH}/phase1-core/data/ntfy/cache"
    "${DATA_PATH}/phase1-core/data/ntfy/etc"
    "${DATA_PATH}/phase1-core/data/node-exporter/textfile_collector"
    "${DATA_PATH}/phase1-core/data/backup/repo"
    "${DATA_PATH}/phase1-core/data/backup/state"
    "${DATA_PATH}/phase1-core/data/backup/verify"
    "${DATA_PATH}/phase2-media/data/jellyfin/config"
    "${DATA_PATH}/phase2-media/data/jellyfin/cache"
    "${DATA_PATH}/phase2-media/data/audiobookshelf/config"
    "${DATA_PATH}/phase2-media/data/audiobookshelf/metadata"
    "${DATA_PATH}/phase2-media/data/navidrome/data"
    "${DATA_PATH}/phase2-media/data/navidrome/cache"
    "${DATA_PATH}/phase2-media/data/paperless/data"
    "${DATA_PATH}/phase2-media/data/paperless/media"
    "${DATA_PATH}/phase2-media/data/paperless/export"
    "${DATA_PATH}/phase2-media/data/paperless/consume"
    "${DATA_PATH}/phase2-media/data/immich/upload"
    "${DATA_PATH}/phase2-media/data/immich/db"
    "${DATA_PATH}/phase2-media/data/immich/ml-cache"
    "${DATA_PATH}/phase2-media/data/prowlarr"
    "${DATA_PATH}/phase2-media/data/bazarr"
    "${DATA_PATH}/phase2-media/data/qbittorrent/config"
    "${DATA_PATH}/phase3-ai-gaming/data/ollama"
    "${DATA_PATH}/phase3-ai-gaming/data/openwebui"
    "${DATA_PATH}/phase3-ai-gaming/data/minecraft"
    "${DATA_PATH}/phase3-ai-gaming/data/n8n"
    "${DATA_PATH}/phase3-ai-gaming/data/homeassistant"
    "${DATA_PATH}/phase3-ai-gaming/data/spoolman"
    "${DATA_PATH}/phase3-ai-gaming/data/actual"
    "${DATA_PATH}/phase3-ai-gaming/data/stirling-pdf"
    "${DATA_PATH}/phase4-ondemand/data/kasm/profiles"
    "${DATA_PATH}/phase4-ondemand/data/guacamole"
    "${DATA_PATH}/phase4-ondemand/data/nextcloud/html"
    "${DATA_PATH}/phase4-ondemand/data/nextcloud/data"
    "${DATA_PATH}/phase4-ondemand/data/gitea"
    "${DATA_PATH}/phase4-ondemand/data/supabase"
    "${DATA_PATH}/phase4-ondemand/data/kiwix/library"
    "${DATA_PATH}/phase4-ondemand/data/docmost"
    "${DATA_PATH}/phase4-ondemand/data/calcom"
    "${DATA_PATH}/phase4-ondemand/data/nocodb"
    "${DATA_PATH}/shared/media/movies"
    "${DATA_PATH}/shared/media/tv"
    "${DATA_PATH}/shared/media/music"
    "${DATA_PATH}/shared/media/audiobooks"
    "${DATA_PATH}/shared/media/podcasts"
    "${DATA_PATH}/shared/media/books"
    "${DATA_PATH}/shared/downloads/complete"
    "${DATA_PATH}/shared/downloads/incomplete"
  )

  mkdir -p "${dirs[@]}"

  if [[ -f "${REPO_ROOT}/phase1-core/homepage/docker.yaml" && ! -f "${DATA_PATH}/phase1-core/data/homepage/docker.yaml" ]]; then
    cp "${REPO_ROOT}/phase1-core/homepage/docker.yaml" "${DATA_PATH}/phase1-core/data/homepage/docker.yaml"
  fi
}

fix_permissions() {
  log "[2/5] Applying ownership for non-database application data"

  local paths=(
    "${DATA_PATH}/phase1-core/data/portainer"
    "${DATA_PATH}/phase1-core/data/npm"
    "${DATA_PATH}/phase1-core/data/authentik"
    "${DATA_PATH}/phase1-core/data/homepage"
    "${DATA_PATH}/phase1-core/data/beszel"
    "${DATA_PATH}/phase1-core/data/uptime-kuma"
    "${DATA_PATH}/phase1-core/data/scrutiny"
    "${DATA_PATH}/phase1-core/data/vaultwarden"
    "${DATA_PATH}/phase1-core/data/ntfy"
    "${DATA_PATH}/phase1-core/data/node-exporter"
    "${DATA_PATH}/phase1-core/data/backup"
    "${DATA_PATH}/phase2-media"
    "${DATA_PATH}/phase3-ai-gaming"
    "${DATA_PATH}/phase4-ondemand"
    "${DATA_PATH}/shared"
  )

  if chown -R "${PUID}:${PGID}" "${paths[@]}" 2>/dev/null; then
    log "Ownership applied."
  else
    log "WARN: Some paths could not be chowned. Re-run with sudo on the Linux host if containers hit permission errors."
  fi
}

ensure_networks() {
  log "[3/5] Ensuring Docker networks exist"
  need_cmd docker

  docker network inspect homelab_proxy >/dev/null 2>&1 || docker network create homelab_proxy >/dev/null
  docker network inspect homelab_internal >/dev/null 2>&1 || docker network create homelab_internal >/dev/null
}

validate_compose() {
  log "[4/5] Validating compose files"
  need_cmd docker

  local phases=(
    "phase1-core/docker-compose.yml"
    "phase2-media/docker-compose.yml"
    "phase3-ai-gaming/docker-compose.yml"
    "phase4-ondemand/docker-compose.yml"
  )

  for file in "${phases[@]}"; do
    docker compose --env-file "$ENV_FILE" -f "${REPO_ROOT}/${file}" config >/dev/null
    log "OK: ${file}"
  done
}

validate_catalog() {
  log "Validating services.yaml catalog"
  need_cmd python3
  python3 - <<'PY'
import json
from pathlib import Path

catalog = json.loads(Path("services.yaml").read_text(encoding="utf-8"))
services = catalog["services"]
errors = []

for name, service in services.items():
    if service["phase"] not in catalog["phases"]:
        errors.append(f"{name}: unknown phase {service['phase']}")
    if service.get("schedule") not in catalog["schedules"]:
        errors.append(f"{name}: unknown schedule {service.get('schedule')}")
    for dependency in service.get("dependencies", []):
        if dependency not in services:
            errors.append(f"{name}: unknown dependency {dependency}")

if errors:
    raise SystemExit("\n".join(errors))

print(f"OK: services.yaml catalog contains {len(services)} services")
PY
}

start_phase1() {
  log "[5/5] Starting Phase 1"
  docker compose --env-file "$ENV_FILE" -f "${REPO_ROOT}/phase1-core/docker-compose.yml" up -d
}

main() {
  cd "$REPO_ROOT"

  [[ -f "$ENV_EXAMPLE" ]] || fail ".env.example not found at ${ENV_EXAMPLE}"
  load_env
  validate_env_file
  ensure_host_values

  if [[ "$VALIDATE_ONLY" == true ]]; then
    validate_catalog
    validate_compose
    log "Validation complete."
    exit 0
  fi

  create_directories
  fix_permissions
  ensure_networks
  validate_catalog
  validate_compose

  if [[ "$WITH_PHASE1" == true ]]; then
    start_phase1
  else
    log "[5/5] Skipping service start. Use --with-phase1 to start core services."
  fi

  log "Setup complete."
  log "Next: replace any CHANGE_ME values in .env, then run:"
  log "  docker compose --env-file .env -f phase1-core/docker-compose.yml up -d"
}

main "$@"
