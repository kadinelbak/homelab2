#!/bin/bash
# bootstrap.sh
# One-time bootstrap: dependency checks, directories, networks, ownership
# Then start all phases in order.

set -euo pipefail

echo "=== Homelab Bootstrap ==="

# Step 0: Check if .env exists, if not generate it
if [[ ! -f "../.env" ]]; then
  echo "No .env found, generating secrets..."
  ./generate-secrets.sh
else
  echo ".env found, using existing."
fi

# Step 1: Source .env to get variables
if [[ -f "../.env" ]]; then
  # Export all variables in .env
  export $(grep -v '^#' ../.env | xargs)
else
  echo "Error: .env not found and generation failed."
  exit 1
fi

# Step 2: Create necessary directories under $DATA_PATH
echo "Creating directory structure under $DATA_PATH..."
mkdir -p \
  "${DATA_PATH}/phase1-core/data/postgres" \
  "${DATA_PATH}/phase1-core/data/redis" \
  "${DATA_PATH}/phase1-core/data/portainer" \
  "${DATA_PATH}/phase1-core/data/npm/{data,letsencrypt}" \
  "${DATA_PATH}/phase1-core/data/authentik/{media,templates,certs}" \
  "${DATA_PATH}/phase1-core/data/homepage" \
  "${DATA_PATH}/phase1-core/data/beszel/{hub,agent}" \
  "${DATA_PATH}/phase1-core/data/uptime-kuma" \
  "${DATA_PATH}/phase1-core/data/scrutiny" \
  "${DATA_PATH}/phase1-core/data/vaultwarden" \
  "${DATA_PATH}/phase1-core/data/ntfy/{cache,etc}" \
  "${DATA_PATH}/phase2-media/data/jellyfin/{config,cache}" \
  "${DATA_PATH}/phase2-media/data/audiobookshelf/{config,metadata}" \
  "${DATA_PATH}/phase2-media/data/navidrome/{data,cache}" \
  "${DATA_PATH}/phase2-media/data/paperless/{data,media,export,consume}" \
  "${DATA_PATH}/phase2-media/data/immich/{upload,db,ml-cache}" \
  "${DATA_PATH}/phase2-media/data/prowlarr" \
  "${DATA_PATH}/phase2-media/data/bazarr" \
  "${DATA_PATH}/phase2-media/data/qbittorrent/config" \
  "${DATA_PATH}/phase3-ai-gaming/data/ollama" \
  "${DATA_PATH}/phase3-ai-gaming/data/openwebui" \
  "${DATA_PATH}/phase3-ai-gaming/data/minecraft" \
  "${DATA_PATH}/phase3-ai-gaming/data/n8n" \
  "${DATA_PATH}/phase3-ai-gaming/data/homeassistant" \
  "${DATA_PATH}/phase3-ai-gaming/data/spoolman" \
  "${DATA_PATH}/phase3-ai-gaming/data/actual" \
  "${DATA_PATH}/phase3-ai-gaming/data/stirling_pdf" \
  "${DATA_PATH}/phase3-ai-gaming/data/it_tools" \
  "${DATA_PATH}/phase4-ondemand/data/kasm/{profiles}" \
  "${DATA_PATH}/phase4-ondemand/data/guacamole" \
  "${DATA_PATH}/phase4-ondemand/data/nextcloud/{html,data}" \
  "${DATA_PATH}/phase4-ondemand/data/gitea" \
  "${DATA_PATH}/phase4-ondemand/data/supabase" \
  "${DATA_PATH}/phase4-ondemand/data/kiwix/library" \
  "${DATA_PATH}/phase4-ondemand/data/docmost" \
  "${DATA_PATH}/phase4-ondemand/data/calcom" \
  "${DATA_PATH}/phase4-ondemand/data/nocodb" \
  "${DATA_PATH}/shared/{movies,tv,music,audiobooks,podcasts,books}" \
  "${DATA_PATH}/shared/downloads/{complete,incomplete}"

# Step 3: Set permissions (assuming PUID=1000, PGID=1000 from .env)
echo "Setting ownership to ${PUID}:${PGID}..."
chown -R ${PUID}:${PGID} $DATA_PATH

# Step 4: Create Docker networks if they don't exist
echo "Ensuring Docker networks exist..."
docker network inspect homelab_proxy >/dev/null 2>&1 || docker network create homelab_proxy
docker network inspect homelab_internal >/dev/null 2>&1 || docker network create homelab_internal

# Step 5: Start Phase 1 (Core) - now includes monitoring
echo "Starting Phase 1 (Core Infrastructure)..."
cd phase1-core
docker compose --env-file ../.env up -d
cd ..

# Wait for Phase 1 to be healthy (simple check: wait for postgres and redis)
echo "Waiting for Phase 1 services to be healthy..."
max_attempts=30
attempt=0
while [[ $attempt -lt $max_attempts ]]; do
  # Check if postgres and redis are healthy
  postgres_healthy=$(docker inspect --format='{{.State.Health.Status}}' homelab_postgres 2>/dev/null || echo "starting")
  redis_healthy=$(docker inspect --format='{{.State.Health.Status}}' homelab_redis 2>/dev/null || echo "starting")
  if [[ "$postgres_healthy" == "healthy" && "$redis_healthy" == "healthy" ]]; then
    echo "PostgreSQL and Redis are healthy."
    break
  fi
  echo "Waiting for databases... (attempt $((attempt+1))/$max_attempts)"
  sleep 10
  ((attempt++))
done

if [[ $attempt -eq $max_attempts ]]; then
  echo "Warning: Timed out waiting for databases to be healthy. Continuing anyway."
fi

# Step 6: Start Phase 2 (Media)
echo "Starting Phase 2 (Media and Documents)..."
cd phase2-media
docker compose --env-file ../.env up -d
cd ..

# Step 7: Start Phase 3 (AI, Gaming, Utility)
echo "Starting Phase 3 (AI, Gaming, Utility)..."
cd phase3-ai-gaming
docker compose --env-file ../.env up -d
cd ..

# Step 8: Offer to start Phase 4 (On-Demand)
echo "Phase 1, 2, and 3 are now starting."
echo "Phase 4 (On-Demand) is designed to be toggled on/off as needed."
echo "To start Phase 4, run: ./scripts/toggle-ondemand.sh up"
echo "To stop Phase 4, run: ./scripts/toggle-ondemand.sh down"

# Step 9: Post-deploy tasks (seeding, etc.) - we'll call a separate script
echo "Running post-deploy setup..."
if [[ -f "./scripts/post-deploy.sh" ]]; then
  ./scripts/post-deploy.sh
else
  echo "Post-deploy script not found, skipping."
fi

echo "=== Bootstrap Complete ==="
echo "Next steps:"
echo "1. Edit .env if needed (especially CHANGEME_* values)."
echo "2. Refer to ENV_REFERENCE.md for variable descriptions."
echo "3. Access services via the URLs in README.md."
echo "4. Check Homepage at http://<tailnet-host>:3000 for service links."
echo "5. Grafana is available at http://<tailnet-host>:30030 (admin/admin or generated password)."
echo "6. Prometheus is available at http://<tailnet-host>:9090."
echo "7. Run './scripts/toggle-ondemand.sh up' to start Phase 4 services when needed."