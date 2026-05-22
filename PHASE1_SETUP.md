# Phase 1 Setup Guide – Core Infrastructure (Current)

This guide reflects the current working Phase 1 stack after troubleshooting fixes.

## Quick Start

```bash
cd phase1-core
docker compose --env-file ../.env up -d
```

## Current Access URLs

- Homepage: `http://kadin-main-sys.tail00cf0e.ts.net:3000`
- Portainer: `http://kadin-main-sys.tail00cf0e.ts.net:9000`
- Authentik: `http://kadin-main-sys.tail00cf0e.ts.net:9001`
- Uptime Kuma: `http://kadin-main-sys.tail00cf0e.ts.net:3001`
- Beszel Hub: `http://kadin-main-sys.tail00cf0e.ts.net:8090`
- ntfy: `http://kadin-main-sys.tail00cf0e.ts.net:8085`

## Setup Order (Fastest Path)

1. Open Authentik and create/verify admin login.
2. Open Portainer and create admin login.
3. Open Beszel Hub and add your system.
4. Open Uptime Kuma and create admin login.
5. Seed monitors automatically:
   ```bash
   cd ~/homelab2 && docker run --rm --network host -e DOMAIN='kadin-main-sys.tail00cf0e.ts.net' -e UPTIME_KUMA_PASSWORD='YOUR_KUMA_PASSWORD' -v "$PWD":/work -w /work python:3.12-slim sh -lc "pip install --quiet uptime-kuma-api && python scripts/seed_uptime_kuma.py --username 'YOUR_KUMA_USERNAME'"
   ```

## Important Fixes Applied (Time Savers)

1. Homepage auto-discovery fix:
   - Homepage must be able to read `/var/run/docker.sock`.
   - `homepage` now runs with:
     - `user: "0:0"`
     - `group_add: ["125"]` (docker socket group on this host)
     - `PUID: 0`, `PGID: 0`
   - If tiles disappear again, check Homepage logs first.

2. Beszel registration fix:
   - Beszel agent now uses env vars, not hardcoded values:
     - `BESZEL_KEY`
     - `BESZEL_TOKEN`
     - `BESZEL_HUB_URL` (defaults to `http://127.0.0.1:8090`)
   - This avoids 401 loops and makes key/token rotation simple.

3. Watchtower stability fix:
   - Removed invalid `WATCHTOWER_NOTIFICATIONS=apprise` setting.
   - Added `DOCKER_API_VERSION: "1.44"` to match host daemon.

4. Reverse proxy simplification:
   - NPM was removed from active Phase 1 flow.
   - Services are accessed directly over Tailscale + ports.

## Beszel: Exact Working Procedure

1. In Beszel Hub, add a new system.
2. Copy KEY and TOKEN.
3. Update `.env`:
   - `BESZEL_KEY=...`
   - `BESZEL_TOKEN=...`
   - `BESZEL_HUB_URL=http://127.0.0.1:8090`
4. Restart agent:
   ```bash
   cd ~/homelab2/phase1-core
   docker compose --env-file ../.env up -d beszel-agent
   docker compose --env-file ../.env logs --tail=50 beszel-agent
   ```
5. Success log looks like:
   - `WebSocket connected host=127.0.0.1:8090`

## Verification Checklist

```bash
cd ~/homelab2/phase1-core
docker compose --env-file ../.env ps
docker compose --env-file ../.env logs --tail=80 homepage beszel-agent watchtower
```

Expected:
- `homepage`: no `EACCES /var/run/docker.sock`
- `beszel-agent`: websocket connected (no repeated 401)
- `watchtower`: no fatal notification/API version errors

## Current Known Non-Blockers

- `CHANGEME` values still present in `.env` for later phases are okay during Phase 1.
- Only Phase 1 services need to be healthy right now.

## Next Steps After Phase 1

1. Backup `.env` and Phase 1 data directories.
2. Launch Phase 2 only after VPN keys are ready.
3. Keep using Homepage as the main launcher to avoid memorizing URLs/ports.

