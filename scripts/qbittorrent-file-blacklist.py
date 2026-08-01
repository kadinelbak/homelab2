#!/usr/bin/env python3
"""Set and verify qBittorrent's global excluded file name patterns."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request


BASE_URL = "http://localhost:8097"

EXCLUDED_PATTERNS = [
    "*.exe",
    "*.msi",
    "*.bat",
    "*.cmd",
    "*.com",
    "*.scr",
    "*.ps1",
    "*.vbs",
    "*.js",
    "*.jse",
    "*.wsf",
    "*.hta",
    "*.lnk",
    "*.sh",
    "*.run",
    "*.app",
    "*.apk",
    "*.jar",
    "*.deb",
    "*.rpm",
    "*.dmg",
    "*.pkg",
    "*.iso",
    "*.img",
    "*.bin",
    "*.cue",
    "*.dll",
    "*.so",
    "*.zip",
    "*.rar",
    "*.r00",
    "*.r01",
    "*.7z",
    "*.tar",
    "*.gz",
    "*.bz2",
    "*.xz",
    "*.par2",
    "*.sfv",
    "*.url",
    "*.torrent",
    "*.nfo",
    "sample.*",
    "*sample*",
    "*screens*",
    "*screenshot*",
    "*proof*",
    "*Downloaded from*",
    "*RARBG*",
    "*YTS.MX*",
    "*1337x*",
]


def request(path: str, data: bytes | None = None) -> bytes:
    with urllib.request.urlopen(f"{BASE_URL}{path}", data=data, timeout=15) as response:
        return response.read()


def main() -> None:
    preferences = {
        "excluded_file_names_enabled": True,
        "excluded_file_names": "\n".join(EXCLUDED_PATTERNS),
    }
    encoded = urllib.parse.urlencode({"json": json.dumps(preferences)}).encode()
    request("/api/v2/app/setPreferences", encoded)

    saved = json.loads(request("/api/v2/app/preferences"))
    result = {
        "excluded_file_names_enabled": saved.get("excluded_file_names_enabled"),
        "excluded_file_names": saved.get("excluded_file_names"),
    }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
