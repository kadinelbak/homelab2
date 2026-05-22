#!/usr/bin/env bash
# =============================================================================
# setup.sh – One-time Ground Zero setup script
#
# Run this ONCE on a fresh system before starting any compose stack.
# It will:
#   1. Verify dependencies (Docker, Docker Compose, NVIDIA toolkit)
#   2. Create all required host directories with correct ownership
#   3. Copy .env.example → .env (if .env doesn't exist)
#   4. Create Docker networks
#   5. Set correct permissions on sensitive paths
#
# Usage:  bash scripts/setup.sh
#         DATA_PATH=/custom/path bash scripts/setup.sh
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
ENV_FILE="${REPO_ROOT}/.env"

# ---------------------------------------------------------------------------
# Load DATA_PATH from .env if it exists, else use default
# ---------------------------------------------------------------------------
if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC2046
  export $(grep -E '^DATA_PATH=' "$ENV_FILE" | xargs) 2>/dev/null || true
  export $(grep -E '^PUID=' "$ENV_FILE" | xargs) 2>/dev/null || true
  export $(grep -E '^PGID=' "$ENV_FILE" | xargs) 2>/dev/null || true
fi

DATA_PATH="${DATA_PATH:-/mnt/nvme/homelab}"
PUID="${PUID:-1000}"
PGID="${PGID:-1000}"

echo "============================================================"
echo " Homelab Ground Zero Setup"
echo " DATA_PATH : ${DATA_PATH}"
echo " PUID/PGID : ${PUID}/${PGID}"
echo "============================================================"
echo ""

# ---------------------------------------------------------------------------
# STEP 1 – Dependency checks
# ---------------------------------------------------------------------------
echo "[1/5] Checking dependencies..."

check_cmd() {
  if ! command -v "$1" &>/dev/null; then
    echo "  MISSING: $1 – please install it before continuing."
    echo "           $2"
    exit 1
  else
    echo "  OK: $1 ($(command -v "$1"))"
  fi
}

check_cmd docker         "https://docs.docker.com/engine/install/"
if docker compose version &>/dev/null; then
  echo "  OK: docker compose plugin"
else
  echo "  MISSING: docker compose plugin"
  echo "           https://docs.docker.com/compose/install/"
  exit 1
fi

# Check NVIDIA toolkit (non-fatal – just warn)
if nvidia-smi &>/dev/null; then
  echo "  OK: nvidia-smi found – GPU available"
  if docker run --rm --gpus all nvidia/cuda:12.0-base-ubuntu22.04 nvidia-smi &>/dev/null 2>&1; then
    echo "  OK: NVIDIA Container Toolkit is working"
  else
    echo "  WARN: nvidia-smi works but NVIDIA Container Toolkit may not be installed."
    echo "        Install: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html"
    echo "        Ollama (Phase 3) will not use the GPU until this is resolved."
  fi
else
  echo "  INFO: nvidia-smi not found – GPU will not be used (Ollama runs on CPU)."
fi
echo ""

# ---------------------------------------------------------------------------
# STEP 2 – Create .env
# ---------------------------------------------------------------------------
echo "[2/5] Environment file..."
if [[ -f "$ENV_FILE" ]]; then
  echo "  OK: .env already exists – skipping copy."
else
  cp "${REPO_ROOT}/.env.example" "$ENV_FILE"
  echo "  CREATED: .env from .env.example"
  echo "  ACTION REQUIRED: Open .env and fill in every CHANGEME value before continuing!"
  echo ""
  read -rp "  Press ENTER once you have edited .env, or Ctrl+C to exit now... "
fi
echo ""

# ---------------------------------------------------------------------------
# STEP 3 – Create directory tree on NVMe
# ---------------------------------------------------------------------------
echo "[3/5] Creating directory structure at ${DATA_PATH}..."

