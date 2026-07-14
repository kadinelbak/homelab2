# Infrastructure as Code & Zero-Touch Setup Feature Spec

## Overview
Transform the homelab deployment into a fully reproducible, zero-touch infrastructure-as-code (IaC) experience. After cloning the repo and running a single bootstrap script, all services should be running with sensible defaults, pre-configured users/passwords (stored securely in Vaultwarden or .env), and integrated monitoring (from spec 01) already connected. The user should not need to manually click through dashboards to create datasources, dashboards, or users.

## Core Principles
1. **One Command Deploy**: `./scripts/bootstrap.sh` (or `make deploy`) clones repo, generates secrets, creates directories, starts all phases.
2. **Secrets Management**: Auto-generate strong passwords, store them in `.env` and also seed Vaultwarden for later retrieval.
3. **Pre-configured Services**: Grafana datasources, dashboards, alerting rules; Prometheus scrape configs; Loki/Promtail configs; n8n credentials; etc., are applied on first start via init containers, entrypoint scripts, or post-deploy hooks.
4. **Immutable Configuration**: All service configuration lives in the repo (under `config/` or `*/init/`). No runtime changes outside of version control.
5. **Self-Documenting**: Post-deploy, a n8n workflow updates README.md with service status, default credentials (if safe), and links to Grafana dashboards.

## Components Affected
- **phase1-core**: postgres, redis, portainer, npm, authentik, homepage, beszel, uptime-kuma, scrutiny, vaultwarden, ntfy, plus monitoring stack (prometheus, grafana, loki, alertmanager, node-exporter, cadvisor).
- **phase2-media**: jellyfin, audiobookshelf, navidrome, paperless, immich, prowlarr, bazarr, gluetun/qbittorrent.
- **phase3-ai-gaming**: ollama, open-webui, minecraft, n8n, homeassistant, spoolman, actual, stirling-pdf, it-tools, hearts-mp.
- **phase4-ondemand**: kasm, guacamole, nextcloud, gitea, supabase, kiwix, docmost, cal.com, nocodb.
- **Scripts**: bootstrap, update, backup, deploy-monitoring, deploy-wol, etc.

## Implementation Plan (Single AI Execution - Focus on Bootstrapping & Pre‑Configuration)

### Phase 1: Repository Structure for IaC
Create the following directories (if not existing):
```
config/
  grafana/
    provisioning/
      datasources/
      dashboards/
      alerting/
  prometheus/
    rules/
    file_sd/
  loki/
  promtail/
  n8n/
    credentials/
  authentik/
    init/
  vaultwarden/
    admin/
scripts/
  bootstrap.sh
  generate-secrets.sh
  init-services.sh
  post-deploy.sh
```

### Phase 2: Secret Generation & Seeding
1. **generate-secrets.sh**:
   - Generate random strings for:
     - POSTGRES_PASSWORD, POSTGRES_USER (default: homelab)
     - REDIS_PASSWORD
     - AUTHENTIK_SECRET_KEY
     - VAULTWARDEN_ADMIN_TOKEN
     - NUT_PASSWORD
     - BESZEL_KEY, BESZEL_TOKEN
     - GRAFANA_ADMIN_PASSWORD (default admin user: admin)
     - N8N_BASIC_AUTH_USER, N8N_BASIC_AUTH_PASSWORD
     - ANY other service requiring secrets (e.g., JWT tokens)
   - Write to `.env` (with export statements) and also to a temporary file for seeding.
   - Optionally output a QR code or print to console (with warning to store securely).

2. **Seed Vaultwarden**:
   - After vaultwarden container starts, run a one‑time init container (or use `post-deploy.sh`) that:
     - Uses the vaultwarden CLI (`vaultwarden-cli`) or direct API to create an admin user (if not exists) using the generated ADMIN_TOKEN.
     - Create a folder “Homelab Secrets” and insert login entries for each service (username/password) as secure notes.
   - This makes secrets available via the Vaultwarden UI or API for the user.

### Phase 3: Pre‑Configure Grafana (via Provisioning)
All Grafana config is declarative via files under `config/grafana/provisioning/`.

