#!/usr/bin/env python3
"""Ensure qBittorrent has persistent WebUI/API credentials in .env."""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import secrets
import string
import urllib.parse
import urllib.request
from pathlib import Path


def parse_env(path: Path) -> tuple[list[str], dict[str, str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    values: dict[str, str] = {}
    for line in lines:
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key] = value.strip().split(" #", 1)[0].strip().strip("\"'")
    return lines, values


def set_env_value(lines: list[str], key: str, value: str) -> list[str]:
    rendered = f"{key}={value}"
    for index, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[index] = rendered
            return lines
    lines.append(rendered)
    return lines


def generate_password() -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(32))


def request(opener: urllib.request.OpenerDirector, base_url: str, path: str, data: bytes | None = None) -> bytes:
    with opener.open(f"{base_url}{path}", data=data, timeout=20) as response:
        return response.read()


def login(opener: urllib.request.OpenerDirector, base_url: str, username: str, password: str) -> None:
    encoded = urllib.parse.urlencode({"username": username, "password": password}).encode()
    request(opener, base_url, "/api/v2/auth/login", encoded)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--base-url", default="http://localhost:8097")
    parser.add_argument("--rotate", action="store_true")
    args = parser.parse_args()

    env_path = Path(args.env_file)
    lines, env = parse_env(env_path)
    username = env.get("QBITTORRENT_WEBUI_USERNAME") or "kelbakkouri"
    old_password = env.get("QBITTORRENT_WEBUI_PASSWORD")
    password = generate_password() if args.rotate or not old_password else old_password

    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    if old_password:
        login(opener, args.base_url, username, old_password)

    lines = set_env_value(lines, "QBITTORRENT_WEBUI_USERNAME", username)
    lines = set_env_value(lines, "QBITTORRENT_WEBUI_PASSWORD", password)
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    env_path.chmod(0o600)

    preferences = {
        "web_ui_username": username,
        "web_ui_password": password,
        "bypass_local_auth": False,
        "bypass_auth_subnet_whitelist_enabled": False,
        "bypass_auth_subnet_whitelist": "",
    }
    encoded = urllib.parse.urlencode({"json": json.dumps(preferences)}).encode()
    request(opener, args.base_url, "/api/v2/app/setPreferences", encoded)
    print(f"qBittorrent WebUI/API credentials ensured for user: {username}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
