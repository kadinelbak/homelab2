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
telegram = load("telegram_bridge", ROOT / "telegram-bridge" / "app.py")


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


class GmailContractValidationTests(unittest.TestCase):
    def test_gmail_create_draft_contract(self):
        contract = core.validate_gmail_contract({
            "operation": "create_draft",
            "to": ["person@example.com"],
            "subject": "Hello",
            "body": "Hi there",
        })
        self.assertEqual(contract["operation"], "create_draft")
        self.assertEqual(contract["to"], ["person@example.com"])

    def test_gmail_unknown_fields_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "unknown_fields"):
            core.validate_gmail_contract({"operation": "search_messages", "query": "in:inbox", "extra": True})

    def test_gmail_send_requires_verified_draft_artifact(self):
        payload = {"request": "send that draft", "inputs": {}}
        contract = core.validate_gmail_contract({"operation": "send_draft", "draft_id": "draft123"})
        with self.assertRaisesRegex(ValueError, "verified_draft"):
            core.validate_gmail_contract_semantics(payload, contract, [])

    def test_explicit_send_inputs_cannot_reuse_old_draft(self):
        payload = {
            "request": "Send email",
            "inputs": {"to": ["person@example.com"], "subject": "Cool", "body": "Hello"},
        }
        contract = core.validate_gmail_contract({"operation": "send_draft", "draft_id": "draft123"})
        with self.assertRaisesRegex(ValueError, "explicit_message_must_use_send_message"):
            core.validate_gmail_contract_semantics(payload, contract, [{"draft_id": "draft123", "status": "draft_verified"}])

    def test_explicit_send_inputs_accept_send_message(self):
        payload = {
            "request": "Send email",
            "inputs": {"to": ["person@example.com"], "subject": "Cool", "body": "Hello"},
        }
        contract = core.validate_gmail_contract({
            "operation": "send_message",
            "to": ["person@example.com"],
            "subject": "Cool",
            "body": "Hello",
        })
        self.assertEqual(core.validate_gmail_contract_semantics(payload, contract, []), contract)

    def test_gmail_named_recipient_without_email_needs_retry_or_clarification(self):
        payload = {"request": "Draft an email to Sarah about tomorrow", "inputs": {}}
        contract = core.validate_gmail_contract({"operation": "create_draft", "subject": "Tomorrow", "body": "Hello"})
        with self.assertRaisesRegex(ValueError, "named_recipient_unresolved"):
            core.validate_gmail_contract_semantics(payload, contract, [])

    def test_gmail_draft_with_do_not_send_is_still_a_draft(self):
        payload = {"request": "Create a Gmail draft to person@example.com and do not send it", "inputs": {}}
        contract = core.validate_gmail_contract({
            "operation": "create_draft",
            "to": ["person@example.com"],
            "subject": "Hello",
            "body": "Hi there",
        })
        self.assertEqual(core.validate_gmail_contract_semantics(payload, contract, []), contract)

    def test_gmail_bad_contract_is_retried(self):
        payload = {"request": "Draft an email to person@example.com saying hi", "inputs": {}}
        bad = '{"operation":"create_draft","to":["person@example.com"],"subject":"Hi"}'
        good = '{"operation":"create_draft","to":["person@example.com"],"subject":"Hi","body":"Hi there."}'
        core.GMAIL_CONTRACT_CACHE.clear()
        with mock.patch.object(core, "verified_gmail_artifacts", return_value=[]), mock.patch.object(core, "call_profile_assistant", side_effect=[bad, good]) as call:
            contract, source = core.build_gmail_contract(payload)
        self.assertEqual(contract["body"], "Hi there.")
        self.assertEqual(source, "nemotron_retry")
        self.assertEqual(call.call_count, 2)

    def test_gmail_named_recipient_resolves_through_contacts(self):
        payload = {"request": "Draft an email to Sarah saying hi", "inputs": {}}
        contract = core.validate_gmail_contract({"operation": "create_draft", "subject": "Hi", "body": "Hi there."})
        with mock.patch.object(core, "call_google_tools", return_value={"status": "completed", "resolved_recipient": {"name": "Sarah", "email": "sarah@example.com"}}):
            resolved = core.resolve_gmail_named_recipient(payload, contract)
        self.assertEqual(resolved["to"], ["sarah@example.com"])


