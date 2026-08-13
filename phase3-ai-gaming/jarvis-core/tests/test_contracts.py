import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jarvis_core.contracts import RiskLevel, parse_calendar_request, redact, requires_approval


class ContractTests(unittest.TestCase):
    def test_calendar_parser_handles_interview_example(self):
        now = datetime(2026, 8, 10, 10, 0, tzinfo=timezone(timedelta(hours=-4), "America/New_York"))
        intent = parse_calendar_request(
            "Schedule 90 minutes on Tuesday evening to prepare for my EnMed interview.",
            "America/New_York",
            now=now,
        )

        self.assertIsNotNone(intent)
        self.assertEqual(intent.duration_minutes, 90)
        self.assertEqual(intent.title, "Prepare for my EnMed interview")
        self.assertEqual(intent.starts_at.isoformat(), "2026-08-11T22:00:00+00:00")
        self.assertEqual(intent.calendar_target, "development-calendar")

    def test_external_write_requires_approval(self):
        self.assertTrue(requires_approval(RiskLevel.EXTERNAL_WRITE))
        self.assertFalse(requires_approval(RiskLevel.READ_ONLY))

    def test_redaction_removes_secret_like_fields(self):
        payload = {"api_key": "abc", "nested": {"password": "secret", "safe": "ok"}}
        self.assertEqual(redact(payload)["api_key"], "[REDACTED]")
        self.assertEqual(redact(payload)["nested"]["password"], "[REDACTED]")
        self.assertEqual(redact(payload)["nested"]["safe"], "ok")


if __name__ == "__main__":
    unittest.main()
