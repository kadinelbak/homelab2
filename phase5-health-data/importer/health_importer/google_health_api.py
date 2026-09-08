from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from . import db
from .config import Settings

API_BASE = "https://health.googleapis.com/v4"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SOURCE = "google_health_fitbit_inspire_3"


def sync_date(conn, settings: Settings, day: date) -> dict[str, int]:
    if not all((settings.google_health_client_id, settings.google_health_client_secret, settings.google_health_refresh_token)):
        raise SystemExit("GOOGLE_HEALTH_CLIENT_ID, GOOGLE_HEALTH_CLIENT_SECRET, and GOOGLE_HEALTH_REFRESH_TOKEN are required")
    token = _access_token(settings)
    run_id = db.start_import_run(conn, "google_health_api", day.isoformat())
    counts = {"files_seen": 0, "raw_documents_inserted": 0, "metric_samples_inserted": 0, "sleep_sessions_inserted": 0, "sleep_stages_inserted": 0}
    try:
        for data_type, metric, filter_name, kind in (
            ("steps", "steps", "steps", "interval"),
            ("distance", "distance", "distance", "interval"),
            ("active-energy-burned", "calories", "active_energy_burned", "interval"),
            ("heart-rate", "heart_rate", "heart_rate", "sample"),
            ("sleep", None, "sleep", "sleep"),
            ("exercise", None, "exercise", "interval"),
        ):
            records = _list(data_type, filter_name, kind, day, token)
            source_file = f"google-health/{day}/{data_type}.json"
            payload = {"dataPoints": records}
            counts["files_seen"] += 1
            digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
            if db.insert_raw_document(conn, "google_health_api", source_file, digest, payload, run_id): counts["raw_documents_inserted"] += 1
            if metric:
                for record in records: _store_metric(conn, record, data_type, metric, source_file, run_id, counts)
            elif data_type == "sleep":
                for record in records: _store_sleep(conn, record, source_file, run_id, counts)
            conn.commit()
        db.finish_import_run(conn, run_id, "success", counts)
        return counts
    except Exception as exc:
        conn.rollback(); db.finish_import_run(conn, run_id, "failed", counts, str(exc)); raise


def _access_token(s: Settings) -> str:
    body = urlencode({"client_id": s.google_health_client_id, "client_secret": s.google_health_client_secret, "refresh_token": s.google_health_refresh_token, "grant_type": "refresh_token"}).encode()
    with urlopen(Request(TOKEN_URL, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST"), timeout=30) as r: return str(json.load(r)["access_token"])


def _list(data_type: str, filter_name: str, kind: str, day: date, token: str) -> list[dict[str, Any]]:
    # Fetch all available pages. The API reconciles current data server-side;
    # database upserts make periodic re-reads idempotent and avoid timezone
    # filter edge cases around sleep sessions and daylight saving transitions.
    url = f"{API_BASE}/users/me/dataTypes/{data_type}/dataPoints?{urlencode({'pageSize': 1000})}"
    result: list[dict[str, Any]] = []
    while url:
        with urlopen(Request(url, headers={"Authorization": f"Bearer {token}"}), timeout=30) as r: payload = json.load(r)
        result.extend(payload.get("dataPoints") or [])
        page = payload.get("nextPageToken")
        url = f"{API_BASE}/users/me/dataTypes/{data_type}/dataPoints?{urlencode({'pageSize': 1000, 'pageToken': page})}" if page else ""
    return result


def _store_metric(conn, record, data_type, metric, source_file, run_id, counts):
    key = "".join(part.title() if i else part for i, part in enumerate(data_type.split("-")))
    payload = record.get(key) or {}
    if data_type == "steps": value, when = payload.get("count"), (payload.get("interval") or {}).get("startTime")
    elif data_type == "heart-rate": value, when = payload.get("beatsPerMinute"), (payload.get("sampleTime") or {}).get("physicalTime")
    else: value, when = payload.get("energyKilocalories") or payload.get("distanceMeters"), (payload.get("interval") or {}).get("startTime")
    if value is None or not when: return
    sample = {"ts": _ts(when), "metric_type": metric, "value": float(value), "unit": {"steps":"count","heart_rate":"bpm","calories":"kcal","distance":"m"}.get(metric), "source": SOURCE, "source_file": source_file, "confidence": None, "metadata": {"data_source": record.get("dataSource")}, "import_run_id": run_id}
    if db.upsert_metric_sample(conn, sample): counts["metric_samples_inserted"] += 1


def _store_sleep(conn, record, source_file, run_id, counts):
    payload = record.get("sleep") or {}; interval = payload.get("interval") or {}; start, end = interval.get("startTime"), interval.get("endTime")
    if not start or not end: return
    log_id = record.get("name") or hashlib.sha256(f"{start}:{end}".encode()).hexdigest()
    session = {"source": SOURCE, "log_id": log_id, "date_of_sleep": _ts(end).date(), "start_time": _ts(start), "end_time": _ts(end), "duration_seconds": int((_ts(end)-_ts(start)).total_seconds()), "efficiency": None, "minutes_asleep": None, "minutes_awake": None, "is_main_sleep": True, "source_file": source_file, "metadata": payload.get("summary") or {}, "import_run_id": run_id}
    if db.upsert_sleep_session(conn, session): counts["sleep_sessions_inserted"] += 1


def _ts(value: str) -> datetime: return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
