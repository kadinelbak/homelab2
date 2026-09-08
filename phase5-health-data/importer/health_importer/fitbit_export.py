from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import date, datetime
from pathlib import Path
from typing import Any

FITBIT_SOURCE = "fitbit_inspire_3"


def import_export_dir(conn, export_dir: str) -> dict[str, int]:
    from . import db

    root = Path(export_dir)
    if not root.exists():
        raise FileNotFoundError(f"Fitbit export directory does not exist: {root}")

    run_id = db.start_import_run(conn, "fitbit_export", str(root))
    counts = {
        "files_seen": 0,
        "raw_documents_inserted": 0,
        "metric_samples_inserted": 0,
        "sleep_sessions_inserted": 0,
        "sleep_stages_inserted": 0,
    }

    try:
        for path in sorted(root.rglob("*.json")):
            counts["files_seen"] += 1
            rel_path = path.relative_to(root).as_posix()
            text = path.read_text(encoding="utf-8")
            payload = json.loads(text)
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()

            if db.insert_raw_document(conn, "fitbit_export", rel_path, digest, payload, run_id):
                counts["raw_documents_inserted"] += 1

            for sample in extract_metric_samples(payload, rel_path, run_id):
                if db.upsert_metric_sample(conn, sample):
                    counts["metric_samples_inserted"] += 1

            for session, stages in extract_sleep(payload, rel_path, run_id):
                if db.upsert_sleep_session(conn, session):
                    counts["sleep_sessions_inserted"] += 1
                for stage in stages:
                    if db.upsert_sleep_stage(conn, stage):
                        counts["sleep_stages_inserted"] += 1

            conn.commit()

        db.finish_import_run(conn, run_id, "success", counts)
        return counts
    except Exception as exc:
        conn.rollback()
        db.finish_import_run(conn, run_id, "failed", counts, str(exc))
        raise


def extract_metric_samples(payload: Any, source_file: str, import_run_id: int) -> Iterable[dict[str, Any]]:
    metric_hint = metric_from_filename(source_file)
    records = payload if isinstance(payload, list) else [payload]

    for record in records:
        if not isinstance(record, dict):
            continue

        if "dateTime" not in record:
            continue

        ts = parse_timestamp(record["dateTime"])
        value = record.get("value")

        if isinstance(value, dict) and "bpm" in value:
            yield sample(ts, "heart_rate", value["bpm"], "bpm", source_file, import_run_id, value)
            continue

        if isinstance(value, dict) and "value" in value and metric_hint:
            yield sample(ts, metric_hint, value["value"], unit_for_metric(metric_hint), source_file, import_run_id, value)
            continue

        if isinstance(value, (int, float, str)) and metric_hint:
            yield sample(ts, metric_hint, value, unit_for_metric(metric_hint), source_file, import_run_id, {})


def extract_sleep(payload: Any, source_file: str, import_run_id: int) -> Iterable[tuple[dict[str, Any], list[dict[str, Any]]]]:
    records = payload if isinstance(payload, list) else [payload]

    for record in records:
        if not isinstance(record, dict):
            continue
        if not ("logId" in record or "dateOfSleep" in record):
            continue

        log_id = str(record.get("logId") or f"{source_file}:{record.get('startTime', '')}")
        session = {
            "source": FITBIT_SOURCE,
            "log_id": log_id,
            "date_of_sleep": parse_date(record.get("dateOfSleep")),
            "start_time": parse_optional_timestamp(record.get("startTime")),
            "end_time": parse_optional_timestamp(record.get("endTime")),
            "duration_seconds": millis_to_seconds(record.get("duration")),
            "efficiency": optional_int(record.get("efficiency")),
            "minutes_asleep": optional_int(record.get("minutesAsleep")),
            "minutes_awake": optional_int(record.get("minutesAwake")),
            "is_main_sleep": record.get("isMainSleep"),
            "source_file": source_file,
            "metadata": {
                "type": record.get("type"),
                "info_code": record.get("infoCode"),
                "time_in_bed": record.get("timeInBed"),
            },
            "import_run_id": import_run_id,
        }

        stages = []
        levels = record.get("levels") or {}
        for level_record in levels.get("data") or []:
            if not isinstance(level_record, dict) or "dateTime" not in level_record:
                continue
            stages.append(
                {
                    "source": FITBIT_SOURCE,
                    "log_id": log_id,
                    "ts": parse_timestamp(level_record["dateTime"]),
                    "level": str(level_record.get("level", "unknown")),
                    "seconds": int(level_record.get("seconds") or 0),
                    "source_file": source_file,
                    "import_run_id": import_run_id,
                }
            )

        yield session, stages


def metric_from_filename(source_file: str) -> str | None:
    name = source_file.lower()
    mapping = {
        "heart_rate": "heart_rate",
        "steps": "steps",
        "calories": "calories",
        "distance": "distance",
        "very_active_minutes": "very_active_minutes",
        "moderately_active_minutes": "moderately_active_minutes",
        "lightly_active_minutes": "lightly_active_minutes",
        "sedentary_minutes": "sedentary_minutes",
        "resting_heart_rate": "resting_heart_rate",
        "spo2": "spo2",
        "breathing_rate": "breathing_rate",
    }
    for needle, metric in mapping.items():
        if needle in name:
            return metric
    return None


def sample(
    ts,
    metric_type: str,
    raw_value: Any,
    unit: str | None,
    source_file: str,
    import_run_id: int,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    return {
        "ts": ts,
        "metric_type": metric_type,
        "value": float(raw_value),
        "unit": unit,
        "source": FITBIT_SOURCE,
        "source_file": source_file,
        "confidence": optional_int(metadata.get("confidence")),
        "metadata": metadata,
        "import_run_id": import_run_id,
    }


def unit_for_metric(metric_type: str) -> str | None:
    return {
        "heart_rate": "bpm",
        "resting_heart_rate": "bpm",
        "steps": "count",
        "calories": "kcal",
        "distance": "km",
        "spo2": "percent",
        "breathing_rate": "breaths/min",
    }.get(metric_type)


def parse_timestamp(value: Any):
    text = str(value).strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    return datetime.fromisoformat(text)


def parse_optional_timestamp(value: Any):
    return parse_timestamp(value) if value else None


def parse_date(value: Any):
    if not value:
        return None
    parsed = parse_timestamp(str(value))
    return date(parsed.year, parsed.month, parsed.day)


def millis_to_seconds(value: Any) -> int | None:
    if value is None:
        return None
    return int(int(value) / 1000)


def optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)
