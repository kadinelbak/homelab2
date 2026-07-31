#!/usr/bin/env python3
"""Secure qBittorrent WebUI and align its listen port with Gluetun."""

from __future__ import annotations

import json
import os
import re
import secrets
import string
import subprocess
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path


def random_password(length: int = 28) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


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


def login(base_url: str, username: str, password: str) -> urllib.request.OpenerDirector:
    jar = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    payload = urllib.parse.urlencode({"username": username, "password": password}).encode()
    req = urllib.request.Request(
        f"{base_url}/api/v2/auth/login",
        data=payload,
        headers={
            "Origin": base_url,
            "Referer": f"{base_url}/",
            "User-Agent": "homelab-qbittorrent-provisioner",
        },
        method="POST",
    )
    response = opener.open(req, timeout=20).read().decode().strip()
    if response != "Ok.":
        raise SystemExit("qBittorrent WebUI login failed")
    return opener


def main() -> int:
    base_url = os.environ.get("QBITTORRENT_WEBUI_URL", "http://127.0.0.1:8097")
    env_path = Path(os.environ.get("ENV_FILE", ".env"))
    listen_port = int(os.environ.get("QBITTORRENT_LISTEN_PORT", "56789"))

    bootstrap_password = os.environ.get("QBITTORRENT_BOOTSTRAP_PASSWORD")
    if not bootstrap_password:
        logs = subprocess.check_output(
            ["docker", "logs", "--tail", "160", "qbittorrent"],
            text=True,
            stderr=subprocess.STDOUT,
        )
        matches = re.findall(r"temporary password is provided for this session: (\S+)", logs)
        if not matches:
            raise SystemExit("Could not find qBittorrent temporary password in recent logs")
        bootstrap_password = matches[-1]

    username = "admin"
    password = random_password()
    opener = login(base_url, username, bootstrap_password)
    preferences = {
        "web_ui_username": username,
        "web_ui_password": password,
        "listen_port": listen_port,
    }
    payload = urllib.parse.urlencode({"json": json.dumps(preferences)}).encode()
    req = urllib.request.Request(
        f"{base_url}/api/v2/app/setPreferences",
        data=payload,
        headers={
            "Origin": base_url,
            "Referer": f"{base_url}/",
            "User-Agent": "homelab-qbittorrent-provisioner",
        },
        method="POST",
    )
    opener.open(req, timeout=20).read()

    upsert_env(
        env_path,
        {
            "QBITTORRENT_WEBUI_USER": username,
            "QBITTORRENT_WEBUI_PASSWORD": password,
            "QBITTORRENT_LISTEN_PORT": str(listen_port),
        },
    )
    print("qBittorrent WebUI password and listen port set")
    print("QBITTORRENT_WEBUI_USER=set")
    print("QBITTORRENT_WEBUI_PASSWORD=set")
    print("QBITTORRENT_LISTEN_PORT=set")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
