#!/usr/bin/env python3
import json
import os
import shlex
import shutil
import subprocess
import time
import urllib.parse
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
RETENTION_DAYS = int(os.environ.get("CODEX_WORKER_RETENTION_DAYS", "14"))
COMMAND_PREFIX = os.environ.get(
    "CODEX_COMMAND_PREFIX",
    "codex exec --json --sandbox workspace-write --approve-for-me",
)
MODE_SANDBOX = {
    "inspect-only": "read-only",
    "plan-only": "read-only",
    "patch-only": "workspace-write",
    "test-only": "workspace-write",
    "execute": "workspace-write",
}


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


def classify_request(text):
    lowered = (text or "").lower()
    if "github issue" in lowered or ("issue" in lowered and "github" in lowered):
        return "github_issue"
    if "summarize repo" in lowered or "summarize repository" in lowered or "repo summary" in lowered:
        return "repo_summary"
    if any(term in lowered for term in ("fix", "implement", "add feature", "refactor", "test", "debug")):
        return "coding_task"
    return "general_code"


def normalize_mode(payload):
    requested = (
        payload.get("mode")
        or ((payload.get("action") or {}).get("inputs") or {}).get("mode")
        or "plan-only"
    )
    mode = str(requested).strip().lower().replace("_", "-")
    aliases = {
        "inspect": "inspect-only",
        "read-only": "inspect-only",
        "plan": "plan-only",
        "patch": "patch-only",
        "test": "test-only",
        "write": "patch-only",
        "run": "execute",
    }
    return aliases.get(mode, mode if mode in MODE_SANDBOX else "plan-only")


def build_prompt(payload):
    action = payload.get("action") or payload
    inputs = action.get("inputs") or {}
    request_text = inputs.get("request") or payload.get("request") or ""
    request_kind = classify_request(request_text)
    mode = normalize_mode(payload)
    mode_rules = {
        "inspect-only": "Inspect and summarize. Do not propose patches, write files, or run mutating commands.",
        "plan-only": "Create a concrete implementation plan. Do not edit files or run tests that modify the workspace.",
        "patch-only": "Make the smallest scoped code changes needed. Do not run broad or destructive commands.",
        "test-only": "Run targeted tests or read-only checks. Do not edit source files.",
        "execute": "Carry out the approved coding task with scoped edits and targeted verification.",
    }
    return (
        "You are the Codex coding worker for Jarvis running on Kadin's homelab.\n"
        "Work only inside the mounted workspace. Keep changes scoped to the user's request. "
        "Do not publish, push, or expose secrets. If credentials or destructive actions are needed, stop and explain.\n\n"
        f"Worker mode: {mode}\n"
        f"Mode rules: {mode_rules[mode]}\n"
        f"Request kind: {request_kind}\n"
        f"User request:\n{request_text}\n"
    )


def read_text_preview(path, limit=4000):
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")[-limit:]


def run_git(args, timeout=20):
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(WORKSPACE),
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        return completed.stdout.strip()
    except Exception:
        return ""


def workspace_repositories():
    candidates = [WORKSPACE]
    try:
        candidates.extend(path for path in WORKSPACE.iterdir() if path.is_dir())
    except Exception:
        pass
    repos = []
    seen = set()
    for path in candidates:
        try:
            resolved = path.resolve()
        except Exception:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        try:
            if resolved.name.endswith(".git") and (resolved / "HEAD").exists():
                repos.append({"path": resolved, "git_dir": resolved})
            elif (resolved / ".git").exists():
                repos.append({"path": resolved, "cwd": resolved})
        except PermissionError:
            continue
        except OSError:
            continue
    return repos


