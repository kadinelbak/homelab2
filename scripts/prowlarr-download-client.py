#!/usr/bin/env python3
"""Inspect or configure Prowlarr download clients using the local API key."""

from __future__ import annotations

import argparse
import json
import re
import socket
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


def request_json(method: str, path: str, key: str, body: object | None = None, timeout: int = 20) -> object:
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
        with urllib.request.urlopen(req, timeout=timeout) as response:
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


def qbit_payload(key: str, env: dict[str, str]) -> dict[str, object]:
    schemas = request_json("GET", "/downloadclient/schema", key)
    for schema in schemas:
        if schema.get("implementation") != "QBittorrent":
            continue
        schema["name"] = "qBittorrent VPN"
        schema["enable"] = True
        schema["priority"] = 1
        schema["protocol"] = "torrent"
        field_values = {
            "host": "localhost",
            "port": 8097,
            "useSsl": False,
            "urlBase": "",
            "username": env["QBITTORRENT_WEBUI_USERNAME"],
            "password": env["QBITTORRENT_WEBUI_PASSWORD"],
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


def upsert_qbit_client(key: str, env: dict[str, str]) -> int:
    clients = request_json("GET", "/downloadclient", key)
    payload = qbit_payload(key, env)
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
    ports = {
        "sonarr": 8989,
        "radarr": 7878,
        "lidarr": 8686,
        "readarr": 8787,
    }
    categories = {
        "sonarr": [5000, 5030, 5040],
        "radarr": [2000, 2010, 2020, 2030, 2040, 2045, 2050, 2060],
        "lidarr": [3000, 3010, 3020, 3030, 3040],
        "readarr": [7000, 7010, 7020, 7030, 7040, 7050, 7060],
    }
    schemas = request_json("GET", "/applications/schema", key)
    for schema in schemas:
        if schema.get("implementation") != implementation:
            continue
        port = ports[app]
        schema["name"] = implementation
        schema["syncLevel"] = "fullSync"
        schema["enable"] = True
        values = {
            "prowlarrUrl": "http://localhost:9696",
            f"{app}Url": f"http://localhost:{port}",
            "baseUrl": f"http://localhost:{port}",
            "apiKey": app_api_key(env, app),
            "syncCategories": categories[app],
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


def list_indexer_schemas(key: str, terms: list[str]) -> None:
    schemas = request_json("GET", "/indexer/schema", key)
    lowered = [term.lower() for term in terms]
    matches = []
    for schema in schemas:
        haystack = " ".join(
            str(schema.get(item, "")) for item in ("name", "implementation", "description")
        ).lower()
        if not lowered or any(term in haystack for term in lowered):
            matches.append(
                {
                    "name": schema.get("name"),
                    "implementation": schema.get("implementation"),
                    "protocol": schema.get("protocol"),
                    "privacy": schema.get("privacy"),
                    "capabilities": schema.get("capabilities", {}).get("categories", []),
                    "fields": [
                        {
                            "name": field.get("name"),
                            "label": field.get("label"),
                            "value": field.get("value"),
                            "required": field.get("required"),
                        }
                        for field in schema.get("fields", [])
                    ],
                }
            )
    print(json.dumps(matches, indent=2))


def indexer_payload(key: str, name: str, base_url: str) -> dict[str, object]:
    schemas = request_json("GET", "/indexer/schema", key)
    for schema in schemas:
        if schema.get("name") != name:
            continue
        schema["name"] = name
        schema["enable"] = True
        schema["priority"] = 25
        schema["protocol"] = "torrent"
        schema["appProfileId"] = 1
        values = {
            "baseUrl": base_url,
            "baseSettings.queryLimit": 1000,
            "baseSettings.grabLimit": 100,
            "baseSettings.limitsUnit": 0,
            "torrentBaseSettings.appMinimumSeeders": 1,
            "torrentBaseSettings.seedRatio": 1.0,
            "torrentBaseSettings.seedTime": 60,
            "torrentBaseSettings.packSeedTime": 60,
            "torrentBaseSettings.preferMagnetUrl": True,
        }
        for field in schema.get("fields", []):
            if field.get("name") in values:
                field["value"] = values[field["name"]]
        return schema
    raise SystemExit(f"{name} indexer schema not found")


def upsert_public_indexers(key: str) -> None:
    targets = {
        "Internet Archive": "https://archive.org",
        "BT.etree": "http://bt.etree.org",
        "LinuxTracker": "https://linuxtracker.org",
    }
    indexers = request_json("GET", "/indexer", key)
    for name, base_url in targets.items():
        payload = indexer_payload(key, name, base_url)
        existing = next((item for item in indexers if item.get("name") == name), None)
        test_payload = dict(payload)
        if existing:
            payload["id"] = existing["id"]
            test_payload["id"] = existing["id"]
        try:
            request_json("POST", "/indexer/test", key, test_payload, timeout=60)
        except (TimeoutError, socket.timeout) as exc:
            print(f"Skipped indexer after timeout: {name}")
            continue
        if existing:
            request_json("PUT", f"/indexer/{existing['id']}", key, payload)
            print(f"Updated indexer: {name}")
        else:
            request_json("POST", "/indexer", key, payload)
            print(f"Created indexer: {name}")
    list_indexers(key)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default=".env")
    parser.add_argument(
        "command",
        choices=[
            "list",
            "qbit-schema",
            "upsert-qbit",
            "upsert-apps",
            "list-apps",
            "list-indexers",
            "list-indexer-schemas",
            "upsert-public-indexers",
        ],
    )
    parser.add_argument("terms", nargs="*")
    args = parser.parse_args()

    env = load_env(Path(args.env_file))
    key = api_key(env)
    if args.command == "list":
        return list_clients(key)
    if args.command == "qbit-schema":
        return qbit_schema(key)
    if args.command == "upsert-qbit":
        return upsert_qbit_client(key, env)
    if args.command == "upsert-apps":
        for app in ("sonarr", "radarr", "lidarr", "readarr"):
            upsert_application(key, env, app)
        list_applications(key)
        return 0
    if args.command == "list-apps":
        list_applications(key)
        return 0
    if args.command == "list-indexers":
        list_indexers(key)
        return 0
    if args.command == "list-indexer-schemas":
        list_indexer_schemas(key, args.terms)
        return 0
    if args.command == "upsert-public-indexers":
        upsert_public_indexers(key)
        return 0
    raise SystemExit(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
