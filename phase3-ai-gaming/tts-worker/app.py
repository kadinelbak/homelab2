#!/usr/bin/env python3
import json
import os
import subprocess
import tempfile
import wave
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST = os.environ.get("JARVIS_TTS_HOST", "0.0.0.0")
PORT = int(os.environ.get("JARVIS_TTS_PORT", "8101"))
TOKEN = os.environ.get("JARVIS_TTS_TOKEN", "")
MAX_CHARS = int(os.environ.get("JARVIS_TTS_MAX_CHARS", "12000"))
DEFAULT_VOICE = os.environ.get("JARVIS_TTS_VOICE", "default")
ENGINE = os.environ.get("JARVIS_TTS_ENGINE", "kokoro").strip().lower()
PIPER_MODEL_DIR = Path(os.environ.get("JARVIS_PIPER_MODEL_DIR", "/models/piper"))
PIPER_MODEL = os.environ.get("JARVIS_PIPER_MODEL", "en_US-lessac-high.onnx")
KOKORO_MODEL_DIR = Path(os.environ.get("JARVIS_KOKORO_MODEL_DIR", "/models/kokoro"))
KOKORO_MODEL = os.environ.get("JARVIS_KOKORO_MODEL", "kokoro-v1.0.onnx")
KOKORO_VOICES = os.environ.get("JARVIS_KOKORO_VOICES", "voices-v1.0.bin")
KOKORO_LANG = os.environ.get("JARVIS_KOKORO_LANG", "en-us")
KOKORO_SPEED = float(os.environ.get("JARVIS_KOKORO_SPEED", "1.0"))
_kokoro = None


def write_float_wav(path, samples, sample_rate):
    import struct

    values = []
    for sample in samples:
        sample = max(-1.0, min(1.0, float(sample)))
        values.append(int(sample * 32767))
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(int(sample_rate))
        wav.writeframes(struct.pack("<" + "h" * len(values), *values))


def encode_ogg(wav_path, ogg_path):
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(wav_path), "-c:a", "libopus", "-b:a", "40k", "-application", "voip", str(ogg_path)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        timeout=180,
    )


def piper_model_path(voice):
    if voice and voice not in {"default", "piper"}:
        candidate = PIPER_MODEL_DIR / voice
        if candidate.suffix != ".onnx":
            candidate = candidate.with_suffix(".onnx")
        if candidate.exists():
            return candidate
    return PIPER_MODEL_DIR / PIPER_MODEL


def kokoro_paths():
    return KOKORO_MODEL_DIR / KOKORO_MODEL, KOKORO_MODEL_DIR / KOKORO_VOICES


def kokoro_voice(voice):
    if voice and voice not in {"", "default", "kokoro", "piper"}:
        return voice
    return "af_heart"


def get_kokoro():
    global _kokoro
    if _kokoro is None:
        from kokoro_onnx import Kokoro

        model_path, voices_path = kokoro_paths()
        if not model_path.exists():
            raise FileNotFoundError(f"kokoro_model_not_found: {model_path}")
        if not voices_path.exists():
            raise FileNotFoundError(f"kokoro_voices_not_found: {voices_path}")
        _kokoro = Kokoro(str(model_path), str(voices_path))
    return _kokoro


def audio_bytes(wav_path, ogg_path, output_format):
    if output_format == "wav":
        return wav_path.read_bytes(), "audio/wav"
    encode_ogg(wav_path, ogg_path)
    return ogg_path.read_bytes(), "audio/ogg"


def synthesize_kokoro(text, voice, tmpdir, output_format="ogg"):
    wav_path = Path(tmpdir) / "briefing.wav"
    ogg_path = Path(tmpdir) / "briefing.ogg"
    samples, sample_rate = get_kokoro().create(
        text,
        voice=kokoro_voice(voice),
        speed=KOKORO_SPEED,
        lang=KOKORO_LANG,
    )
    write_float_wav(wav_path, samples, sample_rate)
    return audio_bytes(wav_path, ogg_path, output_format)


def synthesize_piper(text, voice, tmpdir, output_format="ogg"):
    model_path = piper_model_path(voice)
    if not model_path.exists():
        raise FileNotFoundError(f"piper_model_not_found: {model_path}")
    wav_path = Path(tmpdir) / "briefing.wav"
    ogg_path = Path(tmpdir) / "briefing.ogg"
    subprocess.run(
        ["piper", "--model", str(model_path), "--output_file", str(wav_path)],
        input=text,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        timeout=240,
    )
    return audio_bytes(wav_path, ogg_path, output_format)


def synthesize_espeak(text, voice, tmpdir, output_format="ogg"):
    voice_arg = "en-us" if voice in {"", "default", "piper"} else voice
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
    return audio_bytes(wav_path, ogg_path, output_format)


def synthesize(text, voice, output_format="ogg"):
    text = str(text or "").strip()[:MAX_CHARS]
    if not text:
        raise ValueError("text_required")
    output_format = str(output_format or "ogg").lower()
    if output_format not in {"ogg", "wav"}:
        raise ValueError("format_must_be_ogg_or_wav")
    with tempfile.TemporaryDirectory() as tmpdir:
        if ENGINE == "espeak":
            return synthesize_espeak(text, voice, tmpdir, output_format)
        if ENGINE == "piper":
            try:
                return synthesize_piper(text, voice, tmpdir, output_format)
            except Exception:
                if os.environ.get("JARVIS_TTS_ALLOW_FALLBACK", "true").lower() in {"1", "true", "yes", "on"}:
                    return synthesize_espeak(text, "default", tmpdir, output_format)
                raise
        try:
            return synthesize_kokoro(text, voice, tmpdir, output_format)
        except Exception:
            if os.environ.get("JARVIS_TTS_ALLOW_FALLBACK", "true").lower() in {"1", "true", "yes", "on"}:
                try:
                    return synthesize_piper(text, "default", tmpdir, output_format)
                except Exception:
                    return synthesize_espeak(text, "default", tmpdir, output_format)
            raise


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
            self.write_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "engine": ENGINE,
                    "voice": DEFAULT_VOICE,
                    "kokoro_model": str(kokoro_paths()[0]),
                    "kokoro_voice": kokoro_voice(DEFAULT_VOICE),
                    "piper_model": str(piper_model_path(DEFAULT_VOICE)),
                    "fallback": os.environ.get("JARVIS_TTS_ALLOW_FALLBACK", "true"),
                },
            )
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
            audio, content_type = synthesize(
                payload.get("text"),
                payload.get("voice") or DEFAULT_VOICE,
                payload.get("format") or "ogg",
            )
        except Exception as exc:
            self.write_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": str(exc)})
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(audio)))
        self.end_headers()
        self.wfile.write(audio)


def main():
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"TTS worker listening on {HOST}:{PORT}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
