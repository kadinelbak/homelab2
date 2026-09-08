from __future__ import annotations

import json, os, time
from datetime import datetime
from zoneinfo import ZoneInfo
import requests
from psycopg.types.json import Jsonb
from .db import connect, migrate

BOT_TOKEN = os.environ.get("JARVIS_TELEGRAM_BOT_TOKEN", "")
CHAT_IDS = [item.strip() for item in os.environ.get("JARVIS_TELEGRAM_ALLOWED_CHAT_IDS", "").split(",") if item.strip()]

def send(text: str) -> None:
    if not BOT_TOKEN or not CHAT_IDS:
        raise RuntimeError("Telegram delivery is not configured")
    for chat_id in CHAT_IDS:
        response = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={"chat_id": chat_id, "text": text}, timeout=20)
        response.raise_for_status()

def deliver(conn, subject_id: int, key: str, kind: str, text: str) -> None:
    row = conn.execute("INSERT INTO notification_deliveries (subject_id,dedupe_key,kind,payload) VALUES (%s,%s,%s,%s) ON CONFLICT (dedupe_key) DO NOTHING RETURNING id", (subject_id, key, kind, Jsonb({"text": text}))).fetchone()
    if not row:
        return
    try:
        send(text)
        conn.execute("UPDATE notification_deliveries SET status='sent',attempted_at=now(),sent_at=now() WHERE id=%s", (row["id"],))
    except Exception as exc:
        conn.execute("UPDATE notification_deliveries SET status='failed',attempted_at=now(),error=%s WHERE id=%s", (str(exc)[:400], row["id"]))
    conn.commit()

def tick() -> None:
    with connect() as conn:
        for subject in conn.execute("SELECT * FROM subjects").fetchall():
            local = datetime.now(ZoneInfo(subject["timezone"]))
            minute = local.strftime("%H:%M")
            today = local.date()
            templates = conn.execute("SELECT * FROM intervention_templates WHERE subject_id=%s AND is_active AND active_from<=%s AND (active_until IS NULL OR active_until>=%s)", (subject["id"], today, today)).fetchall()
            for template in templates:
                for scheduled in template["scheduled_times"]:
                    if str(scheduled)[:5] == minute:
                        key = f"intervention:{template['id']}:{today}:{minute}"
                        text = f"N-of-1 reminder: {template['name']}" + (f" — {template['dose']} {template['unit'] or ''}".rstrip() if template["dose"] else "")
                        deliver(conn, subject["id"], key, "intervention", text)
            if minute == "20:00":
                deliver(conn, subject["id"], f"daily-checkin:{subject['id']}:{today}", "daily_checkin", "N-of-1 reminder: log today's weight, ratings, food, and intervention adherence.")

def main() -> None:
    migrate()
    while True:
        tick()
        time.sleep(30)

if __name__ == "__main__": main()