- **datasources/datasource.yml**:
  ```yaml
  apiVersion: 1
  datasources:
    - name: Prometheus
      type: prometheus
      url: http://homelab_prometheus:9090
      access: proxy
      isDefault: true
      editable: false
    - name: Loki
      type: loki
      url: http://homelab_loki:3100
      access: proxy
      isDefault: false
      editable: false
    - name: VictoriaMetrics (optional)
      ...
  ```
- **dashboards/dashboard.yml**:
  ```yaml
  apiVersion: 1
  providers:
    - name: 'default'
      orgId: 1
      folder: ''
      type: file
      disableDeletion: false
      updateIntervalSeconds: 10
      allowUiUpdates: false
      options:
        path: /var/lib/grafana/dashboards
  ```
  - Provide JSON dashboards under `config/grafana/provisioning/dashboards/`:
    - `homelab-overview.json` (imported from community or custom)
    - `node-exporter-full.json`
    - `docker-monitoring.json`
    - `service-health-summary.json`
- **alerting/alert_rules.yml** (optional, if using Grafana managed alerting):
  - Import rules from Prometheus or define Grafana‑managed alerts.

These files are mounted into the grafana container:
```yaml
grafana:
  image: grafana/grafana:latest
  ...
  volumes:
    - ${DATA_PATH}/phase1-core/data/grafana:/var/lib/grafana
    - ./config/grafana/provisioning:/etc/grafana/provisioning:ro
```

On first start, Grafana automatically provisions the datasources, dashboards (read‑only), and alert rules. The admin user/password comes from environment variables:
```yaml
environment:
  - GF_SECURITY_ADMIN_USER=${GF_SECURITY_ADMIN_USER:-admin}
  - GF_SECURITY_ADMIN_PASSWORD=${GF_SECURITY_ADMIN_PASSWORD}
```

### Phase 4: Pre‑Configure Prometheus & Alertmanager
- **Prometheus**:
  - `config/prometheus/prometheus.yml` includes:
    - `scrape_configs` for node-exporter, cadvisor, each service that exposes metrics (via annotations or fixed targets).
    - `rule_files: [ "/etc/prometheus/rules/*.yml" ]`
  - Mount `config/prometheus/rules/` with pre‑made alert rules (e.g., high CPU, disk space, service down via blackbox if added).
