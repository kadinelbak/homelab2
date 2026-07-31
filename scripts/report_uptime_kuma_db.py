#!/usr/bin/env python3
"""Report latest Uptime Kuma heartbeat state from kuma.db."""

from __future__ import annotations

import argparse
import sqlite3
from collections import Counter


def status_name(status: int | None) -> str:
    return {
        None: "pending",
        0: "down",
        1: "up",
        2: "pending",
        3: "maintenance",
    }.get(status, f"unknown:{status}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Report latest Uptime Kuma heartbeat state")
    parser.add_argument("db_path", help="Path to Uptime Kuma kuma.db")
    args = parser.parse_args()

    query = """
        WITH latest AS (
            SELECT
                monitor_id,
                status,
                msg,
                time,
                ROW_NUMBER() OVER (PARTITION BY monitor_id ORDER BY time DESC) rn
            FROM heartbeat
        )
        SELECT m.name, m.active, l.status, COALESCE(l.msg, 'no heartbeat')
        FROM monitor m
        LEFT JOIN latest l ON l.monitor_id = m.id AND l.rn = 1
        ORDER BY m.active DESC, m.name
    """

    with sqlite3.connect(args.db_path) as conn:
        rows = conn.execute(query).fetchall()

    counts: Counter[str] = Counter()
    rendered: list[tuple[str, str, str]] = []
    for name, active, status, message in rows:
        state = "paused" if not active else status_name(status)
        counts[state] += 1
        rendered.append((state, name, message))

    print("summary: " + ", ".join(f"{key}={counts[key]}" for key in sorted(counts)))
    for state, name, message in rendered:
        print(f"{state:11} {name} -> {message}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
