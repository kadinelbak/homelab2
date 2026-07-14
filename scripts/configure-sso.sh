#!/bin/bash
# configure-sso.sh
# Automate SSO configuration for Authentik using its API

set -euo pipefail

echo "=== Configuring SSO via Authentik API ==="

# Source .env to get variables
if [[ -f "../.env" ]]; then
  export $(grep -v '^#' ../.env | xargs)
else
  echo "Error: .env not found."
  exit 1
fi

# Check if required variables are set
if [[ -z "${AUTHENTIK_SECRET_KEY:-}" ]]; then
  echo "Error: AUTHENTIK_SECRET_KEY not set in .env"
  exit 1
fi

if [[ -z "${DOMAIN:-}" ]]; then
  echo "Error: DOMAIN not set in .env"
  exit 1
fi

AUTHENTIK_URL="https://authentik.${DOMAIN}"
API_TOKEN="${AUTHENTIK_SECRET_KEY}"

echo "Authentik URL: $AUTHENTIK_URL"

# Function to make authenticated API calls
authentik_api() {
  local method="$1"
  local endpoint="$2"
  local data="$3"
  
  local url="${AUTHENTIK_URL}${endpoint}"
  
  if [[ -n "$data" ]]; then
    curl -s -X "$method" "$url" \
      -H "Authorization: Bearer $API_TOKEN" \
      -H "Content-Type: application/json" \
      -d "$data"
  else
    curl -s -X "$method" "$url" \
      -H "Authorization: Bearer $API_TOKEN"
  fi
}

# Check if Authentik is accessible
echo "Checking Authentik accessibility..."
if ! auth_response=$(authentik_api "GET" "/api/v3/core/meta-info/"); then
  echo "Error: Cannot connect to Authentik at $AUTHENTIK_URL"
  exit 1
fi

echo "Authentik is accessible"

# Create or get applications and providers for each service
declare -A services=(
  ["grafana"]="Grafana"
  ["n8n"]="n8n"
  ["homepage"]="Homepage"
  ["vaultwarden"]="Vaultwarden"
  ["portainer"]="Portainer"
  ["homeassistant"]="Home Assistant"
)

# Create a directory to store client secrets if needed
mkdir -p ../config/authentik

echo "Creating Authentik applications and providers..."

