# Single Sign-On & Centralized Account Management Feature Spec

## Overview
Enable seamless authentication across all homelab services using a central Identity Provider (IdP). After logging into Authentik (or any SSO portal), users should be able to access any integrated service without re‑entering credentials. This spec outlines making Authentik the IdP and configuring each supported service to trust it via OIDC, SAML, or proxy‑based authentication (e.g., via Authelia/OAuth2‑Proxy where native support is lacking).

## Core Components
- **Authentik** (already in phase1-core): Open‑source IdP supporting OIDC, SAML, LDAP, and proxy modes.
- **Authelia** or **OAuth2‑Proxy** (optional): For services that lack native OIDC/SAML but support HTTP‑based auth (e.g., via headers).
- **Service‑specific OIDC/SAML configuration**: Where the service natively supports it.
- **Homepage integration**: Display login status and provide SSO login links.
- **Vaultwarden integration**: Store service accounts or API tokens needed for SSO setup.

## Implementation Plan (Single AI Execution)

### Phase 1: Prepare Authentik as the Central IdP
1. **Ensure Authentik is running** (already in phase1-core).
2. **Create a default Admin user** (if not exists) via the Authentik UI or API on first start (handled by infra‑as‑code spec).
3. **Define a Homelab Realm** (or use the default realm) that will hold all users and groups.
4. **Set up a user directory**:
   - Option A: Built‑in Authentik user store (simplest).
   - Option B: Connect to an external LDAP/Active Directory if desired.
5. **Configure default authentication flows**:
   - Enable username/email + password.
   - Optionally enable TOTP (2FA) for admins.
   - Optionally enable social login (GitHub, Google) if desired.

### Phase 2: Create Service Applications & Providers in Authentik
For each service that supports OIDC or SAML, create an **Application** and a **Provider** in Authentik.

#### Generic Steps (to be scripted or documented)
1. In Authentik UI → Applications → New Application:
   - Name: e.g., "Grafana"
   - Slug: `grafana`
   - Provider: (will be created next)
   - Metadata: optional icon, description.
2. Create a Provider:
   - Type: **OIDC** (preferred) or **SAML** if the service only supports SAML.
   - Redirect URIs: `https://<service>.<domain>/oauth2/callback` (or as required by service).
   - Signing key: use Authentik’s default.
   - Grant types: Authorization Code, Refresh Token.
   - Ensure scopes include `openid`, `profile`, `email`, and optionally `groups`.
3. Note the **Client ID**, **Client Secret**, and **Issuer URL** (`https://authentik.<domain>/application/o/grafana/`).

Repeat for each service.

### Phase 3: Configure Each Service to Use Authentik
Below is a checklist for major services. For services not listed, a fallback is to place them behind **Authelia** or **OAuth2‑Proxy** (see Phase 4).

