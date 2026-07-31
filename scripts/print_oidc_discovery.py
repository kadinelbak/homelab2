#!/usr/bin/env python3
"""Print selected non-secret OIDC discovery endpoints."""

from __future__ import annotations

import json
import sys
import urllib.request


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: print_oidc_discovery.py URL", file=sys.stderr)
        return 2
    with urllib.request.urlopen(sys.argv[1], timeout=10) as response:
        data = json.loads(response.read().decode("utf-8"))
    for key in ("issuer", "authorization_endpoint", "token_endpoint", "userinfo_endpoint", "end_session_endpoint"):
        if key in data:
            print(f"{key}={data[key]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
