import importlib.util
import pathlib
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


worker = load("decision_google_worker", ROOT / "google-tools-worker" / "app.py")
telegram = load("decision_telegram_bridge", ROOT / "telegram-bridge" / "app.py")

sys.modules.setdefault("jwt", types.SimpleNamespace(encode=lambda *args, **kwargs: "jwt"))
github_worker = load("decision_github_worker", ROOT / "github-tools-worker" / "app.py")


class BriefingProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.profile_path = pathlib.Path(self.tmpdir.name) / "profile.sqlite3"
        self.profile_patch = mock.patch.object(worker, "PROFILE_DB_PATH", self.profile_path)
        self.profile_patch.start()

    def tearDown(self):
        self.profile_patch.stop()
        self.tmpdir.cleanup()

    def test_default_profile_uses_gainesville(self):
        profile = worker.get_briefing_profile()
        self.assertEqual(profile["current_city"], "Gainesville")
        self.assertEqual(profile["watched_repos"], [])

    def test_update_profile_filters_invalid_repos_and_notes(self):
        result = worker.update_briefing_profile(
            {"current_city": "Gainesville", "watched_repos": ["owner/repo", "bad repo"]}
        )
        self.assertEqual(result["profile"]["watched_repos"], ["owner/repo"])
        note = worker.add_briefing_note("MCAT is top priority")
        self.assertEqual(note["status"], "completed")
        self.assertEqual(len(worker.get_briefing_profile()["notes"]), 1)
        worker.delete_briefing_note(note["note"]["id"])
        self.assertEqual(worker.get_briefing_profile()["notes"], [])


class WeatherAndComposerTests(unittest.TestCase):
    def test_weather_filters_to_current_city_only(self):
        payload = {
            "cities": [
                {"id": "okc", "name": "Oklahoma City", "label": "Hot"},
                {"id": "gainesville", "name": "Gainesville", "label": "Rain likely"},
            ]
        }
        fake_response = mock.Mock()
        fake_response.__enter__ = mock.Mock(return_value=fake_response)
        fake_response.__exit__ = mock.Mock(return_value=False)
        fake_response.read.return_value = worker.json.dumps(payload).encode("utf-8")
        with mock.patch.object(worker.urllib.request, "urlopen", return_value=fake_response):
            result = worker.fetch_weather_summary("Gainesville")
        self.assertEqual(len(result["cities"]), 1)
        self.assertIn("Gainesville", result["text"])
        self.assertNotIn("Oklahoma City", result["text"])

    def test_morning_brief_uses_decision_sections(self):
        text = worker.compose_morning_brief(
            {"events": [{"summary": "Research meeting", "start": {"dateTime": "2026-08-03T09:00:00-04:00"}}]},
            {"review": [{"from": "Professor <p@example.edu>", "subject": "Deadline", "snippet": "Reply today", "labels": ["IMPORTANT", "UNREAD"]}], "fyi": []},
            [{"title": "Draft MCAT plan", "due": "2026-08-03T20:00:00Z", "status": "needsAction"}],
            {"text": "- Gainesville: Rain likely"},
            {"text": "- Major headline (Source)"},
            {"items": [{"repo": "owner/repo", "title": "PR needs review"}]},
            {"active_projects": ["MCAT"], "important_senders": ["professor"], "ignored_topics": []},
        )
        for section in ("TODAY", "TOP 3", "RISKS", "MESSAGES", "PROJECTS", "GITHUB", "WEATHER", "NEWS", "ONE QUESTION"):
            self.assertIn(section, text)
        self.assertIn("Gainesville", text)
        self.assertIn("owner/repo", text)

    def test_morning_brief_uses_speakable_calendar_and_sender_text(self):
        text = worker.compose_morning_brief(
            {
                "events": [
                    {
                        "summary": "Dentist reminder",
                        "start": {"dateTime": "2026-08-03T21:00:00-04:00"},
                        "end": {"dateTime": "2026-08-03T21:30:00-04:00"},
                    }
                ]
            },
            {
                "review": [
                    {
                        "from": "Google <no-reply@accounts.google.com>",
                        "subject": "Security alert",
                        "snippet": "Review account access",
                        "labels": ["IMPORTANT", "UNREAD"],
                    }
                ],
                "fyi": [],
            },
            [],
            {"text": "- Gainesville: Rain likely"},
            {"text": "- Headline - AP News (AP News)"},
            {"items": []},
            {"active_projects": [], "important_senders": [], "ignored_topics": []},
        )
        self.assertIn("9pm to 9:30pm: Dentist reminder", text)
        self.assertIn("Google Accounts: Security alert", text)
        self.assertNotIn("no-reply@accounts.google.com", text)
        self.assertIn("Headline - AP News", text)
        self.assertNotIn("(AP News)", text)