- **Alertmanager**:
  - `config/alertmanager/config.yml` with receivers:
    - email (using SMTP credentials from .env)
    - n8n webhook (http://n8n:5678/webhook/alert)
    - mattermost/telegram (if configured)
  - Inhibition rules to silence notifications when a parent alert is firing.

Both containers mount their config as read‑only.

### Phase 5: Loki & Promtail
- **Loki**:
  - Simple local filesystem config under `config/loki/loki-config.yaml`.
- **Promtail**:
  - `config/promtail/config.yaml` scrapes:
    - Docker container logs (via `/var/lib/docker/containers/*/*.log`)
    - System logs (`/var/log/*.log`)
    - Uses Docker labels to auto‑add `job`, `service`, `hostname`.
  - Mount as read‑only.

### Phase 6: n8n Pre‑Setup
- **Credentials**: Use n8n’s built‑in credentials mechanism via environment variables or pre‑load via `config/n8n/credentials/`.
  - Set basic auth: `N8N_BASIC_AUTH_ACTIVE=true`, `N8N_BASIC_AUTH_USER=`, `N8N_BASIC_AUTH_PASSWORD=`.
  - Optionally pre‑create API keys or OAuth credentials via the n8n API in a post‑deploy script.
- **Default Workflow**: Include a sample workflow (e.g., “Alert Enrichment”) in `config/n8n/workflows/` that gets imported on first start via the n8n API (post‑deploy script).

### Phase 7: Post‑Deploy Automation Script (`scripts/post-deploy.sh`)
After `docker compose up -d` for each phase, run:
1. **Wait for services to be healthy** (using `docker compose ps` or `curl` loops).
2. **Seed Vaultwarden** (as described).
3. **Initialize Authentik** (if needed): create default admin user, application, provider using authentik‑go CLI or API calls.
4. **Trigger n8n workflow import** (post to `/api/v1/workflows/import`).
5. **Update README.md**: Generate a status table with service URLs, default credentials (only non‑sensitive ones like Grafana admin if you want to show), and links to Grafana dashboards.
6. **Optional**: Run a health check script that outputs success/failure.

### Phase 8: Bootstrap Script (`scripts/bootstrap.sh`)
Orchestrates everything:
```bash
#!/usr/bin/env echo "Do not source this script; run with ./bootstrap.sh"
set -euo pipefail

# 1. Clone repo (if not already)
# 2. Copy .env.example -> .env if missing
# 3. Run generate-secrets.sh to fill .env
# 4. Create required directories under $DATA_PATH
# 5. Fix permissions (chown -R $PUID:$PGID $DATA_PATH)
# 6. Start phase1-core (wait for healthy)
# 7. Run post-deploy for phase1 (seeds vaultwarden, etc.)
# 8. Start phase2-media
# 9. Start phase3-ai-gaming
#10. Offer to start phase4-ondemand via toggle-ondemand.sh
#11. Output final instructions and link to README
```

### Phase 9: Making It Reproducible
- All generated secrets are stored in `.env` (which should be git‑ignored) but can be backed up.
- The repo contains a `makefile` with targets:
  ```makefile
  up:           ## Start all phases (except on‑demand)
      ./scripts/bootstrap.sh

  up-all:       ## Include phase4
      ./scripts/bootstrap.sh && ./scripts/toggle-ondemand.sh up

  down:         ## Stop all phases
      docker compose --env-file .env -f phase1-core/docker-compose.yml -f phase2-media/docker-compose.yml -f phase3-ai-gaming/docker-compose.yml down
      ./scripts/toggle-ondemand.sh down

  backup:       ## Run backup scripts
      ./scripts/backup-all.sh

  update:       ## Pull latest images and recreate
      ./scripts/update-all.sh
  ```

### Success Criteria
- After `git clone` and `./scripts/bootstrap.sh` (with minimal edits to .env for domain, TZ, etc.), the user can:
  - Open `http://<host>:3000` (Homepage) and see tiles for all services.
  - Open Grafana (`http://<host>:30030` – adjust port) and login with admin/admin password (or the one generated) and immediately see pre‑populated dashboards and datasources.
  - Open Vaultwarden and find login entries for each service.
  - Open n8n and see credentials already configured and a sample workflow.
  - Receive alert emails/messages if any alert rules fire (based on realistic thresholds).
  - Have monitoring already scraping node‑exporter, cadvisor, and each service that exposes metrics.
- No manual steps required to connect Prometheus → Grafana, add Loki datasource, create dashboards, or set up admin users.

## Files to Create/Modify
```
context/feature-specs/03-infrastructure-as-code.md                (this file)
config/grafana/provisioning/datasources/datasource.yml
config/grafana/provisioning/dashboards/dashboard.yml
config/grafana/provisioning/dashboards/homelab-overview.json
config/grafana/provisioning/dashboards/node-exporter-full.json
config/grafana/provisioning/dashboards/docker-monitoring.json
config/grafana/provisioning/dashboards/service-health-summary.json
config/prometheus/prometheus.yml
config/prometheus/rules/*.yml
config/alertmanager/config.yml
config/loki/loki-config.yaml
config/promtail/config.yaml
config/n8n/credentials/basic-auth.env   (or similar)
config/n8n/workflows/alert-enrichment.json
scripts/bootstrap.sh
scripts/generate-secrets.sh
scripts/post-deploy.sh
scripts/update-all.sh
scripts/backup-all.sh
makefile (optional)
phase1-core/docker-compose.yml          (add volumes for config, env vars for admin passwords)
phase3-ai-gaming/docker-compose.yml     (ensure n8n env vars for basic auth)
```

### Dependencies
- Docker Compose v2+
- Ability to generate random passwords (`pwgen`, `openssl rand`, or `/dev/urandom`)
- Optional: `jq`, `yq` for manipulating JSON/YAML in scripts.
- For Vaultwarden seeding: either the official CLI or ability to call its HTTP API.
- For n8n workflow import: ability to POST to n8n API (requires API key or basic auth).
- Sufficient disk space under `$DATA_PATH`.

### Estimated Effort
Single AI execution to create the directory structure, write the bootstrap and secret generation scripts, add provisioning files for Grafana/Prometheus/Alertmanager/Loki/Promtail/n8n, and modify the relevant docker‑compose files to mount those configs and consume the generated secrets. Additional polishing (testing the end‑to‑end flow) may be required but the core IaC foundation is achievable in one go.