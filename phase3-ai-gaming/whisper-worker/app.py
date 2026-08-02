#!/usr/bin/env python3
import cgi
import json
import os
import tempfile
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HOST = os.environ.get("WHISPER_WORKER_HOST", "0.0.0.0")
PORT = int(os.environ.get("WHISPER_WORKER_PORT", "8099"))
TOKEN = os.environ.get("WHISPER_WORKER_TOKEN", "")
MODEL_NAME = os.environ.get("WHISPER_MODEL", "base")
DEVICE = os.environ.get("WHISPER_DEVICE", "cpu")
COMPUTE_TYPE = os.environ.get("WHISPER_COMPUTE_TYPE", "int8")
CACHE_DIR = os.environ.get("WHISPER_CACHE_DIR", "/models")
MAX_UPLOAD_MB = int(os.environ.get("WHISPER_MAX_UPLOAD_MB", "100"))

MODEL = None


def authorized(handler):
    if not TOKEN or TOKEN.startswith("CHANGE_ME"):
        return True
    auth = handler.headers.get("Authorization", "")
    if auth == f"Bearer {TOKEN}":
        return True
    parsed = urlparse(handler.path)
    return parse_qs(parsed.query).get("token", [""])[0] == TOKEN


def load_model():
    global MODEL
    if MODEL is None:
        from faster_whisper import WhisperModel

        MODEL = WhisperModel(
            MODEL_NAME,
            device=DEVICE,
            compute_type=COMPUTE_TYPE,
            download_root=CACHE_DIR,
        )
    return MODEL


class Handler(BaseHTTPRequestHandler):
    server_version = "homelab-whisper-worker/0.1"

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args), flush=True)

    def write_json(self, status, payload):
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path == "/health":
            self.write_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "model": MODEL_NAME,
                    "device": DEVICE,
                    "compute_type": COMPUTE_TYPE,
                    "loaded": MODEL is not None,
                },
            )
            return
        self.write_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})

    def do_POST(self):
        path = urlparse(self.path).path.rstrip("/") or "/"
        openai_compatible = path == "/v1/audio/transcriptions"
        if path != "/transcribe" and not openai_compatible:
            self.write_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})
            return
        if not authorized(self):
            self.write_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
            return

        content_length = int(self.headers.get("Content-Length", "0") or "0")
        if content_length > MAX_UPLOAD_MB * 1024 * 1024:
            self.write_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"ok": False, "error": "upload_too_large"})
            return

        content_type = self.headers.get("Content-Type", "")
        if not content_type.startswith("multipart/form-data"):
            self.write_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "expected multipart/form-data"})
            return

        started = time.time()
        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": content_type},
        )
        file_item = form["file"] if "file" in form else form["audio"] if "audio" in form else None
        if file_item is None or not getattr(file_item, "file", None):
            self.write_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "missing audio field"})
            return

        suffix = Path(getattr(file_item, "filename", "") or "audio").suffix or ".audio"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(file_item.file.read())
            tmp_path = tmp.name

        try:
            language = form.getfirst("language") or None
            task = form.getfirst("task") or "transcribe"
            model = load_model()
            segments, info = model.transcribe(tmp_path, language=language, task=task)
            segment_list = [
                {"start": round(segment.start, 2), "end": round(segment.end, 2), "text": segment.text.strip()}
                for segment in segments
            ]
            text = " ".join(segment["text"] for segment in segment_list).strip()
            if openai_compatible:
                self.write_json(HTTPStatus.OK, {"text": text})
            else:
                self.write_json(
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "text": text,
                        "language": info.language,
                        "language_probability": info.language_probability,
                        "seconds": round(time.time() - started, 2),
                        "segments": segment_list,
                    },
                )
        except Exception as exc:
            self.write_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": str(exc)})
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def main():
    Path(CACHE_DIR).mkdir(parents=True, exist_ok=True)
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Whisper worker listening on {HOST}:{PORT}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
