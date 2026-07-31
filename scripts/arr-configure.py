#!/usr/bin/env python3
"""Configure Sonarr/Radarr integrations for the homelab media stack."""

from __future__ import annotations

import argparse
import json
import re
import urllib.error
import urllib.request
from pathlib import Path


APPS = {
    "sonarr": {
        "port": 8989,
        "config": "phase2-media/data/sonarr/config.xml",
        "root_path": "/tv",
        "qbit_category": "sonarr",
    },
    "radarr": {
        "port": 7878,
        "config": "phase2-media/data/radarr/config.xml",
        "root_path": "/movies",
        "qbit_category": "radarr",
    },
}


def clean_env_value(value: str) -> str:
    return value.strip().split(" #", 1)[0].strip().strip("\"'")


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key] = clean_env_value(value)
    return values


def api_key(data_path: Path, app: str) -> str:
    config = data_path / APPS[app]["config"]
    match = re.search(r"<ApiKey>([^<]+)</ApiKey>", config.read_text(encoding="utf-8"))
    if not match:
        raise SystemExit(f"{app} API key not found")
    return match.group(1)


def request_json(app: str, key: str, method: str, path: str, body: object | None = None) -> object:
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        f"http://127.0.0.1:{APPS[app]['port']}/api/v3{path}",
        data=payload,
        headers={
            "X-Api-Key": key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"{app} {method} {path} failed with HTTP {exc.code}: {detail}") from exc


def get_qbit_payload(app: str, key: str) -> dict[str, object]:
    schemas = request_json(app, key, "GET", "/downloadclient/schema")
    for schema in schemas:
        if schema.get("implementation") != "QBittorrent":
            continue
        schema["name"] = "qBittorrent VPN"
        schema["enable"] = True
        schema["priority"] = 1
        schema["protocol"] = "torrent"
        values = {
            "host": "gluetun",
            "port": 8097,
            "useSsl": False,
            "urlBase": "",
            "username": "",
            "password": "",
            "category": APPS[app]["qbit_category"],
            "recentTvPriority": 0,
            "olderTvPriority": 0,
            "initialState": 0,
            "sequentialOrder": False,
            "firstAndLast": False,
            "contentLayout": 0,
        }
        for field in schema.get("fields", []):
            if field.get("name") in values:
                field["value"] = values[field["name"]]
        return schema
    raise SystemExit(f"{app} qBittorrent schema not found")


def upsert_download_client(app: str, key: str) -> None:
    clients = request_json(app, key, "GET", "/downloadclient")
    payload = get_qbit_payload(app, key)
    existing = next((item for item in clients if item.get("implementation") == "QBittorrent"), None)
    test_payload = dict(payload)
    if existing:
        payload["id"] = existing["id"]
        test_payload["id"] = existing["id"]
    request_json(app, key, "POST", "/downloadclient/test", test_payload)
    if existing:
        request_json(app, key, "PUT", f"/downloadclient/{existing['id']}", payload)
        print(f"{app}: updated qBittorrent download client")
    else:
        request_json(app, key, "POST", "/downloadclient", payload)
        print(f"{app}: created qBittorrent download client")


def ensure_root_folder(app: str, key: str) -> None:
    root_path = APPS[app]["root_path"]
    folders = request_json(app, key, "GET", "/rootfolder")
    if any(folder.get("path") == root_path for folder in folders):
        print(f"{app}: root folder already present")
        return
    request_json(app, key, "POST", "/rootfolder", {"path": root_path})
    print(f"{app}: added root folder {root_path}")


def list_status(app: str, key: str) -> None:
    clients = request_json(app, key, "GET", "/downloadclient")
    roots = request_json(app, key, "GET", "/rootfolder")
    print(f"{app}: download_clients={len(clients)} root_folders={len(roots)}")
    for client in clients:
        print(f"{app}: CLIENT {client.get('id')} {client.get('name')} {client.get('implementation')} {client.get('enable')}")
    for root in roots:
        print(f"{app}: ROOT {root.get('path')}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("command", choices=["configure", "list"])
    parser.add_argument("apps", nargs="*", choices=sorted(APPS), default=sorted(APPS))
    args = parser.parse_args()

    env = load_env(Path(args.env_file))
    data_path = Path(env["DATA_PATH"])
    for app in args.apps:
        key = api_key(data_path, app)
        if args.command == "configure":
            upsert_download_client(app, key)
            ensure_root_folder(app, key)
        list_status(app, key)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
