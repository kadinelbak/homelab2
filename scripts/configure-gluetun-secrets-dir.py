#!/usr/bin/env python3
"""Point Gluetun at a Docker secrets directory and remove raw WireGuard envs."""

from __future__ import annotations

import argparse
import os
import shutil
from datetime import datetime
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Configure Gluetun secret-file path in .env")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--secrets-dir", required=True)
    args = parser.parse_args()

    env_path = Path(args.env_file)
    if not env_path.exists():
        raise SystemExit(f"env file not found: {env_path}")

    backup = env_path.with_name(f"{env_path.name}.backup-before-gluetun-secrets-{datetime.now():%Y%m%d-%H%M%S}")
    shutil.copy2(env_path, backup)

    lines: list[str] = []
    inserted = False
    for line in env_path.read_text(encoding="utf-8").splitlines():
        key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else None
        if key in {"WIREGUARD_PRIVATE_KEY", "WIREGUARD_ADDRESSES", "GLUETUN_SECRETS_DIR"}:
            continue
        lines.append(line)
        if key == "VPN_PORT_FORWARDING":
            lines.append(f"GLUETUN_SECRETS_DIR={args.secrets_dir}")
            inserted = True

    if not inserted:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(f"GLUETUN_SECRETS_DIR={args.secrets_dir}")

    tmp = env_path.with_suffix(env_path.suffix + ".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, env_path)
    os.chmod(env_path, 0o600)
    print(f"updated={env_path}")
    print(f"backup={backup}")
    print("WIREGUARD_PRIVATE_KEY=removed")
    print("WIREGUARD_ADDRESSES=removed")
    print("GLUETUN_SECRETS_DIR=set")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
