# Environment Variable Reference

`.env.example` is the source of truth for required configuration. Copy it to `.env`, replace every `CHANGE_ME_*` value, and keep `.env` out of git.

## Validation

```bash
cp .env.example .env
grep -n "CHANGE_ME" .env
bash scripts/setup.sh --validate-only
```

## Host and Path Variables

| Variable | Required | Purpose |
| --- | --- | --- |
| `TZ` | Yes | Timezone used by containers, schedules, logs, and maintenance windows. |
| `PUID` | Yes | Host user ID used by LinuxServer-style containers for file ownership. Get it with `id -u`. |
| `PGID` | Yes | Host group ID used by containers for file ownership. Get it with `id -g`. |
| `DOCKER_GID` | Yes | Host Docker socket group ID for Homepage Docker discovery. Get it with `getent group docker`. |
| `DOCKER_HOST_IP` | Yes | LAN or tailnet IP of the Docker host. Used for callbacks and direct links. |
| `DATA_PATH` | Yes | Root path for all persistent bind-mounted application data. |
| `DOMAIN` | Yes | Base DNS name used for dashboard links and reverse proxy hosts. |

## Phase 1: Core Infrastructure

| Variable | Required | Purpose |
| --- | --- | --- |
| `POSTGRES_USER` | Yes | Shared PostgreSQL owner/user for service databases. |
| `POSTGRES_PASSWORD` | Yes | Shared PostgreSQL password. Generate with `openssl rand -hex 32`. |
| `REDIS_PASSWORD` | Yes | Shared Redis password. Generate with `openssl rand -hex 32`. |
| `AUTHENTIK_SECRET_KEY` | Yes | Authentik cryptographic key. This is not an API token. |
| `AUTHENTIK_BOOTSTRAP_EMAIL` | Yes | Initial Authentik admin email. |
| `AUTHENTIK_BOOTSTRAP_PASSWORD` | Yes | Initial Authentik admin password. |
| `AUTHENTIK_ADMIN_EMAIL` | Yes | Public/admin email reused by downstream services such as Paperless. Usually match `AUTHENTIK_BOOTSTRAP_EMAIL`. |
| `AUTHENTIK_URL` | Phase 2 SSO | Public Authentik URL used by provisioning scripts. |
| `AUTHENTIK_API_TOKEN` | Phase 2 SSO | Real Authentik API token for automation. Do not use `AUTHENTIK_SECRET_KEY` for API calls. |
| `VAULTWARDEN_ADMIN_TOKEN` | Yes | Vaultwarden admin panel token. Prefer an argon2 hash for exposed deployments. |
| `VAULTWARDEN_ADMIN_EMAIL` | Optional | Admin email used by docs/provisioning. |
| `VAULTWARDEN_ADMIN_PASSWORD` | Optional | Initial user password value for future provisioning scripts. |
| `BESZEL_KEY` | Yes | Beszel agent key from the Beszel Hub enrollment flow. |
| `BESZEL_TOKEN` | Yes | Beszel agent token when required by your agent version. |
| `BESZEL_HUB_URL` | Yes | Agent callback URL for the Beszel Hub. |
| `GF_SECURITY_ADMIN_USER` | Yes | Grafana admin username. |
| `GF_SECURITY_ADMIN_PASSWORD` | Yes | Grafana admin password. |
| `PROMETHEUS_RETENTION` | Yes | Prometheus local retention window, for example `30d`. |
| `NTFY_BASE_URL` | Yes | Base URL announced by ntfy. |
| `NTFY_TOPIC` | Yes | Default topic for homelab notifications. |
| `WATCHTOWER_CRON` | Yes | Six-field Watchtower update schedule. |
| `WATCHTOWER_NOTIFICATION_URL` | Yes | Watchtower notification URL, usually an internal ntfy URL. |

## Optional Core Integrations

| Variable | Required | Purpose |
| --- | --- | --- |
| `NUT_PASSWORD` | Optional | UPS monitoring password for future NUT integration. |
| `WOL_API_KEY` | Optional | Wake-on-LAN API key used by the `/wake` endpoint. |
| `WOL_MAC_ADDRESS` | Optional | Default target MAC address for Wake-on-LAN packets. |
| `WOL_BROADCAST_ADDRESS` | Optional | Broadcast address used for WoL packets, usually `255.255.255.255` or your subnet broadcast. |
| `WOL_PORT` | Optional | UDP port used for WoL packets, usually `9`. |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `SMTP_FROM` | Optional | Alert email transport. |
| `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_ENDPOINT`, `S3_BUCKET`, `S3_REGION` | Optional | Offsite object storage for backups. |
| `RESTIC_PASSWORD` | Phase 2 backup | Restic repository password. Store it somewhere recoverable. |
| `RESTIC_KEEP_DAILY` | Phase 2 backup | Number of daily snapshots to retain. |
| `RESTIC_KEEP_WEEKLY` | Phase 2 backup | Number of weekly snapshots to retain. |
| `RESTIC_KEEP_MONTHLY` | Phase 2 backup | Number of monthly snapshots to retain. |
| `BACKUP_INTERVAL_SECONDS` | Phase 2 backup | Backup loop interval in seconds. Default is once per day. |

