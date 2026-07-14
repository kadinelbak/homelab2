#!/bin/bash
# post-deploy.sh
# Run after all services are started to seed initial data and configure integrations

set -euo pipefail

echo "=== Running Post-Deploy Setup ==="

# Source .env to get variables
if [[ -f "../.env" ]]; then
  export $(grep -v '^#' ../.env | xargs)
else
  echo "Error: .env not found."
  exit 1
fi

# Wait for additional services to be healthy if needed
echo "Waiting for additional services to stabilize..."
sleep 30

# Seed Vaultwarden with initial admin user (if not already done via environment)
# Note: Vaultwarden admin user is typically set via ADMIN_TOKEN env var on first start
# We'll just verify it's accessible
echo "Checking Vaultwarden accessibility..."
if curl -s -o /dev/null -w "%{http_code}" "http://vaultwarden:80" | grep -q "200\|302"; then
  echo "Vaultwarden is accessible"
else
  echo "Warning: Vaultwarden may not be ready yet"
fi

# Seed Uptime Kuma with basic monitors (if script exists)
if [[ -f "../scripts/seed_uptime_kuma.py" ]]; then
  echo "Seeding Uptime Kuma with initial monitors..."
  python3 ../scripts/seed_uptime_kuma.py || echo "Seed script completed or failed (may be expected if already seeded)"
else
  echo "Uptime Kuma seed script not found, skipping."
fi

# Create initial n8n workflow credential for Ollama (if n8n is ready)
echo "Setting up initial n8n Ollama credential..."
# We'll do this via n8n API if available, otherwise document manual step
MAX_RETRIES=5
RETRY_DELAY=10
for i in $(seq 1 $MAX_RETRIES); do
  if curl -s -o /dev/null -w "%{http_code}" "http://n8n:5678/rest/health" | grep -q "200"; then
    echo "n8n API is accessible"
    # In a real implementation, we would:
    # 1. Create Ollama credential via POST to /api/v1/credentials
    # 2. Create a sample workflow
    # For now, we'll just note that manual setup may be needed
    echo "Note: n8n Ollama credential may need to be created manually:"
    echo "  - Go to n8n -> Credentials -> New Credential -> Ollama API"
    echo "  - Host: http://ollama:11434"
    break
  else
    echo "Waiting for n8n to be ready... (attempt $i/$MAX_RETRIES)"
    sleep $RETRY_DELAY
  fi
done

# Update README with current service status and URLs
echo "Updating README with service information..."
# We'll create a simple status section
cat >> ../README.md <<EOF

## 📊 Service Status (Auto-generated post-deploy)

As of $(date), the following services are deployed:

### Phase 1 - Core Infrastructure
- **PostgreSQL**: `homelab_postgres:5432` (internal)
- **Redis**: `homelab_redis:6379` (internal)
- **Portainer**: http://\${DOMAIN}:9000
- **Nginx Proxy Manager**: http://\${DOMAIN}:81
- **Authentik**: http://\${DOMAIN}:9001
- **Homepage**: http://\${DOMAIN}:3000
- **Beszel**: http://\${DOMAIN}:8090
- **Uptime Kuma**: http://\${DOMAIN}:3001
- **Watchtower**: Automatic updates
- **Scrutiny**: http://\${DOMAIN}:8089
- **Vaultwarden**: https://\${DOMAIN}:4443
- **ntfy**: http://\${DOMAIN}:8085
- **Prometheus**: http://\${DOMAIN}:9090
- **Grafana**: http://\${DOMAIN}:30030 (admin / [see .env for password])
- **Loki**: http://\${DOMAIN}:3100
- **Alertmanager**: http://\${DOMAIN}:9093

### Phase 2 - Media & Documents
- **Jellyfin**: http://\${DOMAIN}:8096
- **Audiobookshelf**: http://\${DOMAIN}:13378
- **Navidrome**: http://\${DOMAIN}:4533
- **Paperless**: http://\${DOMAIN}:8000
- **Immich**: http://\${DOMAIN}:2283
- **Prowlarr**: http://\${DOMAIN}:9696
- **Bazarr**: http://\${DOMAIN}:6767
- **qBittorrent**: http://\${DOCKER_HOST_IP}:8080 (via Gluetun VPN)

### Phase 3 - AI, Gaming & Utility
- **Ollama**: http://ollama:11434 (internal)
- **Open WebUI**: http://\${DOMAIN}:8080
- **Minecraft**: \${DOMAIN}:25565
- **n8n**: http://\${DOMAIN}:5678
- **Home Assistant**: http://\${DOMAIN}:8123
- **Spoolman**: http://\${DOMAIN}:7912
- **Actual Budget**: http://\${DOMAIN}:5006
- **Stirling PDF**: http://\${DOMAIN}:8086
- **IT-Tools**: http://\${DOMAIN}:8087
- **Hearts Multiplayer**: http://\${DOMAIN}:8094

### Phase 4 - On-Demand (start with ./scripts/toggle-ondemand.sh up)
- **Kasm**: https://\${DOMAIN}
- **Guacamole**: http://\${DOMAIN}:8080
- **Nextcloud**: http://\${DOMAIN}:443
- **Gitea**: http://\${DOMAIN}:3000
- **Supabase**: http://\${DOMAIN}:8000
- **Kiwix**: http://\${DOMAIN}:8080
- **Docmost**: http://\${DOMAIN}:8080
- **Cal.com**: http://\${DOMAIN}:8080
- **NocoDB**: http://\${DOMAIN}:8080

> **Note**: Replace \${DOMAIN} with your actual domain or Tailscale hostname.
> **Credentials**: Check your .env file for auto-generated passwords.
> **Grafana**: Default user is 'admin', password is in GF_SECURITY_ADMIN_PASSWORD in .env
> **n8n**: Default user is 'admin', password is in N8N_BASIC_AUTH_PASSWORD in .env
> **Vaultwarden**: Invitation system enabled, admin token in VAULTWARDEN_ADMIN_TOKEN

EOF

echo "Post-deploy setup complete."
echo "Remember to:"
echo "1. Check your .env file for generated secrets"
echo "2. Complete any manual service setup wizards (Authentik, etc.)"
echo "3. Configure service-specific settings as needed"
echo "4. Use the toggle-ondemand.sh script to control Phase 4 services"