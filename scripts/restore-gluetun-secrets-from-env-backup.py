#!/usr/bin/env python3
"""Restore Gluetun WireGuard Docker secret files from an old .env backup."""

from __future__ import annotations

import argparse
import os
import shutil
from datetime import datetime
from pathlib import Path


SECRET_KEYS = {"WIREGUARD_PRIVATE_KEY", "WIREGUARD_ADDRESSES"}
COPY_KEYS = {"VPN_SERVICE_PROVIDER", "VPN_TYPE", "SERVER_COUNTRIES", "SERVER_CITIES", "VPN_PORT_FORWARDING"}


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def write_secret(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(value.strip() + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    os.chmod(path, 0o600)


def upsert_env(env_path: Path, updates: dict[str, str], remove: set[str]) -> Path:
    backup = env_path.with_name(f"{env_path.name}.backup-before-vpn-restore-{datetime.now():%Y%m%d-%H%M%S}")
    shutil.copy2(env_path, backup)

    remaining = dict(updates)
    rendered: list[str] = []
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        key = raw.split("=", 1)[0].strip() if "=" in raw and not raw.lstrip().startswith("#") else None
        if key in remove:
            continue
        if key in remaining:
            rendered.append(f"{key}={remaining.pop(key)}")
            continue
        rendered.append(raw)

    if remaining:
        if rendered and rendered[-1].strip():
            rendered.append("")
        rendered.append("# Gluetun VPN")
        for key, value in remaining.items():
            rendered.append(f"{key}={value}")

    tmp = env_path.with_suffix(env_path.suffix + ".tmp")
    tmp.write_text("\n".join(rendered) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, env_path)
    os.chmod(env_path, 0o600)
    return backup


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore Gluetun WireGuard secrets from an env backup")
    parser.add_argument("--backup-env", required=True)
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--secrets-dir", default="")
    args = parser.parse_args()

    backup_env = Path(args.backup_env)
    env_path = Path(args.env_file)
    if not backup_env.exists():
        raise SystemExit(f"backup env not found: {backup_env}")
    if not env_path.exists():
        raise SystemExit(f"active env not found: {env_path}")

    old_values = read_env(backup_env)
    missing = SECRET_KEYS - old_values.keys()
    if missing:
        raise SystemExit("backup env missing required keys: " + ", ".join(sorted(missing)))

    secrets_dir = Path(args.secrets_dir) if args.secrets_dir else env_path.parent / "phase2-media" / "secrets"
    write_secret(secrets_dir / "wireguard_private_key", old_values["WIREGUARD_PRIVATE_KEY"])
    write_secret(secrets_dir / "wireguard_addresses", old_values["WIREGUARD_ADDRESSES"])

    updates = {key: old_values[key] for key in COPY_KEYS if old_values.get(key)}
    updates["GLUETUN_SECRETS_DIR"] = str(secrets_dir)
    env_backup = upsert_env(env_path, updates, remove=SECRET_KEYS)

    print(f"secret_dir={secrets_dir}")
    print(f"env_backup={env_backup}")
    print("WIREGUARD_PRIVATE_KEY=secret_file")
    print("WIREGUARD_ADDRESSES=secret_file")
    for key in sorted(updates):
        print(f"{key}=set")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
