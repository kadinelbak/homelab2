#!/usr/bin/env python3
"""Verify qBittorrent WebUI login using server-side .env credentials."""

from __future__ import annotations

from http.cookiejar import CookieJar
from pathlib import Path
from urllib import parse, request


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key] = value
    return values


def main() -> int:
    env = load_env(Path(".env"))
    jar = CookieJar()
    opener = request.build_opener(request.HTTPCookieProcessor(jar))
    payload = parse.urlencode(
        {
            "username": env["QBITTORRENT_WEBUI_USER"],
            "password": env["QBITTORRENT_WEBUI_PASSWORD"],
        }
    ).encode()
    base_url = "http://127.0.0.1:8097"
    login = request.Request(
        f"{base_url}/api/v2/auth/login",
        data=payload,
        headers={
            "Origin": base_url,
            "Referer": f"{base_url}/",
            "User-Agent": "homelab-qbittorrent-provisioner",
        },
        method="POST",
    )
    response = opener.open(login, timeout=20).read().decode().strip()
    if response != "Ok.":
        raise SystemExit("LOGIN_FAILED")
    prefs = opener.open(f"{base_url}/api/v2/app/preferences", timeout=20).read().decode()
    if "listen_port" not in prefs:
        raise SystemExit("PREFS_READ_FAILED")
    print("LOGIN_OK")
    print("PREFS_READ_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