def workspace_git_commits(limit=20):
    commits = []
    per_repo_limit = max(1, min(int(limit or 20), 50))
    for repo in workspace_repositories():
        command = [
            "git",
            "log",
            f"--max-count={per_repo_limit}",
            "--date=iso-strict",
            "--pretty=format:%H%x1f%h%x1f%ad%x1f%s",
        ]
        cwd = str(repo["cwd"]) if repo.get("cwd") else None
        if repo.get("git_dir"):
            command = ["git", f"--git-dir={repo['git_dir']}", *command[1:]]
        try:
            completed = subprocess.run(
                command,
                cwd=cwd,
                text=True,
                capture_output=True,
                timeout=20,
                check=False,
            )
        except Exception as exc:
            commits.append({"repo": str(repo["path"]), "status": "unavailable", "error": str(exc)[:240]})
            continue
        if completed.returncode != 0:
            commits.append({"repo": str(repo["path"]), "status": "unavailable", "error": (completed.stderr or completed.stdout)[:240]})
            continue
        for line in completed.stdout.splitlines():
            parts = line.split("\x1f")
            if len(parts) == 4:
                commits.append(
                    {
                        "repo": str(repo["path"]),
                        "sha": parts[0],
                        "short_sha": parts[1],
                        "date": parts[2],
                        "subject": parts[3],
                    }
                )
    commits.sort(key=lambda item: item.get("date") or "", reverse=True)
    return commits[:per_repo_limit]


def changed_files():
    status = run_git(["status", "--short"], timeout=20)
    files = []
    for line in status.splitlines():
        path = line[3:].strip() if len(line) > 3 else line.strip()
        if path:
            files.append({"status": line[:2].strip(), "path": path})
    return files


def extract_test_results(stdout, stderr):
    text = "\n".join(part for part in (stdout, stderr) if part)
    interesting = []
    markers = (" passed", " failed", "error", "failures", "OK", "Ran ", "pytest", "unittest", "npm test", "exit code")
    for line in text.splitlines():
        if any(marker.lower() in line.lower() for marker in markers):
            interesting.append(line.strip())
    return interesting[-30:]


def write_summary(job_dir, payload, status, stdout="", stderr="", return_code=None, started_at=None, finished_at=None):
    mode = normalize_mode(payload)
    request = payload.get("request") or (((payload.get("action") or {}).get("inputs") or {}).get("request")) or ""
    summary = {
        "job_id": job_dir.name,
        "status": status,
        "mode": mode,
        "request": request,
        "request_kind": classify_request(request),
        "return_code": return_code,
        "started_at": started_at,
        "finished_at": finished_at or now(),
        "changed_files": changed_files(),
        "test_results": extract_test_results(stdout or "", stderr or ""),
        "stdout_preview": (stdout or "")[-1600:],
        "stderr_preview": (stderr or "")[-1600:],
        "summary": summarize_output(status, stdout, stderr),
    }
    (job_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return summary


def summarize_output(status, stdout, stderr):
    text = (stdout or stderr or "").strip()
    if not text:
        return f"Codex worker {status} without output."
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines[-8:])[:1200]


def job_summary(job_dir):
    request_path = job_dir / "request.json"
    stdout_path = job_dir / "stdout.txt"
    stderr_path = job_dir / "stderr.txt"
    summary_path = job_dir / "summary.json"
    request = {}
    durable = {}
    if request_path.exists():
        try:
            request = json.loads(request_path.read_text(encoding="utf-8"))
        except Exception:
            request = {"raw": read_text_preview(request_path, 1200)}
    if summary_path.exists():
        try:
            durable = json.loads(summary_path.read_text(encoding="utf-8"))
        except Exception:
            durable = {"summary": read_text_preview(summary_path, 1200)}
    stdout = read_text_preview(stdout_path, 1600)
    stderr = read_text_preview(stderr_path, 1600)
    status = durable.get("status") or ("completed" if stdout_path.exists() else "proposed")
    if stderr and not stdout:
        status = "failed_or_stderr"
    request_text = durable.get("request") or request.get("request") or ((request.get("action") or {}).get("inputs") or {}).get("request") or ""
    return {
        "job_id": job_dir.name,
        "status": status,
        "mode": durable.get("mode") or normalize_mode(request),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(job_dir.stat().st_mtime)),
        "request": request_text,
        "changed_files": durable.get("changed_files") or [],
        "test_results": durable.get("test_results") or [],
        "artifacts": [
            {"name": "request.json", "path": str(request_path), "exists": request_path.exists()},
            {"name": "summary.json", "path": str(summary_path), "exists": summary_path.exists()},
            {"name": "stdout.txt", "path": str(stdout_path), "exists": stdout_path.exists(), "preview": stdout[:800]},
            {"name": "stderr.txt", "path": str(stderr_path), "exists": stderr_path.exists(), "preview": stderr[:800]},
        ],
        "summary": (durable.get("summary") or stdout or stderr or "No Codex output recorded yet.")[:800],
    }