dirs=(
  # Phase 1 – Core
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
  "${DATA_PATH}/phase1-core/data/ntfy/cache"
  "${DATA_PATH}/phase1-core/data/ntfy/etc"

  # Phase 2 – Media
  "${DATA_PATH}/phase2-media/data/jellyfin/config"
  "${DATA_PATH}/phase2-media/data/jellyfin/cache"
  "${DATA_PATH}/phase2-media/data/audiobookshelf/config"
  "${DATA_PATH}/phase2-media/data/audiobookshelf/metadata"
  "${DATA_PATH}/phase2-media/data/paperless/data"
  "${DATA_PATH}/phase2-media/data/paperless/media"
  "${DATA_PATH}/phase2-media/data/paperless/export"
  "${DATA_PATH}/phase2-media/data/paperless/consume"
  "${DATA_PATH}/phase2-media/data/immich/upload"
  "${DATA_PATH}/phase2-media/data/immich/db"
  "${DATA_PATH}/phase2-media/data/immich/ml-cache"
  "${DATA_PATH}/phase2-media/data/qbittorrent/config"

  # Phase 3 – AI / Gaming
  "${DATA_PATH}/phase3-ai-gaming/data/ollama"
  "${DATA_PATH}/phase3-ai-gaming/data/openwebui"
  "${DATA_PATH}/phase3-ai-gaming/data/minecraft"
  "${DATA_PATH}/phase3-ai-gaming/data/n8n"
  "${DATA_PATH}/phase3-ai-gaming/data/homeassistant"
  "${DATA_PATH}/phase3-ai-gaming/data/spoolman"
  "${DATA_PATH}/phase3-ai-gaming/data/actual"

  # Phase 4 – On-Demand
  "${DATA_PATH}/phase4-ondemand/data/kasm"
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

  # Shared media library
  "${DATA_PATH}/shared/media/movies"
  "${DATA_PATH}/shared/media/tv"
  "${DATA_PATH}/shared/media/music"
  "${DATA_PATH}/shared/media/audiobooks"
  "${DATA_PATH}/shared/media/podcasts"
  "${DATA_PATH}/shared/media/books"
  "${DATA_PATH}/shared/downloads/complete"
  "${DATA_PATH}/shared/downloads/incomplete"
)

for dir in "${dirs[@]}"; do
  mkdir -p "$dir"
done

echo "  Created $(echo "${dirs[@]}" | wc -w) directories."
echo ""

# ---------------------------------------------------------------------------
# STEP 4 – Set ownership
# ---------------------------------------------------------------------------
echo "[4/5] Setting ownership (${PUID}:${PGID}) on data directories..."

# Postgres and Redis data must be owned by the container's internal user,
# not the host user. Leave those to Docker.
chown -R "${PUID}:${PGID}" \
  "${DATA_PATH}/phase1-core/data/portainer" \
  "${DATA_PATH}/phase1-core/data/npm" \
  "${DATA_PATH}/phase1-core/data/authentik" \
  "${DATA_PATH}/phase1-core/data/homepage" \
  "${DATA_PATH}/phase1-core/data/beszel" \
  "${DATA_PATH}/phase1-core/data/uptime-kuma" \
  "${DATA_PATH}/phase1-core/data/ntfy" \
  "${DATA_PATH}/phase2-media/data/jellyfin" \
  "${DATA_PATH}/phase2-media/data/audiobookshelf" \
  "${DATA_PATH}/phase2-media/data/paperless" \
  "${DATA_PATH}/phase2-media/data/immich/upload" \
  "${DATA_PATH}/phase2-media/data/immich/ml-cache" \
  "${DATA_PATH}/phase2-media/data/qbittorrent" \
  "${DATA_PATH}/phase3-ai-gaming/data/ollama" \
  "${DATA_PATH}/phase3-ai-gaming/data/openwebui" \
  "${DATA_PATH}/phase3-ai-gaming/data/minecraft" \
  "${DATA_PATH}/phase3-ai-gaming/data/n8n" \
  "${DATA_PATH}/phase3-ai-gaming/data/homeassistant" \
  "${DATA_PATH}/phase3-ai-gaming/data/spoolman" \
  "${DATA_PATH}/phase3-ai-gaming/data/actual" \
  "${DATA_PATH}/phase4-ondemand" \
  "${DATA_PATH}/shared" \
  2>/dev/null && echo "  Done." || echo "  WARN: Some paths need sudo to chown. Run with sudo if needed."

echo ""

# ---------------------------------------------------------------------------
# STEP 5 – Create Docker networks
# ---------------------------------------------------------------------------
echo "[5/5] Creating Docker networks..."

create_network() {
  if docker network inspect "$1" &>/dev/null; then
    echo "  EXISTS: $1"
  else
    docker network create "$1" --driver bridge
    echo "  CREATED: $1"
  fi
}

create_network homelab_proxy
create_network homelab_internal

echo ""
echo "============================================================"
echo " Setup complete!"
echo "============================================================"
echo ""
echo " Next steps:"
echo "  1. Ensure .env has all CHANGEME values filled in."
echo "  2. cd phase1-core && docker compose --env-file ../.env up -d"
echo "  3. Access NPM admin at http://localhost:81 (default: admin@example.com / changeme)"
echo "  4. Configure your domain's DNS and set up proxy hosts in NPM."
echo "  5. See README.md for the full phased rollout guide."
echo ""
echo " Toggle on-demand services:"
echo "  ./scripts/toggle-ondemand.sh up      # Wake Phase 4"
echo "  ./scripts/toggle-ondemand.sh down    # Sleep Phase 4"
echo ""
