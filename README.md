# Homelab Ground Zero Rebuild Guide

This repository is a full phased Docker Compose architecture tuned for **16GB RAM first**, with clear expansion paths when you upgrade to 48GB.

Design priorities:
- Keep foundational services always-on.
- Keep heavy workloads off by default.
- Centralize databases/caches where practical to reduce memory overhead.
- Enforce sane host permissions to avoid `EACCES` headaches.

## 1. Directory Structure (NVMe)

The stack assumes `DATA_PATH=/mnt/nvme/homelab2` (set in `.env`).

```text
/mnt/nvme/homelab2/
├── phase1-core/
│   └── data/
│       ├── postgres/
│       ├── redis/
│       ├── portainer/
│       ├── npm/{data,letsencrypt}/
│       ├── authentik/{media,certs,custom-templates}/
│       ├── homepage/
│       ├── beszel/{hub,agent}/
│       ├── uptime-kuma/
│       ├── scrutiny/
│       ├── vaultwarden/
│       └── ntfy/{cache,etc}/
├── phase2-media/
│   └── data/
│       ├── jellyfin/{config,cache}/
│       ├── audiobookshelf/{config,metadata}/
│       ├── navidrome/{data,cache}/
│       ├── paperless/{data,media,export,consume}/
│       ├── immich/{upload,db,ml-cache}/
│       ├── prowlarr/
│       ├── bazarr/
│       └── qbittorrent/config/
├── phase3-ai-gaming/
│   └── data/
│       ├── ollama/
│       ├── openwebui/
│       ├── minecraft/
│       ├── n8n/
│       ├── homeassistant/
│       ├── spoolman/
│       └── actual/
├── phase4-ondemand/
│   └── data/
│       ├── kasm/{profiles}/
│       ├── guacamole/
│       ├── nextcloud/{html,data}/
│       ├── gitea/
│       ├── supabase/
│       ├── kiwix/library/
│       ├── docmost/
│       ├── calcom/
│       └── nocodb/
└── shared/
    ├── media/{movies,tv,music,audiobooks,podcasts,books}/
    └── downloads/{complete,incomplete}/
```

## 2. What Is In This Repo

- `phase1-core/docker-compose.yml`
  - Portainer, Nginx Proxy Manager, Authentik, Homepage, Beszel, Uptime Kuma,
    Watchtower, Scrutiny, Vaultwarden, ntfy
  - Central PostgreSQL + Redis
- `phase1-core/init-db/01-create-databases.sql`
  - Creates shared DBs for downstream services
- `phase2-media/docker-compose.yml`
  - Jellyfin, Audiobookshelf, Navidrome, Paperless, Immich (+ML), Prowlarr, Bazarr
  - Gluetun + qBittorrent are gated behind the `torrent` Compose profile
- `phase3-ai-gaming/docker-compose.yml`
  - Ollama (+NVIDIA), Open WebUI, Minecraft, n8n, Home Assistant, Spoolman,
    Actual, Stirling PDF, IT-Tools
- `phase4-ondemand/docker-compose.yml`
  - Kasm, Guacamole, Nextcloud, Gitea, Supabase Studio, Kiwix, Docmost, Cal.com, NocoDB
  - All services `restart: "no"` for memory protection
- `scripts/setup.sh`
  - One-time bootstrap: dependency checks, directories, networks, ownership
- `scripts/toggle-ondemand.sh`
  - Fast wake/sleep/status controls for Phase 4
- `.env.example`
  - Complete variable template

## 3. Prerequisites

1. Linux host with Docker Engine + Docker Compose plugin.
2. DNS records for your domain/subdomains.
3. Tailscale installed on host (recommended host-level).
4. NVIDIA driver + toolkit for Ollama GPU acceleration.

NVIDIA toolkit:
- https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html

## 4. First-Time Setup

1. Clone repo and enter it.
2. Run bootstrap:

```bash
bash scripts/setup.sh
```

3. Copy and edit env file if not already created:

```bash
cp .env.example .env
```

4. Fill **all** `CHANGEME_*` values in `.env`.

5. Use the full variable-by-variable guide:

- [ENV_REFERENCE.md](ENV_REFERENCE.md)

## 5. Phased Rollout Plan

### Phase 1: Core Foundation (must come first)

```bash
cd phase1-core
docker compose --env-file ../.env up -d
```

Do immediately after start:
1. Open Homepage and confirm auto-discovered tiles appear.
2. Open Authentik and complete initial setup.
3. Add Beszel key + token to `.env` (`BESZEL_KEY`, `BESZEL_TOKEN`) and restart `beszel-agent`.
4. Create Uptime Kuma admin and seed monitors with `scripts/seed_uptime_kuma.py`.

### Phase 2: Media and Documents

```bash
cd ../phase2-media
docker compose --env-file ../.env up -d
```

Critical checks:
1. Confirm Navidrome is reachable on port `4533` and scans `/shared/media/music`.
2. Validate Audiobookshelf on port `13378`.
3. Validate Paperless ingestion from `consume` directory.
4. Validate Immich upload + machine learning indexing.
5. Validate Prowlarr on port `9696`.
6. Validate Bazarr on port `6767`.
7. Start the torrent stack only when needed with `docker compose --env-file ../.env --profile torrent up -d`.
8. If qBittorrent is enabled, verify the public IP matches the VPN endpoint, not the ISP IP.

