#!/usr/bin/env python3
"""Configure Immich OAuth/OIDC using Authentik.

Requires:
  IMMICH_API_KEY from an Immich admin account.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


def clean_env_value(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    if value[0] in "\"'":
        quote = value[0]
        end = value.find(quote, 1)
        return value[1:end] if end != -1 else value[1:]
    return value.split(" #", 1)[0].strip()


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        values[key.strip()] = clean_env_value(value)
    return values


def request(method: str, url: str, headers: dict[str, str], body: object | None = None) -> object:
    payload = None
    merged_headers = {"Accept": "application/json", **headers}
    if body is not None:
        payload = json.dumps(body).encode("utf-8")
        merged_headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=payload, headers=merged_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"ERROR: {method} {url} failed with HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"ERROR: {method} {url} failed: {exc.reason}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="Configure Immich OAuth against Authentik")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--immich-url", default=os.getenv("IMMICH_URL", "http://127.0.0.1:2283"))
    parser.add_argument("--api-key", default=os.getenv("IMMICH_API_KEY"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.api_key:
        raise SystemExit("ERROR: set IMMICH_API_KEY or pass --api-key from an Immich admin account")

    env = load_env(Path(args.env_file))
    domain = env["DOMAIN"]
    client_id = env["IMMICH_OIDC_CLIENT_ID"]
    client_secret = env["IMMICH_OIDC_CLIENT_SECRET"]
    base_url = args.immich_url.rstrip("/")
    headers = {"x-api-key": args.api_key}

    config = request("GET", f"{base_url}/api/system-config", headers=headers)
    if not isinstance(config, dict):
        raise SystemExit("ERROR: unexpected Immich system config response")

    config["oauth"] = {
        **config.get("oauth", {}),
        "enabled": True,
        "issuerUrl": f"https://{domain}:9443/application/o/immich/.well-known/openid-configuration",
        "clientId": client_id,
        "clientSecret": client_secret,
        "scope": "openid email profile",
        "buttonText": "Login with Authentik",
        "autoLaunch": False,
        "autoRegister": True,
        "mobileOverrideEnabled": False,
        "storageLabelClaim": "preferred_username",
        "storageQuotaClaim": "immich_quota",
        "defaultStorageQuota": 0,
    }

    print("would update" if args.dry_run else "updating", "Immich OAuth settings")
    print(f"IssuerURL=https://{domain}:9443/application/o/immich/.well-known/openid-configuration")
    print(f"RedirectURI=http://{domain}:2283/auth/login")
    print("AutoRegister=true")

    if not args.dry_run:
        request("PUT", f"{base_url}/api/system-config", headers=headers, body=config)
        print("Immich OAuth settings updated.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