for service_key in "${!services[@]}"; do
  service_name="${services[$service_key]}"
  echo "Processing $service_name..."
  
  # Check if application already exists
  app_response=$(authentik_api "GET" "/api/v3/core/applications/?slug=${service_key}")
  app_count=$(echo "$app_response" | grep -o '"count":[0-9]*' | grep -o '[0-9]*')
  
  if [[ "$app_count" -eq 0 ]]; then
    echo "Creating application for $service_name..."
    
    # Create application
    app_data=$(cat <<EOF
{
  "name": "$service_name",
  "slug": "$service_key",
  "meta": {
    "description": "SSO access to $service_name via Authentik",
    "icon": "circle"
  },
  "provider": "",
  "meta_launch_url": "",
  "meta_description": "SSO access to $service_name via Authentik",
  "meta_icon": "circle"
}
EOF
)
    
    app_create_response=$(authentik_api "POST" "/api/v3/core/applications/" "$app_data")
    app_slug=$(echo "$app_create_response" | grep -o '"slug":"[^"]*"' | grep -o '[^"]*$' | tr -d '"')
    
    if [[ -z "$app_slug" ]]; then
      echo "Warning: Could not extract slug from application creation response"
      app_slug="$service_key"
    fi
  else
    echo "Application for $service_name already exists"
    app_slug="$service_key"
  fi
  
  # Check if provider already exists for this application
  provider_response=$(authentik_api "GET" "/api/v3/core/providers/?application=${app_slug}")
  provider_count=$(echo "$provider_response" | grep -o '"count":[0-9]*' | grep -o '[0-9]*')
  
  if [[ "$provider_count" -eq 0 ]]; then
    echo "Creating OAuth2/OpenID Connect provider for $service_name..."
    
    # Generate a redirect URI (this would need to be adjusted based on actual service URLs)
    case "$service_key" in
      "grafana")
        redirect_uri="https://grafana.${DOMAIN}/login/generic_oauth"
        ;;
      "n8n")
        redirect_uri="https://n8n.${DOMAIN}/rest/oauth2-credentials"
        ;;
      "homepage")
        redirect_uri="https://homepage.${DOMAIN}/api/auth/authentik/callback"
        ;;
      "vaultwarden")
        redirect_uri="https://vaultwarden.${DOMAIN}/api/auth/ssodelegate"
        ;;
      "portainer")
        redirect_uri="https://portainer.${DOMAIN}/api/oauth2"
        ;;
      "homeassistant")
        redirect_uri="https://homeassistant.${DOMAIN}/auth/external/callback"
        ;;
      *)
        redirect_uri="https://${service_key}.${DOMAIN}/oauth2/callback"
        ;;
    esac
    
    # Create provider
    provider_data=$(cat <<EOF
{
  "name": "${service_name} Provider",
  "slug": "${service_key}-provider",
  "authorization_redirect_uri": "$redirect_uri",
  "authorization_consent_required": false,
  "authorization_scopes": "openid profile email groups",
  "meta": {
    "description": "OAuth2/OpenID Connect provider for $service_name",
    "icon": "shield"
  },
  "metadata": {
    "client_authentication_method": "client_secret_basic",
    "grant_types": [
      "authorization_code",
      "refresh_token"
    ],
    "response_types": [
      "code"
    ],
    "token_endpoint_auth_method": "client_secret_post"
  }
}
EOF
)
    
    provider_create_response=$(authentik_api "POST" "/api/v3/core/providers/" "$provider_data")
    
    # Extract client ID and secret from the response
    client_id=$(echo "$provider_create_response" | grep -o '"client_id":"[^"]*"' | grep -o '[^"]*$' | tr -d '"')
    client_secret=$(echo "$provider_create_response" | grep -o '"client_secret":"[^"]*"' | grep -o '[^"]*$' | tr -d '"')
    
    if [[ -n "$client_id" && -n "$client_secret" ]]; then
      echo "Created provider for $service_name"
      echo "Client ID: $client_id"
      echo "Client Secret: [REDACTED]"
      
      # Save to file for reference
      echo "${service_key}_client_id=$client_id" >> ../config/authentik/client-secrets.env
      echo "${service_key}_client_secret=$client_secret" >> ../config/authentik/client-secrets.env
    else
      echo "Warning: Could not extract client credentials from provider creation response"
    fi
  else
    echo "Provider for $service_name already exists"
    # Extract existing credentials
    provider_details=$(echo "$provider_response" | grep -o '"results":\[[^]]*\]' | head -1)
    if [[ -n "$provider_details" ]]; then
      client_id=$(echo "$provider_details" | grep -o '"client_id":"[^"]*"' | grep -o '[^"]*$' | tr -d '"')
      client_secret=$(echo "$provider_details" | grep -o '"client_secret":"[^"]*"' | grep -o '[^"]*$' | tr -d '"')
      
      if [[ -n "$client_id" && -n "$client_secret" ]]; then
        echo "Using existing provider for $service_name"
        echo "${service_key}_client_id=$client_id" >> ../config/authentik/client-secrets.env
        echo "${service_key}_client_secret=$client_secret" >> ../config/authentik/client-secrets.env
      fi
    fi
  fi
  
  echo "---"
done

echo "=== SSO Configuration Complete ==="
echo "Client secrets have been saved to: ../config/authentik/client-secrets.env"
echo "These values need to be added to each service's configuration."
echo ""
echo "Next steps:"
echo "1. Review the generated client-secrets.env file"
echo "2. Add the appropriate OAuth/OIDC settings to each service"
echo "3. Restart services to apply the changes"
echo "4. Test SSO login for each service"