Phase 2 access URLs:
- `http://<tailnet-host>:8096` -> Jellyfin
- `http://<tailnet-host>:13378` -> Audiobookshelf
- `http://<tailnet-host>:4533` -> Navidrome
- `http://<tailnet-host>:8000` -> Paperless-ngx
- `http://<tailnet-host>:2283` -> Immich
- `http://<tailnet-host>:9696` -> Prowlarr
- `http://<tailnet-host>:6767` -> Bazarr

### Phase 3: AI, Gaming, Utility

```bash
cd ../phase3-ai-gaming
docker compose --env-file ../.env up -d
```

Critical checks:
1. For Ollama GPU path, run `docker exec -it ollama nvidia-smi`.
2. Point Open WebUI to `http://ollama:11434` (already prewired).
3. Tune Minecraft memory (`MINECRAFT_MEMORY`) to avoid host swapping.
4. Confirm n8n can connect to central Postgres (`n8n` database).
5. For direct HTTP access to n8n, keep `N8N_PROTOCOL=http` and `N8N_SECURE_COOKIE=false`.
6. Validate Spoolman responds on host port `7912` (container listens on `8000`).
7. Validate Stirling PDF on port `8086`.
8. Validate IT-Tools on port `8087`.

Phase 3 access URLs:
- `http://<tailnet-host>:8080` -> Open WebUI
- `http://<tailnet-host>:5678` -> n8n
- `http://<tailnet-host>:8123` -> Home Assistant
- `http://<tailnet-host>:7912` -> Spoolman
- `http://<tailnet-host>:5006` -> Actual Budget
- `http://<tailnet-host>:8086` -> Stirling PDF
- `http://<tailnet-host>:8087` -> IT-Tools

### Phase 4: On-Demand Heavy Stack

Do **not** keep this up full-time on 16GB RAM.

```bash
cd ../phase4-ondemand
docker compose --env-file ../.env up -d
```

Or use the helper:

```bash
./scripts/toggle-ondemand.sh up
./scripts/toggle-ondemand.sh down
./scripts/toggle-ondemand.sh status
```

## 6. Access and Identity Flow

Recommended path:
1. Tailscale connection on client device
2. Direct service access via `http://<tailnet-host>:<port>`
3. Homepage as the launcher for all service links
4. Authentik as identity provider for services that support SSO

Tailscale note:
- Keep Tailscale at host level.
- For admin surfaces, prefer Tailscale ACL restrictions.

## 7. Permissions Model (UID/GID 1000)

Your stack is built around:
- `PUID=1000`
- `PGID=1000`

Why:
- Prevents service write failures on bind mounts.
- Keeps ownership consistent for app data.

If you changed host user IDs, update `.env` and re-run ownership fix:

```bash
sudo chown -R <uid>:<gid> /mnt/nvme/homelab
```

## 8. Database Consolidation Strategy

Central Postgres (`phase1-core`) holds:
- `authentik`, `paperless`, `n8n`, `gitea`, `nextcloud`, `outline`, `calcom`, `nocodb`, `guacamole`

Central Redis (`phase1-core`) backs:
- Authentik, Paperless, Docmost (and optionally more)

Exception:
- Immich uses a dedicated Postgres image because it requires vector extension support that the shared central Postgres does not provide by default.

## 9. Memory-Protect Defaults (16GB)

- Phase 4 services: all `restart: "no"`.
- Keep only Phase 1-3 up by default.
- If memory pressure occurs:
  - Stop `immich_ml` temporarily.
  - Lower Minecraft memory.
  - Limit loaded Ollama model sizes.

Quick memory watch:

```bash
docker stats --no-stream
free -h
```

## 10. Daily Operations

Update images safely:
- Watchtower updates only containers explicitly labeled with `com.centurylinklabs.watchtower.enable=true`.

Backups (minimum):
1. PostgreSQL dumps.
2. `${DATA_PATH}` bind-mounted app data.
3. `.env` secret file in secure vault.

## 11. Important One-Time Initializations

### Guacamole DB schema

```bash
docker run --rm guacamole/guacamole /opt/guacamole/bin/initdb.sh --postgresql > /tmp/guacamole-initdb.sql
docker exec -i homelab_postgres psql -U homelab -d guacamole < /tmp/guacamole-initdb.sql
```

### Homepage discovery hardening

1. Keep Homepage Docker socket mount read-only.
2. Keep Homepage running with docker socket group access (`group_add`) and root PUID/PGID.

## 12. Service URLs (current Phase 1)

- `http://<tailnet-host>:3000` -> Homepage
- `http://<tailnet-host>:9001` -> Authentik
- `http://<tailnet-host>:3001` -> Uptime Kuma
- `http://<tailnet-host>:9000` -> Portainer
- `http://<tailnet-host>:81` -> Nginx Proxy Manager UI
- `https://<tailnet-host>:4443` -> Vaultwarden via NPM TLS endpoint
- `http://<tailnet-host>:8089` -> Scrutiny

## 13. Service URLs (current Phase 3)

- `http://<tailnet-host>:8080` -> Open WebUI
- `http://<tailnet-host>:5678` -> n8n
- `http://<tailnet-host>:8123` -> Home Assistant
- `http://<tailnet-host>:7912` -> Spoolman
- `http://<tailnet-host>:5006` -> Actual Budget
- `http://<tailnet-host>:8086` -> Stirling PDF
- `http://<tailnet-host>:8087` -> IT-Tools
- `http://<tailnet-host>:8090` -> Beszel Hub
- `http://<tailnet-host>:8085` -> ntfy

## 13. If Something Breaks

Use:
- `AI_CONTEXT.md` for fast troubleshooting prompts and context handoff.
- `scripts/toggle-ondemand.sh logs <service>` for immediate diagnostics.

