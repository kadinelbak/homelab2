# Environment Variable Reference

This file explains every variable in [.env.example](.env.example), where to get it, and when you actually need it.

## Quick Use Order

1. Fill System, Postgres, Redis, Authentik first (required for Phase 1).
2. Fill VPN and Immich values for Phase 2.
3. Fill n8n and Minecraft values for Phase 3.
4. Fill Nextcloud, Gitea, Docmost/Outline, Cal.com, Supabase, NocoDB only before Phase 4.

## How To Generate Secrets

Use these commands on the host:

```bash
# 64-char hex secret
openssl rand -hex 32

# Long base64 secret for Authentik
openssl rand -base64 60 | tr -d '\n'

# Base64 secret for web auth apps
openssl rand -base64 32 | tr -d '\n'
```

## System Variables

### TZ
- Purpose: timezone for logs and scheduled jobs.
- How to get it:

```bash
timedatectl | grep 'Time zone'
```

- Example: `America/New_York`
- Required for: all phases.

### PUID
- Purpose: host user ID used for container file ownership.
- How to get it:

```bash
id -u
```

- Example: `1000`
- Required for: all phases.

### PGID
- Purpose: host group ID used for container file ownership.
- How to get it:

```bash
id -g
```

- Example: `1000`
- Required for: all phases.

### DOCKER_HOST_IP
- Purpose: host LAN IP for service callbacks and local references.
- How to get it:

```bash
hostname -I | awk '{print $1}'
```

- Example: `192.168.1.50`
- Required for: helpful generally, some apps/callbacks.

### DOMAIN
- Purpose: root domain for all proxy hosts.
- How to get it: use your registered domain or internal DNS suffix.
- Example: `example.com`
- Required for: all proxied services.

### DATA_PATH
- Purpose: absolute base path for all persistent bind mounts.
- How to get it: choose your NVMe mount point.
- Example: `/mnt/nvme/homelab`
- Required for: all phases.

## Central Database/Cache (Phase 1)

### POSTGRES_USER
- Purpose: central PostgreSQL admin/app user for shared databases.
- How to choose it: any stable username.
- Example: `homelab`
- Required for: Phase 1 and all DB-backed apps.

### POSTGRES_PASSWORD
- Purpose: central PostgreSQL password.
- How to generate:

```bash
openssl rand -hex 32
```

- Required for: Phase 1 and DB-backed apps.

### REDIS_PASSWORD
- Purpose: central Redis password.
- How to generate:

```bash
openssl rand -hex 32
```

- Required for: Phase 1 and Redis-backed apps.

## Authentik (Phase 1)

### AUTHENTIK_SECRET_KEY
- Purpose: cryptographic signing key for Authentik.
- How to generate:

```bash
openssl rand -base64 60 | tr -d '\n'
```

- Required for: Phase 1.

### AUTHENTIK_ADMIN_EMAIL
- Purpose: initial admin email.
- How to choose: a valid inbox you own.
- Example: `admin@example.com`
- Required for: Phase 1.

## Beszel and Notifications (Phase 1)

### BESZEL_KEY
- Purpose: agent enrollment key for Beszel.
- How to get it:
1. Start Phase 1.
2. Open Beszel Hub UI.
3. Generate/copy agent key.
4. Paste into `.env`, then restart beszel-agent.

- Required for: Beszel agent.

### NTFY_TOPIC
- Purpose: topic channel for Watchtower notifications.
- How to choose: any simple string.
- Example: `watchtower`

### NTFY_URL
- Purpose: ntfy server URL used internally by containers.
- Default: `http://ntfy:80`
- Change only if ntfy runs elsewhere.

## VPN and qBittorrent (Phase 2)

### VPN_SERVICE_PROVIDER
- Purpose: tells Gluetun which provider profile to use.
- How to get it: provider name from Gluetun docs.
- Example: `mullvad`, `nordvpn`.

### VPN_TYPE
- Purpose: connection protocol.
- Allowed: `wireguard` or `openvpn`.

### WIREGUARD_PRIVATE_KEY
- Purpose: VPN tunnel private key.
- How to get it: generated in VPN provider dashboard/client.

### WIREGUARD_ADDRESSES
- Purpose: assigned tunnel IP/CIDR from provider.
- Example: `10.x.x.x/32`

### SERVER_COUNTRIES
- Purpose: preferred VPN exit location.
- Example: `Netherlands`, `United States`.

Note:
- Exact variable names differ by provider and protocol. Validate against Gluetun provider docs before first run.

## Immich (Phase 2)

### IMMICH_DB_PASSWORD
- Purpose: password for Immich dedicated PostgreSQL.
- How to generate:

```bash
openssl rand -hex 32
```

### IMMICH_DB_USERNAME
- Purpose: Immich DB username.
- Default: `immich`

