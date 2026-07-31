#!/usr/bin/env python3
"""Remove qBittorrent WebUI password entries so it regenerates a temporary password."""

from __future__ import annotations

from pathlib import Path


CONF_PATH = Path("/mnt/nvme/homelab2/phase2-media/data/qbittorrent/config/qBittorrent/qBittorrent.conf")


def main() -> int:
    if not CONF_PATH.exists():
        raise SystemExit(f"missing qBittorrent config: {CONF_PATH}")
    lines = CONF_PATH.read_text(encoding="utf-8").splitlines()
    filtered = [
        line
        for line in lines
        if not line.startswith("WebUI\\Password_PBKDF2=")
        and not line.startswith("WebUI\\Password_ha1=")
    ]
    CONF_PATH.write_text("\n".join(filtered) + "\n", encoding="utf-8")
    print("qBittorrent WebUI password entries removed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
