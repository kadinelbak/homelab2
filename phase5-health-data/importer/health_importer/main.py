from __future__ import annotations

import argparse
import time
from datetime import date, timedelta

from . import db
from .config import load_settings
from .fitbit_export import import_export_dir
from .google_health_api import sync_date


def main() -> None:
    parser = argparse.ArgumentParser(description="Import personal health data into TimescaleDB.")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("init-db", help="Apply the health database schema.")

    export_parser = subcommands.add_parser("import-export", help="Import a Fitbit/Google JSON export directory.")
    export_parser.add_argument("--path", help="Export directory. Defaults to FITBIT_EXPORT_DIR.")
    sync_parser = subcommands.add_parser("sync-google-health", help="Pull one or more days from the Google Health API.")
    sync_parser.add_argument("--date", type=date.fromisoformat, help="Start date (YYYY-MM-DD); defaults to yesterday.")
    sync_parser.add_argument("--days", type=int, default=2, help="Number of days to pull, ending at --date or yesterday.")
    subcommands.add_parser("sync-loop", help="Pull the most recent Google Health days once per configured interval.")

    args = parser.parse_args()
    settings = load_settings()

    with db.connect(settings.database_url) as conn:
        # Apply additive schema updates before every operation. This keeps a
        # previously initialized health database compatible with new collectors.
        db.init_schema(conn)
        if args.command == "init-db":
            print("Health schema applied.")
            return

        if args.command == "import-export":
            counts = import_export_dir(conn, args.path or settings.fitbit_export_dir)
            print("Fitbit export import complete.")
            for key, value in counts.items():
                print(f"{key}: {value}")
            return

        def run_sync() -> None:
            end_date = getattr(args, "date", None) or (date.today() - timedelta(days=1))
            days = max(1, getattr(args, "days", 2))
            for offset in range(days - 1, -1, -1):
                counts = sync_date(conn, settings, end_date - timedelta(days=offset))
                print(f"Google Health API sync complete for {end_date - timedelta(days=offset)}.")
                for key, value in counts.items():
                    print(f"{key}: {value}")

        if args.command == "sync-google-health":
            run_sync()
            return

        if args.command == "sync-loop":
            while True:
                run_sync()
                time.sleep(settings.sync_interval_seconds)


if __name__ == "__main__":
    main()
