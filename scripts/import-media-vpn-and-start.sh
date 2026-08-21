#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${ROOT_DIR:-/home/kadin/homelab2}"
ENV_FILE="${ENV_FILE:-${ROOT_DIR}/.env}"
SECRETS_DIR="${GLUETUN_SECRETS_DIR:-${ROOT_DIR}/phase2-media/secrets}"
PROVIDER="${VPN_SERVICE_PROVIDER:-mullvad}"
SERVER_COUNTRIES="${SERVER_COUNTRIES:-Netherlands}"
VPN_PORT_FORWARDING="${VPN_PORT_FORWARDING:-off}"

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 /path/to/wireguard.conf" >&2
  exit 2
fi

CONFIG_PATH="$1"
if [[ ! -f "$CONFIG_PATH" ]]; then
  echo "WireGuard config not found: $CONFIG_PATH" >&2
  exit 2
fi

python3 "${ROOT_DIR}/scripts/apply-wireguard-config-env.py" \
  --config "$CONFIG_PATH" \
  --env-file "$ENV_FILE" \
  --provider "$PROVIDER" \
  --server-countries "$SERVER_COUNTRIES" \
  --port-forwarding "$VPN_PORT_FORWARDING" \
  --secrets-dir "$SECRETS_DIR"

chmod 700 "$SECRETS_DIR"
chmod 600 "$SECRETS_DIR"/wireguard_private_key "$SECRETS_DIR"/wireguard_addresses

cd "${ROOT_DIR}/phase2-media"
docker compose --env-file ../.env --profile torrent --profile arr up -d gluetun qbittorrent prowlarr bazarr sonarr radarr lidarr readarr
docker compose --env-file ../.env --profile torrent --profile arr ps gluetun qbittorrent prowlarr bazarr sonarr radarr lidarr readarr