## Phase 2: Media and Documents

| Variable | Required | Purpose |
| --- | --- | --- |
| `PAPERLESS_ADMIN_PASSWORD` | Yes for Paperless | Initial Paperless admin password. |
| `IMMICH_DB_USERNAME` | Yes for Immich | Dedicated Immich database user. |
| `IMMICH_DB_PASSWORD` | Yes for Immich | Dedicated Immich database password. |
| `IMMICH_DB_DATABASE_NAME` | Yes for Immich | Dedicated Immich database name. |
| `VPN_SERVICE_PROVIDER` | Torrent profile | Gluetun VPN provider name. |
| `VPN_TYPE` | Torrent profile | `wireguard` or `openvpn`. |
| `WIREGUARD_PRIVATE_KEY` | Torrent profile | WireGuard private key from your VPN provider. |
| `WIREGUARD_ADDRESSES` | Torrent profile | WireGuard tunnel address/CIDR. |
| `SERVER_COUNTRIES` | Torrent profile | Gluetun region preference. |

## Phase 3: AI, Automation, and Gaming

| Variable | Required | Purpose |
| --- | --- | --- |
| `OLLAMA_MODEL` | Optional | Default model pulled by helper scripts. |
| `OLLAMA_HOST` | Optional | Internal Ollama API URL. |
| `N8N_ENCRYPTION_KEY` | Yes for n8n | Credential encryption key. Generate once and never rotate casually. |
| `N8N_USER_MANAGEMENT_JWT_SECRET` | Yes for n8n | JWT signing secret for n8n user management. |
| `N8N_BASIC_AUTH_USER` | Optional | Basic auth username if enabled. |
| `N8N_BASIC_AUTH_PASSWORD` | Optional | Basic auth password if enabled. |
| `AI_ORCHESTRATOR_TOKEN` | Yes for AI orchestrator | Bearer token required for request intake, approval, and action handoff endpoints. |
| `TOOLS_PUBLIC_SCHEME` | Optional | Protocol used by Docker-discovered Tools dashboard links. Use `http` for direct tailnet ports or `https` after TLS/reverse proxy access is ready. |
| `ACTUAL_PUBLIC_SCHEME` | Optional | Protocol for Actual Budget dashboard links. Defaults to `https` because Actual requires HTTPS for SharedArrayBuffer outside localhost. |
| `ACTUAL_LOGIN_METHOD` | Optional | Actual Budget login method. Defaults to `password`; keep password enabled unless OpenID has been fully configured in Actual. |
| `ACTUAL_ALLOWED_LOGIN_METHODS` | Optional | Comma-separated Actual Budget login methods allowed by the server, for example `password,openid`. |
| `ACTUAL_TRUSTED_PROXIES` | Optional | Proxy CIDRs trusted by Actual Budget for forwarded client information. Defaults to private/internal networks. |
| `ACTUAL_HTTPS_KEY` | Yes for direct-port Actual HTTPS | Path inside the container to Actual's HTTPS private key. Defaults to `/data/selfhost.key`; generate it with `bash scripts/ensure-actual-https-cert.sh`. |
| `ACTUAL_HTTPS_CERT` | Yes for direct-port Actual HTTPS | Path inside the container to Actual's HTTPS certificate. Defaults to `/data/selfhost.crt`; generate it with `bash scripts/ensure-actual-https-cert.sh`. |
| `STIRLING_PDF_ENABLE_LOGIN` | Optional | Enables Stirling PDF native username/password login. Defaults to `true`. |
| `STIRLING_PDF_LOGIN_METHOD` | Optional | Stirling PDF login method. Defaults to `normal` for username/password login; use `all` only when SSO is configured. |
| `STIRLING_PDF_INITIAL_USERNAME` | Optional | Initial Stirling PDF admin username, used only before the Stirling database/account exists. |
| `STIRLING_PDF_INITIAL_PASSWORD` | Yes for Stirling PDF | Initial Stirling PDF admin password. Change it in the app after first login; later env changes do not rotate an existing account. |
| `MINECRAFT_EULA` | Yes for Minecraft | Must be `TRUE` to accept the Minecraft server EULA. |
| `MINECRAFT_MEMORY` | Yes for Minecraft | JVM memory limit, for example `3G` on a 16 GB host. |
| `MINECRAFT_TYPE` | Yes for Minecraft | Server type such as `PAPER`, `VANILLA`, `FORGE`, or `FABRIC`. |
| `MINECRAFT_VERSION` | Yes for Minecraft | Minecraft version, for example `LATEST` or `1.21.1`. |
| `MINECRAFT_OPS` | Optional | Comma-separated operator usernames. |

