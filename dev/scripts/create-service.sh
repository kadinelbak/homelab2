#!/bin/bash
# create-service.sh
# Create a new service from a template

set -euo pipefail

# Check if required arguments are provided
if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <service-name> <template-type> [language]"
  echo "  service-name: Name of the service to create (e.g., my-webapp)"
  echo "  template-type: Type of template (web-app, api-service, worker, cron-job, dashboard)"
  echo "  language: Optional language override (for templates that support multiple languages)"
  echo ""
  echo "Example:"
  echo "  $0 my-webapp web-app"
  echo "  $0 my-api api-service"
  echo "  $0 my-worker worker"
  exit 1
fi

SERVICE_NAME="$1"
TEMPLATE_TYPE="$2"
LANGUAGE_OVERRIDE="${3:-}"

# Validate template type
VALID_TEMPLATES=("web-app" "api-service" "worker" "cron-job" "dashboard")
if [[ ! " ${VALID_TEMPLATES[*]} " =~ " ${TEMPLATE_TYPE} " ]]; then
  echo "Error: Invalid template type '$TEMPLATE_TYPE'"
  echo "Valid types: ${VALID_TEMPLATES[*]}"
  exit 1
fi

# Define paths
TEMPLATE_DIR="dev/templates/$TEMPLATE_TYPE"
TARGET_DIR="dev/services/$SERVICE_NAME"

# Check if template exists
if [[ ! -d "$TEMPLATE_DIR" ]]; then
  echo "Error: Template directory not found: $TEMPLATE_DIR"
  exit 1
fi

# Check if service already exists
if [[ -d "$TARGET_DIR" ]]; then
  echo "Error: Service already exists: $TARGET_DIR"
  echo "Remove it first if you want to recreate it."
  exit 1
fi

# Create service directory
echo "Creating service: $SERVICE_NAME from template: $TEMPLATE_TYPE"
mkdir -p "$TARGET_DIR"

# Copy template files
cp -r "$TEMPLATE_DIR"/* "$TARGET_DIR/"

# If language override is provided, handle language-specific files
if [[ -n "$LANGUAGE_OVERRIDE" ]]; then
  echo "Applying language override: $LANGUAGE_OVERRIDE"
  # This would be template-specific logic
  # For now, we just note it in README
  echo "Language override: $LANGUAGE_OVERRIDE" >> "$TARGET_DIR/README.md"
fi

# Initialize git repo if not already initialized
if [[ ! -d "$TARGET_DIR/.git" ]]; then
  echo "Initializing git repository..."
  cd "$TARGET_DIR"
  git init
  # Add all files
  git add .
  git commit -m "Initial commit: Create $SERVICE_NAME from $TEMPLATE_TYPE template"
  cd - > /dev/null
fi

# Create a basic README if not exists
if [[ ! -f "$TARGET_DIR/README.md" ]]; then
  cat > "$TARGET_DIR/README.md" << 'EOF'
# $SERVICE_NAME

A $TEMPLATE_TYPE service created from the homelab developer template.

## Overview
This service was created using the create-service.sh script.

## Development
To start development:
```
cd dev/services/$SERVICE_NAME
docker compose -f docker-compose.dev.yml up -d
```

## Deployment
To deploy to homelab:
```
./deploy-to-homelab.sh
```

## Notes
- Service name: $SERVICE_NAME
- Template type: $TEMPLATE_TYPE
- Created: $(date)
EOF
else
  # Append to existing README
  cat >> "$TARGET_DIR/README.md" << 'EOF'

## Development Notes
- Service name: $SERVICE_NAME
- Template type: $TEMPLATE_TYPE
- Created: $(date)
EOF
fi

echo "Service created successfully: $TARGET_DIR"
echo ""
echo "Next steps:"
echo "1. Review the generated files in $TARGET_DIR"
echo "2. Customize the service for your needs"
echo "3. For development: cd $TARGET_DIR && docker compose -f docker-compose.dev.yml up -d"
echo "4. For deployment: ./deploy-to-homelab.sh (after creating the script)"