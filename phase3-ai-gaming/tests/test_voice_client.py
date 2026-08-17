import http.client
import importlib.util
import json
import pathlib
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


voice_client = load("jarvis_voice_client", ROOT / "jarvis-voice-client" / "client.py")
jarvis_chat = load("voice_jarvis_chat", ROOT / "jarvis-chat" / "app.py")


class FakeClient:
    def __init__(self, approval_required=False, fail_tts=False, transcript="what is on my calendar today", response_text=None, planned=None):
        self.config = voice_client.VoiceConfig(greeting="Hey Kad, what do you need?")
        self.approval_required = approval_required
        self.fail_tts = fail_tts
        self.transcript = transcript
        self.response_text = response_text or "You have one dentist reminder."
        self.planned = planned
        self.asked = []
        self.synthesized = []

    def transcribe(self, wav_bytes):
        return self.transcript

    def ask(self, text):
        self.asked.append(text)
        data = {"text": self.response_text, "approval_required": self.approval_required}
        if self.planned is not None:
            data["planned"] = self.planned
        return data

    def synthesize(self, text):
        if self.fail_tts:
            raise RuntimeError("tts down")
        self.synthesized.append(text)
        return b"ogg", "audio/ogg"


class FakeSpeaker:
    def __init__(self):
        self.local = []
        self.user = []
        self.status = []
        self.audio = []

    def print_jarvis(self, text):
        self.local.append(text)

    def print_user(self, text):
        self.user.append(text)

    def print_status(self, text):
        self.status.append(text)

    def play_audio(self, audio_bytes, content_type):
        self.audio.append((audio_bytes, content_type))


class FakeDesktopClient:
    def __init__(self):
        self.requests = []

    def request_json(self, path, payload, timeout=180):
        self.requests.append((path, payload, timeout))
        return {"ok": True}


class FakeTunnel:
    def __init__(self, ok=True):
        self.ok = ok
        self.ensure_calls = 0
        self.restart_calls = 0

    def ensure(self):
        self.ensure_calls += 1
        return self.ok

    def restart(self):
        self.restart_calls += 1
        return self.ok