def list_jobs():
    apply_retention()
    jobs_dir = DATA_DIR / "jobs"
    if not jobs_dir.exists():
        return []
    jobs = [job_summary(path) for path in jobs_dir.iterdir() if path.is_dir()]
    return sorted(jobs, key=lambda item: item["created_at"], reverse=True)


def safe_job_file(job_id, name):
    allowed = {"request.json", "summary.json", "stdout.txt", "stderr.txt"}
    if name not in allowed:
        raise ValueError("artifact_not_allowed")
    if not job_id.startswith("codex-"):
        raise ValueError("job_id_invalid")
    path = (DATA_DIR / "jobs" / job_id / name).resolve()
    root = (DATA_DIR / "jobs").resolve()
    if root not in path.parents:
        raise ValueError("artifact_path_invalid")
    return path


def apply_retention():
    if RETENTION_DAYS <= 0:
        return
    jobs_dir = DATA_DIR / "jobs"
    if not jobs_dir.exists():
        return
    cutoff = time.time() - (RETENTION_DAYS * 86400)
    for job_dir in jobs_dir.iterdir():
        if not job_dir.is_dir() or job_dir.stat().st_mtime >= cutoff:
            continue
        if not (job_dir / "summary.json").exists():
            write_summary(job_dir, {}, "retained", read_text_preview(job_dir / "stdout.txt"), read_text_preview(job_dir / "stderr.txt"))
        for name in ("stdout.txt", "stderr.txt"):
            path = job_dir / name
            if path.exists():
                preview = read_text_preview(path, 4000)
                path.write_text(f"[retained summary only after {RETENTION_DAYS} days]\n\n{preview}", encoding="utf-8")


def command_for_mode(mode, prompt):
    parts = shlex.split(COMMAND_PREFIX)
    sandbox = MODE_SANDBOX[mode]
    for index, part in enumerate(parts):
        if part == "--sandbox" and index + 1 < len(parts):
            parts[index + 1] = sandbox
            break
    else:
        parts.extend(["--sandbox", sandbox])
    return parts + [prompt]


