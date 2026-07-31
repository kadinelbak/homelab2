#!/usr/bin/env python3
"""Configure Portainer OAuth/OIDC using Authentik.

Requires one of:
  PORTAINER_API_KEY
  PORTAINER_USERNAME and PORTAINER_PASSWORD
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


def request(method: str, url: str, headers: dict[str, str] | None = None, body: object | None = None) -> object:
    payload = None
    merged_headers = {"Accept": "application/json"}
    if headers:
        merged_headers.update(headers)
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


def auth_headers(base_url: str) -> dict[str, str]:
    api_key = os.getenv("PORTAINER_API_KEY")
    if api_key:
        return {"X-API-Key": api_key}

    username = os.getenv("PORTAINER_USERNAME")
    password = os.getenv("PORTAINER_PASSWORD")
    if not username or not password:
        raise SystemExit("ERROR: set PORTAINER_API_KEY or PORTAINER_USERNAME and PORTAINER_PASSWORD")

    data = request("POST", f"{base_url}/api/auth", body={"Username": username, "Password": password})
    jwt = data.get("jwt") if isinstance(data, dict) else None
    if not jwt:
        raise SystemExit("ERROR: Portainer authentication did not return a JWT")
    return {"Authorization": f"Bearer {jwt}"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Configure Portainer OAuth against Authentik")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--portainer-url", default=os.getenv("PORTAINER_URL", "http://127.0.0.1:9000"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    env = load_env(Path(args.env_file))
    domain = env["DOMAIN"]
    client_id = env["PORTAINER_OIDC_CLIENT_ID"]
    client_secret = env["PORTAINER_OIDC_CLIENT_SECRET"]
    base_url = args.portainer_url.rstrip("/")

    headers = auth_headers(base_url)
    settings = request("GET", f"{base_url}/api/settings", headers=headers)
    if not isinstance(settings, dict):
        raise SystemExit("ERROR: unexpected Portainer settings response")

    settings["AuthenticationMethod"] = 3
    settings["OAuthSettings"] = {
        **settings.get("OAuthSettings", {}),
        "ClientID": client_id,
        "ClientSecret": client_secret,
        "AuthorizationURI": f"http://{domain}:9001/application/o/authorize/",
        "AccessTokenURI": "http://172.18.0.1:9001/application/o/token/",
        "ResourceURI": "http://172.18.0.1:9001/application/o/userinfo/",
        "RedirectURI": f"http://{domain}:9000/",
        "LogoutURI": f"http://{domain}:9001/application/o/portainer/end-session/",
        "UserIdentifier": "email",
        "Scopes": "openid profile email",
        "OAuthAutoCreateUsers": True,
        "DefaultTeamID": 0,
        "SSO": True,
        "HideInternalAuth": False,
        "AuthStyle": 0,
    }

    print("would update" if args.dry_run else "updating", "Portainer OAuth settings")
    print(f"AuthorizationURI=http://{domain}:9001/application/o/authorize/")
    print("AccessTokenURI=http://172.18.0.1:9001/application/o/token/")
    print("ResourceURI=http://172.18.0.1:9001/application/o/userinfo/")
    print(f"RedirectURI=http://{domain}:9000/")
    print("HideInternalAuth=false")

    if not args.dry_run:
        request("PUT", f"{base_url}/api/settings", headers=headers, body=settings)
        print("Portainer OAuth settings updated.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
