#!/usr/bin/env python3
import json
import os
import shlex
import shutil
import subprocess
import time
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST = "0.0.0.0"
PORT = int(os.environ.get("CODEX_WORKER_PORT", "18300"))
TOKEN = os.environ.get("CODEX_WORKER_TOKEN", "")
WORKSPACE = Path(os.environ.get("CODEX_WORKSPACE", "/workspace"))
DATA_DIR = Path(os.environ.get("CODEX_WORKER_DATA_DIR", "/data"))
MAX_OUTPUT_CHARS = int(os.environ.get("CODEX_WORKER_MAX_OUTPUT_CHARS", "12000"))
DEFAULT_TIMEOUT = int(os.environ.get("CODEX_WORKER_TIMEOUT_SECONDS", "1800"))
COMMAND_PREFIX = os.environ.get(
    "CODEX_COMMAND_PREFIX",
    "codex exec --json --sandbox workspace-write --ask-for-approval never",
)


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def error_payload(error):
    return {"ok": False, "error": error}


def redact_env(env):
    redacted = {}
    for key, value in env.items():
        if any(term in key.upper() for term in ("TOKEN", "KEY", "SECRET", "PASSWORD")):
            redacted[key] = "***"
        else:
            redacted[key] = value
    return redacted


def codex_version():
    binary = shlex.split(COMMAND_PREFIX)[0] if COMMAND_PREFIX.strip() else "codex"
    path = shutil.which(binary)
    if not path:
        return {"configured": False, "binary": binary, "path": None, "version": None}
    try:
        completed = subprocess.run(
            [binary, "--version"],
            cwd=str(WORKSPACE),
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )
        version = (completed.stdout or completed.stderr).strip().splitlines()[:3]
    except Exception as exc:
        version = [f"version_check_failed: {exc}"]
    return {"configured": True, "binary": binary, "path": path, "version": "\n".join(version)}


def build_prompt(payload):
    action = payload.get("action") or payload
    inputs = action.get("inputs") or {}
    request_text = inputs.get("request") or payload.get("request") or ""
    return (
        "You are the Codex coding worker for Jarvis running on Kadin's homelab.\n"
        "Work only inside the mounted workspace. Keep changes scoped to the user's request. "
        "Do not publish, push, or expose secrets. If credentials or destructive actions are needed, stop and explain.\n\n"
        f"User request:\n{request_text}\n"
    )


def run_codex(payload):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    job_id = payload.get("job_id") or f"codex-{uuid.uuid4().hex[:12]}"
    job_dir = DATA_DIR / "jobs" / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "request.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    version = codex_version()
    if not version["configured"]:
        return {
            "ok": True,
            "job_id": job_id,
            "status": "worker_not_configured",
            "summary": "Codex CLI is not installed in the codex-worker container yet.",
            "text": "Codex worker is wired, but the Codex CLI binary is missing. Install/authenticate Codex, then rerun the approved action.",
            "artifacts": [{"path": str(job_dir / "request.json"), "kind": "request"}],
            "codex": version,
        }

    prompt = build_prompt(payload)
    timeout = int((payload.get("limits") or {}).get("maximum_runtime_seconds") or DEFAULT_TIMEOUT)
    command = shlex.split(COMMAND_PREFIX) + [prompt]
    started = now()
    try:
        completed = subprocess.run(
            command,
            cwd=str(WORKSPACE),
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        stdout = completed.stdout[-MAX_OUTPUT_CHARS:]
        stderr = completed.stderr[-MAX_OUTPUT_CHARS:]
        (job_dir / "stdout.txt").write_text(stdout, encoding="utf-8")
        (job_dir / "stderr.txt").write_text(stderr, encoding="utf-8")
        response_text = stdout.strip() or stderr.strip() or "Codex finished without output."
        status = "completed" if completed.returncode == 0 else "failed"
        return {
            "ok": True,
            "job_id": job_id,
            "status": status,
            "summary": f"Codex worker {status}.",
            "text": response_text[-MAX_OUTPUT_CHARS:],
            "return_code": completed.returncode,
            "started_at": started,
            "finished_at": now(),
            "artifacts": [
                {"path": str(job_dir / "request.json"), "kind": "request"},
                {"path": str(job_dir / "stdout.txt"), "kind": "stdout"},
                {"path": str(job_dir / "stderr.txt"), "kind": "stderr"},
            ],
            "codex": version,
        }
    except subprocess.TimeoutExpired as exc:
        stdout = (exc.stdout or "")[-MAX_OUTPUT_CHARS:]
        stderr = (exc.stderr or "")[-MAX_OUTPUT_CHARS:]
        (job_dir / "stdout.txt").write_text(stdout, encoding="utf-8")
        (job_dir / "stderr.txt").write_text(stderr, encoding="utf-8")
        return {
            "ok": True,
            "job_id": job_id,
            "status": "timeout",
            "summary": "Codex worker timed out.",
            "text": (stdout or stderr or "Codex timed out.")[-MAX_OUTPUT_CHARS:],
            "started_at": started,
            "finished_at": now(),
            "artifacts": [
                {"path": str(job_dir / "request.json"), "kind": "request"},
                {"path": str(job_dir / "stdout.txt"), "kind": "stdout"},
                {"path": str(job_dir / "stderr.txt"), "kind": "stderr"},
            ],
            "codex": version,
        }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"{self.address_string()} - {fmt % args}", flush=True)

    def write_json(self, status, payload):
        body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def require_auth(self):
        if not TOKEN:
            return True
        expected = f"Bearer {TOKEN}"
        if self.headers.get("Authorization") == expected:
            return True
        self.write_json(HTTPStatus.UNAUTHORIZED, error_payload("unauthorized"))
        return False

    def do_GET(self):
        if self.path.rstrip("/") == "/health":
            self.write_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "service": "codex-worker",
                    "workspace": str(WORKSPACE),
                    "data_dir": str(DATA_DIR),
                    "command_prefix": COMMAND_PREFIX,
                    "codex": codex_version(),
                    "env": redact_env({"CODEX_WORKSPACE": str(WORKSPACE)}),
                },
            )
            return
        self.write_json(HTTPStatus.NOT_FOUND, error_payload("not_found"))

    def do_POST(self):
        if self.path.rstrip("/") != "/run":
            self.write_json(HTTPStatus.NOT_FOUND, error_payload("not_found"))
            return
        if not self.require_auth():
            return
        try:
            payload = self.read_json()
            result = run_codex(payload)
        except Exception as exc:
            self.write_json(HTTPStatus.INTERNAL_SERVER_ERROR, error_payload(str(exc)))
            return
        self.write_json(HTTPStatus.OK, result)


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Codex worker listening on {HOST}:{PORT}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
