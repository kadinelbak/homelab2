# Homelab Template Reuse Guide

This repository is a reusable template for a phased, memory-aware homelab deployment.

Use this guide to adapt it for your own environment.

## 1. Copy and Rename

1. Fork or copy this repository.
2. Rename project folder and update branding/service hostnames.
3. Keep the same phase folder pattern unless you have a strong reason to change it.

## 2. Mandatory Customization

### Environment

Edit `.env`:
- `TZ`
- `DOMAIN`
- `DOCKER_HOST_IP`
- `DATA_PATH`
- all `CHANGEME_*` secrets
- VPN credentials
- app-specific admin credentials

### User/Permission IDs

Set to your host user:

```bash
id -u
id -g
```

Then place those values in `PUID` and `PGID`.

### Storage Paths

Ensure your storage mount exists and is stable across reboots.

Example `/etc/fstab` entry:

```fstab
UUID=<disk-uuid> /mnt/nvme ext4 defaults,nofail 0 2
```

## 3. Phase Model (Why It Matters)

- `phase1-core`: dependencies and control plane
- `phase2-media`: storage-heavy media stack
- `phase3-ai-gaming`: GPU/game/utility workloads
- `phase4-ondemand`: heavy services kept off by default

This model makes it easier to protect low-memory hosts and recover from failures quickly.

## 4. How to Add a New Service

1. Decide phase placement.
2. Add service to that phase compose file.
3. Attach to the correct network(s):
   - `homelab_proxy` if it needs reverse proxy access.
   - `homelab_internal` if it depends on internal DB/cache/services.
4. Add volume paths under `${DATA_PATH}`.
5. Add environment variables to `.env.example`.
6. If it needs SQL, add DB creation to `phase1-core/init-db/01-create-databases.sql`.
7. Add service URL to README operations section.

## 5. Database Rule of Thumb

Prefer central Postgres/Redis if compatible.

Use dedicated DB only when required by extensions, performance isolation, or vendor constraints (example: Immich Postgres variant).

## 6. Security Baseline for New Labs

1. Put all public access behind NPM.
2. Add Authentik/SSO for sensitive apps.
3. Restrict admin interfaces with Tailscale and/or firewall rules.
4. Never commit `.env`.
5. Rotate secrets after cloning template to a new environment.

## 7. Make It Your Own (Safe Edits)

Safe customizations:
- Add/remove services
- Adjust memory-sensitive env values
- Extend scripts with extra health checks
- Replace Docmost with Outline, Gitea with GitLab, etc.

Risky customizations (test carefully):
- Changing shared Docker network names
- Changing central DB credentials post-deploy
- Moving data paths without migration steps

## 8. Initial Bring-Up for a New User

```bash
cp .env.example .env
bash scripts/setup.sh
cd phase1-core && docker compose --env-file ../.env up -d
cd ../phase2-media && docker compose --env-file ../.env up -d
cd ../phase3-ai-gaming && docker compose --env-file ../.env up -d
```

On-demand stack:

```bash
./scripts/toggle-ondemand.sh up
./scripts/toggle-ondemand.sh down
```

## 9. Suggested Optional Enhancements

1. Add nightly DB backups with retention.
2. Add restic/borg backup to offsite storage.
3. Add monitoring alerts from Uptime Kuma to ntfy.
4. Add IaC wrappers (`make`, Taskfile, or Ansible).
5. Add CI linting for compose files.

## 10. Template Support Prompt

If handing this to another person, give them this prompt:

```text
Use TEMPLATE.md and README.md to adapt this phased homelab stack.
My environment:
- OS: <linux distro>
- RAM: <amount>
- GPU: <yes/no + model>
- Domain: <domain>
- Storage path: <path>

Please output:
1) updated .env values,
2) any required compose edits,
3) a safe rollout order with validation commands.
```
