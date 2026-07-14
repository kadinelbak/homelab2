#!/bin/bash
# generate-compose-snippet.sh
# Generate a docker-compose snippet for deploying a service to homelab

set -euo pipefail

# Check if service name is provided
if [[ $# -eq 0 ]]; then
  echo "Usage: $0 <service-name> [phase]"
  echo "  service-name: Name of the service in dev/services/ (e.g., my-webapp)"
  echo "  phase: Optional target phase (phase1-core, phase2-media, phase3-ai-gaming, phase4-ondemand)"
  echo "           If not provided, will attempt to infer from service type"
  echo ""
  echo "Example:"
  echo "  $0 my-webapp"
  echo "  $0 my-api-service phase3-ai-gaming"
  exit 1
fi

SERVICE_NAME="$1"
TARGET_PHASE="${2:-}"
SERVICE_DIR="dev/services/$SERVICE_NAME"

# Check if service exists
if [[ ! -d "$SERVICE_DIR" ]]; then
  echo "Error: Service not found: $SERVICE_DIR"
  echo "Create it first using: ./create-service.sh <service-name> <template-type>"
  exit 1
fi

# Try to infer the template type from the service directory or docker-compose.dev.yml
TEMPLATE_TYPE="unknown"
if [[ -f "$SERVICE_DIR/docker-compose.dev.yml" ]]; then
  # We could parse the file to guess the type, but for now we'll use a simple approach
  # Check if there are any hints in the directory name or files
  if [[ "$SERVICE_DIR" == *"web-app"* ]]; then
    TEMPLATE_TYPE="web-app"
  elif [[ "$SERVICE_DIR" == *"api-service"* ]]; then
    TEMPLATE_TYPE="api-service"
  elif [[ "$SERVICE_DIR" == *"worker"* ]]; then
    TEMPLATE_TYPE="worker"
  elif [[ "$SERVICE_DIR" == *"cron-job"* ]]; then
    TEMPLATE_TYPE="cron-job"
  elif [[ "$SERVICE_DIR" == *"dashboard"* ]]; then
    TEMPLATE_TYPE="dashboard"
  fi
fi

# If still unknown, check for specific files
if [[ "$TEMPLATE_TYPE" == "unknown" ]]; then
  if [[ -f "$SERVICE_DIR/Dockerfile" && -f "$SERVICE_DIR/package.json" ]]; then
    TEMPLATE_TYPE="web-app"
  elif [[ -f "$SERVICE_DIR/Dockerfile" && -f "$SERVICE_DIR/requirements.txt" ]]; then
    TEMPLATE_TYPE="api-service"
  elif [[ -f "$SERVICE_DIR/Dockerfile" && -f "$SERVICE_DIR/worker.py" ]]; then
    TEMPLATE_TYPE="worker"
  elif [[ -f "$SERVICE_DIR/Dockerfile" && -f "$SERVICE_DIR/job.sh" && -f "$SERVICE_DIR/crontab" ]]; then
    TEMPLATE_TYPE="cron-job"
  elif [[ -f "$SERVICE_DIR/Dockerfile" && -d "$SERVICE_DIR" ]]; then
    # Check if it's a simple static dashboard
    TEMPLATE_TYPE="dashboard"
  fi
fi

echo "Generating docker-compose snippet for service: $SERVICE_NAME"
echo "Inferred template type: $TEMPLATE_TYPE"

# Determine target phase if not provided
if [[ -z "$TARGET_PHASE" ]]; then
  case "$TEMPLATE_TYPE" in
    "web-app"|"api-service")
      TARGET_PHASE="phase3-ai-gaming"
      ;;
    "worker"|"cron-job")
      TARGET_PHASE="phase3-ai-gaming"
      ;;
    "dashboard")
      TARGET_PHASE="phase1-core"  # or phase3-ai-gaming depending on dashboard type
      ;;
    *)
      TARGET_PHASE="phase3-ai-gaming"  # Default
      ;;
  esac
fi

echo "Target phase: $TARGET_PHASE"

# Generate the docker-compose snippet
cat > "$SERVICE_DIR/deployment-snippet.yml" <<EOF
# Add this to $TARGET_PHASE/docker-compose.yml under the 'services:' section
# Determine appropriate networks and volumes based on your service needs

  $SERVICE_NAME:
    # Option 1: Build from local context (recommended for active development)
    build:
      context: ../../dev/services/$SERVICE_NAME
      dockerfile: Dockerfile
    # Option 2: Use image from registry (uncomment if you push to a registry)
    # image: your-registry/$SERVICE_NAME:latest
    restart: unless-stopped
    user: "\${PUID}:\${PGID}"  # Recommended for most services
    environment:
      - TZ=\${TZ}
      # Add service-specific environment variables here
      # Example for a web app:
      # - DATABASE_URL=postgres://\${POSTGRES_USER}:\${POSTGRES_PASSWORD}@homelab_postgres:5432/$SERVICE_NAME
      # - REDIS_URL=redis://:\${REDIS_PASSWORD}@homelab_redis:6379
      # - OLLAMA_HOST=http://ollama:11434  # If using AI
    volumes:
      - \${DATA_PATH}/dev-services/$SERVICE_NAME/data:/app/data  # Adjust path as needed
      # Add other volume mounts as required
      # - ./config:/app/config:ro  # For read-only config
    networks:
      - homelab_proxy
      - homelab_internal
    labels:
      - "com.centurylinklabs.watchtower.enable=true"
      - "homepage.group=Developer"
      - "homepage.name=$SERVICE_NAME"
      - "homepage.icon=terminal"
      - "homepage.href=http://\${DOMAIN}:[PORT]"  # CHANGE [PORT] to your service port
      - "homepage.description=Developer service: $SERVICE_NAME"
      # Add other labels as needed (e.g., for traefik, monitoring, etc.)
    # Add ports if needed (usually not needed if behind NPM)
    # ports:
    #   - "[PORT]:[PORT]"  # Only if direct access is needed
    # Add depends_on if your service needs other services
    # depends_on:
    #   - homelab_postgres
    #   - homelab_redis
EOF

echo "Generated deployment snippet: $SERVICE_DIR/deployment-snippet.yml"
echo ""
echo "Next steps:"
echo "1. Review the generated snippet and customize it for your service's needs"
echo "2. Add the service to $TARGET_PHASE/docker-compose.yml under the 'services:' section"
echo "3. Configure environment variables, volumes, and dependencies as required"
echo "4. Deploy with: cd $TARGET_PHASE && docker compose --env-file ../../.env up -d"
echo ""
echo "Note: Make sure to replace [PORT] in the hostname label with your actual service port."