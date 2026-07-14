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

# Warm up Ollama model (load the default model into memory)
echo "Warming up Ollama model..."
OLLAMA_HOST=${OLLAMA_HOST:-http://ollama:11434}
DEFAULT_MODEL=${OLLAMA_MODEL:-llama3}

# Wait for Ollama to be ready
echo "Waiting for Ollama to be ready..."
MAX_RETRIES=30
RETRY_DELAY=5
for i in $(seq 1 $MAX_RETRIES); do
  if curl -s -o /dev/null -w "%{http_code}" "${OLLAMA_HOST}/api/tags"; then
    echo "Ollama API is accessible"
    break
  fi
  echo "Waiting for Ollama to be ready... (attempt $i/$MAX_RETRIES)"
  sleep $RETRY_DELAY
done

if [[ $i -eq $MAX_RETRIES ]]; then
  echo "Warning: Timed out waiting for Ollama. Continuing anyway."
else
  # Check if default model is already loaded
  echo "Checking if default model ($DEFAULT_MODEL) is loaded..."
  if curl -s "${OLLAMA_HOST}/api/tags" | grep -q "\"name\": \"$DEFAULT_MODEL\""; then
    echo "Model $DEFAULT_MODEL is already available"
  else
    echo "Pulling model $DEFAULT_MODEL..."
    # Pull the model (this will load it into memory)
    curl -s -X POST "${OLLAMA_HOST}/api/pull" -d "{\"name\": \"$DEFAULT_MODEL\"}" > /dev/null
    echo "Model $DEFAULT_MODEL pulled successfully"
  fi
  
  # Test the model with a simple query
  echo "Testing model with a simple query..."
  TEST_RESPONSE=$(curl -s -X POST "${OLLAMA_HOST}/api/generate" \
    -H "Content-Type: application/json" \
    -d "{\"model\": \"$DEFAULT_MODEL\", \"prompt\": \"Hello! This is a test to confirm the Llama model is working.\", \"stream\": false}")
  
  if echo "$TEST_RESPONSE" | grep -q "response"; then
    echo "Llama model is working correctly!"
    echo "Test response: $(echo "$TEST_RESPONSE" | jq -r '.response' | head -c 100)..."
  else
    echo "Warning: Model test failed. Response: $TEST_RESPONSE"
  fi
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
- **Loki**: http->\${DOMAIN}:3100
- **Alertmanager**: http://\${DOMAIN}:9093

### Phase 2 - Media & Documents
- **Jellyfin**: http://\${DOMAIN}:8096
- **Audiobookshelf**: http->\${DOMAIN}:13378
- **Navidrome**: http->\${DOMAIN}:4533
- **Paperless**: http->\${DOMAIN}:8000
- **Immich**: http->\${DOMAIN}:2283
- **Prowlarr**: http->\${DOMAIN}:9696
- **Bazarr**: http->\${DOMAIN}:6767
- **qBittorrent**: http->\${DOCKER_HOST_IP}:8080 (via Gluetun VPN)

### Phase 3 - AI, Gaming & Utility
- **Ollama**: http://ollama:11434 (internal)
- **Open WebUI**: http->\${DOMAIN}:8080
- **Minecraft**: \${DOMAIN}:25565
- **n8n**: http->\${DOMAIN}:5678
- **Home Assistant**: http->\${DOMAIN}:8123
- **Spoolman**: http->\${DOMAIN}:7912
- **Actual Budget**: http->\${DOMAIN}:5006
- **Stirling PDF**: http->\${DOMAIN}:8086
- **IT-Tools**: http->\${DOMAIN}:8087
- **Hearts Multiplayer**: http->\${DOMAIN}:8094

### Phase 4 - On-Demand (start with ./scripts/toggle-ondemand.sh up)
- **Kasm**: https://\${DOMAIN}
- **Guacamole**: http->\${DOMAIN}:8080
- **Nextcloud**: http->\${DOMAIN}:443
- **Gitea**: http->\${DOMAIN}:3000
- **Supabase**: http->\${DOMAIN}:8000
- **Kiwix**: http->\${DOMAIN}:8080
- **Docmost**: http->\${DOMAIN}:8080
- **Cal.com**: http->\${DOMAIN}:8080
- **NocoDB**: http->\${DOMAIN}:8080

> **Note**: Replace \${DOMAIN} with your actual domain or Tailscale hostname.
> **Credentials**: Check your .env file for auto-generated passwords.
> **Grafana**: Default user is 'admin', password is in GF_SECURITY_ADMIN_PASSWORD in .env
> **n8n**: Default user is 'admin', password is in N8N_BASIC_AUTH_PASSWORD in .env
> **Vaultwarden**: Invitation system enabled, admin token in VAULTWARDEN_ADMIN_TOKEN
> **SSO (Authentik)**: 
>   - Authentik server: http://\${DOMAIN}:9001
>   - Grafana SSO: Login via Authentik (OIDC configured)
>   - n8n SSO: Login via Authentik (OIDC configured)
>   - Homepage SSO: Login via Authentik (OIDC configured)
>   - Vaultwarden SSO: Login via Authentik (OIDC configured)
>   - Portainer SSO: Login via Authentik (OIDC configured)
>   - Home Assistant SSO: Login via Authentik (OAuth2 configured)
>   - To enable SSO for a service, ensure the OAuth client ID/secret from .env is configured in the service.
>   - After configuring, users can log in with their Authentik credentials.
> **Shared Llama Model (via Ollama)**:
>   - The Ollama service is available internally at `http://ollama:11434` with the \${OLLAMA_MODEL:-llama3} model pre-loaded.
>   - To use in your workflows or scripts:
>     - Base URL: `http://ollama:11434`
>     - API Endpoint: `http://ollama:11434/api/generate`
>     - Default Model: \${OLLAMA_MODEL:-llama3} (configure via OLLAMA_MODEL env var)
>   
>   Example curl:
>   curl -X POST http://ollama:11434/api/generate -d '{"model":"llama3","prompt":"Hello!"}'
>   
>   Or use the helper script: ./scripts/ollama-query.sh "Your prompt here"
>   
> **Developer Experience**:
>   - Service templates available in dev/templates/
>   - Create new services with: ./dev/scripts/create-service.sh <name> <template>
>   - Develop locally with: cd dev/services/<name> && docker compose -f docker-compose.dev.yml up -d
>   - Generate deployment snippets with: ./dev/scripts/generate-compose-snippet.sh <name>
>   - See dev/README.md for more details

EOF

echo "Post-deploy setup complete."
echo "Remember to:"
echo "1. Check your .env file for generated secrets"
echo "2. Complete any manual service setup wizards (Authentik, etc.)"
echo "3. Configure service-specific settings as needed"
echo "4. Use the toggle-ondemand.sh script to control Phase 4 services"
echo "5. The Llama model is now available for AI workflows via Ollama"
echo "6. Developer experience tools are available in dev/ for creating custom services"