#### Services with Native OIDC Support
| Service | Config Path/Env Var | Notes |
|---------|---------------------|-------|
| **Grafana** | `GF_AUTH_GENERIC_OAUTH_ENABLED`, `GF_AUTH_GENERIC_OAUTH_NAME`, `GF_AUTH_GENERIC_OAUTH_CLIENT_ID`, `GF_AUTH_GENERIC_OAUTH_CLIENT_SECRET`, `GF_AUTH_GENERIC_OAUTH_SCOPES`, `GF_AUTH_GENERIC_OAUTH_AUTH_URL`, `GF_AUTH_GENERIC_OAUTH_TOKEN_URL`, `GF_AUTH_GENERIC_OAUTH_API_URL` | Use OIDC generic plugin. Set `GF_AUTH_GENERIC_OAUTH_ALLOW_SIGN_UP=false`. |
| **Prometheus** (via Web UI) | Not directly; protect via **Authelia** or **OAuth2‑Proxy** (see Phase 4). |
| **Alertmanager** | Same as Prometheus. |
| **Loki** | Same. |
| **Homepage** | Enable `auth` section: `auth: authentik: enabled: true, url: https://authentik.<domain>, client_id: ..., client_secret: ...` |
| **Portainer** | Settings → Authentication → Auth Provider → OIDC: fill Issuer URL, Client ID, Client Secret. |
| **Uptime Kuma** | Settings → Authentication → OAuth2 / OIDC: fill similar fields. |
| **Vaultwarden** | Enable `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`. |
| **Authentik** (self‑service) | Already the IdP; can enable self‑service registration/portal. |
| **n8n** | `N8N_AUTH_BASIC_ACTIVE=false`, `N8N_AUTH_OAUTH2_TYPES=generic`, `N8N_AUTH_OAUTH2_GENERIC_TITLE=Authentik`, `N8N_AUTH_OAUTH2_GENERIC_CLIENT_ID`, `N8N_AUTH_OAUTH2_GENERIC_CLIENT_SECRET`, `N8N_AUTH_OAUTH2_GENERIC_AUTH_URL`, `N8N_AUTH_OAUTH2_GENERIC_ACCESS_TOKEN_URL`, `N8N_AUTH_OAUTH2_GENERIC_SCOPE=openid profile email`, `N8N_AUTH_OAUTH2_GENERIC_ICON=authentik` |
| **Home Assistant** | Configure via `auth_providers:` in `configuration.yaml`: type: `oauth2`, `client_id`, `client_secret`, `authorize_url`, `token_url`, `profile_url`. |
| **Nextcloud** | Apps → SSO & SAML Auth → configure OIDC via third‑party app (e.g., OpenID Connect). |
| **Gitea** | `[oauth2]` section in `app.ini`: `ENABLED = true`, `PROVIDERS = oidc`, `OAUTH2_PROVIDERS = oidc; ...` |
| **Docmost, Cal.com, NocoDB** | Check docs; many support OIDC via env vars or config files. |
| **Immich** | Supports OIDC via env vars: `IMMICH_OIDC_ISSUER`, `IMMICH_OIDC_CLIENT_ID`, `IMMICH_OIDC_CLIENT_SECRET`. |
| **Paperless‑ngx** | `PAPERLESS_AUTH_ENABLED_BACKENDS=oauth2`, `PAPERLESS_AUTH_OAUTH2_CLIENT_ID`, `PAPERLESS_AUTH_OAUTH2_CLIENT_SECRET`, `PAPERLESS_AUTH_OAUTH2_METADATA_URL` (or individual URLs). |
| **Audiobookshelf** | Settings → Authentication → OAuth2 / OIDC. |
| **Jellyfin** | Dashboard → Dashboard → Authentication → OpenID Connect. |
| **Navidrome** | `ND_AUTH_OIDC_ENABLED=true`, `ND_AUTH_OIDC_ISSUER_URL`, `ND_AUTH_OIDC_CLIENT_ID`, `ND_AUTH_OIDC_CLIENT_SECRET`. |
| **Spoolman** | Check if supports OIDC; otherwise use Authelia. |
| **Actual Budget** | May need Authelia fallback. |
| **Stirling PDF, IT‑Tools** | Typically no native SSO; protect via Authelia/OAuth2‑Proxy. |
| **Hearts Multiplayer** | If web‑based, protect via Authelia; otherwise consider token‑based auth from a custom gateway. |

For each service, add the necessary environment variables or configuration files under `${DATA_PATH}/<phase>/data/<service>/` (or equivalent) and restart the container.

#### Phase 4: Fallback for Services Without Native OIDC
Deploy **Authelia** (or **OAuth2‑Proxy**) as an upstream auth layer in front of services that lack native support.

1. **Add Authelia** to phase1-core/docker-compose.yml:
   ```yaml
   authelia:
     image: authelia/authelia:latest
     container_name: authelia
     restart: unless-stopped
     environment:
       TZ: ${TZ}
     volumes:
       - ${DATA_PATH}/phase1-core/data/authelia/config:/config
     networks:
       - homelab_proxy
     labels:
       - "homepage.group=Maintenance"
       - "homepage.name=Authelia"
       - "homepage.href=http://${DOMAIN}:9091"   # Authelia UI
   ```
2. **Configure Authelia** to use Authentik as an OIDC / OpenID Connect identity provider (Authelia supports OIDC as an identity provider).
   - In `configuration.yml`:
     ```yaml
     identity_providers:
       oidc:
         issuer_private_key: /config/identity/oidc.key
         issuer_certificate: /config/identity/oidc.crt
         # or reference Authentik as an upstream IdP via "issuer" if Authelia acts as relying party? Actually Authelia can be an OpenID Connect Provider (OP) or Relying Party (RP). For SSO we want Authelia to rely on Authentik -> use "oidc" as a client.
     ```
     More precisely, set up Authelia's `access_control` to require authentication and use an `authentication_backend` of type `oidc` pointing to Authentik.
   - Reference: Authelia docs for "OpenID Connect Relying Party".
