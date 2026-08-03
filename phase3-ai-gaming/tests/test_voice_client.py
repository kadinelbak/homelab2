import http.client
import importlib.util
import json
import pathlib
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
    def __init__(self, approval_required=False, fail_tts=False):
        self.config = voice_client.VoiceConfig(greeting="Hey Kad, what do you need?")
        self.approval_required = approval_required
        self.fail_tts = fail_tts

    def transcribe(self, wav_bytes):
        return "what is on my calendar today"

    def ask(self, text):
        return {"text": "You have one dentist reminder.", "approval_required": self.approval_required}

    def synthesize(self, text):
        if self.fail_tts:
            raise RuntimeError("tts down")
        return b"ogg", "audio/ogg"


class FakeSpeaker:
    def __init__(self):
        self.local = []
        self.audio = []

    def say_local(self, text):
        self.local.append(text)

    def play_audio(self, audio_bytes, content_type):
        self.audio.append((audio_bytes, content_type))


class VoiceClientStateTests(unittest.TestCase):
    def test_voice_config_defaults_to_onnx_for_windows_wake_word(self):
        config = voice_client.VoiceConfig()
        self.assertEqual(config.wake_phrase, "hey_jarvis")
        self.assertEqual(config.wake_inference_framework, "onnx")
        self.assertEqual(config.wake_threshold, 0.85)
        self.assertEqual(config.wake_consecutive_hits, 2)

    def test_state_machine_completes_voice_turn(self):
        speaker = FakeSpeaker()
        session = voice_client.JarvisVoiceSession(FakeClient(), speaker)
        turn = session.handle_recording(b"wav")
        self.assertEqual(turn.transcript, "what is on my calendar today")
        self.assertEqual(turn.response_text, "You have one dentist reminder.")
        self.assertEqual(turn.states, ["wake", "greet", "transcribe", "request", "speak", "idle"])
        self.assertEqual(speaker.local, ["Hey Kad, what do you need?"])
        self.assertEqual(speaker.audio, [(b"ogg", "audio/ogg")])

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
        server = ThreadingHTTPServer(("127.0.0.1", 0), jarvis_chat.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server

    def post(self, server, path, body, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
        conn.request("POST", path, body=body, headers=headers or {})
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
            server.shutdown()

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
            server.shutdown()

    def test_voice_synthesize_proxies_audio(self):
        server = self.serve()
        old_token = jarvis_chat.CHAT_TOKEN
        try:
            jarvis_chat.CHAT_TOKEN = ""
            with mock.patch.object(jarvis_chat.urllib.request, "urlopen", return_value=FakeHTTPResponse(b"ogg-bytes")):
                status, data, headers = self.post(
                    server,
                    "/api/voice/synthesize",
                    json.dumps({"text": "hello"}),
                    {"Content-Type": "application/json"},
                )
            self.assertEqual(status, 200)
            self.assertEqual(data, b"ogg-bytes")
            self.assertEqual(headers.get("Content-Type"), "audio/ogg")
        finally:
            jarvis_chat.CHAT_TOKEN = old_token
            server.shutdown()

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
            server.shutdown()


if __name__ == "__main__":
    unittest.main()
