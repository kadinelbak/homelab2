#!/usr/bin/env python3
"""Temporarily set qBittorrent WebUI to the documented adminadmin hash."""

from __future__ import annotations

from pathlib import Path


CONF_PATH = Path("/mnt/nvme/homelab2/phase2-media/data/qbittorrent/config/qBittorrent/qBittorrent.conf")
DEFAULT_HASH = (
    '"@ByteArray(ARQ77eY1NUZaQsuDHbIMCA==:'
    '0WMRkYTUWVT9wVvdDtHAjU9b3b7uB8NR1Gur2hmQCvCDpm39Q+PsJRJPaCU51dEiz+dTzh8qbPsL8WkFljQYFQ==)"'
)


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
    lines = CONF_PATH.read_text(encoding="utf-8").splitlines()
    lines = [
        line
        for line in lines
        if not line.startswith("WebUI\\Password_PBKDF2=")
        and not line.startswith("WebUI\\Password_ha1=")
    ]
    lines = set_section_value(lines, "Preferences", "WebUI\\Username", "admin")
    lines = set_section_value(lines, "Preferences", "WebUI\\Password_PBKDF2", DEFAULT_HASH)
    lines = set_section_value(lines, "Preferences", "WebUI\\Port", "8097")
    lines = set_section_value(lines, "Preferences", "Connection\\PortRangeMin", "56789")
    lines = set_section_value(lines, "BitTorrent", "Session\\Port", "56789")
    CONF_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("qBittorrent temporary default hash set")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
