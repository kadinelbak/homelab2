#!/usr/bin/env python3
"""Write secure qBittorrent WebUI settings directly to qBittorrent.conf."""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
import string
from pathlib import Path


def clean_env_value(value: str) -> str:
    value = value.strip()
    if value and value[0] in "\"'":
        quote = value[0]
        end = value.find(quote, 1)
        return value[1:end] if end != -1 else value[1:]
    return value.split(" #", 1)[0].strip()


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        if "=" not in raw or raw.lstrip().startswith("#"):
            continue
        key, value = raw.split("=", 1)
        values[key.strip()] = clean_env_value(value)
    return values


def random_password(length: int = 28) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def qbittorrent_password_hash(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha512", password.encode(), salt, 100000)
    encoded_salt = base64.b64encode(salt).decode()
    encoded_digest = base64.b64encode(digest).decode()
    return f'"@ByteArray({encoded_salt}:{encoded_digest})"'


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
        rendered.append("# qBittorrent WebUI values")
        for key, value in remaining.items():
            rendered.append(f"{key}={value}")
    tmp = path.with_suffix(".env.tmp")
    tmp.write_text("\n".join(rendered) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    os.chmod(path, 0o600)


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
    env_path = Path(os.environ.get("ENV_FILE", ".env"))
    env = load_env(env_path)
    data_path = Path(env["DATA_PATH"])
    conf_path = data_path / "phase2-media/data/qbittorrent/config/qBittorrent/qBittorrent.conf"
    conf_path.parent.mkdir(parents=True, exist_ok=True)
    lines = conf_path.read_text(encoding="utf-8").splitlines() if conf_path.exists() else []

    username = "admin"
    password = random_password()
    listen_port = "56789"
    updates = [
        ("Preferences", "WebUI\\Username", username),
        ("Preferences", "WebUI\\Password_PBKDF2", qbittorrent_password_hash(password)),
        ("Preferences", "WebUI\\Port", "8097"),
        ("Preferences", "WebUI\\UseUPnP", "false"),
        ("Preferences", "Connection\\PortRangeMin", listen_port),
        ("BitTorrent", "Session\\Port", listen_port),
    ]
    for section, key, value in updates:
        lines = set_section_value(lines, section, key, value)

    tmp = conf_path.with_suffix(".conf.tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(tmp, conf_path)
    os.chmod(conf_path, 0o600)

    upsert_env(
        env_path,
        {
            "QBITTORRENT_WEBUI_USER": username,
            "QBITTORRENT_WEBUI_PASSWORD": password,
            "QBITTORRENT_LISTEN_PORT": listen_port,
        },
    )
    print("qBittorrent config secured")
    print("QBITTORRENT_WEBUI_USER=set")
    print("QBITTORRENT_WEBUI_PASSWORD=set")
    print("QBITTORRENT_LISTEN_PORT=set")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
