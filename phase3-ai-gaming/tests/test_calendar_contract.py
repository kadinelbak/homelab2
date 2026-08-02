import importlib.util
import pathlib
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


core = load("jarvis_core", ROOT / "ai-orchestrator" / "app.py")
worker = load("google_worker", ROOT / "google-tools-worker" / "app.py")


class ContractValidationTests(unittest.TestCase):
    def test_request_text_reads_nested_inputs(self):
        self.assertEqual(core.request_text({"inputs": {"request": "nested request"}}), "nested request")

    def test_move_that_event_routes_to_calendar(self):
        payload = {"request": "Can you actually move that event by 1 hour later?", "inputs": {}}
        self.assertTrue(core.calendar_intent(payload))

    def test_create_contract(self):
        contract = core.validate_calendar_contract({
            "operation": "create", "title": "cool kids",
            "start": "2026-08-02T22:00:00-04:00", "end": "2026-08-02T23:00:00-04:00",
        })
        self.assertEqual(contract["title"], "cool kids")

    def test_ambiguous_delete_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "delete_target_ambiguous"):
            core.validate_calendar_contract({"operation": "delete"})

    def test_clarification_contract_does_not_need_target(self):
        contract = core.validate_calendar_contract({
            "operation": "clarify", "requires_clarification": True,
            "clarification": "Which event should I delete?",
        })
        self.assertTrue(contract["requires_clarification"])
        self.assertEqual(contract["operation"], "clarify")

    def test_unknown_fields_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "unknown_fields"):
            core.validate_calendar_contract({"operation": "list", "surprise": True})

    def test_contract_cache_avoids_second_model_call(self):
        payload = {"request": "list today", "inputs": {}}
        raw = '{"operation":"list","search_window":{"start":"2026-08-02T00:00:00-04:00","end":"2026-08-03T00:00:00-04:00"}}'
        core.CALENDAR_CONTRACT_CACHE.clear()
        with mock.patch.object(core, "verified_calendar_artifacts", return_value=[]), mock.patch.object(core, "call_profile_assistant", return_value=raw) as call:
            core.build_calendar_contract(payload)
            _, source = core.build_calendar_contract(payload)
        self.assertEqual(source, "nemotron_cache")
        self.assertEqual(call.call_count, 1)

    def test_bad_title_contract_is_retried_by_nemotron(self):
        payload = {"request": "Create an event titled Dentist reminder for 30 minutes tomorrow at 8 PM", "inputs": {}}
        bad = '{"operation":"create","title":"Dentist reminder for 30 minutes","start":"2026-08-03T20:00:00-04:00","end":"2026-08-03T20:30:00-04:00"}'
        good = '{"operation":"create","title":"Dentist reminder","start":"2026-08-03T20:00:00-04:00","end":"2026-08-03T20:30:00-04:00"}'
        core.CALENDAR_CONTRACT_CACHE.clear()
        with mock.patch.object(core, "verified_calendar_artifacts", return_value=[]), mock.patch.object(core, "call_profile_assistant", side_effect=[bad, good]) as call:
            contract, source = core.build_calendar_contract(payload)
        self.assertEqual(contract["title"], "Dentist reminder")
        self.assertEqual(source, "nemotron_retry")
        self.assertEqual(call.call_count, 2)

    def test_relative_move_requires_exact_verified_shift(self):
        payload = {"request": "Move that event by 1 hour later", "inputs": {}}
        artifacts = [{
            "event_id": "event12345", "title": "Dentist reminder",
            "start": "2026-08-03T20:00:00-04:00", "end": "2026-08-03T20:30:00-04:00",
            "status": "created_verified",
        }]
        contract = core.validate_calendar_contract({
            "operation": "reschedule", "target_event_id": "event12345", "title": "Dentist reminder",
            "start": "2026-08-03T21:00:00-04:00", "end": "2026-08-03T21:30:00-04:00",
        })
        self.assertEqual(core.validate_calendar_contract_semantics(payload, contract, artifacts), contract)


