#!/usr/bin/env python3
"""Inspect Servarr database schema related to auth/users."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("db")
    args = parser.parse_args()

    db = sqlite3.connect(Path(args.db))
    tables = [
        row[0]
        for row in db.execute("select name from sqlite_master where type='table' order by name")
        if "auth" in row[0].lower() or "user" in row[0].lower()
    ]
    print("TABLES", tables)
    for table in tables:
        columns = [(row[1], row[2]) for row in db.execute(f"pragma table_info({table})")]
        print(table, columns)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
