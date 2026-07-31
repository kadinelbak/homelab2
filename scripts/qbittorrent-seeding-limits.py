#!/usr/bin/env python3
"""Set and verify qBittorrent global seeding limits."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request


BASE_URL = "http://gluetun:8097"

PREFERENCES = {
    "max_ratio_enabled": True,
    "max_ratio": 1.0,
    "max_seeding_time_enabled": True,
    "max_seeding_time": 60,
    "max_ratio_act": 0,
    "delete_torrent_content_files": False,
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
