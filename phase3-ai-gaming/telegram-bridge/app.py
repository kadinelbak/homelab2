#!/usr/bin/env python3
import json
import mimetypes
import os
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BOT_TOKEN = os.environ.get("JARVIS_TELEGRAM_BOT_TOKEN", "")
ALLOWED_CHAT_IDS = {
    item.strip()
    for item in os.environ.get("JARVIS_TELEGRAM_ALLOWED_CHAT_IDS", "").split(",")
    if item.strip()
}
ORCHESTRATOR_URL = os.environ.get("AI_ORCHESTRATOR_URL", "http://ai-orchestrator:8095").rstrip("/")
ORCHESTRATOR_TOKEN = os.environ.get("AI_ORCHESTRATOR_TOKEN", "")
WHISPER_WORKER_URL = os.environ.get("WHISPER_WORKER_URL", "http://whisper-worker:8099").rstrip("/")
WHISPER_WORKER_TOKEN = os.environ.get("WHISPER_WORKER_TOKEN", "")
POLL_TIMEOUT = int(os.environ.get("JARVIS_TELEGRAM_POLL_TIMEOUT", "45"))
MAX_REPLY_CHARS = int(os.environ.get("JARVIS_TELEGRAM_MAX_REPLY_CHARS", "3500"))
DATA_DIR = Path(os.environ.get("JARVIS_TELEGRAM_DATA_DIR", "/data"))
MEMORY_PATH = DATA_DIR / "memory.json"
MEMORY_TURNS = int(os.environ.get("JARVIS_TELEGRAM_MEMORY_TURNS", "12"))


def telegram_api(method, payload=None):
    if not BOT_TOKEN or BOT_TOKEN.startswith("CHANGE_ME"):
        raise RuntimeError("JARVIS_TELEGRAM_BOT_TOKEN is not configured")
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{BOT_TOKEN}/{method}",
        data=data,
        method="POST" if payload is not None else "GET",
        headers=headers,
    )
    with urllib.request.urlopen(req, timeout=POLL_TIMEOUT + 15) as response:
        return json.loads(response.read().decode("utf-8") or "{}")


def send_message(chat_id, text):
    text = text or "Done."
    chunks = [text[i : i + MAX_REPLY_CHARS] for i in range(0, len(text), MAX_REPLY_CHARS)] or ["Done."]
    for chunk in chunks:
        telegram_api(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": chunk,
                "disable_web_page_preview": True,
            },
        )


def allowed(chat_id):
    return not ALLOWED_CHAT_IDS or str(chat_id) in ALLOWED_CHAT_IDS


