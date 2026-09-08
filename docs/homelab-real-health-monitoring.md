# Homelab Real Health Monitoring

`scripts/homelab_real_health.py` writes Prometheus textfile metrics for checks that are hard to express with a simple HTTP monitor.

It checks:

- Docker unhealthy, restarting, exited, and starting containers.
- Free space on `/`, `${DATA_PATH}`, and `/var/lib/docker`.
- Service-specific readiness probes.
- Authentik HTTPS edge ports.
- qBittorrent/gluetun VPN containment.
- Tailscale HTTPS certificate validity and days remaining.
- Backup target presence/readability and existing backup-job metrics.

Metrics are written to:

```text
${DATA_PATH}/phase1-core/data/node-exporter/textfile_collector/homelab_real_health.prom
${DATA_PATH}/phase1-core/data/node-exporter/textfile_collector/homelab_real_health.json
```

Start or refresh the Docker collector on the server:

```bash
cd ~/homelab2
docker compose --env-file .env -f phase1-core/docker-compose.yml up -d --build homelab-real-health
```

Run once by hand:

```bash
python3 scripts/homelab_real_health.py --repo ~/homelab2 --env-file ~/homelab2/.env
```

The collector mounts backup storage read-only by design. Its
`homelab_backup_target_configured` metric means that the expected target exists
and is readable; it does not assert that this collector can write backups.
Backup success and verification alerts remain the responsibility of the backup
job's own metrics, so an intentionally absent backup disk does not create a
permanent alert.
