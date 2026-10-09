import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DB_DIR = tempfile.mkdtemp()
os.environ.setdefault("JARVIS_CORE_DATABASE_URL", f"sqlite:///{DB_DIR}/people-test.db")

from fastapi.testclient import TestClient  # noqa: E402

from jarvis_core import main  # noqa: E402

REAL_MODEL = main.call_openai_compatible_model


class PeopleApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client_cm = TestClient(main.app)
        cls.client = cls.client_cm.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_cm.__exit__(None, None, None)
        main.call_openai_compatible_model = REAL_MODEL

    def stub_model(self, content):
        main.call_openai_compatible_model = lambda *args, **kwargs: {"content": content}

    def test_note_is_split_by_model_and_read_back_grouped(self):
        self.stub_model(
            'Sure: [{"person": "Maya Torres", "kind": "personality", "text": "Dry sense of humor."},'
            ' {"person": "Maya Torres", "kind": "key_moment", "text": "Told me she got into grad school."},'
            ' {"person": "Maya Torres", "kind": "follow_up", "text": "Ask how the move goes"},'
            ' {"person": "Maya Torres", "kind": "nonsense", "text": "Has a cat."}]'
        )
        saved = self.client.post("/api/v1/people/notes", json={"text": "Coffee with Maya Torres..."}).json()
        self.assertEqual(len(saved["facts"]), 4)
        self.assertEqual(saved["facts"][3]["kind"], "other")

        profile = self.client.get("/api/v1/people/maya").json()
        self.assertEqual(profile["person"], "Maya Torres")
        self.assertEqual([item["text"] for item in profile["sections"]["key_moment"]], ["Told me she got into grad school."])
        self.assertIn("Follow up next time: Ask how the move goes.", profile["text"])
        self.assertIn("Maya Torres", [item["person"] for item in self.client.get("/api/v1/people").json()["people"]])

    def test_falls_back_to_whole_note_when_model_fails(self):
        def broken(*args, **kwargs):
            raise RuntimeError("model down")

        main.call_openai_compatible_model = broken
        saved = self.client.post("/api/v1/people/notes", json={"text": "note about Jordan: loves climbing"}).json()
        self.assertEqual(saved["facts"], [{"person": "Jordan", "kind": "other", "text": "note about Jordan: loves climbing"}])
        self.assertEqual(self.client.post("/api/v1/people/notes", json={"text": "had a good day"}).status_code, 422)

        note_id = self.client.get("/api/v1/people/jordan").json()["sections"]["other"][0]["id"]
        self.assertTrue(self.client.delete(f"/api/v1/people/notes/{note_id}").json()["ok"])
        self.assertEqual(self.client.get("/api/v1/people/jordan").status_code, 404)


if __name__ == "__main__":
    unittest.main()