### IMMICH_DB_DATABASE_NAME
- Purpose: Immich database name.
- Default: `immich`

## n8n (Phase 3)

### N8N_ENCRYPTION_KEY
- Purpose: encrypts n8n credentials and sensitive workflow data.
- How to generate:

```bash
openssl rand -hex 32
```

### N8N_USER_MANAGEMENT_JWT_SECRET
- Purpose: signs auth tokens in n8n user management.
- How to generate:

```bash
openssl rand -hex 32
```

## Minecraft (Phase 3)

### MINECRAFT_EULA
- Purpose: confirms Mojang EULA acceptance.
- Value: must be `TRUE` to start server.

### MINECRAFT_MEMORY
- Purpose: JVM memory assignment for server.
- Suggested on 16GB host: `2G` to `4G`.

### MINECRAFT_OPS
- Purpose: comma-separated operator usernames.
- Example: `YourMinecraftUsername`

### MINECRAFT_VERSION
- Purpose: game version selector.
- Example: `LATEST`, `1.20.1`.

### MINECRAFT_TYPE
- Purpose: server type.
- Example: `FORGE`, `FABRIC`, `VANILLA`, `PAPER`.

## Nextcloud (Phase 4 On-Demand)

### NEXTCLOUD_ADMIN_USER
- Purpose: initial admin account.

### NEXTCLOUD_ADMIN_PASSWORD
- Purpose: initial admin password.
- How to generate: `openssl rand -base64 24 | tr -d '\n'`

### NEXTCLOUD_TRUSTED_DOMAINS
- Purpose: allowed hostnames.
- Example: `cloud.example.com`

## Gitea (Phase 4 On-Demand)

### GITEA_ADMIN_USER
- Purpose: initial admin username.

### GITEA_ADMIN_PASSWORD
- Purpose: initial admin password.

### GITEA_ADMIN_EMAIL
- Purpose: admin email.

### GITEA_SECRET_KEY
- Purpose: cryptographic secret for Gitea internals.
- How to generate: `openssl rand -hex 32`

### GITEA_INTERNAL_TOKEN
- Purpose: internal service token in Gitea.
- How to generate: `openssl rand -hex 32`

## Docmost/Outline Secrets (Phase 4 On-Demand)

### OUTLINE_SECRET_KEY
- Purpose: app secret used by Docmost/Outline-style services.
- How to generate: `openssl rand -hex 32`

### OUTLINE_UTILS_SECRET
- Purpose: secondary utility/session secret.
- How to generate: `openssl rand -hex 32`

## Cal.com (Phase 4 On-Demand)

### CALCOM_NEXTAUTH_SECRET
- Purpose: NextAuth signing secret.
- How to generate: `openssl rand -base64 32 | tr -d '\n'`

### CALCOM_CALENDSO_ENCRYPTION_KEY
- Purpose: encryption key for sensitive Cal.com data.
- How to generate: `openssl rand -base64 32 | tr -d '\n'`

### CALCOM_EMAIL_FROM
- Purpose: outbound email sender identity.
- Example: `noreply@example.com`

## Supabase (Phase 4 On-Demand)

### SUPABASE_POSTGRES_PASSWORD
- Purpose: Supabase Postgres password.
- How to generate: `openssl rand -hex 32`

### SUPABASE_JWT_SECRET
- Purpose: signing root secret for Supabase JWTs.
- How to generate:

```bash
openssl rand -base64 48 | tr -d '\n'
```

### SUPABASE_ANON_KEY
- Purpose: public anon API key derived from JWT setup.
- How to get it:
1. Use official Supabase self-hosting docs.
2. Generate project JWT keys from your `SUPABASE_JWT_SECRET`.
3. Paste generated anon key.

### SUPABASE_SERVICE_ROLE_KEY
- Purpose: privileged server API key derived from JWT setup.
- How to get it:
1. Use official Supabase self-hosting docs key generation flow.
2. Paste generated service role key.

Important:
- For full Supabase, follow their official docker repo and env generation process. The placeholders exist so this monorepo remains compatible with that migration path.

## NocoDB (Phase 4 On-Demand)

### NOCODB_SECRET
- Purpose: JWT/signing secret for NocoDB auth.
- How to generate: `openssl rand -hex 32`

## Validation Checklist Before Bring-Up

```bash
# 1) Ensure no placeholder values remain
grep -n 'CHANGEME' .env

# 2) Validate compose rendering
for p in phase1-core phase2-media phase3-ai-gaming phase4-ondemand; do
  docker compose --env-file .env -f "$p/docker-compose.yml" config >/dev/null || break
done

# 3) Confirm data path exists
[ -d "$(grep '^DATA_PATH=' .env | cut -d= -f2-)" ] && echo OK || echo MISSING
```
