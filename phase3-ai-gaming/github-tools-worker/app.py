#!/usr/bin/env python3
import json
import os
import time
import urllib.parse
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import jwt

HOST = os.environ.get("GITHUB_TOOLS_HOST", "0.0.0.0")
PORT = int(os.environ.get("GITHUB_TOOLS_PORT", "18400"))
TOKEN = os.environ.get("GITHUB_WORKER_TOKEN", os.environ.get("AI_ORCHESTRATOR_TOKEN", ""))
GITHUB_API_URL = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_APP_ID = os.environ.get("GITHUB_APP_ID", "")
GITHUB_APP_INSTALLATION_ID = os.environ.get("GITHUB_APP_INSTALLATION_ID", "")
GITHUB_APP_PRIVATE_KEY = os.environ.get("GITHUB_APP_PRIVATE_KEY", "").replace("\\n", "\n")
_INSTALLATION_TOKEN = {"value": "", "expires_at": 0}


def app_jwt():
    now = int(time.time())
    return jwt.encode(
        {"iat": now - 60, "exp": now + 540, "iss": GITHUB_APP_ID},
        GITHUB_APP_PRIVATE_KEY,
        algorithm="RS256",
    )


def installation_token():
    if GITHUB_TOKEN:
        return GITHUB_TOKEN
    if _INSTALLATION_TOKEN["value"] and _INSTALLATION_TOKEN["expires_at"] > time.time() + 60:
        return _INSTALLATION_TOKEN["value"]
    if not (GITHUB_APP_ID and GITHUB_APP_INSTALLATION_ID and GITHUB_APP_PRIVATE_KEY):
        raise RuntimeError("github_app_not_configured")
    req = urllib.request.Request(
        f"{GITHUB_API_URL}/app/installations/{GITHUB_APP_INSTALLATION_ID}/access_tokens",
        data=b"{}",
        method="POST",
        headers={
            "Authorization": f"Bearer {app_jwt()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8") or "{}")
    _INSTALLATION_TOKEN["value"] = payload["token"]
    _INSTALLATION_TOKEN["expires_at"] = time.time() + 3300
    return _INSTALLATION_TOKEN["value"]


def github_request(method, path, payload=None):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        GITHUB_API_URL + path,
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {installation_token()}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "JarvisGitHubWorker/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as response:
        raw = response.read().decode("utf-8") or ""
        return json.loads(raw) if raw else {}


def repo_digest(repo):
    encoded = urllib.parse.quote(repo, safe="/")
    issues = github_request("GET", f"/repos/{encoded}/issues?state=open&sort=updated&direction=desc&per_page=10")
    pulls = github_request("GET", f"/repos/{encoded}/pulls?state=open&sort=updated&direction=desc&per_page=10")
    items = []
    for issue in issues:
        if "pull_request" in issue:
            continue
        labels = [label.get("name", "") for label in issue.get("labels") or []]
        assigned = bool(issue.get("assignees"))
        if assigned or any(label.lower() in {"bug", "urgent", "blocked"} for label in labels):
            items.append({"type": "issue", "repo": repo, "title": issue.get("title"), "url": issue.get("html_url")})
    for pull in pulls:
        draft = pull.get("draft") is True
        title = pull.get("title") or "Open pull request"
        items.append({"type": "pull_request", "repo": repo, "title": ("Draft: " if draft else "") + title, "url": pull.get("html_url")})
    return items[:8]


def digest(repos):
    items = []
    errors = []
    for repo in repos or []:
        try:
            items.extend(repo_digest(repo))
        except Exception as exc:
            errors.append({"repo": repo, "error": str(exc)[:160]})
    text = "\n".join(f"- {item['repo']}: {item['title']}" for item in items[:10])
    return {"status": "completed" if not errors else "partial", "items": items[:20], "errors": errors, "text": text or "- No GitHub items requiring attention."}


def create_issue(contract, approved=False):
    if not approved:
        raise PermissionError("github_issue_create_requires_approval")
    repo = contract.get("repo")
    title = contract.get("title")
    if not repo or not title:
        raise ValueError("github_issue_contract_incomplete")
    payload = {"title": title, "body": contract.get("body") or ""}
    issue = github_request("POST", f"/repos/{urllib.parse.quote(repo, safe='/')}/issues", payload)
    return {"status": "completed", "issue": issue, "text": f"Created GitHub issue: {issue.get('html_url')}"}


class Handler(BaseHTTPRequestHandler):
    server_version = "homelab-github-tools-worker/0.1"

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
        if path == "/github/health":
            self.write_json(HTTPStatus.OK, {"ok": True, "auth_model": "token" if GITHUB_TOKEN else "github_app", "configured": bool(GITHUB_TOKEN or (GITHUB_APP_ID and GITHUB_APP_INSTALLATION_ID and GITHUB_APP_PRIVATE_KEY))})
            return
        self.write_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})

    def do_POST(self):
        if not self.authorized():
            self.write_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
            return
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        try:
            payload = self.read_json()
            if path == "/github/repos":
                repos = github_request("GET", "/installation/repositories?per_page=100")
                self.write_json(HTTPStatus.OK, {"ok": True, "repositories": repos.get("repositories", [])})
                return
            if path == "/github/digest":
                self.write_json(HTTPStatus.OK, {"ok": True, **digest(payload.get("repos") or [])})
                return
            if path == "/github/issues/create-contract":
                self.write_json(HTTPStatus.OK, {"ok": True, **create_issue(payload.get("contract") or {}, payload.get("approved") is True)})
                return
        except Exception as exc:
            self.write_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": str(exc)})
            return
        self.write_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})


def main():
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"GitHub tools worker listening on {HOST}:{PORT}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