class GmailContractWorkerTests(unittest.TestCase):
    def test_gmail_create_draft_verifies(self):
        contract = {
            "operation": "create_draft",
            "to": ["person@example.com"],
            "subject": "Hello",
            "body": "Hi there",
        }
        created = {"id": "draft123", "message": {"id": "msg123", "threadId": "thread123"}}
        verified = {"id": "draft123", "message": {"id": "msg123", "threadId": "thread123"}}
        with mock.patch.object(worker, "google_request", side_effect=[created, verified]):
            result = worker.execute_gmail_contract(contract)
        self.assertEqual(result["draft"]["id"], "draft123")
        self.assertTrue(result["draft"]["verified"])

    def test_gmail_send_requires_approval(self):
        with self.assertRaises(PermissionError):
            worker.execute_gmail_contract({"operation": "send_draft", "draft_id": "draft123"}, approved=False)

    def test_gmail_send_message_requires_approval(self):
        with self.assertRaises(PermissionError):
            worker.execute_gmail_contract({
                "operation": "send_message",
                "to": ["person@example.com"],
                "subject": "Cool",
                "body": "Hello",
            }, approved=False)

    def test_gmail_label_verifies(self):
        contract = {"operation": "label_messages", "message_ids": ["msg123"], "label_ids": ["IMPORTANT"]}
        modified = {"id": "msg123"}
        verified = {"id": "msg123", "threadId": "thread123", "labelIds": ["INBOX", "IMPORTANT"], "payload": {"headers": []}}
        with mock.patch.object(worker, "google_request", side_effect=[modified, verified]):
            result = worker.execute_gmail_contract(contract, approved=True)
        self.assertEqual(result["messages"][0]["id"], "msg123")


class GmailContractApprovalTests(unittest.TestCase):
    def test_send_contract_requires_approval(self):
        payload = {"request": "Send that draft", "inputs": {}, "permissions": {"may_execute": False}}
        contract = {"operation": "send_draft", "draft_id": "draft123", "requires_clarification": False}
        with mock.patch.object(core, "build_gmail_contract", return_value=(contract, "nemotron")):
            action = core.make_action("req-gmail", payload, core.capability_by_name("manage_email"))
        self.assertTrue(action["requires_approval"])
        self.assertEqual(action["status"], "awaiting_approval")

    def test_send_message_contract_requires_approval(self):
        payload = {"request": "Send email", "inputs": {"to": ["person@example.com"], "subject": "Cool", "body": "Hello"}, "permissions": {"may_execute": False}}
        contract = {"operation": "send_message", "to": ["person@example.com"], "subject": "Cool", "body": "Hello", "requires_clarification": False}
        with mock.patch.object(core, "build_gmail_contract", return_value=(contract, "nemotron")):
            action = core.make_action("req-gmail", payload, core.capability_by_name("manage_email"))
        self.assertTrue(action["requires_approval"])
        self.assertEqual(action["status"], "awaiting_approval")

    def test_draft_contract_executes_without_approval(self):
        payload = {"request": "Draft an email", "inputs": {}, "permissions": {"may_execute": False}}
        contract = {"operation": "create_draft", "body": "Hello", "requires_clarification": False}
        with mock.patch.object(core, "build_gmail_contract", return_value=(contract, "nemotron")):
            action = core.make_action("req-gmail", payload, core.capability_by_name("manage_email"))
        self.assertFalse(action["requires_approval"])
        self.assertEqual(action["status"], "approved")


class ContactsContractTests(unittest.TestCase):
    def test_contacts_create_requires_approval(self):
        payload = {"request": "Create a contact for Sarah sarah@example.com", "inputs": {}, "permissions": {"may_execute": False}}
        contract = {"operation": "create", "name": "Sarah", "email": "sarah@example.com", "requires_clarification": False}
        with mock.patch.object(core, "build_contacts_contract", return_value=(contract, "nemotron")):
            action = core.make_action("req-contact", payload, core.capability_by_name("manage_contacts"))
        self.assertTrue(action["requires_approval"])
        self.assertEqual(action["status"], "awaiting_approval")

    def test_worker_contact_resolve_ambiguous(self):
        with mock.patch.object(worker, "contacts_search", return_value=[
            {"names": ["Sarah A"], "emails": ["a@example.com"]},
            {"names": ["Sarah B"], "emails": ["b@example.com"]},
        ]):
            result = worker.execute_contacts_contract({"operation": "resolve_recipient", "query": "Sarah"})
        self.assertEqual(result["status"], "clarification_required")


