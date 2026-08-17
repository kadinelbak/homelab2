import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jarvis_core.main import JOB_STATUS_TRANSITIONS, RUN_STATUS_TRANSITIONS


class OrchestrationContractTests(unittest.TestCase):
    def test_job_state_machine_rejects_ambiguous_completed_retry(self):
        self.assertIn("claimed", JOB_STATUS_TRANSITIONS["queued"])
        self.assertIn("running", JOB_STATUS_TRANSITIONS["claimed"])
        self.assertIn("completed", JOB_STATUS_TRANSITIONS["running"])
        self.assertNotIn("queued", JOB_STATUS_TRANSITIONS["completed"])

    def test_job_retry_is_explicit_after_failure_only(self):
        self.assertIn("queued", JOB_STATUS_TRANSITIONS["failed"])
        self.assertNotIn("running", JOB_STATUS_TRANSITIONS["failed"])

    def test_run_terminal_states_do_not_transition(self):
        self.assertEqual(RUN_STATUS_TRANSITIONS["completed"], set())
        self.assertEqual(RUN_STATUS_TRANSITIONS["failed"], set())
        self.assertEqual(RUN_STATUS_TRANSITIONS["cancelled"], set())


if __name__ == "__main__":
    unittest.main()
