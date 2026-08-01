#!/usr/bin/env python3
"""Set qBittorrent WebUI API auth bypass for trusted Docker-internal clients."""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request


BASE_URL = "http://localhost:8097"


def request(path: str, data: bytes | None = None) -> bytes:
    with urllib.request.urlopen(f"{BASE_URL}{path}", data=data, timeout=15) as response:
        return response.read()


def main() -> None:
    whitelist = os.environ["QBITTORRENT_AUTH_WHITELIST"]
    preferences = {
        "bypass_local_auth": False,
        "bypass_auth_subnet_whitelist_enabled": True,
        "bypass_auth_subnet_whitelist": whitelist,
    }
    encoded = urllib.parse.urlencode({"json": json.dumps(preferences)}).encode()
    request("/api/v2/app/setPreferences", encoded)

    saved = json.loads(request("/api/v2/app/preferences"))
    result = {
        "bypass_auth_subnet_whitelist_enabled": saved.get("bypass_auth_subnet_whitelist_enabled"),
        "bypass_auth_subnet_whitelist": saved.get("bypass_auth_subnet_whitelist"),
        "bypass_local_auth": saved.get("bypass_local_auth"),
    }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
