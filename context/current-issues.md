# Current Issues

Only list issues verified against the repo or the running homelab. Remove entries once fixed.

## Known Issues
- None recorded yet.

## Technical Debt
- Some images still use `:latest` (e.g. Authentik, Pi-hole, Portainer, Beszel in `phase1-core/docker-compose.yml`; more in phases 2-5). Pin them to specific versions.
- ~27 small one-off arr/qBittorrent/SSO setup scripts in `scripts/` overlap and could be consolidated.

## Notes
- Reverse proxy is Nginx Proxy Manager (`phase1-core`), not Traefik.
- SSO is Authentik; uptime monitoring is Uptime Kuma; metrics are Prometheus + Grafana + Loki.
