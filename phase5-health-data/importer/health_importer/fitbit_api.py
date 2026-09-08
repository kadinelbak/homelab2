from __future__ import annotations

import base64
import hashlib
import json
from datetime import date, datetime, time
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from . import db
from .config import Settings

API_BASE = "https://api.fitbit.com"
TOKEN_URL = f"{API_BASE}/oauth2/token"
SOURCE = "fitbit_inspire_3"


def sync_date(conn, settings: Settings, day: date) -> dict[str, int]:
    if not settings.fitbit_client_id or not settings.fitbit_client_secret:
        raise SystemExit("FITBIT_CLIENT_ID and FITBIT_CLIENT_SECRET are required for Fitbit API sync")
    refresh_token = db.get_fitbit_refresh_token(conn) or settings.fitbit_refresh_token
    if not refresh_token:
        raise SystemExit("FITBIT_REFRESH_TOKEN is required for the first Fitbit API sync")

    access_token, refresh_token = refresh_access_token(settings, refresh_token)
    db.save_fitbit_tokens(conn, refresh_token, access_token)
    run_id = db.start_import_run(conn, "fitbit_api", day.isoformat())
    counts = {"files_seen": 0, "raw_documents_inserted": 0, "metric_samples_inserted": 0, "sleep_sessions_inserted": 0, "sleep_stages_inserted": 0}
    try:
        resources = {
            "heart_rate": f"/1/user/-/activities/heart/date/{day}/{day}/1min.json",
            "steps": f"/1/user/-/activities/steps/date/{day}/{day}/1min.json",
            "calories": f"/1/user/-/activities/calories/date/{day}/{day}/1min.json",
            "distance": f"/1/user/-/activities/distance/date/{day}/{day}/1min.json",
            "sleep": f"/1.2/user/-/sleep/date/{day}.json",
        }
        for metric, path in resources.items():
            payload = get_json(path, access_token)
            source_file = f"api/{day.isoformat()}/{metric}.json"
            counts["files_seen"] += 1
            digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
            if db.insert_raw_document(conn, "fitbit_api", source_file, digest, payload, run_id):
                counts["raw_documents_inserted"] += 1
            if metric == "sleep":
                _store_sleep(conn, payload, source_file, run_id, counts)
            else:
                _store_metric(conn, payload, metric, day, settings.timezone, source_file, run_id, counts)
            conn.commit()
        db.finish_import_run(conn, run_id, "success", counts)
        return counts
    except Exception as exc:
        conn.rollback()
        db.finish_import_run(conn, run_id, "failed", counts, str(exc))
        raise


def refresh_access_token(settings: Settings, refresh_token: str) -> tuple[str, str]:
    basic = base64.b64encode(f"{settings.fitbit_client_id}:{settings.fitbit_client_secret}".encode()).decode()
    request = Request(TOKEN_URL, data=urlencode({"grant_type": "refresh_token", "refresh_token": refresh_token}).encode(), headers={"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    with urlopen(request, timeout=30) as response:
        payload = json.load(response)
    return str(payload["access_token"]), str(payload["refresh_token"])


def get_json(path: str, access_token: str) -> dict[str, Any]:
    request = Request(f"{API_BASE}{path}", headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"})
    try:
        with urlopen(request, timeout=30) as response:
            return json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"Fitbit API request failed for {path}: HTTP {exc.code}") from exc


def _store_metric(conn, payload: dict[str, Any], metric: str, day: date, timezone: str, source_file: str, run_id: int, counts: dict[str, int]) -> None:
    key = f"activities-{metric}-intraday"
    dataset = (payload.get(key) or {}).get("dataset") or []
    unit = {"heart_rate": "bpm", "steps": "count", "calories": "kcal", "distance": "km"}[metric]
    for item in dataset:
        if not isinstance(item, dict) or "time" not in item or "value" not in item:
            continue
        ts = datetime.combine(day, time.fromisoformat(str(item["time"])), tzinfo=ZoneInfo(timezone))
        sample = {"ts": ts, "metric_type": metric, "value": float(item["value"]), "unit": unit, "source": SOURCE, "source_file": source_file, "confidence": None, "metadata": {}, "import_run_id": run_id}
        if db.upsert_metric_sample(conn, sample):
            counts["metric_samples_inserted"] += 1


def _store_sleep(conn, payload: dict[str, Any], source_file: str, run_id: int, counts: dict[str, int]) -> None:
    for record in payload.get("sleep") or []:
        if not isinstance(record, dict):
            continue
        log_id = str(record.get("logId") or record.get("startTime"))
        session = {"source": SOURCE, "log_id": log_id, "date_of_sleep": date.fromisoformat(record["dateOfSleep"]) if record.get("dateOfSleep") else None, "start_time": _timestamp(record.get("startTime")), "end_time": _timestamp(record.get("endTime")), "duration_seconds": int(record.get("duration", 0)) // 1000, "efficiency": record.get("efficiency"), "minutes_asleep": record.get("minutesAsleep"), "minutes_awake": record.get("minutesAwake"), "is_main_sleep": record.get("isMainSleep"), "source_file": source_file, "metadata": {"type": record.get("type"), "time_in_bed": record.get("timeInBed")}, "import_run_id": run_id}
        if db.upsert_sleep_session(conn, session):
            counts["sleep_sessions_inserted"] += 1
        for level in (record.get("levels") or {}).get("data") or []:
            if not isinstance(level, dict) or not level.get("dateTime"):
                continue
            stage = {"source": SOURCE, "log_id": log_id, "ts": _timestamp(level["dateTime"]), "level": str(level.get("level", "unknown")), "seconds": int(level.get("seconds") or 0), "source_file": source_file, "import_run_id": run_id}
            if db.upsert_sleep_stage(conn, stage):
                counts["sleep_stages_inserted"] += 1


def _timestamp(value: str | None):
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