class TasksContractTests(unittest.TestCase):
    def test_tasks_create_executes_without_approval(self):
        payload = {"request": "Add task buy milk", "inputs": {}, "permissions": {"may_execute": False}}
        contract = {"operation": "create", "title": "buy milk", "requires_clarification": False}
        with mock.patch.object(core, "build_tasks_contract", return_value=(contract, "nemotron")):
            action = core.make_action("req-task", payload, core.capability_by_name("manage_tasks"))
        self.assertFalse(action["requires_approval"])
        self.assertEqual(action["status"], "approved")

    def test_worker_task_complete_verifies(self):
        contract = {"operation": "complete", "task_id": "task123"}
        with mock.patch.object(worker, "default_tasklist_id", return_value="list123"), mock.patch.object(worker, "google_request", return_value={}), mock.patch.object(worker, "task_get", return_value={"id": "task123", "title": "buy milk", "status": "completed"}):
            result = worker.execute_tasks_contract(contract)
        self.assertEqual(result["task"]["status"], "completed")


class BriefingTests(unittest.TestCase):
    def test_briefing_combines_calendar_email_and_tasks(self):
        with mock.patch.object(worker, "calendar_list", return_value={"events": []}), mock.patch.object(worker, "briefing_email_sections", return_value={"review": [], "fyi": []}), mock.patch.object(worker, "tasks_list", return_value=[]), mock.patch.object(worker, "call_github_digest", return_value={"items": [], "text": "- No GitHub items."}), mock.patch.object(worker, "fetch_weather_summary", return_value={"status": "completed", "text": "- Gainesville: 80 F"}), mock.patch.object(worker, "fetch_major_news", return_value={"status": "completed", "text": "- Headline (Source)"}):
            result = worker.build_briefing("evening")
        self.assertEqual(result["kind"], "evening")
        self.assertIn("EVENING BRIEF", result["text"])
        self.assertIn("UNRESOLVED", result["text"])

    def test_morning_briefing_includes_weather_and_news(self):
        with mock.patch.object(worker, "calendar_list", return_value={"events": []}), mock.patch.object(worker, "briefing_email_sections", return_value={"review": [], "fyi": []}), mock.patch.object(worker, "tasks_list", return_value=[]), mock.patch.object(worker, "call_github_digest", return_value={"items": [], "text": "- No GitHub items."}), mock.patch.object(worker, "fetch_weather_summary", return_value={"status": "completed", "text": "- Gainesville: 80 F"}), mock.patch.object(worker, "fetch_major_news", return_value={"status": "completed", "text": "- Headline (Source)"}):
            result = worker.build_briefing("morning")
        self.assertIn("WEATHER", result["text"])
        self.assertIn("NEWS", result["text"])


class PaperlessVerificationTests(unittest.TestCase):
    def test_paperless_document_url(self):
        self.assertTrue(telegram.paperless_document_url({"id": 123}).endswith("/documents/123/details"))


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

    def test_multi_command_splitter_extracts_ordered_commands(self):
        payload = {"request": "Find contact Sarah then add task buy milk and then build my morning briefing", "inputs": {}}
        self.assertEqual(core.split_multi_command_request(payload), [
            "Find contact Sarah",
            "add task buy milk",
            "build my morning briefing",
        ])

    def test_multi_command_request_creates_multiple_actions(self):
        payload = {
            "request": "Find contact Sarah then add task buy milk",
            "permissions": {"may_execute": False, "may_publish": False},
        }
        contacts = core.capability_by_name("manage_contacts")
        tasks = core.capability_by_name("manage_tasks")
        with mock.patch.object(core, "route_request", side_effect=[
            (contacts, {"router": "test"}),
            (tasks, {"router": "test"}),
        ]), mock.patch.object(core, "build_contacts_contract", return_value=({"operation": "search", "query": "Sarah", "requires_clarification": False}, "test")), mock.patch.object(core, "build_tasks_contract", return_value=({"operation": "create", "title": "buy milk", "requires_clarification": False}, "test")):
            actions = []
            for index, subrequest in enumerate(core.split_multi_command_request(payload)):
                sub_payload = core.payload_for_subrequest(payload, subrequest)
                capability, _ = core.route_request(sub_payload)
                action = core.make_action("req-multi", sub_payload, capability)
                action["sequence"] = index + 1
                actions.append(action)
        self.assertEqual([item["capability"] for item in actions], ["manage_contacts", "manage_tasks"])
        self.assertEqual([item["sequence"] for item in actions], [1, 2])


if __name__ == "__main__":
    unittest.main()