def load_memory():
    if not MEMORY_PATH.exists():
        return {}
    try:
        return json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_memory(memory):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = MEMORY_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(memory, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(MEMORY_PATH)


def conversation_context(chat_id):
    memory = load_memory()
    return memory.get(str(chat_id), [])[-MEMORY_TURNS:]


def remember(chat_id, role, text):
    text = (text or "").strip()
    if not text:
        return
    memory = load_memory()
    key = str(chat_id)
    turns = memory.get(key, [])
    turns.append({"role": role, "text": text[:2000], "ts": int(time.time())})
    memory[key] = turns[-MEMORY_TURNS:]
    save_memory(memory)


def forget(chat_id):
    memory = load_memory()
    memory.pop(str(chat_id), None)
    save_memory(memory)


def post_json(url, payload=None, timeout=240):
    body = json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {ORCHESTRATOR_TOKEN}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8") or "{}")


def get_json(url, headers=None, timeout=60):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8") or "{}")


def encode_multipart(field_name, file_path, filename):
    boundary = f"----jarvis-telegram-{int(time.time() * 1000)}"
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    prefix = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode("utf-8")
    suffix = f"\r\n--{boundary}--\r\n".encode("utf-8")
    body = prefix + Path(file_path).read_bytes() + suffix
    return body, f"multipart/form-data; boundary={boundary}"


def transcribe_telegram_file(file_id):
    file_info = telegram_api("getFile", {"file_id": file_id})
    if not file_info.get("ok"):
        raise RuntimeError(file_info.get("description") or "Telegram getFile failed")
    file_path = file_info["result"]["file_path"]
    suffix = Path(file_path).suffix or ".ogg"
    download_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
    with urllib.request.urlopen(download_url, timeout=120) as response:
        audio_bytes = response.read()

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name
    try:
        body, content_type = encode_multipart("audio", tmp_path, Path(file_path).name)
        headers = {"Content-Type": content_type}
        if WHISPER_WORKER_TOKEN and not WHISPER_WORKER_TOKEN.startswith("CHANGE_ME"):
            headers["Authorization"] = f"Bearer {WHISPER_WORKER_TOKEN}"
        req = urllib.request.Request(
            WHISPER_WORKER_URL + "/transcribe",
            data=body,
            method="POST",
            headers=headers,
        )
        with urllib.request.urlopen(req, timeout=600) as response:
            data = json.loads(response.read().decode("utf-8") or "{}")
        if not data.get("ok"):
            raise RuntimeError(data.get("error") or "Whisper transcription failed")
        return data.get("text", "").strip()
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def plan_request(chat_id, text):
    payload = {
        "request": text,
        "source": "telegram",
        "inputs": {
            "telegram_chat_id": str(chat_id),
            "conversation_context": conversation_context(chat_id),
        },
        "limits": {"maximum_runtime_seconds": 1800, "maximum_cost_usd": 0},
        "permissions": {"may_execute": False, "may_publish": False},
    }
    return post_json(ORCHESTRATOR_URL + "/requests", payload)


def execute_action(action_id):
    return post_json(ORCHESTRATOR_URL + f"/actions/{action_id}/execute", {})


def approve_and_execute(action_id):
    post_json(ORCHESTRATOR_URL + f"/actions/{action_id}/approve", {})
    return execute_action(action_id)


def summarize_plan(planned):
    request = planned.get("request") or {}
    action = (planned.get("actions") or [{}])[0]
    workflow = action.get("workflow_level") or {}
    lines = [
        request.get("summary") or "I created a Jarvis action.",
        "",
        f"Capability: {request.get('capability', 'unknown')}",
        f"Worker: {action.get('worker', 'unknown')}",
        f"Status: {action.get('status', 'unknown')}",
        f"Level: {workflow.get('level', '?')} - {workflow.get('name', 'unknown')}",
    ]
    if action.get("requires_approval"):
        lines.extend(
            [
                "",
                "Approval required before I do anything else.",
                f"Reply: /approve {action.get('action_id')}",
            ]
        )
    return "\n".join(lines)


def handle_request(chat_id, text):
    remember(chat_id, "user", text)
    planned = plan_request(chat_id, text)
    action = (planned.get("actions") or [{}])[0]
    if action.get("permissions", {}).get("may_execute"):
        executed = execute_action(action["action_id"])
        result = (executed.get("action") or {}).get("result") or {}
        response = result.get("text") or result.get("summary") or "Done."
        remember(chat_id, "assistant", response)
        return response
    response = summarize_plan(planned)
    remember(chat_id, "assistant", response)
    return response


def handle_command(chat_id, text):
    command, _, rest = text.partition(" ")
    if command in {"/start", "/help"}:
        return (
            "Jarvis Telegram is online.\n\n"
            "Send text or a voice note.\n"
            "For approval-gated actions, I will give you an /approve command.\n"
            "Use /forget to clear this chat's memory."
        )
    if command == "/health":
        data = get_json(ORCHESTRATOR_URL + "/health", timeout=60)
        return f"Jarvis Core OK: {data.get('ok')} | capabilities: {data.get('capabilities')}"
    if command == "/approve":
        action_id = rest.strip()
        if not action_id:
            return "Usage: /approve act-..."
        executed = approve_and_execute(action_id)
        result = (executed.get("action") or {}).get("result") or {}
        return result.get("text") or result.get("summary") or "Approved and executed."
    if command == "/forget":
        forget(chat_id)
        return "Forgot this Telegram chat's recent Jarvis context."
    return handle_request(chat_id, text)


def handle_update(update):
    message = update.get("message") or update.get("edited_message")
    if not message:
        return
    chat_id = message.get("chat", {}).get("id")
    if chat_id is None:
        return
    print(f"telegram message chat_id={chat_id}", flush=True)
    if not allowed(chat_id):
        send_message(chat_id, "This Jarvis bot is not enabled for this chat.")
        return

    text = (message.get("text") or "").strip()
    if not text and message.get("voice"):
        send_message(chat_id, "Transcribing voice note...")
        text = transcribe_telegram_file(message["voice"]["file_id"])
    elif not text and message.get("audio"):
        send_message(chat_id, "Transcribing audio...")
        text = transcribe_telegram_file(message["audio"]["file_id"])

    if not text:
        send_message(chat_id, "Send me text or a voice note.")
        return

    if message.get("voice") or message.get("audio"):
        send_message(chat_id, f"Transcript:\n{text}")

    response = handle_command(chat_id, text) if text.startswith("/") else handle_request(chat_id, text)
    send_message(chat_id, response)


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not BOT_TOKEN or BOT_TOKEN.startswith("CHANGE_ME"):
        print("Telegram bridge disabled: set JARVIS_TELEGRAM_BOT_TOKEN to enable polling.", flush=True)
        while True:
            time.sleep(3600)

    offset = None
    print("Jarvis Telegram bridge polling.", flush=True)
    while True:
        try:
            payload = {"timeout": POLL_TIMEOUT}
            if offset is not None:
                payload["offset"] = offset
            data = telegram_api("getUpdates", payload)
            for update in data.get("result", []):
                offset = update["update_id"] + 1
                try:
                    handle_update(update)
                except Exception as exc:
                    chat_id = (update.get("message") or {}).get("chat", {}).get("id")
                    if chat_id and allowed(chat_id):
                        send_message(chat_id, f"Jarvis error: {exc}")
                    print(f"update failed: {exc}", flush=True)
        except urllib.error.HTTPError as exc:
            print(f"telegram http error: {exc}", flush=True)
            time.sleep(10)
        except Exception as exc:
            print(f"telegram bridge error: {exc}", flush=True)
            time.sleep(10)


if __name__ == "__main__":
    main()
