# Homelab Integration Audit

This file tracks which parts of the homelab can be wired into centralized
monitoring, authentication, and service launch.

## Uptime Kuma

Use `scripts/seed_uptime_kuma.py` to create or update monitors.

Recommended run after creating the Uptime Kuma admin account:

```bash
cd ~/homelab2
docker run --rm --network host \
  -e DOMAIN='kadin-main-sys.tail00cf0e.ts.net' \
  -e UPTIME_KUMA_USERNAME='YOUR_KUMA_USERNAME' \
  -e UPTIME_KUMA_PASSWORD='YOUR_KUMA_PASSWORD' \
  -v "$PWD":/work -w /work python:3.12-slim \
  sh -lc "pip install --quiet uptime-kuma-api && python scripts/seed_uptime_kuma.py --update-existing --include-ondemand"
```

Phase 4 monitors are created paused because those services are intentionally
off most of the time.

## Authentik SSO Candidates

Native OAuth/OIDC or documented external authentication:

- Grafana: already has generic OAuth environment wiring.
- Portainer: supports OAuth configuration in the UI.
- Vaultwarden: supports OIDC/SSO in current releases, but still requires a
  master password.
- Gitea: supports OpenID Connect authentication sources.
- Nextcloud: can use an OIDC/social-login integration app.
- NocoDB: supports external auth in paid/enterprise-oriented configurations;
  verify current edition limits before relying on it.

Can be put behind Authentik forward auth at Nginx Proxy Manager:

- Homepage
- Prometheus
- Alertmanager
- Loki
- ntfy
- Scrutiny
- Beszel
- Web Games
- Game Server API
- Hearts Multiplayer
- Kiwix
- Stirling PDF
- IT-Tools

App-specific or manual integrations:

- Home Assistant: can use trusted proxy/header or OAuth add-ons, but it needs
  careful local network handling.
- Tools section auth/access:
  - Home Assistant: native username/password, with protocol-relative Homepage
    link support.
  - Actual Budget: native password login enabled through `ACTUAL_LOGIN_METHOD`.
    Actual must be opened over HTTPS for SharedArrayBuffer support in Chrome;
    direct-port HTTPS uses `/data/selfhost.key` and `/data/selfhost.crt`.
  - Stirling PDF: native username/password login enabled through `SECURITY_*`
    environment values.
  - Spoolman and IT-Tools: protect with Authentik proxy/forward auth; see
    `config/authentik/proxy-providers.json`.
  - Set `TOOLS_PUBLIC_SCHEME=https` after TLS/reverse-proxy access is ready for
    Docker-discovered Homepage links.
- n8n: usually keep native users; OAuth is mostly for credentials/callbacks,
  not a simple global login replacement.
- Paperless-ngx: prefer built-in users or forward auth unless you add an OIDC
  integration layer.
- Immich: has OAuth support, but must be configured inside Immich.
- Jellyfin/Navidrome/Audiobookshelf: each has its own auth model; use forward
  auth only if you are comfortable with how clients/apps behave.

Backend-only services that should not appear as login targets:

- PostgreSQL
- Redis
- Immich PostgreSQL
- exporters
- cAdvisor
- Promtail
- backup runner
- guacd

## What Still Needs Human Action

1. In Authentik, create an API token with permission to manage providers and
   applications.
2. Put that token in `.env` as `AUTHENTIK_API_TOKEN`.
3. Decide whether you want subdomain proxy names, for example
   `grafana.kadin-main-sys.tail00cf0e.ts.net`, or direct ports only.
4. For native OIDC apps, create or generate client IDs/secrets and update
   `.env`.
5. Run `bash scripts/configure-sso.sh --dry-run`, then run it without
   `--dry-run` after the dry run is clean.
6. In Nginx Proxy Manager, add proxy hosts and apply Authentik forward auth for
   apps that do not support native OIDC.
7. In Uptime Kuma, rerun the seed script after services are added or ports move.
