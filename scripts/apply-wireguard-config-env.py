#!/usr/bin/env python3
"""Apply a WireGuard config to the homelab media VPN IaC files.

Sensitive WireGuard values are written to Docker secret files. The shared .env
file only keeps non-secret Gluetun settings such as provider, country, and port
forwarding mode.
"""

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


def upsert_env(path: Path, updates: dict[str, str], remove: set[str] | None = None) -> None:
    remove = remove or set()
    lines = path.read_text(encoding="utf-8").splitlines()
    remaining = dict(updates)
    rendered: list[str] = []

    for line in lines:
        if "=" in line and not line.lstrip().startswith("#"):
            key = line.split("=", 1)[0].strip()
            if key in remove:
                continue
            if key in remaining:
                rendered.append(f"{key}={remaining.pop(key)}")
                continue
        rendered.append(line)

    if remaining:
        if rendered and rendered[-1].strip():
            rendered.append("")
        rendered.append("# WireGuard VPN for Gluetun")
        for key, value in remaining.items():
            rendered.append(f"{key}={value}")

    tmp = path.with_suffix(".env.tmp")
    tmp.write_text("\n".join(rendered) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    os.chmod(path, 0o600)


def write_secret(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(value.strip() + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    os.chmod(path, 0o600)


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply WireGuard config values to Gluetun Docker secret files and .env")
    parser.add_argument("--config", required=True)
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--provider", default="mullvad")
    parser.add_argument("--server-countries", default="Netherlands")
    parser.add_argument("--port-forwarding", choices=["on", "off"], default="off")
    parser.add_argument("--secrets-dir", default="")
    args = parser.parse_args()

    wireguard = parse_wireguard_config(Path(args.config))
    env_path = Path(args.env_file)
    secrets_dir = Path(args.secrets_dir) if args.secrets_dir else env_path.parent / "phase2-media" / "secrets"
    write_secret(secrets_dir / "wireguard_private_key", wireguard["PrivateKey"])
    write_secret(secrets_dir / "wireguard_addresses", wireguard["Address"])

    updates = {
        "VPN_SERVICE_PROVIDER": args.provider,
        "VPN_TYPE": "wireguard",
        "SERVER_COUNTRIES": args.server_countries,
        "VPN_PORT_FORWARDING": args.port_forwarding,
    }
    upsert_env(env_path, updates, remove={"WIREGUARD_PRIVATE_KEY", "WIREGUARD_ADDRESSES"})
    print("Updated Gluetun WireGuard settings.")
    print(f"secret_dir={secrets_dir}")
    for key in updates:
        print(f"{key}=set")
    print("WIREGUARD_PRIVATE_KEY=secret_file")
    print("WIREGUARD_ADDRESSES=secret_file")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