class ContractWorkerTests(unittest.TestCase):
    def test_create_uses_contract_fields_and_verifies(self):
        contract = {
            "operation": "create", "title": "cool kids",
            "start": "2026-08-02T22:00:00-04:00", "end": "2026-08-02T23:00:00-04:00", "attendees": [],
        }
        created = {"id": "event12345"}
        verified = {"id": "event12345", "summary": "cool kids", "start": {"dateTime": contract["start"]}, "end": {"dateTime": contract["end"]}}
        with mock.patch.object(worker, "google_request", side_effect=[created, verified]) as request:
            result = worker.execute_calendar_contract(contract)
        self.assertEqual(result["event"]["summary"], "cool kids")
        self.assertEqual(request.call_args_list[0].args[2]["summary"], "cool kids")

    def test_delete_by_verified_id_and_verify(self):
        contract = {"operation": "delete", "target_event_id": "event12345"}
        existing = {"id": "event12345", "summary": "cool kids", "start": {}, "end": {}}
        with mock.patch.object(worker, "google_request", side_effect=[existing, {}, {"id": "event12345", "status": "cancelled"}]):
            result = worker.execute_calendar_contract(contract)
        self.assertEqual(result["deleted"][0]["id"], "event12345")

    def test_attendees_require_approval(self):
        contract = {
            "operation": "create", "title": "meeting",
            "start": "2026-08-02T22:00:00-04:00", "end": "2026-08-02T23:00:00-04:00",
            "attendees": ["person@example.com"],
        }
        with self.assertRaises(PermissionError):
            worker.execute_calendar_contract(contract, approved=False)

    def test_reschedule_verifies_equivalent_timestamp(self):
        contract = {
            "operation": "reschedule", "target_event_id": "event12345",
            "start": "2026-08-02T22:00:00-04:00", "end": "2026-08-02T23:00:00-04:00",
        }
        existing = {"id": "event12345", "summary": "cool kids"}
        verified = {
            "id": "event12345", "summary": "cool kids",
            "start": {"dateTime": "2026-08-03T02:00:00Z"},
            "end": {"dateTime": "2026-08-03T03:00:00Z"},
        }
        with mock.patch.object(worker, "google_request", side_effect=[existing, {}, verified]):
            result = worker.execute_calendar_contract(contract)
        self.assertEqual(result["event"]["id"], "event12345")

    def test_worker_rejects_unknown_contract_fields(self):
        with self.assertRaisesRegex(ValueError, "unknown_fields"):
            worker.execute_calendar_contract({"operation": "list", "search_window": {}, "extra": True})


class ContractApprovalTests(unittest.TestCase):
    def test_contract_attendee_requires_approval_even_without_invite_keyword(self):
        payload = {
            "inputs": {"request": "Schedule a meeting with person@example.com"},
            "permissions": {"may_execute": False},
        }
        contract = {
            "operation": "create", "title": "meeting",
            "start": "2026-08-04T22:00:00-04:00", "end": "2026-08-04T22:30:00-04:00",
            "attendees": ["person@example.com"],
        }
        with mock.patch.object(core, "build_calendar_contract", return_value=(contract, "nemotron")):
            action = core.make_action("req-test", payload, core.capability_by_name("manage_calendar"))
        self.assertTrue(action["requires_approval"])
        self.assertEqual(action["status"], "awaiting_approval")


class ManagerRoutingTests(unittest.TestCase):
    def test_nemotron_routes_before_calendar_keyword_fallback(self):
        payload = {"request": "Move that calendar event later", "inputs": {}}
        general = core.capability_by_name("general_assistant")
        with mock.patch.object(core, "route_with_llm", return_value=(general, {"router": "external_openai_compatible"})) as router:
            capability, metadata = core.route_request(payload)
        self.assertEqual(capability["capability"], "general_assistant")
        self.assertEqual(metadata["router"], "external_openai_compatible")
        router.assert_called_once_with(payload)

    def test_email_send_safety_override_remains_after_nemotron(self):
        payload = {"request": "Send that email now", "inputs": {}}
        general = core.capability_by_name("general_assistant")
        with mock.patch.object(core, "route_with_llm", return_value=(general, {"router": "external_openai_compatible"})):
            capability, metadata = core.route_request(payload)
        self.assertEqual(capability["capability"], "manage_email")
        self.assertEqual(metadata["router"], "safety_override")


if __name__ == "__main__":
    unittest.main()
