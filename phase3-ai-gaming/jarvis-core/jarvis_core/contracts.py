from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class RiskLevel(str, Enum):
    READ_ONLY = "READ_ONLY"
    LOW_RISK_WRITE = "LOW_RISK_WRITE"
    EXTERNAL_WRITE = "EXTERNAL_WRITE"
    SENSITIVE = "SENSITIVE"
    DESTRUCTIVE = "DESTRUCTIVE"


class ActionStatus(str, Enum):
    PROPOSED = "proposed"
    AWAITING_APPROVAL = "awaiting_approval"
    DENIED = "denied"
    APPROVED = "approved"
    COMPLETED = "completed"
    FAILED = "failed"


APPROVAL_REQUIRED = {
    RiskLevel.EXTERNAL_WRITE,
    RiskLevel.SENSITIVE,
    RiskLevel.DESTRUCTIVE,
}


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    version: str
    description: str
    risk_level: RiskLevel
    required_permissions: tuple[str, ...]
    reversible: bool


@dataclass(frozen=True)
class CalendarIntent:
    title: str
    starts_at: datetime
    duration_minutes: int
    timezone: str
    calendar_target: str
    assumptions: tuple[str, ...]

    @property
    def ends_at(self) -> datetime:
        return self.starts_at + timedelta(minutes=self.duration_minutes)


def requires_approval(risk_level: RiskLevel) -> bool:
    return risk_level in APPROVAL_REQUIRED


def safe_id(prefix: str, raw: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", raw).strip("-").lower()
    return f"{prefix}_{cleaned[:24]}" if cleaned else prefix


def redact(value):
    if isinstance(value, dict):
        return {
            key: ("[REDACTED]" if any(token in key.lower() for token in ("token", "secret", "password", "key")) else redact(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def parse_calendar_request(text: str, user_timezone: str, now: datetime | None = None) -> CalendarIntent | None:
    source = text.strip()
    lowered = source.lower()
    if "schedule" not in lowered and "calendar" not in lowered:
        return None

    duration = 60
    duration_match = re.search(r"\b(\d+)\s*(minute|minutes|min|hour|hours|hr|hrs)\b", lowered)
    if duration_match:
        amount = int(duration_match.group(1))
        unit = duration_match.group(2)
        duration = amount * 60 if unit.startswith(("hour", "hr")) else amount

    title = "Scheduled focus block"
    title_match = re.search(r"\bto\s+(.+?)(?:\.|$)", source, re.IGNORECASE)
    if title_match:
        title = title_match.group(1).strip()
    title = re.sub(r"^(prepare|work|study)\s+", lambda match: match.group(0).capitalize(), title)

    tz = _zone(user_timezone)
    current = (now or datetime.now(tz)).astimezone(tz)
    weekday = _weekday_from_text(lowered)
    if weekday is None:
        return None
    days_ahead = (weekday - current.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    target_date = (current + timedelta(days=days_ahead)).date()

    hour = 18
    minute = 0
    assumptions = [f"Interpreted '{_weekday_name(weekday)} evening' as 6:00 PM local time."]
    time_match = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", lowered)
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2) or "0")
        meridiem = time_match.group(3)
        if meridiem == "pm" and hour != 12:
            hour += 12
        if meridiem == "am" and hour == 12:
            hour = 0
        assumptions = []
    elif "morning" in lowered:
        hour = 9
        assumptions = [f"Interpreted '{_weekday_name(weekday)} morning' as 9:00 AM local time."]
    elif "afternoon" in lowered:
        hour = 14
        assumptions = [f"Interpreted '{_weekday_name(weekday)} afternoon' as 2:00 PM local time."]

    starts_at = datetime(target_date.year, target_date.month, target_date.day, hour, minute, tzinfo=tz)
    return CalendarIntent(
        title=title[0].upper() + title[1:] if title else "Scheduled focus block",
        starts_at=starts_at.astimezone(timezone.utc),
        duration_minutes=duration,
        timezone=user_timezone,
        calendar_target="development-calendar",
        assumptions=tuple(assumptions),
    )


def _weekday_from_text(text: str) -> int | None:
    names = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
    for index, name in enumerate(names):
        if name in text:
            return index
    return None


def _weekday_name(index: int) -> str:
    return ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")[index]


def _zone(name: str):
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        if name == "America/New_York":
            return timezone(timedelta(hours=-4), name)
        return timezone.utc


REGISTERED_TOOLS = (
    ToolDefinition(
        name="calendar.schedule_google_event",
        version="1.0",
        description="Create a verified Google Calendar event through the Google tools worker after approval.",
        risk_level=RiskLevel.EXTERNAL_WRITE,
        required_permissions=("calendar:write:google",),
        reversible=True,
    ),
    ToolDefinition(
        name="calendar.schedule_simulated_event",
        version="1.0",
        description="Create a simulated calendar event in Jarvis Core for development fallback only.",
        risk_level=RiskLevel.EXTERNAL_WRITE,
        required_permissions=("calendar:write:simulated",),
        reversible=True,
    ),
    ToolDefinition(
        name="media.social_image.create",
        version="0.1",
        description="Create an approval-gated media workflow run through media-creation-pipeline.",
        risk_level=RiskLevel.EXTERNAL_WRITE,
        required_permissions=("media:create",),
        reversible=False,
    ),
    ToolDefinition(
        name="homelab.container_health.read",
        version="0.1",
        description="Allowlisted read-only homelab service health check.",
        risk_level=RiskLevel.READ_ONLY,
        required_permissions=("homelab:read",),
        reversible=True,
    ),
    ToolDefinition(
        name="codex.run_task",
        version="1.0",
        description="Run an approval-gated Codex coding task in the mounted Jarvis workspace.",
        risk_level=RiskLevel.EXTERNAL_WRITE,
        required_permissions=("codex:run",),
        reversible=True,
    ),
    ToolDefinition(
        name="drive.copy_to_staging",
        version="0.1",
        description="Copy approved Google Drive files into a homelab staging folder without modifying Google originals.",
        risk_level=RiskLevel.EXTERNAL_WRITE,
        required_permissions=("drive:read", "storage:write:staging"),
        reversible=True,
    ),
    ToolDefinition(
        name="drive.import_to_nextcloud",
        version="0.1",
        description="Copy approved staged Google Drive files into the Nextcloud import queue without modifying Google originals.",
        risk_level=RiskLevel.EXTERNAL_WRITE,
        required_permissions=("storage:read:staging", "nextcloud:write:import_queue"),
        reversible=True,
    ),
    ToolDefinition(
        name="drive.import_to_paperless",
        version="0.1",
        description="Queue approved staged Google Drive documents into Paperless consume with suggested tags.",
        risk_level=RiskLevel.EXTERNAL_WRITE,
        required_permissions=("storage:read:staging", "paperless:write:consume"),
        reversible=True,
    ),
    ToolDefinition(
        name="gmail.apply_cleanup",
        version="0.1",
        description="Apply approved Gmail cleanup label/archive changes after a read-only cleanup summary.",
        risk_level=RiskLevel.EXTERNAL_WRITE,
        required_permissions=("gmail:modify",),
        reversible=True,
    ),
)