3. **Protect Services**: In the Docker‑compose labels (or via nginx‑proxy‑manager custom locations) forward traffic through Authelia:
   - Use the `authelia@docker` forwardAuth mechanism if using a compatible reverse proxy (Traefik, nginx‑plus). With NPM, you can use a custom forward auth URL or place Authelia as an intermediate proxy.
   - Simpler: Deploy **OAuth2‑Proxy** (maybe lighter) for each service that needs protection.

Given the complexity, an alternative is to use **Authentik's built‑in proxy mode** (called "Outpost") which can sit in front of any service and validate sessions via cookies or headers. Authentik can act as a reverse proxy (similar to Authelia) for any service.

Thus:
- Deploy an **Authentik Outpost** (or enable the embedded proxy) for services lacking native OIDC.
- Configure the outpost to validate sessions issued by Authentik and add appropriate headers (e.g., `X-Authentik-User`, `X-Authentik-Email`, `X-Authentik-Groups`).
- Then configure the backend service to trust those headers (if it supports header‑based auth) or place the outpost as a strict gatekeeper (return 401 if invalid).

Given the scope, the spec will focus on native OIDC where possible and note the fallback pattern.

### Phase 5: Automate SSO Configuration via Scripts
Create a script `scripts/configure-sso.sh` that:
- Reads the generated `.env` for Authentik URL and admin credentials.
- Uses the Authentik API (`/api/v1/`) to:
  1. Create applications/providers for each service (if not exist).
  2. Assign the admin user to relevant groups.
  3. Optionally enable user registration/invite.
- Outputs a summary of Client IDs/Secrets to be copied into each service’s `.env` or config files.
- Can be run post‑deploy to ensure IdP is ready.

### Phase 6: Post‑Deploy Integration (via infra‑as‑code spec)
- In `scripts/post-deploy.sh`, after services are healthy:
  1. Run `./scripts/configure-sso.sh` (or call its functions).
  2. For each service, write the necessary env vars/config files based on the output of the SSO configuration step.
  3. Restart services that need new config (or rely on container’s ability to reload env without restart; otherwise schedule a rolling restart).
- Ensure that the **Homepage** shows a "Sign in with Authentik" button and reflects login status.

### Phase 7: User Experience
- User visits any service URL (e.g., `https://grafana.<domain>`).
- If not authenticated, they are redirected to Authentik login page.
- After login, they are redirected back to the service and logged in.
- Logging out from any service (or Authentik) ends the session across all SSO‑integrated services.
- Homepage displays the authenticated user’s name and provides a "Logout" link that hits Authentik’s end‑session endpoint.

## Success Criteria
- A single set of credentials (username/password) grants access to all configured services.
- No duplicate account creation; user attributes (name, email, groups) flow from Authentik.
- Admin can manage users, groups, and application access from the Authentik dashboard.
- Services that cannot be modified to support OIDC are protected via an Authentik outpost or Authelia/OAuth2‑Proxy, still providing a seamless SSO experience.
- The solution is documented and automated via scripts so that a fresh deploy yields working SSO out of the box.

## Files to Create/Modify
```
context/feature-specs/04-sso-account-management.md          (this file)
scripts/configure-sso.sh                                    (SSO automation)
scripts/post-deploy.sh                                      (extend to call SSO config)
config/authentik/                                           (optional: export/import of applications/providers as JSON)
phase1-core/docker-compose.yml                              (ensure Authentik ports exposed, volumes for data)
<service>-specific config files under ${DATA_PATH}/...      (e.g., grafana.ini, n8n config, etc.)
README.md                                                   (updated post‑deploy with SSO instructions)
```

## Dependencies
- Authentik running and healthy.
- Services that support OIDC/SAML (most listed do; others fallback).
- Ability to make HTTP API calls to Authentik (for automation).
- Optional: Authelia or OAuth2‑Proxy for fallback (add to compose if needed).

## Estimated Effort
Single AI execution to:
- Write the SSO specification.
- Create the configuration script that talks to Authentik API.
- Document the per‑service env var mappings.
- Extend the post‑deploy hook to apply SSO configuration.
Actual per‑service tweaks may be needed but the pattern is repeatable.