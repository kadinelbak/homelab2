#!/usr/bin/env python3
"""Apply a WireGuard config's safe-to-store fields to the homelab .env file."""

from __future__ import annotations

import argparse
import os
from pathlib import Path


def parse_wireguard_config(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    section = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue
        if section == "Interface" and "=" in line:
            key, value = [part.strip() for part in line.split("=", 1)]
            if key in {"PrivateKey", "Address"}:
                values[key] = value

    missing = {"PrivateKey", "Address"} - values.keys()
    if missing:
        raise SystemExit("WireGuard config missing required fields: " + ", ".join(sorted(missing)))
    addresses = [item.strip() for item in values["Address"].split(",")]
    ipv4_addresses = [item for item in addresses if ":" not in item]
    if not ipv4_addresses:
        raise SystemExit("WireGuard config does not contain an IPv4 interface address")
    values["Address"] = ipv4_addresses[0]
    return values


def upsert_env(path: Path, updates: dict[str, str]) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    remaining = dict(updates)
    rendered: list[str] = []

    for line in lines:
        if "=" in line and not line.lstrip().startswith("#"):
            key = line.split("=", 1)[0].strip()
            if key in remaining:
                rendered.append(f"{key}={remaining.pop(key)}")
                continue
        rendered.append(line)

    if remaining:
        if rendered and rendered[-1].strip():
            rendered.append("")
        rendered.append("# Proton VPN WireGuard for Gluetun")
        for key, value in remaining.items():
            rendered.append(f"{key}={value}")

    tmp = path.with_suffix(".env.tmp")
    tmp.write_text("\n".join(rendered) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    os.chmod(path, 0o600)


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply Proton WireGuard config values to .env")
    parser.add_argument("--config", required=True)
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--server-countries", default="United States")
    args = parser.parse_args()

    wireguard = parse_wireguard_config(Path(args.config))
    updates = {
        "VPN_SERVICE_PROVIDER": "protonvpn",
        "VPN_TYPE": "wireguard",
        "WIREGUARD_PRIVATE_KEY": wireguard["PrivateKey"],
        "WIREGUARD_ADDRESSES": wireguard["Address"],
        "SERVER_COUNTRIES": args.server_countries,
        "VPN_PORT_FORWARDING": "on",
    }
    upsert_env(Path(args.env_file), updates)
    print("Updated Proton WireGuard env values.")
    for key in updates:
        print(f"{key}=set")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
