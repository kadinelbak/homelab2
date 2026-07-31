#!/usr/bin/env python3
"""Bind qBittorrent to Gluetun's VPN tunnel interface."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request


BASE_URL = "http://gluetun:8097"

PREFERENCES = {
    "current_network_interface": "tun0",
    "current_interface_name": "tun0",
    "current_interface_address": "",
}


def request(path: str, data: bytes | None = None) -> bytes:
    with urllib.request.urlopen(f"{BASE_URL}{path}", data=data, timeout=15) as response:
        return response.read()


def main() -> None:
    encoded = urllib.parse.urlencode({"json": json.dumps(PREFERENCES)}).encode()
    request("/api/v2/app/setPreferences", encoded)

    saved = json.loads(request("/api/v2/app/preferences"))
    result = {key: saved.get(key) for key in PREFERENCES}
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
