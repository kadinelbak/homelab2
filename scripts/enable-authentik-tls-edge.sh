#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ ! -f .env ]]; then
  echo "Run this from a homelab checkout with .env present." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
. ./.env
set +a

DOMAIN="${DOMAIN:?DOMAIN must be set in .env}"
TAILSCALE_HOST_IP="${TAILSCALE_HOST_IP:?TAILSCALE_HOST_IP must be set in .env}"
DATA_PATH="${DATA_PATH:?DATA_PATH must be set in .env}"
CERT_DIR="$DATA_PATH/phase1-core/data/tailscale-certs"
AUTH_PORTS=(
  3000 3100 30030 5055 5678 6767 7878 7912 8086 8087 8089 8090
  8092 8097 8686 8787 8989 9090 9093 9696 9999 18080 18104
)

echo "Issuing Tailscale certificate for $DOMAIN"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT
sudo tailscale cert \
  --cert-file "$tmp_dir/tailscale.crt" \
  --key-file "$tmp_dir/tailscale.key" \
  "$DOMAIN"

echo "Installing certificate in $CERT_DIR"
sudo mkdir -p "$CERT_DIR"
sudo install -m 0644 "$tmp_dir/tailscale.crt" "$CERT_DIR/tailscale.crt"
sudo install -m 0600 "$tmp_dir/tailscale.key" "$CERT_DIR/tailscale.key"

echo "Validating Compose config"
docker compose --env-file .env -f phase1-core/docker-compose.yml config --quiet

echo "Switching Authentik proxy provider external URLs to https"
docker exec -i authentik_server python3 /manage.py shell <<PY
from authentik.providers.proxy.models import ProxyProvider, _get_callback_url

domain = "${DOMAIN}"
for provider in ProxyProvider.objects.filter(external_host__startswith=f"http://{domain}:"):
    provider.external_host = provider.external_host.replace("http://", "https://", 1)
    provider.redirect_uris = _get_callback_url(provider.external_host)
    provider.save(update_fields=["external_host", "_redirect_uris"])
    print(provider.name, provider.external_host)
PY

echo "Recreating Authentik and TLS edge"
docker compose --env-file .env -f phase1-core/docker-compose.yml up -d --force-recreate \
  authentik-server authentik-tls-edge

echo "Updating Uptime Kuma monitors to HTTPS edge URLs"
docker exec -i uptime_kuma python3 <<PY
import json
import shutil
import sqlite3
import time

db_path = "/app/data/kuma.db"
backup_path = f"{db_path}.bak-enable-tls-edge-{time.strftime('%Y%m%d-%H%M%S')}"
shutil.copy2(db_path, backup_path)

ports_by_name = {
    "Homepage": 3000,
    "Beszel": 8090,
    "Scrutiny": 8089,
    "Grafana": 30030,
    "Prometheus": 9090,
    "Alertmanager": 9093,
    "Loki": 3100,
    "Prowlarr": 9696,
    "Bazarr": 6767,
    "Open WebUI": 18080,
    "n8n": 5678,
    "Spoolman": 7912,
    "Stirling PDF": 8086,
    "IT-Tools": 8087,
    "Web Games": 8092,
    "Wake-on-LAN API": 9999,
}

con = sqlite3.connect(db_path)
cur = con.cursor()
for name, port in ports_by_name.items():
    cur.execute(
        "update monitor set url=?, ignore_tls=1, accepted_statuscodes_json=? where name=?",
        (f"https://${TAILSCALE_HOST_IP}:{port}", json.dumps(["200-399"]), name),
    )
con.commit()
print(f"backup {backup_path}")
print(f"changed {con.total_changes}")
PY

docker restart uptime_kuma >/dev/null

echo "Verifying HTTPS edge ports"
for port in "${AUTH_PORTS[@]}"; do
  code="$(curl -sS -m 8 -o /dev/null -w '%{http_code}' \
    --resolve "$DOMAIN:$port:$TAILSCALE_HOST_IP" \
    "https://$DOMAIN:$port/" || true)"
  echo "$port $code"
done

echo "Done. Use https://$DOMAIN:<port> from Windows and Pixel."
