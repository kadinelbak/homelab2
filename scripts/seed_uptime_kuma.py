#!/usr/bin/env python3
"""Seed core Uptime Kuma monitors for this homelab.

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


def build_monitors(base_host: str, interval: int) -> list[dict]:
    return [
        {
            "name": "Homepage",
            "type": MonitorType.HTTP,
            "url": f"http://{base_host}:3000",
            "interval": interval,
            "maxretries": 3,
        },
        {
            "name": "Portainer",
            "type": MonitorType.HTTP,
            "url": f"http://{base_host}:9000",
            "interval": interval,
            "maxretries": 3,
        },
        {
            "name": "Authentik",
            "type": MonitorType.HTTP,
            "url": f"http://{base_host}:9001",
            "interval": interval,
            "maxretries": 3,
        },
        {
            "name": "Beszel Hub",
            "type": MonitorType.HTTP,
            "url": f"http://{base_host}:8090",
            "interval": interval,
            "maxretries": 3,
        },
        {
            "name": "ntfy",
            "type": MonitorType.HTTP,
            "url": f"http://{base_host}:8085",
            "interval": interval,
            "maxretries": 3,
        },
        {
            "name": "Uptime Kuma",
            "type": MonitorType.HTTP,
            "url": f"http://{base_host}:3001",
            "interval": interval,
            "maxretries": 3,
        },
    ]


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
    desired = build_monitors(args.base_host, args.interval)

    created = 0
    skipped = 0

    for monitor in desired:
        if monitor["name"] in existing:
            skipped += 1
            print(f"skip: {monitor['name']} (already exists)")
            continue

        api.add_monitor(**monitor)
        created += 1
        print(f"add:  {monitor['name']} -> {monitor['url']}")

    print(f"done: created={created}, skipped={skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
