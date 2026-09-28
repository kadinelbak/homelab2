import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DB_DIR = tempfile.mkdtemp()
os.environ["JARVIS_CORE_DATABASE_URL"] = f"sqlite:///{DB_DIR}/assistant-test.db"
os.environ["AI_ORCHESTRATOR_USE_OLLAMA_ROUTER"] = "false"

from fastapi.testclient import TestClient  # noqa: E402

from jarvis_core import main, router  # noqa: E402

REAL_EXECUTE_ACTION = router.execute_action
REAL_PROFILE_ASSISTANT = router.call_profile_assistant


class AssistantApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        router.call_profile_assistant = lambda prompt, profile, system=None: "stub answer"
        cls.client_cm = TestClient(main.app)
        cls.client = cls.client_cm.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_cm.__exit__(None, None, None)
        router.call_profile_assistant = REAL_PROFILE_ASSISTANT

    def plan(self, text):
        response = self.client.post("/api/v1/assistant/requests", json={"request": text, "source": "test"})
        self.assertEqual(response.status_code, 202)
        return response.json()

    def test_general_question_plans_executes_and_completes(self):
        planned = self.plan("what is the capital of France?")
        action = planned["actions"][0]
        self.assertEqual(action["capability"], "general_assistant")
        self.assertTrue(action["permissions"]["may_execute"])

        executed = self.client.post(f"/api/v1/assistant/actions/{action['action_id']}/execute").json()["action"]
        self.assertEqual(executed["status"], "completed")
        self.assertEqual(executed["result"]["text"], "stub answer")
        request = self.client.get(f"/api/v1/assistant/requests/{planned['request']['request_id']}").json()["request"]
        self.assertEqual(request["status"], "completed")

    def test_gated_action_uses_core_approval_queue(self):
        router.execute_action = lambda action: {"status": "completed", "summary": "stubbed codex run"}
        try:
            action = self.plan("refactor the telegram bridge in my homelab repo")["actions"][0]
            self.assertEqual(action["capability"], "edit_repository")
            self.assertEqual(self.client.post(f"/api/v1/assistant/actions/{action['action_id']}/execute").status_code, 409)

            pending = self.client.get("/api/v1/approvals").json()["approvals"]
            approval = next(item for item in pending if item["action"]["id"] == action["action_id"])
            decided = self.client.post(f"/api/v1/approvals/{approval['id']}/decision", json={"approved": True})
            self.assertEqual(decided.json()["status"], "approved")

            request = self.client.get(f"/api/v1/assistant/requests/{action['request_id']}").json()
            self.assertEqual(request["actions"][0]["status"], "completed")
            self.assertEqual(request["request"]["status"], "completed")
        finally:
            router.execute_action = REAL_EXECUTE_ACTION

    def test_unknown_action_is_404(self):
        self.assertEqual(self.client.post("/api/v1/assistant/actions/act_missing/execute").status_code, 404)


if __name__ == "__main__":
    unittest.main()
