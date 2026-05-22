# Homelab Ground Zero Rebuild Guide

This repository is a full phased Docker Compose architecture tuned for **16GB RAM first**, with clear expansion paths when you upgrade to 48GB.

Design priorities:
- Keep foundational services always-on.
- Keep heavy workloads off by default.
- Centralize databases/caches where practical to reduce memory overhead.
- Enforce sane host permissions to avoid `EACCES` headaches.

## 1. Directory Structure (NVMe)

The stack assumes `DATA_PATH=/mnt/nvme/homelab` (set in `.env`).

```text
/mnt/nvme/homelab/
├── phase1-core/
│   └── data/
│       ├── postgres/
│       ├── redis/
│       ├── portainer/
│       ├── npm/{data,letsencrypt}/
│       ├── authentik/{media,certs,custom-templates}/
│       ├── homepage/
│       ├── beszel/hub/
│       ├── uptime-kuma/
│       └── ntfy/{cache,etc}/
├── phase2-media/
│   └── data/
│       ├── jellyfin/{config,cache}/
│       ├── audiobookshelf/{config,metadata}/
│       ├── paperless/{data,media,export,consume}/
│       ├── immich/{upload,db,ml-cache}/
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
  - Portainer, NPM, Authentik, Homepage, Beszel, Uptime Kuma, Watchtower, ntfy
  - Central PostgreSQL + Redis
- `phase1-core/init-db/01-create-databases.sql`
  - Creates shared DBs for downstream services
- `phase2-media/docker-compose.yml`
  - Jellyfin, Audiobookshelf, Paperless, Immich (+ML), Gluetun + qBittorrent
- `phase3-ai-gaming/docker-compose.yml`
  - Ollama (+NVIDIA), Open WebUI, Minecraft, n8n, Home Assistant, Spoolman, Actual
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
1. Open Nginx Proxy Manager admin at `http://localhost:81`.
2. Change default credentials.
3. Create SSL certs and proxy hosts.
4. Open Authentik and complete initial setup.
5. Add Beszel agent key to `.env` (`BESZEL_KEY`) and restart `beszel-agent`.

### Phase 2: Media and Documents

```bash
cd ../phase2-media
docker compose --env-file ../.env up -d
```

Critical checks:
1. Confirm `qbittorrent` is attached via `network_mode: service:gluetun`.
2. In qBittorrent, verify public IP matches VPN endpoint (not ISP IP).
3. Validate Paperless ingestion from `consume` directory.
4. Validate Immich upload + machine learning indexing.

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

## 6. Proxy and Identity Flow

Recommended path:
1. Public DNS -> NPM
2. NPM forward auth / Authentik outpost for protected apps
3. App container on `homelab_proxy`
4. Internal dependencies on `homelab_internal`

Tailscale note:
- Keep Tailscale at host level.
- For admin surfaces, prefer Tailscale ACL + NPM access restrictions.

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
- Immich uses a dedicated Postgres image due to required extension compatibility.

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

### NPM hardening

1. Bind port 81 to localhost only (already configured).
2. Restrict access through firewall/Tailscale.

## 12. Service URLs (suggested)

- `https://home.<domain>` -> Homepage
- `https://auth.<domain>` -> Authentik
- `https://status.<domain>` -> Uptime Kuma
- `https://portainer.<domain>` -> Portainer
- `https://jellyfin.<domain>` -> Jellyfin
- `https://paperless.<domain>` -> Paperless
- `https://photos.<domain>` -> Immich
- `https://ai.<domain>` -> Open WebUI
- `https://n8n.<domain>` -> n8n
- `https://ha.<domain>` -> Home Assistant (if proxied)
- `https://cloud.<domain>` -> Nextcloud (on-demand)
- `https://git.<domain>` -> Gitea (on-demand)

## 13. If Something Breaks

Use:
- `AI_CONTEXT.md` for fast troubleshooting prompts and context handoff.
- `scripts/toggle-ondemand.sh logs <service>` for immediate diagnostics.

