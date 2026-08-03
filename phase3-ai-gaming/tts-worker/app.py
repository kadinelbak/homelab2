#!/usr/bin/env python3
import json
import os
import subprocess
import tempfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST = os.environ.get("JARVIS_TTS_HOST", "0.0.0.0")
PORT = int(os.environ.get("JARVIS_TTS_PORT", "8101"))
TOKEN = os.environ.get("JARVIS_TTS_TOKEN", "")
MAX_CHARS = int(os.environ.get("JARVIS_TTS_MAX_CHARS", "12000"))
DEFAULT_VOICE = os.environ.get("JARVIS_TTS_VOICE", "default")


def synthesize(text, voice):
    text = str(text or "").strip()[:MAX_CHARS]
    if not text:
        raise ValueError("text_required")
    voice_arg = "en-us" if voice in {"", "default"} else voice
    with tempfile.TemporaryDirectory() as tmpdir:
        wav_path = Path(tmpdir) / "briefing.wav"
        ogg_path = Path(tmpdir) / "briefing.ogg"
        subprocess.run(
            ["espeak-ng", "-v", voice_arg, "-s", "165", "-w", str(wav_path), text],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=180,
        )
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(wav_path), "-c:a", "libopus", "-b:a", "32k", str(ogg_path)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=180,
        )
        return ogg_path.read_bytes()


class Handler(BaseHTTPRequestHandler):
    server_version = "homelab-tts-worker/0.1"

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args), flush=True)

    def authorized(self):
        if not TOKEN or TOKEN.startswith("CHANGE_ME"):
            return True
        return self.headers.get("Authorization", "") == f"Bearer {TOKEN}"

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8") or "{}")

    def write_json(self, status, payload):
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path == "/health":
            self.write_json(HTTPStatus.OK, {"ok": True, "engine": "espeak-ng", "voice": DEFAULT_VOICE})
            return
        self.write_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})

    def do_POST(self):
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path != "/tts/synthesize":
            self.write_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})
            return
        if not self.authorized():
            self.write_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
            return
        try:
            payload = self.read_json()
            audio = synthesize(payload.get("text"), payload.get("voice") or DEFAULT_VOICE)
        except Exception as exc:
            self.write_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": str(exc)})
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "audio/ogg")
        self.send_header("Content-Length", str(len(audio)))
        self.end_headers()
        self.wfile.write(audio)


def main():
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"TTS worker listening on {HOST}:{PORT}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
