#!/usr/bin/env python3
import json
import sqlite3


DB_PATH = "/app/backend/data/webui.db"
connection = sqlite3.connect(DB_PATH)
connection.row_factory = sqlite3.Row
tables = [
    row["name"]
    for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    if any(term in row["name"].lower() for term in ("model", "config", "tool", "function"))
]

result = {}
for table in tables:
    columns = [row["name"] for row in connection.execute(f'PRAGMA table_info("{table}")')]
    result[table] = {"columns": columns, "count": connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]}


def decode(value):
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except Exception:
        return value


def redact(value):
    if isinstance(value, dict):
        return {
            key: "<redacted>" if any(term in key.lower() for term in ("key", "token", "secret", "password")) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


models = []
for row in connection.execute("SELECT id, base_model_id, name, meta, params, is_active FROM model ORDER BY id"):
    models.append({
        "id": row["id"], "base_model_id": row["base_model_id"], "name": row["name"],
        "meta": redact(decode(row["meta"])), "params": redact(decode(row["params"])),
        "is_active": bool(row["is_active"]),
    })

config = {}
for row in connection.execute("SELECT key, value FROM config ORDER BY key"):
    key = row["key"]
    if not any(term in key.upper() for term in ("OPENAI", "OLLAMA", "MODEL", "TOOL", "FUNCTION")):
        continue
    if any(term in key.upper() for term in ("KEY", "TOKEN", "SECRET", "PASSWORD")):
        config[key] = "<redacted>"
    else:
        config[key] = redact(decode(row["value"]))

print(json.dumps({"schema": result, "models": models, "config": config}, indent=2, sort_keys=True))
