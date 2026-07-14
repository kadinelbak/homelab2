#!/bin/bash
# deploy-to-homelab.sh
# Deploy a service from dev/services/ to the homelab

set -euo pipefail

# Check if service name is provided
if [[ $# -eq 0 ]]; then
  echo "Usage: $0 <service-name>"
  echo "  service-name: Name of the service in dev/services/ to deploy (e.g., my-webapp)"
  echo ""
  echo "Example:"
  echo "  $0 my-webapp"
  exit 1
fi

SERVICE_NAME="$1"
SERVICE_DIR="dev/services/$SERVICE_NAME"

# Check if service exists
if [[ ! -d "$SERVICE_DIR" ]]; then
  echo "Error: Service not found: $SERVICE_DIR"
  echo "Create it first using: ./create-service.sh <service-name> <template-type>"
  exit 1
fi

echo "Deploying service: $SERVICE_NAME"

# Check if there's a deploy script in the service directory
if [[ -f "$SERVICE_DIR/deploy.sh" ]]; then
  echo "Running service-specific deploy script..."
  cd "$SERVICE_DIR"
  ./deploy.sh
  cd - > /dev/null
elif [[ -f "$SERVICE_DIR/docker-compose.yml" ]]; then
  # If there's a production docker-compose.yml, we can deploy it
  # But we need to determine where to deploy it (which phase)
  echo "Found docker-compose.yml in service directory."
  echo "To deploy to homelab, you would typically:"
  echo "1. Copy the service to the appropriate phase directory"
  echo "2. Add it to that phase's docker-compose.yml"
  echo "3. Run: docker compose --env-file ../.env up -d"
  echo ""
  echo "For now, we'll create a basic deployment manifest."
  
  # Create a basic deployment snippet
  cat > "$SERVICE_DIR/deployment-snippet.yml" <<EOF
# Add this to the appropriate phase's docker-compose.yml
# Determine which phase based on service type:
#   - web-app, api-service: usually phase3-ai-gaming or phase2-media
#   - worker, cron-job: usually phase3-ai-gaming
#   - dashboard: usually phase1-core or phase3-ai-gaming

services:
  $SERVICE_NAME:
    # Build from local context or use a registry
    build: ./dev/services/$SERVICE_NAME
    # Or if you've pushed to a registry:
    # image: your-registry/$SERVICE_NAME:latest
    restart: unless-stopped
    # Add appropriate networks (usually homelab_proxy and/or homelab_internal)
    networks:
      - homelab_proxy
      - homelab_internal
    # Add environment variables as needed
    environment:
      - TZ=\${TZ}
      # Add service-specific environment variables
    # Add volumes for persistent data
    volumes:
      - \${DATA_PATH}/dev-services/$SERVICE_NAME/data:/app/data
    # Add labels for homepage, watchtower, etc.
    labels:
      - "com.centurylinklabs.watchtower.enable=true"
      - "homepage.group=Developer"
      - "homepage.name=$SERVICE_NAME"
      - "homepage.icon=terminal"
      - "homepage.href=http://\${DOMAIN}:[PORT]"  # Change [PORT] as needed
      - "homepage.description=Developer service: $SERVICE_NAME"
EOF
  
  echo "Created deployment snippet: $SERVICE_DIR/deployment-snippet.yml"
  echo "Review this file and add the service to the appropriate phase's docker-compose.yml"
else
  echo "Warning: No docker-compose.yml or deploy.sh found in service directory."
  echo "You may need to create deployment files manually."
fi

echo ""
echo "Deployment preparation complete for: $SERVICE_NAME"
echo ""
echo "Next steps:"
echo "1. Review any generated deployment files"
echo "2. Move the service to the appropriate phase directory (if needed)"
echo "3. Add the service to that phase's docker-compose.yml"
echo "4. Configure environment variables and volumes as required"
echo "5. Deploy with: docker compose --env-file ../.env up -d"