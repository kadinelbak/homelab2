#!/usr/bin/env python3
"""Check qBittorrent API login with credentials from .env."""

from __future__ import annotations

import argparse
import urllib.parse
import urllib.request
from pathlib import Path


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key] = value.strip().split(" #", 1)[0].strip().strip("\"'")
    return values


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--base-url", default="http://localhost:8097")
    args = parser.parse_args()

    env = load_env(Path(args.env_file))
    payload = urllib.parse.urlencode(
        {
            "username": env["QBITTORRENT_WEBUI_USERNAME"],
            "password": env["QBITTORRENT_WEBUI_PASSWORD"],
        }
    ).encode()
    req = urllib.request.Request(f"{args.base_url}/api/v2/auth/login", data=payload, method="POST")
    with urllib.request.urlopen(req, timeout=15) as response:
        print(f"status={response.status}")
        print(response.read().decode("utf-8", errors="replace"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
