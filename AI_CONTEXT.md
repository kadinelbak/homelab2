# AI Troubleshooting Context – Homelab2

Use this file when asking an AI assistant for help. Paste relevant sections so the assistant gets accurate context immediately.

## 1. Environment Snapshot

- Host OS: Linux
- GPU: NVIDIA RTX 3050
- RAM: 16GB currently (planned 48GB)
- Orchestration: Docker Compose, phased stacks
- Repo layout:
  - `phase1-core/`
  - `phase2-media/`
  - `phase3-ai-gaming/`
  - `phase4-ondemand/`
  - `scripts/`
- Data root: `${DATA_PATH}` from `.env` (default `/mnt/nvme/homelab`)
- User mapping: `PUID=1000`, `PGID=1000`

## 2. Architecture Rules (Important)

1. Heavy services in Phase 4 are on-demand only and set to `restart: "no"`.
2. qBittorrent must stay behind Gluetun with `network_mode: service:gluetun`.
3. Ollama must use NVIDIA deployment block for GPU access.
4. Central Postgres + Redis live in Phase 1 and are reused by many services.
5. `homelab_proxy` and `homelab_internal` Docker networks must exist.

## 3. Common Commands

### Start stacks

```bash
cd phase1-core && docker compose --env-file ../.env up -d
cd phase2-media && docker compose --env-file ../.env up -d
cd phase3-ai-gaming && docker compose --env-file ../.env up -d
```

### On-demand controls

```bash
./scripts/toggle-ondemand.sh up
./scripts/toggle-ondemand.sh down
./scripts/toggle-ondemand.sh status
./scripts/toggle-ondemand.sh logs <service>
```

### Diagnostics

```bash
docker ps -a
docker stats --no-stream
free -h
docker network ls
docker compose --env-file .env -f phase1-core/docker-compose.yml config
```

## 4. High-Value Debug Checklist

1. Is `.env` complete (no `CHANGEME` values left)?
2. Are both Docker networks present?
3. Is Phase 1 healthy before Phase 2/3/4 start?
4. Do bind mounts exist and have UID/GID ownership?
5. For auth/database apps, can containers resolve `homelab_postgres` and `homelab_redis`?
6. For GPU issues, does `nvidia-smi` work on host and in container?

## 5. Frequent Failure Patterns and Fixes

### `EACCES: permission denied`

Cause:
- Host directory owner mismatch.

Fix:

```bash
sudo chown -R 1000:1000 /mnt/nvme/homelab
```

Then restart affected service.

### `connection refused` to Postgres/Redis

Cause:
- Phase 1 not running or service not on `homelab_internal` network.

Fix:
1. Check `docker ps` for `homelab_postgres` and `homelab_redis`.
2. Check service networks in compose.
3. Verify env credentials and DB name.

### qBittorrent IP leak concern

Validation:
1. Ensure `network_mode: service:gluetun` remains unchanged.
2. Check Gluetun logs for VPN established tunnel.
3. Validate qBittorrent visible IP via torrent IP-check tool.

### Ollama not using GPU

Checks:
1. Host: `nvidia-smi`
2. Toolkit install test:

```bash
docker run --rm --gpus all nvidia/cuda:12.0-base-ubuntu22.04 nvidia-smi
```

3. Confirm `deploy.resources.reservations.devices` block is present for Ollama.

### NPM proxy host not reachable

Checks:
1. DNS record points to host.
2. Ports 80/443 reachable.
3. Target container is on `homelab_proxy` network.
4. Upstream/forward host uses container name and internal port.

## 6. What to Provide an AI Assistant

When asking for troubleshooting, always include:
1. Exact command run.
2. Exact error log lines.
3. Relevant compose section for failing service.
4. Output of:

```bash
docker ps -a
docker logs --tail=200 <container>
docker inspect <container> --format '{{json .NetworkSettings.Networks}}'
```

5. Any recent changes to `.env` or compose files.

## 7. Prompt Template for Debugging

```text
I am debugging a Docker homelab stack on Linux.
Service failing: <service>
Phase file: <phaseX>/docker-compose.yml
Recent change: <what changed>
Error:
<full error text>

Diagnostics:
<docker ps -a>
<docker logs --tail=200 service>
<network inspect / compose snippet>

Please provide:
1) root cause,
2) exact minimal fix,
3) validation commands.
```

## 8. Safety Notes

- Do not run destructive Docker cleanup (`docker system prune -a --volumes`) unless you have backups.
- Do not expose admin UIs publicly without auth restrictions.
- Keep `.env` out of git.
