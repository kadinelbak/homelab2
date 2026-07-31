#!/usr/bin/env python3
"""Seed Uptime Kuma monitors for this homelab.

Usage:
  python3 scripts/seed_uptime_kuma.py --username admin

Environment variables supported:
  DOMAIN                   Base host for monitor URLs (default: kadin-main-sys.tail00cf0e.ts.net)
  UPTIME_KUMA_URL          Kuma URL (default: http://127.0.0.1:3001)
  UPTIME_KUMA_USERNAME     Kuma username (used if --username omitted)
  UPTIME_KUMA_PASSWORD     Kuma password (used if --password omitted)
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys

try:
    from uptime_kuma_api import MonitorType, UptimeKumaApi
except ImportError:
    print(
        "Missing dependency: uptime-kuma-api\n"
        "Install it with: python3 -m pip install --user uptime-kuma-api",
        file=sys.stderr,
    )
    sys.exit(1)


def http(
    name: str,
    url: str,
    interval: int,
    active: bool = True,
    accepted_statuscodes: list[str] | None = None,
) -> dict:
    monitor = {
        "name": name,
        "type": MonitorType.HTTP,
        "url": url,
        "interval": interval,
        "maxretries": 3,
        "active": active,
    }
    if accepted_statuscodes:
        monitor["accepted_statuscodes"] = accepted_statuscodes
    return monitor


def tcp(name: str, hostname: str, port: int, interval: int, active: bool = True) -> dict:
    return {
        "name": name,
        "type": MonitorType.PORT,
        "hostname": hostname,
        "port": port,
        "interval": interval,
        "maxretries": 3,
        "active": active,
    }


def push(name: str, interval: int, active: bool = True) -> dict:
    return {
        "name": name,
        "type": MonitorType.PUSH,
        "interval": interval,
        "maxretries": 3,
        "active": active,
    }


def build_monitors(base_host: str, interval: int, include_ondemand: bool) -> list[dict]:
    monitors = [
        http("Homepage", f"http://{base_host}:3000", interval),
        http("Nginx Proxy Manager", f"http://{base_host}:81", interval),
        http("Portainer", f"http://{base_host}:9000", interval),
        http("Authentik", f"http://{base_host}:9001/-/health/live/", interval),
        http("Vaultwarden", f"http://{base_host}:7070", interval),
        http("ntfy", f"http://{base_host}:8085", interval),
        http("Uptime Kuma", f"http://{base_host}:3001", interval),
        http("Beszel", f"http://{base_host}:8090", interval),
        http("Scrutiny", f"http://{base_host}:8089", interval),
        http("Grafana", f"http://{base_host}:30030", interval),
        http("Prometheus", f"http://{base_host}:9090", interval),
        http("Alertmanager", f"http://{base_host}:9093", interval),
        http("Loki", f"http://{base_host}:3100/ready", interval),
        http("Jellyfin", f"http://{base_host}:8096", interval),
        http("Audiobookshelf", f"http://{base_host}:13378", interval),
        http("Navidrome", f"http://{base_host}:4533", interval),
        http("Immich", f"http://{base_host}:2283", interval),
        http("Paperless-ngx", f"http://{base_host}:8000", interval),
        http("Prowlarr", f"http://{base_host}:9696", interval),
        http("Bazarr", f"http://{base_host}:6767", interval),
        http("Open WebUI", f"http://{base_host}:8080", interval),
        http("n8n", f"http://{base_host}:5678/healthz", interval),
        http("Home Assistant", f"http://{base_host}:8123", interval),
        http("Spoolman", f"http://{base_host}:7912", interval),
        http("Actual Budget", f"http://{base_host}:5006", interval),
        http("Stirling PDF", f"http://{base_host}:8086", interval),
        http("IT-Tools", f"http://{base_host}:8087", interval),
        http("Web Games", f"http://{base_host}:8092", interval, accepted_statuscodes=["200-299", "300-399", "400-499"]),
        http("Game Server API", f"http://{base_host}:8093/health", interval),
        http("Hearts Multiplayer", f"http://{base_host}:8094", interval),
        http("Wake-on-LAN API", f"http://{base_host}:9999/health", interval),
        tcp("Minecraft", base_host, 25565, interval),
    ]

    if include_ondemand:
        monitors.extend(
            [
                http("Kasm", f"https://{base_host}:444", interval, active=False),
                http("Guacamole", f"http://{base_host}:8088/guacamole", interval, active=False),
                http("Nextcloud", f"http://{base_host}:8091", interval, active=False),
                http("Gitea", f"http://{base_host}:3002", interval, active=False),
                http("Supabase Studio", f"http://{base_host}:3003", interval, active=False),
                http("Kiwix", f"http://{base_host}:8095", interval, active=False),
                http("Docmost", f"http://{base_host}:3004", interval, active=False),
                http("Cal.com", f"http://{base_host}:3005", interval, active=False),
                http("NocoDB", f"http://{base_host}:8098", interval, active=False),
            ]
        )

    return monitors


def update_monitor(api: UptimeKumaApi, monitor_id: int, monitor: dict) -> None:
    monitor = {k: v for k, v in monitor.items() if k != "active"}
    if hasattr(api, "edit_monitor"):
        api.edit_monitor(monitor_id, **monitor)
        return
    if hasattr(api, "update_monitor"):
        api.update_monitor(monitor_id, **monitor)
        return
    print(f"warn: cannot update {monitor['name']} with this uptime-kuma-api version")


def apply_monitor_state(api: UptimeKumaApi, monitor_id: int, active: bool) -> None:
    if active and hasattr(api, "resume_monitor"):
        api.resume_monitor(monitor_id)
        return
    if not active and hasattr(api, "pause_monitor"):
        api.pause_monitor(monitor_id)
        return
    print(f"warn: cannot set monitor state for id={monitor_id} with this uptime-kuma-api version")


def monitor_target(monitor: dict) -> str:
    if monitor["type"] == MonitorType.PORT:
        return f"{monitor['hostname']}:{monitor['port']}"
    if monitor["type"] == MonitorType.PUSH:
        return "push"
    return monitor["url"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed Uptime Kuma core monitors")
    parser.add_argument(
        "--kuma-url",
        default=os.getenv("UPTIME_KUMA_URL", "http://127.0.0.1:3001"),
        help="Uptime Kuma base URL",
    )
    parser.add_argument(
        "--base-host",
        default=os.getenv("DOMAIN", "kadin-main-sys.tail00cf0e.ts.net"),
        help="Host/domain used in monitor URLs",
    )
    parser.add_argument(
        "--username",
        default=os.getenv("UPTIME_KUMA_USERNAME"),
        help="Uptime Kuma username",
    )
    parser.add_argument(
        "--password",
        default=os.getenv("UPTIME_KUMA_PASSWORD"),
        help="Uptime Kuma password",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=60,
        help="Monitor interval in seconds",
    )
    parser.add_argument(
        "--include-ondemand",
        action="store_true",
        help="Create paused monitors for Phase 4 on-demand services.",
    )
    parser.add_argument(
        "--update-existing",
        action="store_true",
        help="Update existing monitors by name instead of only creating missing monitors.",
    )

    args = parser.parse_args()

    if not args.username:
        print("Missing username. Pass --username or set UPTIME_KUMA_USERNAME.", file=sys.stderr)
        return 2

    password = args.password or getpass.getpass("Uptime Kuma password: ")
    if not password:
        print("Password is required.", file=sys.stderr)
        return 2

    api = UptimeKumaApi(args.kuma_url)
    api.login(args.username, password)

    existing = {m.get("name"): m for m in api.get_monitors()}
    desired = build_monitors(args.base_host, args.interval, args.include_ondemand)

    created = 0
    updated = 0
    skipped = 0

    for monitor in desired:
        current = existing.get(monitor["name"])
        if current and args.update_existing:
            monitor_id = current.get("id")
            if monitor_id is None:
                skipped += 1
                print(f"skip: {monitor['name']} (missing monitor id)")
                continue
            update_monitor(api, monitor_id, monitor)
            apply_monitor_state(api, monitor_id, monitor.get("active", True))
            updated += 1
            print(f"edit: {monitor['name']}")
            continue
        if current:
            skipped += 1
            print(f"skip: {monitor['name']} (already exists)")
            continue

        payload = {k: v for k, v in monitor.items() if k != "active"}
        created_monitor = api.add_monitor(**payload)
        monitor_id = created_monitor.get("monitorID") or created_monitor.get("id")
        if monitor_id is not None:
            apply_monitor_state(api, monitor_id, monitor.get("active", True))
        created += 1
        print(f"add:  {monitor['name']} -> {monitor_target(monitor)}")

    print(f"done: created={created}, updated={updated}, skipped={skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