## Phase 4: On-Demand Services

| Variable | Required | Purpose |
| --- | --- | --- |
| `NEXTCLOUD_ADMIN_USER` | Yes for Nextcloud | Initial Nextcloud admin username. |
| `NEXTCLOUD_ADMIN_PASSWORD` | Yes for Nextcloud | Initial Nextcloud admin password. |
| `NEXTCLOUD_TRUSTED_DOMAINS` | Yes for Nextcloud | Trusted hostnames for Nextcloud. |
| `GITEA_ADMIN_USER`, `GITEA_ADMIN_PASSWORD`, `GITEA_ADMIN_EMAIL` | Future provisioning | Initial Gitea admin account values. |
| `GITEA_SECRET_KEY` | Yes for Gitea | Gitea app secret. |
| `GITEA_INTERNAL_TOKEN` | Yes for Gitea | Gitea internal token. |
| `OUTLINE_SECRET_KEY` | Yes for Docmost | Docmost app secret in this repo. |
| `OUTLINE_UTILS_SECRET` | Optional | Reserved for Outline-compatible future services. |
| `CALCOM_NEXTAUTH_SECRET` | Yes for Cal.com | NextAuth signing secret. |
| `CALCOM_CALENDSO_ENCRYPTION_KEY` | Yes for Cal.com | Cal.com encryption key. |
| `CALCOM_EMAIL_FROM` | Yes for Cal.com | Sender address for Cal.com email. |
| `SUPABASE_POSTGRES_PASSWORD` | Supabase placeholder | Password for a full Supabase deployment. |
| `SUPABASE_JWT_SECRET`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY` | Supabase placeholder | Required by the official Supabase self-hosting stack. |
| `NOCODB_SECRET` | Yes for NocoDB | NocoDB JWT/signing secret. |

## SSO/OIDC Client Variables

The `*_CLIENT_ID` and `*_CLIENT_SECRET` values are reserved for Phase 2 declarative Authentik provisioning. Until that is implemented, create providers in Authentik and paste the generated values into `.env`.

Variables:

- `GF_AUTH_GENERIC_OAUTH_CLIENT_ID`
- `GF_AUTH_GENERIC_OAUTH_CLIENT_SECRET`
- `N8N_AUTH_OAUTH2_GENERIC_CLIENT_ID`
- `N8N_AUTH_OAUTH2_GENERIC_CLIENT_SECRET`
- `HOMEPAGE_AUTH_CLIENT_ID`
- `HOMEPAGE_AUTH_CLIENT_SECRET`
- `VAULTWARDEN_OIDC_CLIENT_ID`
- `VAULTWARDEN_OIDC_CLIENT_SECRET`
- `PORTAINER_OIDC_CLIENT_ID`
- `PORTAINER_OIDC_CLIENT_SECRET`
- `HOME_ASSISTANT_OAUTH2_CLIENT_ID`
- `HOME_ASSISTANT_OAUTH2_CLIENT_SECRET`

## Capacity Governor Variables

| Variable | Required | Purpose |
| --- | --- | --- |
| `HOMELAB_RAM_LIMIT_MB` | Phase 3 | Total RAM budget used by admission control. |
| `HOMELAB_RESERVED_RAM_MB` | Phase 3 | RAM kept free for the host OS and emergency headroom. |
| `HOMELAB_VRAM_LIMIT_MB` | Phase 3 | GPU VRAM budget used by admission control. |
| `HOMELAB_ADMISSION_MODE` | Phase 3 | `warn` or `enforce`. |

## Secret Generation

Use strong stable values. Do not regenerate secrets for stateful services after first deploy unless you also plan a migration.

```bash
openssl rand -hex 32
openssl rand -base64 48 | tr -d '\n'
```

## Bring-Up Order

```bash
bash scripts/setup.sh
docker compose --env-file .env -f phase1-core/docker-compose.yml up -d
docker compose --env-file .env -f phase2-media/docker-compose.yml up -d
docker compose --env-file .env -f phase3-ai-gaming/docker-compose.yml up -d
```

Phase 4 remains on-demand:

```bash
bash scripts/toggle-ondemand.sh up
bash scripts/toggle-ondemand.sh down
```
