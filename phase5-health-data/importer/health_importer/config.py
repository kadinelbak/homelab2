from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str
    fitbit_export_dir: str
    fitbit_client_id: str
    fitbit_client_secret: str
    fitbit_refresh_token: str
    timezone: str
    sync_interval_seconds: int
    google_health_client_id: str
    google_health_client_secret: str
    google_health_refresh_token: str


def load_settings() -> Settings:
    database_url = os.environ.get("HEALTH_DATABASE_URL")
    if not database_url:
        raise SystemExit("HEALTH_DATABASE_URL is required")

    return Settings(
        database_url=database_url,
        fitbit_export_dir=os.environ.get("FITBIT_EXPORT_DIR", "/health/raw/fitbit-export"),
        fitbit_client_id=os.environ.get("FITBIT_CLIENT_ID", ""),
        fitbit_client_secret=os.environ.get("FITBIT_CLIENT_SECRET", ""),
        fitbit_refresh_token=os.environ.get("FITBIT_REFRESH_TOKEN", ""),
        timezone=os.environ.get("TZ", "UTC"),
        sync_interval_seconds=int(os.environ.get("HEALTH_SYNC_INTERVAL_SECONDS", "86400")),
        google_health_client_id=os.environ.get("GOOGLE_HEALTH_CLIENT_ID", ""),
        google_health_client_secret=os.environ.get("GOOGLE_HEALTH_CLIENT_SECRET", ""),
        google_health_refresh_token=os.environ.get("GOOGLE_HEALTH_REFRESH_TOKEN", ""),
    )
