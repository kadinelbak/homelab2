from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Jsonb


def connect(database_url: str) -> psycopg.Connection:
    return psycopg.connect(database_url)


def init_schema(conn: psycopg.Connection) -> None:
    schema_path = Path(__file__).resolve().parents[1] / "schema.sql"
    conn.execute(schema_path.read_text(encoding="utf-8"))
    conn.commit()


def start_import_run(conn: psycopg.Connection, source: str, source_path: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO import_runs (source, source_path)
            VALUES (%s, %s)
            RETURNING id
            """,
            (source, source_path),
        )
        return int(cur.fetchone()[0])


def finish_import_run(
    conn: psycopg.Connection,
    run_id: int,
    status: str,
    counts: dict[str, int],
    error: str | None = None,
) -> None:
    conn.execute(
        """
        UPDATE import_runs
        SET status = %s,
            finished_at = now(),
            files_seen = %s,
            raw_documents_inserted = %s,
            metric_samples_inserted = %s,
            sleep_sessions_inserted = %s,
            sleep_stages_inserted = %s,
            error = %s
        WHERE id = %s
        """,
        (
            status,
            counts.get("files_seen", 0),
            counts.get("raw_documents_inserted", 0),
            counts.get("metric_samples_inserted", 0),
            counts.get("sleep_sessions_inserted", 0),
            counts.get("sleep_stages_inserted", 0),
            error,
            run_id,
        ),
    )
    conn.commit()


def insert_raw_document(
    conn: psycopg.Connection,
    source: str,
    source_file: str,
    document_hash: str,
    payload: Any,
    import_run_id: int,
) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO raw_documents
              (source, source_file, document_hash, payload, import_run_id)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (source, source_file, document_hash, Jsonb(payload), import_run_id),
        )
        return cur.rowcount > 0


def upsert_metric_sample(conn: psycopg.Connection, sample: dict[str, Any]) -> bool:
    metadata = sample.get("metadata") or {}
    # Force JSON serializability before sending to Postgres.
    json.dumps(metadata)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO metric_samples
              (ts, metric_type, value, unit, source, source_file, confidence, metadata, import_run_id)
            VALUES (%(ts)s, %(metric_type)s, %(value)s, %(unit)s, %(source)s, %(source_file)s,
                    %(confidence)s, %(metadata)s, %(import_run_id)s)
            ON CONFLICT (ts, metric_type, source, source_file)
            DO UPDATE SET
              value = EXCLUDED.value,
              unit = EXCLUDED.unit,
              confidence = EXCLUDED.confidence,
              metadata = EXCLUDED.metadata,
              import_run_id = EXCLUDED.import_run_id
            """,
            {**sample, "metadata": Jsonb(metadata)},
        )
        return cur.rowcount > 0


def upsert_sleep_session(conn: psycopg.Connection, session: dict[str, Any]) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO sleep_sessions
              (source, log_id, date_of_sleep, start_time, end_time, duration_seconds,
               efficiency, minutes_asleep, minutes_awake, is_main_sleep, source_file,
               metadata, import_run_id)
            VALUES
              (%(source)s, %(log_id)s, %(date_of_sleep)s, %(start_time)s, %(end_time)s,
               %(duration_seconds)s, %(efficiency)s, %(minutes_asleep)s, %(minutes_awake)s,
               %(is_main_sleep)s, %(source_file)s, %(metadata)s, %(import_run_id)s)
            ON CONFLICT (source, log_id)
            DO UPDATE SET
              date_of_sleep = EXCLUDED.date_of_sleep,
              start_time = EXCLUDED.start_time,
              end_time = EXCLUDED.end_time,
              duration_seconds = EXCLUDED.duration_seconds,
              efficiency = EXCLUDED.efficiency,
              minutes_asleep = EXCLUDED.minutes_asleep,
              minutes_awake = EXCLUDED.minutes_awake,
              is_main_sleep = EXCLUDED.is_main_sleep,
              source_file = EXCLUDED.source_file,
              metadata = EXCLUDED.metadata,
              import_run_id = EXCLUDED.import_run_id
            """,
            {**session, "metadata": Jsonb(session.get("metadata") or {})},
        )
        return cur.rowcount > 0


def upsert_sleep_stage(conn: psycopg.Connection, stage: dict[str, Any]) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO sleep_stages
              (source, log_id, ts, level, seconds, source_file, import_run_id)
            VALUES
              (%(source)s, %(log_id)s, %(ts)s, %(level)s, %(seconds)s, %(source_file)s, %(import_run_id)s)
            ON CONFLICT (source, log_id, ts, level)
            DO UPDATE SET
              seconds = EXCLUDED.seconds,
              source_file = EXCLUDED.source_file,
              import_run_id = EXCLUDED.import_run_id
            """,
            stage,
        )
        return cur.rowcount > 0


def get_fitbit_refresh_token(conn: psycopg.Connection) -> str | None:
    row = conn.execute(
        "SELECT refresh_token FROM fitbit_oauth_tokens WHERE source = 'fitbit_inspire_3'"
    ).fetchone()
    return str(row[0]) if row else None


def save_fitbit_tokens(conn: psycopg.Connection, refresh_token: str, access_token: str) -> None:
    conn.execute(
        """
        INSERT INTO fitbit_oauth_tokens (source, refresh_token, access_token, updated_at)
        VALUES ('fitbit_inspire_3', %s, %s, now())
        ON CONFLICT (source) DO UPDATE SET
          refresh_token = EXCLUDED.refresh_token,
          access_token = EXCLUDED.access_token,
          updated_at = EXCLUDED.updated_at
        """,
        (refresh_token, access_token),
    )
    conn.commit()
