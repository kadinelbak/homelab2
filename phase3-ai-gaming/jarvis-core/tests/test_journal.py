import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DB_DIR = tempfile.mkdtemp()
os.environ["JARVIS_CORE_DATABASE_URL"] = f"sqlite:///{DB_DIR}/journal-test.db"

from fastapi.testclient import TestClient  # noqa: E402

from jarvis_core import main  # noqa: E402

REAL_MODEL = main.call_openai_compatible_model


class JournalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client_cm = TestClient(main.app)
        cls.client = cls.client_cm.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_cm.__exit__(None, None, None)
        main.call_openai_compatible_model = REAL_MODEL

    def test_voice_entry_is_structured_and_listed(self):
        reply = {"title": "Climbing with Sam", "summary": "I went climbing.", "mood": "happy", "highlights": ["sent a V4"], "people": ["Sam"], "todos": [], "tags": ["climbing"]}
        main.call_openai_compatible_model = lambda **kwargs: {"content": "```json\n" + json.dumps(reply) + "\n```"}
        created = self.client.post("/api/v1/journal", json={"text": "Went climbing with Sam today and sent a V4.", "source": "telegram-voice"})
        self.assertEqual(created.status_code, 200)
        entry = created.json()["entry"]
        self.assertEqual(entry["title"], "Climbing with Sam")
        self.assertEqual(entry["people"], ["Sam"])
        self.assertEqual(entry["gratitude"], [])
        self.assertTrue(entry["structured_ok"])

        listed = self.client.get("/api/v1/journal", params={"days": 1, "q": "climbing"}).json()["entries"]
        self.assertEqual([item["id"] for item in listed], [entry["id"]])

    def test_entry_is_kept_when_model_fails(self):
        def fail(**kwargs):
            raise RuntimeError("model down")

        main.call_openai_compatible_model = fail
        entry = self.client.post("/api/v1/journal", json={"text": "Rough day, but dinner was good."}).json()["entry"]
        self.assertFalse(entry["structured_ok"])
        self.assertEqual(entry["title"], "Rough day, but dinner was good.")
        self.assertEqual(entry["transcript"], "Rough day, but dinner was good.")


if __name__ == "__main__":
    unittest.main()
