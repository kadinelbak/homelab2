#!/usr/bin/env python3
import json
import os
import sys
import urllib.error
import urllib.request
import uuid


ORCHESTRATOR_URL = os.environ.get("AI_ORCHESTRATOR_URL", "http://127.0.0.1:8095").rstrip("/")
GOOGLE_TOOLS_URL = os.environ.get("GOOGLE_TOOLS_URL", "http://127.0.0.1:18200").rstrip("/")
CODEX_WORKER_URL = os.environ.get("CODEX_WORKER_URL", "http://127.0.0.1:18300").rstrip("/")
TOKEN = os.environ.get("AI_ORCHESTRATOR_TOKEN", os.environ.get("GOOGLE_TOOLS_TOKEN", ""))
CONTACT_QUERY = os.environ.get("QA_CONTACT_QUERY", "a")


def api(base_url, method, path, payload=None, timeout=180):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    request = urllib.request.Request(base_url + path, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {base_url}{path} returned HTTP {exc.code}: {raw}") from exc


def assert_ok(label, condition, detail=None):
    if not condition:
        raise AssertionError(f"{label} failed: {detail}")
    print(json.dumps({"label": label, "ok": True}, separators=(",", ":")))


def task_roundtrip():
    title = f"Jarvis Productivity QA {uuid.uuid4().hex[:8]}"
    created = api(
        GOOGLE_TOOLS_URL,
        "POST",
        "/tasks/execute-contract",
        {"contract": {"version": 1, "operation": "create", "title": title}, "approved": True},
    )
    task = created.get("task") or {}
    assert_ok("task_create", created.get("ok") and task.get("id") and task.get("title") == title, created)

    completed = api(
        GOOGLE_TOOLS_URL,
        "POST",
        "/tasks/execute-contract",
        {
            "contract": {
                "version": 1,
                "operation": "complete",
                "task_id": task["id"],
                "tasklist_id": task.get("tasklist_id"),
            },
            "approved": True,
        },
    )
    assert_ok("task_complete", completed.get("ok") and (completed.get("task") or {}).get("status") == "completed", completed)

    deleted = api(
        GOOGLE_TOOLS_URL,
        "POST",
        "/tasks/execute-contract",
        {
            "contract": {
                "version": 1,
                "operation": "delete",
                "task_id": task["id"],
                "tasklist_id": task.get("tasklist_id"),
            },
            "approved": True,
        },
    )
    assert_ok("task_delete", deleted.get("ok") and deleted.get("status") == "completed", deleted)


def contacts_checks():
    searched = api(
        GOOGLE_TOOLS_URL,
        "POST",
        "/contacts/execute-contract",
        {"contract": {"version": 1, "operation": "search", "query": CONTACT_QUERY, "max_results": 5}, "approved": False},
    )
    assert_ok("contacts_search", searched.get("ok") and searched.get("status") == "completed", searched)

    planned = api(
        ORCHESTRATOR_URL,
        "POST",
        "/requests",
        {
            "request": "Create a contact for Jarvis QA jarvis.qa@example.com",
            "capability": "manage_contacts",
            "permissions": {"may_execute": False, "may_publish": False},
        },
    )
    action = (planned.get("actions") or [{}])[0]
    assert_ok("contacts_write_approval_gate", action.get("requires_approval") is True and action.get("status") == "awaiting_approval", action)


def briefing_check():
    briefing = api(GOOGLE_TOOLS_URL, "POST", "/briefing/build", {"kind": "morning"})
    assert_ok(
        "briefing_build",
        briefing.get("ok") and briefing.get("status") == "completed" and "Morning briefing" in (briefing.get("text") or ""),
        briefing,
    )


def codex_health_check():
    try:
        health = api(CODEX_WORKER_URL, "GET", "/health", None, timeout=30)
    except urllib.error.URLError as exc:
        print(json.dumps({"label": "codex_health", "ok": False, "skipped": True, "error": str(exc)}, separators=(",", ":")))
        return
    assert_ok("codex_health", health.get("ok") is True and "codex" in health, health)


def google_health_check():
    health = api(GOOGLE_TOOLS_URL, "GET", "/health", None, timeout=30)
    required = {
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.compose",
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/calendar",
        "https://www.googleapis.com/auth/contacts",
        "https://www.googleapis.com/auth/contacts.readonly",
        "https://www.googleapis.com/auth/tasks",
    }
    scopes = set(health.get("scopes") or [])
    assert_ok("google_health", health.get("ok") is True and health.get("authorized") is True, health)
    assert_ok("google_scopes_declared", required.issubset(scopes), sorted(required - scopes))


def main():
    if not TOKEN:
        raise RuntimeError("AI_ORCHESTRATOR_TOKEN or GOOGLE_TOOLS_TOKEN is required")
    google_health_check()
    contacts_checks()
    task_roundtrip()
    briefing_check()
    codex_health_check()
    print(json.dumps({"ok": True, "live_productivity_qa": "completed"}, separators=(",", ":")))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, separators=(",", ":")))
        sys.exit(1)
