#!/usr/bin/env python3
"""Idempotently provision the private Fitbit & N-of-1 Metabase dashboard."""
from __future__ import annotations
import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

MANIFEST = Path(__file__).with_name("fitbit-n1-dashboard.json")

def api(url: str, key: str, path: str, *, method: str = "GET", body: Any = None) -> Any:
    request = Request(f"{url.rstrip('/')}/api{path}", data=json.dumps(body).encode() if body is not None else None, method=method, headers={"X-API-Key": key, "Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=30) as response: payload = response.read()
    except HTTPError as error:
        raise RuntimeError(f"Metabase API {method} {path} failed ({error.code}): {error.read().decode('utf-8', 'replace')[:500]}") from error
    return json.loads(payload) if payload else None

def find_named(items: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    return next((item for item in items if item.get("name") == name), None)

def upsert_card(url: str, key: str, database_id: int, spec: dict[str, Any]) -> dict[str, Any]:
    payload = {"name":spec["name"],"description":spec["description"],"display":spec["display"],"visualization_settings":{},"dataset_query":{"database":database_id,"type":"native","native":{"query":spec["sql"],"template-tags":{}}}}
    current = find_named(api(url, key, "/card"), spec["name"])
    return api(url, key, f"/card/{current['id']}" if current else "/card", method="PUT" if current else "POST", body=payload)

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Validate and list resources without contacting Metabase")
    parser.add_argument("--url", default=os.environ.get("METABASE_URL", "http://127.0.0.1:13000"))
    parser.add_argument("--database-name", default=os.environ.get("METABASE_DATABASE_NAME", "Homelab Health"))
    args = parser.parse_args(); manifest = json.loads(MANIFEST.read_text(encoding="utf-8")); cards = manifest.get("cards", [])
    if not manifest.get("dashboard", {}).get("name") or not cards: raise ValueError("Dashboard manifest must contain a name and cards")
    for card in cards:
        if not all(card.get(field) for field in ("name", "description", "display", "sql", "layout")): raise ValueError(f"Invalid card definition: {card.get('name', '<unnamed>')}")
    if args.dry_run:
        print(f"Validated dashboard: {manifest['dashboard']['name']} ({len(cards)} cards)")
        for card in cards: print(f"- {card['name']}")
        return 0
    key = os.environ.get("METABASE_API_KEY", "").strip()
    if not key: raise RuntimeError("METABASE_API_KEY is required (store it only in the server .env file)")
    database = find_named(api(args.url, key, "/database"), args.database_name)
    if not database: raise RuntimeError(f"Metabase database not found: {args.database_name}")
    existing_dashboard = find_named(api(args.url, key, "/dashboard"), manifest["dashboard"]["name"])
    dashboard = api(args.url, key, f"/dashboard/{existing_dashboard['id']}" if existing_dashboard else "/dashboard", method="PUT" if existing_dashboard else "POST", body=manifest["dashboard"])
    existing = api(args.url, key, f"/dashboard/{dashboard['id']}")
    existing_card_ids = {dashcard.get("card_id") for dashcard in existing.get("dashcards", [])}
    for spec in cards:
        card = upsert_card(args.url, key, database["id"], spec)
        if card["id"] not in existing_card_ids:
            col, row, size_x, size_y = spec["layout"]
            api(args.url, key, f"/dashboard/{dashboard['id']}/cards", method="POST", body={"cardId":card["id"],"col":col,"row":row,"sizeX":size_x,"sizeY":size_y,"parameter_mappings":[]})
    print(f"Provisioned dashboard: {args.url.rstrip('/')}/dashboard/{dashboard['id']}")
    return 0

if __name__ == "__main__":
    try: raise SystemExit(main())
    except (RuntimeError, ValueError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr); raise SystemExit(1)
