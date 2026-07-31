#!/usr/bin/env python3
"""Print a compact Uptime Kuma monitor summary."""

from __future__ import annotations

import argparse
import getpass
import os
import sys

try:
    from uptime_kuma_api import UptimeKumaApi
except ImportError:
    print(
        "Missing dependency: uptime-kuma-api\n"
        "Install it with: python3 -m pip install --user uptime-kuma-api",
        file=sys.stderr,
    )
    sys.exit(1)


def status_name(status: object) -> str:
    return {
        0: "down",
        1: "up",
        2: "pending",
        3: "maintenance",
    }.get(status, f"unknown:{status}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Report Uptime Kuma monitor state")
    parser.add_argument(
        "--kuma-url",
        default=os.getenv("UPTIME_KUMA_URL", "http://127.0.0.1:3001"),
        help="Uptime Kuma base URL",
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
    monitors = api.get_monitors()

    counts: dict[str, int] = {}
    rows: list[tuple[str, str, str]] = []
    for monitor in monitors:
        state = "paused" if not monitor.get("active") else status_name(monitor.get("status"))
        counts[state] = counts.get(state, 0) + 1
        rows.append((monitor.get("name", ""), state, monitor.get("url") or monitor.get("hostname") or ""))

    print("summary: " + ", ".join(f"{key}={counts[key]}" for key in sorted(counts)))
    for name, state, target in sorted(rows):
        print(f"{state:10} {name} -> {target}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