def run_codex(payload):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    job_id = payload.get("job_id") or f"codex-{uuid.uuid4().hex[:12]}"
    job_dir = DATA_DIR / "jobs" / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "request.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    version = codex_version()
    prompt = build_prompt(payload)
    mode = normalize_mode(payload)
    request_kind = classify_request(prompt)
    if not version["configured"]:
        summary = write_summary(job_dir, payload, "worker_not_configured")
        return {
            "ok": True,
            "job_id": job_id,
            "status": "worker_not_configured",
            "mode": mode,
            "summary": "Codex CLI is not installed in the codex-worker container yet.",
            "text": "Codex worker is wired, but the Codex CLI binary is missing. Install/authenticate Codex, then rerun the approved action.",
            "job_summary": summary,
            "artifacts": [
                {"path": str(job_dir / "request.json"), "kind": "request"},
                {"path": str(job_dir / "summary.json"), "kind": "summary"},
                {"kind": "codex_job", "job_id": job_id, "request_kind": request_kind, "status": "worker_not_configured"},
            ],
            "codex": version,
        }

    timeout = int((payload.get("limits") or {}).get("maximum_runtime_seconds") or DEFAULT_TIMEOUT)
    command = command_for_mode(mode, prompt)
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
        summary = write_summary(job_dir, payload, status, stdout, stderr, completed.returncode, started, now())
        return {
            "ok": True,
            "job_id": job_id,
            "status": status,
            "mode": mode,
            "summary": f"Codex worker {status}.",
            "text": response_text[-MAX_OUTPUT_CHARS:],
            "return_code": completed.returncode,
            "started_at": started,
            "finished_at": now(),
            "job_summary": summary,
            "artifacts": [
                {"path": str(job_dir / "request.json"), "kind": "request"},
                {"path": str(job_dir / "summary.json"), "kind": "summary"},
                {"path": str(job_dir / "stdout.txt"), "kind": "stdout"},
                {"path": str(job_dir / "stderr.txt"), "kind": "stderr"},
                {"kind": "codex_job", "job_id": job_id, "request_kind": request_kind, "status": status},
            ],
            "codex": version,
        }
    except subprocess.TimeoutExpired as exc:
        stdout = (exc.stdout or "")[-MAX_OUTPUT_CHARS:]
        stderr = (exc.stderr or "")[-MAX_OUTPUT_CHARS:]
        (job_dir / "stdout.txt").write_text(stdout, encoding="utf-8")
        (job_dir / "stderr.txt").write_text(stderr, encoding="utf-8")
        summary = write_summary(job_dir, payload, "timeout", stdout, stderr, None, started, now())
        return {
            "ok": True,
            "job_id": job_id,
            "status": "timeout",
            "mode": mode,
            "summary": "Codex worker timed out.",
            "text": (stdout or stderr or "Codex timed out.")[-MAX_OUTPUT_CHARS:],
            "started_at": started,
            "finished_at": now(),
            "job_summary": summary,
            "artifacts": [
                {"path": str(job_dir / "request.json"), "kind": "request"},
                {"path": str(job_dir / "summary.json"), "kind": "summary"},
                {"path": str(job_dir / "stdout.txt"), "kind": "stdout"},
                {"path": str(job_dir / "stderr.txt"), "kind": "stderr"},
                {"kind": "codex_job", "job_id": job_id, "request_kind": request_kind, "status": "timeout"},
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
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = urllib.parse.parse_qs(parsed.query)
        if path == "/health":
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
        if path == "/jobs":
            if not self.require_auth():
                return
            self.write_json(HTTPStatus.OK, {"ok": True, "jobs": list_jobs()})
            return
        if path == "/git/commits":
            if not self.require_auth():
                return
            limit = int(query.get("limit", ["20"])[0] or "20")
            self.write_json(HTTPStatus.OK, {"ok": True, "commits": workspace_git_commits(limit)})
            return
        if path.startswith("/jobs/"):
            if not self.require_auth():
                return
            parts = path.strip("/").split("/")
            job_id = parts[1] if len(parts) > 1 else ""
            if len(parts) == 2:
                job_dir = DATA_DIR / "jobs" / job_id
                if not job_dir.exists() or not job_dir.is_dir():
                    self.write_json(HTTPStatus.NOT_FOUND, error_payload("job_not_found"))
                    return
                self.write_json(HTTPStatus.OK, {"ok": True, "job": job_summary(job_dir)})
                return
            if len(parts) == 3 and parts[2] == "artifact":
                name = query.get("name", [""])[0]
                try:
                    artifact = safe_job_file(job_id, name)
                except ValueError as exc:
                    self.write_json(HTTPStatus.BAD_REQUEST, error_payload(str(exc)))
                    return
                if not artifact.exists():
                    self.write_json(HTTPStatus.NOT_FOUND, error_payload("artifact_not_found"))
                    return
                self.write_json(HTTPStatus.OK, {"ok": True, "job_id": job_id, "name": name, "path": str(artifact), "text": read_text_preview(artifact, MAX_OUTPUT_CHARS)})
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
