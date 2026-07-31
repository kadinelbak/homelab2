#!/usr/bin/env python3
"""Inspect or configure Prowlarr download clients using the local API key."""

from __future__ import annotations

import argparse
import json
import re
import urllib.error
import urllib.request
from pathlib import Path


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key] = value.strip().split(" #", 1)[0].strip().strip("\"'")
    return values


def api_key(env: dict[str, str]) -> str:
    config = Path(env["DATA_PATH"]) / "phase2-media/data/prowlarr/config.xml"
    match = re.search(r"<ApiKey>([^<]+)</ApiKey>", config.read_text(encoding="utf-8"))
    if not match:
        raise SystemExit("Prowlarr API key not found")
    return match.group(1)


def app_api_key(env: dict[str, str], app: str) -> str:
    config = Path(env["DATA_PATH"]) / f"phase2-media/data/{app}/config.xml"
    match = re.search(r"<ApiKey>([^<]+)</ApiKey>", config.read_text(encoding="utf-8"))
    if not match:
        raise SystemExit(f"{app} API key not found")
    return match.group(1)


def request_json(method: str, path: str, key: str, body: object | None = None) -> object:
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        f"http://127.0.0.1:9696/api/v1{path}",
        data=payload,
        headers={
            "X-Api-Key": key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"{method} {path} failed with HTTP {exc.code}: {detail}") from exc


def list_clients(key: str) -> int:
    clients = request_json("GET", "/downloadclient", key)
    print(f"PROWLARR_CLIENTS={len(clients)}")
    for client in clients:
        print(
            "CLIENT",
            client.get("id"),
            client.get("name"),
            client.get("implementation"),
            client.get("enable"),
        )
    return 0


def qbit_schema(key: str) -> int:
    schemas = request_json("GET", "/downloadclient/schema", key)
    for schema in schemas:
        if schema.get("implementation") == "QBittorrent":
            fields = [
                {
                    "name": field.get("name"),
                    "label": field.get("label"),
                    "type": field.get("type"),
                    "value": "<set>" if field.get("value") else "",
                    "required": field.get("required"),
                }
                for field in schema.get("fields", [])
            ]
            print(json.dumps({"implementation": "QBittorrent", "fields": fields}, indent=2))
            return 0
    raise SystemExit("QBittorrent schema not found")


def qbit_payload(key: str) -> dict[str, object]:
    schemas = request_json("GET", "/downloadclient/schema", key)
    for schema in schemas:
        if schema.get("implementation") != "QBittorrent":
            continue
        schema["name"] = "qBittorrent VPN"
        schema["enable"] = True
        schema["priority"] = 1
        schema["protocol"] = "torrent"
        field_values = {
            "host": "gluetun",
            "port": 8097,
            "useSsl": False,
            "urlBase": "",
            "username": "",
            "password": "",
            "category": "prowlarr",
            "initialState": 0,
            "sequentialOrder": False,
            "firstAndLast": False,
        }
        for field in schema.get("fields", []):
            if field.get("name") in field_values:
                field["value"] = field_values[field["name"]]
        return schema
    raise SystemExit("QBittorrent schema not found")


def upsert_qbit_client(key: str) -> int:
    clients = request_json("GET", "/downloadclient", key)
    payload = qbit_payload(key)
    existing = next((item for item in clients if item.get("implementation") == "QBittorrent"), None)
    test_payload = dict(payload)
    if existing:
        payload["id"] = existing["id"]
        test_payload["id"] = existing["id"]
    request_json("POST", "/downloadclient/test", key, test_payload)
    if existing:
        request_json("PUT", f"/downloadclient/{existing['id']}", key, payload)
        print("Updated qBittorrent download client in Prowlarr")
    else:
        request_json("POST", "/downloadclient", key, payload)
        print("Created qBittorrent download client in Prowlarr")
    return list_clients(key)


def application_payload(key: str, env: dict[str, str], app: str) -> dict[str, object]:
    implementation = app.capitalize()
    schemas = request_json("GET", "/applications/schema", key)
    for schema in schemas:
        if schema.get("implementation") != implementation:
            continue
        port = 8989 if app == "sonarr" else 7878
        schema["name"] = implementation
        schema["syncLevel"] = "fullSync"
        schema["enable"] = True
        values = {
            "prowlarrUrl": "http://prowlarr:9696",
            f"{app}Url": f"http://{app}:{port}",
            "baseUrl": f"http://{app}:{port}",
            "apiKey": app_api_key(env, app),
            "syncCategories": [5000, 5030, 5040] if app == "sonarr" else [2000, 2010, 2020, 2030, 2040, 2045, 2050, 2060],
        }
        for field in schema.get("fields", []):
            if field.get("name") in values:
                field["value"] = values[field["name"]]
        return schema
    raise SystemExit(f"{implementation} application schema not found")


def upsert_application(key: str, env: dict[str, str], app: str) -> None:
    implementation = app.capitalize()
    payload = application_payload(key, env, app)
    applications = request_json("GET", "/applications", key)
    existing = next((item for item in applications if item.get("implementation") == implementation), None)
    test_payload = dict(payload)
    if existing:
        payload["id"] = existing["id"]
        test_payload["id"] = existing["id"]
    request_json("POST", "/applications/test", key, test_payload)
    if existing:
        request_json("PUT", f"/applications/{existing['id']}", key, payload)
        print(f"Updated {implementation} application in Prowlarr")
    else:
        request_json("POST", "/applications", key, payload)
        print(f"Created {implementation} application in Prowlarr")


def list_applications(key: str) -> None:
    applications = request_json("GET", "/applications", key)
    print(f"PROWLARR_APPLICATIONS={len(applications)}")
    for app in applications:
        print("APP", app.get("id"), app.get("name"), app.get("implementation"), app.get("syncLevel"))


def list_indexers(key: str) -> None:
    indexers = request_json("GET", "/indexer", key)
    print(f"PROWLARR_INDEXERS={len(indexers)}")
    for indexer in indexers:
        print("INDEXER", indexer.get("id"), indexer.get("name"), indexer.get("enable"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("command", choices=["list", "qbit-schema", "upsert-qbit", "upsert-apps", "list-apps", "list-indexers"])
    args = parser.parse_args()

    env = load_env(Path(args.env_file))
    key = api_key(env)
    if args.command == "list":
        return list_clients(key)
    if args.command == "qbit-schema":
        return qbit_schema(key)
    if args.command == "upsert-qbit":
        return upsert_qbit_client(key)
    if args.command == "upsert-apps":
        upsert_application(key, env, "sonarr")
        upsert_application(key, env, "radarr")
        list_applications(key)
        return 0
    if args.command == "list-apps":
        list_applications(key)
        return 0
    if args.command == "list-indexers":
        list_indexers(key)
        return 0
    raise SystemExit(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