class VoiceClientStateTests(unittest.TestCase):
    def test_voice_config_defaults_to_onnx_for_windows_wake_word(self):
        config = voice_client.VoiceConfig()
        self.assertEqual(config.wake_phrase, "hey_jarvis")
        self.assertEqual(config.wake_inference_framework, "onnx")
        self.assertEqual(config.wake_threshold, 0.98)
        self.assertEqual(config.wake_consecutive_hits, 4)
        self.assertTrue(config.enable_wake_word)
        self.assertTrue(config.enable_push_to_talk)
        self.assertEqual(config.push_to_talk_hotkey, "ctrl+alt+j")

    def test_state_machine_completes_voice_turn(self):
        speaker = FakeSpeaker()
        session = voice_client.JarvisVoiceSession(FakeClient(), speaker)
        turn = session.handle_recording(b"wav")
        self.assertEqual(turn.transcript, "what is on my calendar today")
        self.assertEqual(turn.response_text, "You have one dentist reminder.")
        self.assertEqual(turn.states, ["wake", "greet", "transcribe", "request", "speak", "idle"])
        self.assertEqual(speaker.local, ["Hey Kad, what do you need?", "You have one dentist reminder."])
        self.assertEqual(speaker.user, ["what is on my calendar today"])
        self.assertEqual(speaker.audio, [(b"ogg", "audio/ogg"), (b"ogg", "audio/ogg")])

    def test_state_machine_marks_approval_required(self):
        speaker = FakeSpeaker()
        session = voice_client.JarvisVoiceSession(FakeClient(approval_required=True), speaker)
        turn = session.handle_recording(b"wav")
        self.assertTrue(turn.approval_required)

    def test_state_machine_does_not_transcribe_empty_recording(self):
        speaker = FakeSpeaker()
        client = FakeClient()
        with mock.patch.object(client, "transcribe") as transcribe:
            session = voice_client.JarvisVoiceSession(client, speaker)
            turn = session.handle_recording(b"")
        transcribe.assert_not_called()
        self.assertEqual(turn.response_text, "I did not hear anything.")
        self.assertEqual(turn.states, ["wake", "greet", "idle"])

    def test_state_machine_falls_back_to_local_speech_when_tts_fails(self):
        speaker = FakeSpeaker()
        session = voice_client.JarvisVoiceSession(FakeClient(fail_tts=True), speaker)
        turn = session.handle_recording(b"wav")
        self.assertIn(turn.response_text, speaker.local)
        self.assertTrue(speaker.status)

    def test_push_to_talk_records_without_wake_detection(self):
        speaker = FakeSpeaker()
        client = FakeClient()
        tunnel = FakeTunnel()
        states = []
        controller = voice_client.VoiceController(
            client.config,
            speaker=speaker,
            tunnel=tunnel,
            recorder=lambda config: b"wav",
            client=client,
        )
        controller.on_state_change = lambda state, message="": states.append(state)
        turn = controller.push_to_talk()
        self.assertEqual(turn.transcript, "what is on my calendar today")
        self.assertEqual(tunnel.ensure_calls, 1)
        self.assertIn(voice_client.VoiceState.RECORDING, states)
        self.assertIn(voice_client.VoiceState.PROCESSING, states)
        self.assertEqual(controller.state, voice_client.VoiceState.LISTENING)

    def test_wake_suppressed_while_speaking_and_after_turn(self):
        config = voice_client.VoiceConfig(suppress_wake_while_speaking=True)
        controller = voice_client.VoiceController(config, speaker=FakeSpeaker(), tunnel=FakeTunnel(), client=FakeClient())
        controller.set_state(voice_client.VoiceState.SPEAKING)
        self.assertFalse(controller.should_accept_wake())
        controller.set_state(voice_client.VoiceState.LISTENING)
        controller.suppress_until = voice_client.time.time() + 30
        self.assertFalse(controller.should_accept_wake())

    def test_tunnel_restart_updates_state(self):
        config = voice_client.VoiceConfig()
        tunnel = FakeTunnel(ok=True)
        controller = voice_client.VoiceController(config, speaker=FakeSpeaker(), tunnel=tunnel, client=FakeClient())
        self.assertTrue(controller.restart_tunnel())
        self.assertEqual(tunnel.restart_calls, 1)
        self.assertEqual(controller.state, voice_client.VoiceState.LISTENING)

    def test_desktop_worker_resolves_only_allowed_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            allowed = root / "allowed"
            denied = root / "denied"
            allowed.mkdir()
            denied.mkdir()
            resolved = voice_client.resolve_allowed_path(str(allowed), [allowed.resolve()])
            self.assertEqual(resolved, allowed.resolve())
            with self.assertRaises(PermissionError):
                voice_client.resolve_allowed_path(str(denied), [allowed.resolve()])

    def test_desktop_files_list_returns_metadata_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "note.txt").write_text("secret-body", encoding="utf-8")
            config = voice_client.VoiceConfig(desktop_worker_allowed_roots=str(root))
            worker = voice_client.JarvisDesktopWorker(config, client=FakeDesktopClient(), speaker=FakeSpeaker())
            result = worker.cap_files_list({"path": str(root), "max_items": 10})
            self.assertEqual(result["count"], 1)
            self.assertEqual(result["items"][0]["name"], "note.txt")
            self.assertNotIn("secret-body", json.dumps(result))

    def test_desktop_files_move_stays_in_allowed_roots_and_avoids_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            source = root / "note.txt"
            target_dir = root / "Documents"
            target_dir.mkdir()
            source.write_text("new", encoding="utf-8")
            (target_dir / "note.txt").write_text("existing", encoding="utf-8")
            worker = voice_client.JarvisDesktopWorker(
                voice_client.VoiceConfig(desktop_worker_allowed_roots=str(root)),
                client=FakeDesktopClient(),
                speaker=FakeSpeaker(),
            )
            result = worker.cap_files_move({"moves": [{"source": str(source), "destination_dir": str(target_dir), "category": "Documents"}]})
            self.assertEqual(result["count"], 1)
            self.assertFalse(source.exists())
            self.assertTrue((target_dir / "note (2).txt").exists())
            self.assertTrue(result["moved"][0]["verified"])

    def test_desktop_files_move_rejects_destination_outside_allowed_roots(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as denied:
            root = pathlib.Path(tmp)
            source = root / "note.txt"
            source.write_text("new", encoding="utf-8")
            worker = voice_client.JarvisDesktopWorker(
                voice_client.VoiceConfig(desktop_worker_allowed_roots=str(root)),
                client=FakeDesktopClient(),
                speaker=FakeSpeaker(),
            )
            with self.assertRaises(PermissionError):
                worker.cap_files_move({"moves": [{"source": str(source), "destination_dir": denied}]})

    def test_desktop_open_url_rejects_unsafe_protocols(self):
        worker = voice_client.JarvisDesktopWorker(voice_client.VoiceConfig(), client=FakeDesktopClient(), speaker=FakeSpeaker())
        with self.assertRaises(PermissionError):
            worker.cap_open_url({"url": "file:///C:/Windows/System32/calc.exe"})

    def test_desktop_worker_handles_notify_job(self):
        client = FakeDesktopClient()
        speaker = FakeSpeaker()
        worker = voice_client.JarvisDesktopWorker(voice_client.VoiceConfig(desktop_worker_id="test-worker"), client=client, speaker=speaker)
        worker.handle_job({"id": "job_1", "capability": "desktop.notify", "input": {"title": "Hi", "body": "There"}})
        paths = [call[0] for call in client.requests]
        self.assertIn("/api/core/workers/test-worker/jobs/job_1/start", paths)
        self.assertIn("/api/core/workers/test-worker/jobs/job_1/complete", paths)
        self.assertTrue(any("Hi" in item for item in speaker.status))

    def test_response_normalization_humanizes_calendar_times_and_ids(self):
        text = "Calendar:\n1. Dentist reminder | 2026-08-03T21:00:00-04:00 -> 2026-08-03T21:30:00-04:00\nEvent ID: abc123"
        normalized = voice_client.normalize_response_text(text)
        self.assertIn("Dentist reminder, 9 PM to 9:30 PM", normalized)
        self.assertNotIn("Event ID", normalized)

    def test_spoken_response_text_shortens_long_answers(self):
        text = " ".join(f"Sentence {idx} has helpful detail." for idx in range(40))
        spoken = voice_client.spoken_response_text(text, max_chars=180)
        self.assertLessEqual(len(spoken), 230)
        self.assertIn("full answer on screen", spoken)

    def test_spoken_response_expands_numbers_money_percent_temperature(self):
        text = "WEATHER\n- Gainesville: 78.7 F, 80% rain\nNEWS\n- 65,000 people affected by $1.8B fund"
        spoken = voice_client.spoken_response_text(text, max_chars=0)
        self.assertIn("seventy-nine degrees fahrenheit", spoken)
        self.assertIn("eighty percent rain", spoken)
        self.assertIn("sixty-five thousand people affected", spoken)
        self.assertIn("one point eight billion dollars fund", spoken)

    def test_spoken_response_reads_numbered_lists_naturally(self):
        text = "TOP 3\n1. MCAT Studying\n2. buy milk\n3. check the mail"
        spoken = voice_client.spoken_response_text(text, max_chars=0)
        self.assertIn("Top three.", spoken)
        self.assertIn("Number one is MCAT Studying.", spoken)
        self.assertIn("Number two is buy milk.", spoken)
        self.assertIn("Number three is check the mail.", spoken)

    def test_visual_response_text_stays_compact(self):
        self.assertIn("78.7 F", voice_client.normalize_response_text("Weather: 78.7 F"))

    def test_full_speech_response_detects_briefing(self):
        data = {
            "planned": {
                "actions": [
                    {
                        "capability": "daily_briefing",
                        "worker": "briefing_worker",
                        "tool": "jarvis.daily_briefing",
                    }
                ]
            }
        }
        self.assertTrue(voice_client.full_speech_response(data))
        self.assertFalse(voice_client.full_speech_response({"planned": {"actions": [{"capability": "general_assistant"}]}}))

    def test_briefing_response_is_not_shortened_for_speech(self):
        long_text = "WEATHER\n- Gainesville: 78.7 F\n" + " ".join(f"Brief item {idx} has useful detail." for idx in range(80))
        speaker = FakeSpeaker()
        client = FakeClient(
            response_text=long_text,
            planned={"actions": [{"capability": "daily_briefing", "worker": "briefing_worker"}]},
        )
        session = voice_client.JarvisVoiceSession(client, speaker)
        session.handle_recording(b"wav", greet=False)
        self.assertIn("seventy-nine degrees fahrenheit", client.synthesized[-1])
        self.assertNotIn("full answer on screen", speaker.local[-1])

    def test_jarvis_chat_client_marks_voice_requests_concise(self):
        client = voice_client.JarvisChatClient(voice_client.VoiceConfig(chat_url="http://jarvis.local"))
        with mock.patch.object(voice_client.urllib.request, "urlopen", return_value=FakeHTTPResponse(b'{"ok":true,"text":"short"}', headers={"Content-Type": "application/json"})) as urlopen:
            data = client.ask("explain bikes")
        self.assertEqual(data["text"], "short")
        request = urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["inputs"]["response_style"], "spoken_concise")
        self.assertTrue(payload["inputs"]["voice_response"])

    def test_easter_egg_exact_match_only_and_harmless(self):
        self.assertEqual(
            voice_client.easter_egg_response("How fat is Zach?"),
            "Zach is running in full legendary mode today.",
        )
        self.assertIsNone(voice_client.easter_egg_response("how fat is Zach today"))
        self.assertIsNone(voice_client.easter_egg_response("tell me how fat is Zach"))

    def test_easter_egg_does_not_call_jarvis_core(self):
        speaker = FakeSpeaker()
        client = FakeClient(transcript="How fat is Zach?")
        session = voice_client.JarvisVoiceSession(client, speaker)
        turn = session.handle_recording(b"wav", greet=False)
        self.assertEqual(turn.response_text, "Zach is running in full legendary mode today.")
        self.assertEqual(client.asked, [])


