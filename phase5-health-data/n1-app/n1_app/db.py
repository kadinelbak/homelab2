from __future__ import annotations

import os
from pathlib import Path
import psycopg

DATABASE_URL = os.environ["HEALTH_DATABASE_URL"]

def connect():
    return psycopg.connect(DATABASE_URL, row_factory=psycopg.rows.dict_row)

def migrate() -> None:
    migration_dir = Path(__file__).resolve().parents[1] / "migrations"
    with connect() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS n1_schema_migrations (version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())")
        for path in sorted(migration_dir.glob("*.sql")):
            if conn.execute("SELECT 1 FROM n1_schema_migrations WHERE version=%s", (path.name,)).fetchone():
                continue
            conn.execute(path.read_text(encoding="utf-8"))
            conn.execute("INSERT INTO n1_schema_migrations (version) VALUES (%s)", (path.name,))
        conn.commit()

def owner(conn):
    return conn.execute("SELECT * FROM subjects WHERE slug='owner'").fetchone()
