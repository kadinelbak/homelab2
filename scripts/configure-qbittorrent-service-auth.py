#!/usr/bin/env python3
"""Allow Docker-internal services to call qBittorrent without storing UI passwords."""

from __future__ import annotations

import os
from pathlib import Path


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key] = value.strip().split(" #", 1)[0].strip().strip("\"'")
    return values


def set_section_value(lines: list[str], section: str, key: str, value: str) -> list[str]:
    header = f"[{section}]"
    section_start = None
    section_end = len(lines)
    for index, line in enumerate(lines):
        if line.strip() == header:
            section_start = index
            continue
        if section_start is not None and index > section_start and line.startswith("[") and line.endswith("]"):
            section_end = index
            break

    if section_start is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend([header, f"{key}={value}"])
        return lines

    for index in range(section_start + 1, section_end):
        if lines[index].split("=", 1)[0] == key:
            lines[index] = f"{key}={value}"
            return lines

    lines.insert(section_end, f"{key}={value}")
    return lines


def main() -> int:
    env = load_env(Path(os.environ.get("ENV_FILE", ".env")))
    whitelist = os.environ.get("QBITTORRENT_AUTH_WHITELIST", "172.18.0.11/32")
    conf_path = Path(env["DATA_PATH"]) / "phase2-media/data/qbittorrent/config/qBittorrent/qBittorrent.conf"
    lines = conf_path.read_text(encoding="utf-8").splitlines()
    updates = [
        ("Preferences", "WebUI\\AuthSubnetWhitelistEnabled", "true"),
        ("Preferences", "WebUI\\AuthSubnetWhitelist", whitelist),
        ("Preferences", "WebUI\\HostHeaderValidation", "false"),
        ("Preferences", "WebUI\\CSRFProtection", "true"),
        ("Preferences", "WebUI\\Port", "8097"),
        ("Preferences", "Connection\\PortRangeMin", "56789"),
        ("Preferences", "PortForwardingEnabled", "false"),
        ("BitTorrent", "Session\\Port", "56789"),
    ]
    for section, key, value in updates:
        lines = set_section_value(lines, section, key, value)
    tmp = conf_path.with_suffix(".conf.tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(tmp, conf_path)
    os.chmod(conf_path, 0o600)
    print("qBittorrent Docker service auth whitelist configured")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