class FakeHTTPResponse:
    def __init__(self, body, status=200, headers=None):
        self.body = body
        self.status = status
        self.headers = headers or {"Content-Type": "audio/ogg"}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return self.body


class JarvisChatVoiceProxyTests(unittest.TestCase):
    def serve(self):
        class TestServer(ThreadingHTTPServer):
            daemon_threads = True
            allow_reuse_address = True

        server = TestServer(("127.0.0.1", 0), jarvis_chat.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        server._thread = thread
        return server

    def close_server(self, server):
        server.shutdown()
        server.server_close()
        server._thread.join(timeout=2)

    def post(self, server, path, body, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
        request_headers = {"Connection": "close"}
        request_headers.update(headers or {})
        conn.request("POST", path, body=body, headers=request_headers)
        response = conn.getresponse()
        data = response.read()
        conn.close()
        return response.status, data, dict(response.getheaders())

    def test_voice_request_requires_chat_auth(self):
        server = self.serve()
        old_token = jarvis_chat.CHAT_TOKEN
        try:
            jarvis_chat.CHAT_TOKEN = "secret"
            status, data, _ = self.post(
                server,
                "/api/voice/request",
                json.dumps({"text": "hello"}),
                {"Content-Type": "application/json"},
            )
            self.assertEqual(status, 401)
            self.assertIn(b"unauthorized", data)
        finally:
            jarvis_chat.CHAT_TOKEN = old_token
            self.close_server(server)

    def test_voice_request_executes_allowed_actions_and_reports_approval(self):
        server = self.serve()
        old_token = jarvis_chat.CHAT_TOKEN
        old_proxy = jarvis_chat.Handler.proxy

        def fake_proxy(self, method, path, payload=None):
            if path == "/requests":
                return 200, {
                    "request": {"summary": "Calendar request planned."},
                    "actions": [
                        {"action_id": "a1", "capability": "calendar", "permissions": {"may_execute": True}},
                        {"action_id": "a2", "capability": "gmail", "permissions": {"may_execute": False}, "requires_approval": True},
                    ],
                }
            if path == "/actions/a1/execute":
                return 200, {"action": {"result": {"text": "You have one dentist reminder."}}}
            return 404, {"error": "unexpected"}

        try:
            jarvis_chat.CHAT_TOKEN = ""
            jarvis_chat.Handler.proxy = fake_proxy
            status, data, _ = self.post(
                server,
                "/api/voice/request",
                json.dumps({"text": "what is today"}),
                {"Content-Type": "application/json"},
            )
            payload = json.loads(data.decode())
            self.assertEqual(status, 200)
            self.assertTrue(payload["approval_required"])
            self.assertIn("You have one dentist reminder.", payload["text"])
            self.assertIn("Approval is required", payload["text"])
        finally:
            jarvis_chat.CHAT_TOKEN = old_token
            jarvis_chat.Handler.proxy = old_proxy
            self.close_server(server)

    def test_voice_synthesize_proxies_audio(self):
        server = self.serve()
        old_token = jarvis_chat.CHAT_TOKEN
        try:
            jarvis_chat.CHAT_TOKEN = ""
            with mock.patch.object(jarvis_chat.urllib.request, "urlopen", return_value=FakeHTTPResponse(b"wav-bytes", headers={"Content-Type": "audio/wav"})) as urlopen:
                status, data, headers = self.post(
                    server,
                    "/api/voice/synthesize",
                    json.dumps({"text": "hello", "format": "wav"}),
                    {"Content-Type": "application/json"},
                )
            self.assertEqual(status, 200)
            self.assertEqual(data, b"wav-bytes")
            self.assertEqual(headers.get("Content-Type"), "audio/wav")
            request = urlopen.call_args.args[0]
            self.assertEqual(json.loads(request.data.decode("utf-8")).get("format"), "wav")
        finally:
            jarvis_chat.CHAT_TOKEN = old_token
            self.close_server(server)

    def test_voice_synthesize_rejects_invalid_json(self):
        server = self.serve()
        old_token = jarvis_chat.CHAT_TOKEN
        try:
            jarvis_chat.CHAT_TOKEN = ""
            status, data, _ = self.post(
                server,
                "/api/voice/synthesize",
                "{bad json",
                {"Content-Type": "application/json"},
            )
            self.assertEqual(status, 400)
            self.assertIn(b"invalid_json", data)
        finally:
            jarvis_chat.CHAT_TOKEN = old_token
            self.close_server(server)


if __name__ == "__main__":
    unittest.main()
