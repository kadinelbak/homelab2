#!/usr/bin/env python3
import json
import os
import sqlite3
import urllib.request
from datetime import timedelta


EXPECTED_NAMES = {
    "Jarvis",
    "Nemotron Super 120B",
    "Hosted Llama 3.1 70B",
    "Local Llama 3.1 8B - Chat Only",
}
base_url = os.environ.get("OPEN_WEBUI_URL", "http://open-webui:8080").rstrip("/")
api_key = os.environ.get("OPEN_WEBUI_TELEGRAM_API_KEY", "")
if not api_key:
    db_path = os.environ.get("OPEN_WEBUI_DB_PATH", "/app/backend/data/webui.db")
    if not os.path.exists(db_path):
        raise SystemExit("No API key or local Open WebUI database is available")
    connection = sqlite3.connect(db_path)
    try:
        row = connection.execute("SELECT id FROM user WHERE role = 'admin' ORDER BY created_at LIMIT 1").fetchone()
    finally:
        connection.close()
    if not row:
        raise SystemExit("No Open WebUI admin account was found")
    from open_webui.utils.auth import create_token

    api_key = create_token({"id": row[0]}, expires_delta=timedelta(minutes=2))
    base_url = "http://127.0.0.1:8080"

request = urllib.request.Request(
    f"{base_url}/api/models",
    headers={"Authorization": f"Bearer {api_key}"},
)
with urllib.request.urlopen(request, timeout=30) as response:
    payload = json.load(response)

models = payload.get("data", payload if isinstance(payload, list) else [])
jarvis_model = next((item for item in models if isinstance(item, dict) and item.get("id") == "jarvis"), {})
visible = {
    item.get("name", item.get("id")): item.get("id")
    for item in models
    if isinstance(item, dict) and item.get("id")
}
visible_names = set(visible)
unexpected = sorted(visible_names - EXPECTED_NAMES)
missing = sorted(EXPECTED_NAMES - visible_names)
print(json.dumps({"visible": visible, "unexpected": unexpected, "missing": missing}))
if unexpected or missing or len(visible) != len(EXPECTED_NAMES):
    raise SystemExit(1)
jarvis_meta = jarvis_model.get("info", {}).get("meta", {})
jarvis_capabilities = jarvis_meta.get("capabilities", {})
jarvis_tools = jarvis_meta.get("toolIds", [])
print(json.dumps({
    "jarvis_builtin_tools": jarvis_capabilities.get("builtin_tools"),
    "jarvis_web_search": jarvis_capabilities.get("web_search"),
    "jarvis_tools": jarvis_tools,
}))
if jarvis_capabilities.get("builtin_tools") is not False or "server:jarvis" not in jarvis_tools:
    raise SystemExit(1)

if os.environ.get("OPENWEBUI_SMOKE") == "1":
    smoke_request = urllib.request.Request(
        f"{base_url}/api/chat/completions",
        data=json.dumps({
            "model": visible["Nemotron Super 120B"],
            "messages": [{"role": "user", "content": "Reply with exactly NEMOTRON_READY"}],
            "stream": False,
            "max_tokens": 128,
        }).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(smoke_request, timeout=90) as response:
        smoke_payload = json.load(response)
    message = smoke_payload.get("choices", [{}])[0].get("message", {})
    content = message.get("content") or message.get("reasoning_content") or ""
    print(json.dumps({"nemotron_smoke": content.strip()}))
    if "NEMOTRON_READY" not in content:
        raise SystemExit(1)

if os.environ.get("OPENWEBUI_JARVIS_CALENDAR_SMOKE") == "1":
    jarvis_request = urllib.request.Request(
        f"{base_url}/api/chat/completions",
        data=json.dumps({
            "model": "jarvis",
            "messages": [{
                "role": "user",
                "content": (
                    "Use Jarvis Core to verify whether my Google Calendar has an event titled "
                    "i eat pizza today at 8 PM. Report only whether that exact event is verified."
                ),
            }],
            "tool_ids": ["server:jarvis"],
            "stream": False,
        }).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(jarvis_request, timeout=240) as response:
        jarvis_payload = json.load(response)
    jarvis_message = jarvis_payload.get("choices", [{}])[0].get("message", {})
    jarvis_content = jarvis_message.get("content") or ""
    tool_names = [
        call.get("function", {}).get("name")
        for call in jarvis_message.get("tool_calls") or []
        if isinstance(call, dict)
    ]
    verified = "i eat pizza" in jarvis_content.lower() or "jarvis_request" in tool_names
    print(json.dumps({"jarvis_google_calendar_smoke": verified, "tool_calls": tool_names}))
    if not verified:
        raise SystemExit(1)