class TelegramBriefingCommandTests(unittest.TestCase):
    def test_city_commands_update_profile(self):
        with mock.patch.object(telegram, "update_profile", return_value={"profile": {"current_city": "Gainesville"}}):
            self.assertIn("Gainesville", telegram.handle_command(123, "/setcity Gainesville"))
        with mock.patch.object(telegram, "get_profile", return_value={"profile": {"current_city": "Gainesville"}}):
            self.assertIn("Gainesville", telegram.handle_command(123, "/city"))

    def test_watchrepo_updates_profile(self):
        with mock.patch.object(telegram, "get_profile", return_value={"profile": {"watched_repos": []}}), mock.patch.object(telegram, "update_profile") as update:
            response = telegram.handle_command(123, "/watchrepo owner/repo")
        self.assertIn("owner/repo", response)
        update.assert_called_with({"watched_repos": ["owner/repo"]})

    def test_voice_failure_falls_back_to_text_notice(self):
        with mock.patch.object(telegram, "BRIEFING_VOICE_ENABLED", True), mock.patch.object(telegram, "synthesize_voice", side_effect=RuntimeError("tts down")), mock.patch.object(telegram, "send_message") as send:
            result = telegram.send_voice_briefing(123, "Brief text")
        self.assertEqual(result["status"], "failed")
        send.assert_called()

    def test_speechify_briefing_turns_lists_into_sentences(self):
        spoken = telegram.speechify_briefing_text(
            """MORNING BRIEF - Monday, August 3

TOP 3
1. MCAT Studying
2. buy milk
3. check the mail

MESSAGES
- Google Accounts: Security alert
"""
        )
        self.assertIn("Morning brief for Monday, August 3.", spoken)
        self.assertIn("Top three. Number one is MCAT Studying. Number two is buy milk. Number three is check the mail.", spoken)
        self.assertIn("Messages. Google Accounts: Security alert.", spoken)

    def test_speechify_briefing_expands_units_and_money(self):
        spoken = telegram.speechify_briefing_text(
            """WEATHER
- Gainesville: 78.7 F, Raining, 80% next-hour rain

NEWS
- Acting AG reaches deal on $1.8B fund
"""
        )
        self.assertIn("seventy-nine degrees fahrenheit", spoken)
        self.assertIn("eighty percent", spoken)
        self.assertIn("one point eight billion dollars", spoken)

    def test_speechify_briefing_converts_regular_numbers_but_keeps_times_and_dates(self):
        spoken = telegram.speechify_briefing_text(
            """MORNING BRIEF - Monday, August 3

TODAY
- 9pm to 9:30pm: Dentist reminder

NEWS
- Almost 65,000 people evacuated and 78 buildings damaged
"""
        )
        self.assertIn("Monday, August 3", spoken)
        self.assertIn("9pm to 9:30pm", spoken)
        self.assertIn("sixty-five thousand people evacuated", spoken)
        self.assertIn("seventy-eight buildings damaged", spoken)

    def test_telegram_voice_message_transcribes_and_enqueues(self):
        update = {
            "update_id": 123,
            "message": {
                "chat": {"id": 456},
                "voice": {"file_id": "voice-file"},
            },
        }
        with mock.patch.object(telegram, "allowed", return_value=True), mock.patch.object(telegram, "transcribe_telegram_file", return_value="what is on my calendar"), mock.patch.object(telegram, "enqueue_job", return_value="job-1") as enqueue, mock.patch.object(telegram, "send_message") as send:
            telegram.handle_update(update)
        enqueue.assert_called_once_with(123, 456, "what is on my calendar")
        sent_text = "\n".join(str(call.args[1]) for call in send.call_args_list)
        self.assertIn("Transcribing voice note", sent_text)
        self.assertIn("Heard: what is on my calendar", sent_text)
        self.assertIn("Working on it", sent_text)

    def test_telegram_voice_message_reports_enqueue_failure(self):
        update = {
            "update_id": 123,
            "message": {
                "chat": {"id": 456},
                "voice": {"file_id": "voice-file"},
            },
        }
        with mock.patch.object(telegram, "allowed", return_value=True), mock.patch.object(telegram, "transcribe_telegram_file", return_value="what is on my calendar"), mock.patch.object(telegram, "enqueue_job", side_effect=PermissionError("state not writable")), mock.patch.object(telegram, "send_message") as send:
            telegram.handle_update(update)
        sent_text = "\n".join(str(call.args[1]) for call in send.call_args_list)
        self.assertIn("Heard: what is on my calendar", sent_text)
        self.assertIn("could not queue the Jarvis request", sent_text)


class GitHubDigestTests(unittest.TestCase):
    def test_digest_classifies_assigned_issues_and_open_prs(self):
        issue = {"title": "Fix bug", "html_url": "https://github.test/i", "labels": [{"name": "bug"}], "assignees": [{"login": "me"}]}
        pull = {"title": "Improve briefing", "html_url": "https://github.test/p", "draft": False}
        with mock.patch.object(github_worker, "github_request", side_effect=[[issue], [pull]]):
            result = github_worker.digest(["owner/repo"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual({item["type"] for item in result["items"]}, {"issue", "pull_request"})
        self.assertIn("owner/repo", result["text"])

    def test_issue_create_requires_approval(self):
        with self.assertRaises(PermissionError):
            github_worker.create_issue({"repo": "owner/repo", "title": "New issue"}, approved=False)


if __name__ == "__main__":
    unittest.main()
