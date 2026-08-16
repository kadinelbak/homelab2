#!/usr/bin/env python3
import json
import mimetypes
import os
import re
import sqlite3
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

BOT_TOKEN = os.environ.get("JARVIS_TELEGRAM_BOT_TOKEN", "")
ALLOWED_CHAT_IDS = {
    item.strip()
    for item in os.environ.get("JARVIS_TELEGRAM_ALLOWED_CHAT_IDS", "").split(",")
    if item.strip()
}
ORCHESTRATOR_URL = os.environ.get("AI_ORCHESTRATOR_URL", "http://ai-orchestrator:8095").rstrip("/")
ORCHESTRATOR_TOKEN = os.environ.get("AI_ORCHESTRATOR_TOKEN", "")
JARVIS_CORE_URL = os.environ.get("JARVIS_CORE_URL", "http://jarvis-core:8097").rstrip("/")
JARVIS_CORE_TOKEN = os.environ.get("JARVIS_CORE_TOKEN", ORCHESTRATOR_TOKEN)
WHISPER_WORKER_URL = os.environ.get("WHISPER_WORKER_URL", "http://whisper-worker:8099").rstrip("/")
WHISPER_WORKER_TOKEN = os.environ.get("WHISPER_WORKER_TOKEN", "")
OPEN_WEBUI_URL = os.environ.get("OPEN_WEBUI_URL", "http://open-webui:8080").rstrip("/")
OPEN_WEBUI_API_KEY = os.environ.get("OPEN_WEBUI_TELEGRAM_API_KEY", "")
OPEN_WEBUI_ENABLED = os.environ.get("JARVIS_TELEGRAM_USE_OPENWEBUI", "false").lower() == "true"
OPEN_WEBUI_PRIMARY_MODEL = os.environ.get("JARVIS_TELEGRAM_OPENWEBUI_PRIMARY_MODEL", "jarvis-telegram-nemotron")
OPEN_WEBUI_FALLBACK_MODEL = os.environ.get("JARVIS_TELEGRAM_OPENWEBUI_FALLBACK_MODEL", "jarvis")
OPEN_WEBUI_TIMEOUT = int(os.environ.get("JARVIS_TELEGRAM_OPENWEBUI_TIMEOUT", "180"))
MEMORY_OLLAMA_URL = os.environ.get("JARVIS_TELEGRAM_MEMORY_OLLAMA_URL", "http://ollama:11434").rstrip("/")
MEMORY_MODEL = os.environ.get("JARVIS_TELEGRAM_MEMORY_MODEL", "llama3.1:latest")
MEMORY_SUMMARY_CHARS = int(os.environ.get("JARVIS_TELEGRAM_MEMORY_SUMMARY_CHARS", "5000"))
POLL_TIMEOUT = int(os.environ.get("JARVIS_TELEGRAM_POLL_TIMEOUT", "45"))
MAX_REPLY_CHARS = int(os.environ.get("JARVIS_TELEGRAM_MAX_REPLY_CHARS", "3500"))
DATA_DIR = Path(os.environ.get("JARVIS_TELEGRAM_DATA_DIR", "/data"))
MEMORY_PATH = DATA_DIR / "memory.json"
QUEUE_PATH = DATA_DIR / "telegram-jobs.sqlite3"
MEMORY_TURNS = int(os.environ.get("JARVIS_TELEGRAM_MEMORY_TURNS", "12"))
PAPERLESS_CONSUME_DIR = Path(os.environ.get("PAPERLESS_CONSUME_DIR", "/paperless-consume"))
MAX_DOCUMENT_BYTES = int(os.environ.get("JARVIS_TELEGRAM_MAX_DOCUMENT_BYTES", str(50 * 1024 * 1024)))
PAPERLESS_PICKUP_WAIT_SECONDS = int(os.environ.get("PAPERLESS_PICKUP_WAIT_SECONDS", "20"))
PAPERLESS_API_URL = os.environ.get("PAPERLESS_API_URL", "http://paperless:8000").rstrip("/")
PAPERLESS_PUBLIC_URL = os.environ.get("PAPERLESS_PUBLIC_URL", "").rstrip("/")
PAPERLESS_API_TOKEN = os.environ.get("PAPERLESS_API_TOKEN", "")
PAPERLESS_USERNAME = os.environ.get("PAPERLESS_USERNAME", "admin")
PAPERLESS_PASSWORD = os.environ.get("PAPERLESS_PASSWORD", "")
PAPERLESS_IMPORT_WAIT_SECONDS = int(os.environ.get("PAPERLESS_IMPORT_WAIT_SECONDS", "180"))
BRIEFING_ENABLED = os.environ.get("JARVIS_TELEGRAM_BRIEFING_ENABLED", "false").lower() in {"1", "true", "yes", "on"}
BRIEFING_CHAT_IDS = {
    item.strip()
    for item in os.environ.get("JARVIS_TELEGRAM_BRIEFING_CHAT_IDS", "").split(",")
    if item.strip()
}
BRIEFING_MORNING_TIME = os.environ.get("JARVIS_TELEGRAM_MORNING_BRIEF_TIME", "07:30")
BRIEFING_EVENING_TIME = os.environ.get("JARVIS_TELEGRAM_EVENING_BRIEF_TIME", "20:30")
BRIEFING_VOICE_ENABLED = os.environ.get("JARVIS_TELEGRAM_BRIEFING_VOICE_ENABLED", "false").lower() in {"1", "true", "yes", "on"}
NOTIFICATIONS_ENABLED = os.environ.get("JARVIS_TELEGRAM_NOTIFICATIONS_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
NOTIFICATION_POLL_SECONDS = int(os.environ.get("JARVIS_TELEGRAM_NOTIFICATIONS_POLL_SECONDS", "30"))
TTS_WORKER_URL = os.environ.get("JARVIS_TTS_WORKER_URL", "http://tts-worker:8101").rstrip("/")
TTS_WORKER_TOKEN = os.environ.get("JARVIS_TTS_TOKEN", "")
TTS_VOICE = os.environ.get("JARVIS_TTS_VOICE", "default")
TTS_MAX_CHARS = int(os.environ.get("JARVIS_TTS_MAX_CHARS", "12000"))
try:
    LOCAL_TZ = ZoneInfo(os.environ.get("TZ", "America/New_York"))
except ZoneInfoNotFoundError:
    LOCAL_TZ = timezone.utc


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


def telegram_api_multipart(method, fields, files):
    boundary = "----JarvisTelegramBoundary" + uuid.uuid4().hex
    chunks = []
    for key, value in fields.items():
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"))
        chunks.append(str(value).encode("utf-8"))
        chunks.append(b"\r\n")
    for key, file_info in files.items():
        filename, content_type, data = file_info
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(
            f'Content-Disposition: form-data; name="{key}"; filename="{filename}"\r\n'.encode("utf-8")
        )
        chunks.append(f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"))
        chunks.append(data)
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{BOT_TOKEN}/{method}",
        data=b"".join(chunks),
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=POLL_TIMEOUT + 60) as response:
        return json.loads(response.read().decode("utf-8") or "{}")


def sentence_text(value):
    value = re.sub(r"\s+", " ", str(value or "")).strip()
    value = value.strip("-* ")
    if not value:
        return ""
    if value[-1] not in ".?!":
        value += "."
    return value


SMALL_NUMBER_WORDS = [
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
]
TENS_NUMBER_WORDS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def integer_words(value):
    number = int(str(value).replace(",", ""))
    if number < 0:
        return "negative " + integer_words(abs(number))
    if number < 20:
        return SMALL_NUMBER_WORDS[number]
    if number < 100:
        tens, ones = divmod(number, 10)
        return TENS_NUMBER_WORDS[tens] if ones == 0 else f"{TENS_NUMBER_WORDS[tens]}-{SMALL_NUMBER_WORDS[ones]}"
    if number < 1000:
        hundreds, rest = divmod(number, 100)
        return f"{SMALL_NUMBER_WORDS[hundreds]} hundred" + (f" {integer_words(rest)}" if rest else "")
    for scale, label in ((1_000_000_000, "billion"), (1_000_000, "million"), (1_000, "thousand")):
        if number >= scale:
            high, rest = divmod(number, scale)
            return f"{integer_words(high)} {label}" + (f" {integer_words(rest)}" if rest else "")
    return str(number)


def number_words(value):
    value = str(value).replace(",", "")
    if "." not in value:
        return integer_words(value)
    whole, decimal = value.split(".", 1)
    spoken_decimal = " ".join(SMALL_NUMBER_WORDS[int(digit)] for digit in decimal if digit.isdigit())
    return f"{integer_words(whole)} point {spoken_decimal}".strip()


def protect_speech_numbers(pattern, value, placeholders):
    def replacement(match):
        key = f"__JARVIS_SPEECH_PROTECT_{len(placeholders)}__"
        placeholders[key] = match.group(0)
        return key

    return re.sub(pattern, replacement, value)


def restore_speech_numbers(value, placeholders):
    for key, original in placeholders.items():
        value = value.replace(key, original)
    return value


def regular_numbers_to_words(text):
    placeholders = {}
    text = protect_speech_numbers(r"^\s*\d+[.)]", text, placeholders)
    text = protect_speech_numbers(r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b", text, placeholders)
    text = protect_speech_numbers(
        r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}\b",
        text,
        placeholders,
    )
    text = protect_speech_numbers(r"\b\d{4}-\d{2}-\d{2}\b", text, placeholders)
    text = re.sub(r"(?<![\w:./-])-?\d[\d,]*(?:\.\d+)?(?![\w:./-])", lambda match: number_words(match.group(0)), text)
    return restore_speech_numbers(text, placeholders)


def speech_unit_text(text):
    text = str(text or "")

    def spoken_decimal(value):
        return str(value).replace(".", " point ")

    def money(match):
        amount = match.group("amount")
        suffix = match.group("suffix").upper()
        scale = {"K": "thousand", "M": "million", "B": "billion", "T": "trillion"}[suffix]
        return f"{amount} {scale} dollars"

    def temp(match):
        amount = str(round(float(match.group("amount"))))
        unit = match.group("unit").upper()
        return f"{amount} degrees {'fahrenheit' if unit == 'F' else 'celsius'}"

    text = re.sub(r"\$(?P<amount>\d+(?:\.\d+)?)\s*(?P<suffix>[KMBT])\b", money, text, flags=re.I)
    text = re.sub(r"(?P<amount>-?\d+(?:\.\d+)?)\s*°?\s*(?P<unit>[FC])\b", temp, text)
    text = re.sub(r"\b(\d+(?:\.\d+)?)%", r"\1 percent", text)
    text = re.sub(r"\b(\d+(?:\.\d+)?)\s*mph\b", r"\1 miles per hour", text, flags=re.I)
    text = re.sub(r"\b(\d+(?:\.\d+)?)\s*mi\b", r"\1 miles", text, flags=re.I)
    text = re.sub(r"\b(\d+(?:\.\d+)?)\s*in\b", r"\1 inches", text, flags=re.I)
    text = re.sub(r"\b(\d+(?:\.\d+)?)\s*hr\b", r"\1 hours", text, flags=re.I)
    text = re.sub(r"\b(\d+(?:\.\d+)?)\s*min\b", r"\1 minutes", text, flags=re.I)
    text = re.sub(r"\bPRs\b", "pull requests", text)
    text = re.sub(r"\bPR\b", "pull request", text)
    text = re.sub(r"\bCI\b", "C I", text)
    text = re.sub(r"\bAPI\b", "A P I", text)
    text = re.sub(r"\bOAuth\b", "O auth", text)
    text = re.sub(r"\bGitHub\b", "GitHub", text)
    text = regular_numbers_to_words(text)
    return text


def speechify_briefing_text(text):
    spoken = []
    current_section = ""
    section_names = {
        "TOP 3": "Top three.",
        "TODAY": "Today.",
        "MESSAGES": "Messages.",
        "PROJECTS": "Projects.",
        "GITHUB": "GitHub.",
        "WEATHER": "Weather.",
        "NEWS": "News.",
        "RISKS": "Risks.",
        "SUGGESTED PLAN": "Suggested plan.",
        "ONE QUESTION": "One question.",
        "COMPLETED": "Completed.",
        "UNRESOLVED": "Unresolved.",
        "WAITING": "Waiting.",
        "PROJECT CHANGES": "Project changes.",
        "TOMORROW": "Tomorrow.",
        "SHUTDOWN": "Shutdown.",
    }
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r"[*_`]+", "", line)
        line = re.sub(r"<([^>]+)>", "", line)
        if line in section_names:
            current_section = line
            spoken.append(section_names[line])
            continue
        if line.startswith("MORNING BRIEF"):
            date = line.split("-", 1)[1].strip() if "-" in line else ""
            spoken.append(sentence_text(f"Morning brief for {date}" if date else "Morning brief"))
            continue
        if line.startswith("EVENING BRIEF"):
            date = line.split("-", 1)[1].strip() if "-" in line else ""
            spoken.append(sentence_text(f"Evening brief for {date}" if date else "Evening brief"))
            continue
        line = speech_unit_text(line)
        numbered = re.match(r"^(\d+)[.)]\s*(.+)$", line)
        if numbered:
            spoken.append(sentence_text(f"Number {numbered.group(1)} is {numbered.group(2)}"))
            continue
        if line.startswith("- "):
            item = line[2:].strip()
            if current_section == "TOP 3":
                spoken.append(sentence_text(item))
            else:
                spoken.append(sentence_text(item))
            continue
        spoken.append(sentence_text(line))
    result = "\n\n".join(spoken)
    result = re.sub(r"\b(\d{4})-(\d{2})-(\d{2})T\d{2}:\d{2}:\d{2}[^\s,]*", r"\1-\2-\3", result)
    result = speech_unit_text(result)
    result = re.sub(r"\s+", " ", result)
    result = re.sub(r"\.\s+([A-Z][A-Z ]{2,})\.", lambda m: f". {m.group(1).title()}.", result)
    return result.strip()


def synthesize_voice(text):
    speech_text = speechify_briefing_text(text)
    payload = json.dumps({"text": speech_text, "voice": TTS_VOICE, "format": "ogg", "max_chars": 0}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if TTS_WORKER_TOKEN and not TTS_WORKER_TOKEN.startswith("CHANGE_ME"):
        headers["Authorization"] = f"Bearer {TTS_WORKER_TOKEN}"
    req = urllib.request.Request(
        TTS_WORKER_URL + "/tts/synthesize",
        data=payload,
        method="POST",
        headers=headers,
    )
    with urllib.request.urlopen(req, timeout=240) as response:
        return response.read(), response.headers.get("Content-Type", "audio/ogg")


def send_voice_briefing(chat_id, text):
    if not BRIEFING_VOICE_ENABLED:
        return {"status": "disabled"}
    try:
        audio, content_type = synthesize_voice(text)
        telegram_api_multipart(
            "sendVoice",
            {"chat_id": chat_id},
            {"voice": ("briefing.ogg", content_type or "audio/ogg", audio)},
        )
        return {"status": "completed"}
    except Exception as exc:
        print(f"telegram briefing voice error: {exc}", flush=True)
        send_message(chat_id, f"Voice briefing unavailable: {str(exc)[:160]}")
        return {"status": "failed", "error": str(exc)}


def allowed(chat_id):
    return not ALLOWED_CHAT_IDS or str(chat_id) in ALLOWED_CHAT_IDS


def openwebui_configured():
    return OPEN_WEBUI_ENABLED and bool(OPEN_WEBUI_API_KEY and not OPEN_WEBUI_API_KEY.startswith("CHANGE_ME"))


def queue_connection():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(QUEUE_PATH, timeout=30)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            update_id INTEGER UNIQUE,
            chat_id TEXT NOT NULL,
            text TEXT NOT NULL,
            status TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            next_attempt_at INTEGER NOT NULL,
            created_at INTEGER NOT NULL,
            last_error TEXT NOT NULL DEFAULT ''
        )
        """
    )
    connection.commit()
    return connection


def enqueue_job(update_id, chat_id, text):
    now = int(time.time())
    job_id = f"tg-{update_id or uuid.uuid4().hex}"
    with queue_connection() as connection:
        try:
            connection.execute(
                "INSERT INTO jobs (id, update_id, chat_id, text, status, next_attempt_at, created_at) VALUES (?, ?, ?, ?, 'queued', ?, ?)",
                (job_id, update_id, str(chat_id), text, now, now),
            )
        except sqlite3.IntegrityError:
            return None
    return job_id


def post_openwebui(path, payload, timeout=OPEN_WEBUI_TIMEOUT):
    if not openwebui_configured():
        raise RuntimeError("Open WebUI Telegram integration is not configured")
    req = urllib.request.Request(
        OPEN_WEBUI_URL + path,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {OPEN_WEBUI_API_KEY}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8") or "{}")


def openwebui_messages(chat_id, text):
    messages = [
        {
            "role": "system",
            "content": (
                "You are Jarvis. Use the configured Jarvis tools for verified Gmail, Calendar, "
                "Paperless, Google Tasks, Google Contacts, Daily Briefing, Codex, and homelab actions. Never claim an external "
                "action completed unless the tool result says completed or verified. Resolve named email recipients through Contacts instead of guessing. Explain approval "
                "requirements and include an action ID when one is returned."
            ),
        }
    ]
    for turn in conversation_context(chat_id):
        role = turn.get("role")
        if role in {"user", "assistant"} and turn.get("text"):
            messages.append({"role": role, "content": turn["text"]})
    messages.append({"role": "user", "content": text})
    return messages


def openwebui_response(chat_id, text):
    payload = {
        "model": OPEN_WEBUI_PRIMARY_MODEL,
        "messages": openwebui_messages(chat_id, text),
        "tool_ids": ["server:jarvis"],
        "stream": False,
    }
    try:
        result = post_openwebui("/api/chat/completions", payload)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
        # The local profile is intentionally used only when the hosted path is unavailable.
        payload["model"] = OPEN_WEBUI_FALLBACK_MODEL
        result = post_openwebui("/api/chat/completions", payload)
    choice = ((result.get("choices") or [{}])[0]).get("message") or {}
    content = choice.get("content") or "Jarvis completed the request, but Open WebUI returned no text."
    return content.strip()


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
    record = memory.get(str(chat_id), [])
    if isinstance(record, list):
        record = {"recent": record, "summary": ""}
    summary = (record.get("summary") or "").strip()
    context = []
    if summary:
        context.append(
            {
                "role": "system",
                "text": (
                    "Background memory from older messages. Use it only to resolve references to earlier "
                    "conversations; the most recent user request is authoritative.\n" + summary
                )[:MEMORY_SUMMARY_CHARS],
            }
        )
    return context + (record.get("recent") or [])[-MEMORY_TURNS:]


def summarize_memory(previous_summary, evicted_turns):
    material = "\n".join(f"{turn.get('role', 'user')}: {turn.get('text', '')}" for turn in evicted_turns)
    if not material:
        return previous_summary
    prompt = {
        "model": MEMORY_MODEL,
        "stream": False,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Maintain concise background memory for a personal assistant. Preserve stable preferences, "
                    "named people, unresolved follow-ups, and identifiers of recently created calendar, email, "
                    "or document actions. Do not invent facts. This memory is background only and must never "
                    "override a newer user request."
                ),
            },
            {"role": "user", "content": f"Existing summary:\n{previous_summary}\n\nOlder turns to merge:\n{material}"},
        ],
        "options": {"temperature": 0, "num_predict": 400},
    }
    try:
        req = urllib.request.Request(
            MEMORY_OLLAMA_URL + "/api/chat",
            data=json.dumps(prompt).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=45) as response:
            text = json.loads(response.read().decode("utf-8") or "{}").get("message", {}).get("content", "").strip()
        if text:
            return text[:MEMORY_SUMMARY_CHARS]
    except Exception as exc:
        print(f"telegram memory summary fallback: {exc}", flush=True)
    fallback = (previous_summary + "\n" + material).strip()
    return fallback[-MEMORY_SUMMARY_CHARS:]


def remember(chat_id, role, text):
    text = (text or "").strip()
    if not text:
        return
    memory = load_memory()
    key = str(chat_id)
    record = memory.get(key, [])
    if isinstance(record, list):
        record = {"recent": record, "summary": ""}
    turns = record.get("recent") or []
    turns.append({"role": role, "text": text[:2000], "ts": int(time.time())})
    evicted = turns[:-MEMORY_TURNS]
    if evicted:
        record["summary"] = summarize_memory(record.get("summary", ""), evicted)
    record["recent"] = turns[-MEMORY_TURNS:]
    memory[key] = record
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


def core_headers():
    headers = {"Content-Type": "application/json"}
    if JARVIS_CORE_TOKEN:
        headers["Authorization"] = f"Bearer {JARVIS_CORE_TOKEN}"
    return headers


def core_get(path, timeout=60):
    return get_json(JARVIS_CORE_URL + path, headers=core_headers(), timeout=timeout)


def core_post(path, payload=None, timeout=60):
    body = json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(JARVIS_CORE_URL + path, data=body, method="POST", headers=core_headers())
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8") or "{}")


def notification_text(item):
    payload = item.get("payload") or {}
    title = payload.get("title") or "Jarvis notification"
    body = payload.get("body") or ""
    severity = payload.get("severity") or "info"
    return f"Jarvis {severity.upper()}: {title}\n{body}".strip()


def deliver_core_notifications():
    targets = BRIEFING_CHAT_IDS or ALLOWED_CHAT_IDS
    if not NOTIFICATIONS_ENABLED or not targets:
        return
    data = core_get("/api/v1/notifications?channel=telegram&status=pending", timeout=60)
    for item in data.get("notifications") or []:
        sent_count = 0
        failed_count = 0
        for chat_id in targets:
            try:
                if allowed(chat_id):
                    send_message(chat_id, notification_text(item))
                    sent_count += 1
            except Exception as exc:
                failed_count += 1
                print(f"telegram notification delivery failed: {exc}", flush=True)
        status = "delivered" if sent_count else "failed"
        core_post(
            f"/api/v1/notifications/{item.get('id')}/delivery",
            {"status": status, "delivered_by": f"telegram-bridge sent={sent_count} failed={failed_count}"},
            timeout=60,
        )


def paperless_headers():
    headers = {"Accept": "application/json"}
    if PAPERLESS_API_TOKEN:
        headers["Authorization"] = f"Token {PAPERLESS_API_TOKEN}"
    elif PAPERLESS_PASSWORD:
        raw = f"{PAPERLESS_USERNAME}:{PAPERLESS_PASSWORD}".encode("utf-8")
        import base64

        headers["Authorization"] = "Basic " + base64.b64encode(raw).decode("ascii")
    return headers


def paperless_api_get(path, query=None, timeout=30):
    if not PAPERLESS_API_URL:
        return {}
    suffix = path if path.startswith("/") else f"/{path}"
    url = PAPERLESS_API_URL + suffix
    if query:
        url += "?" + urllib.parse.urlencode(query)
    return get_json(url, headers=paperless_headers(), timeout=timeout)


def document_matches_upload(doc, original_name, queued_name, upload_started_at):
    haystack = " ".join(
        str(doc.get(key, ""))
        for key in ("title", "original_file_name", "archive_filename", "filename")
    ).lower()
    stems = {
        Path(original_name).stem.lower(),
        Path(queued_name).stem.lower(),
        original_name.lower(),
        queued_name.lower(),
    }
    if any(stem and stem in haystack for stem in stems):
        return True
    return False


def wait_for_paperless_document(original_name, queued_name, upload_started_at):
    if not (PAPERLESS_API_TOKEN or PAPERLESS_PASSWORD):
        return {"status": "api_not_configured"}
    deadline = time.time() + max(0, PAPERLESS_IMPORT_WAIT_SECONDS)
    last_error = ""
    while time.time() < deadline:
        try:
            data = paperless_api_get(
                "/api/documents/",
                {
                    "page_size": 10,
                    "ordering": "-created",
                    "query": Path(original_name).stem,
                },
                timeout=30,
            )
            results = data.get("results") or []
            if not results:
                data = paperless_api_get("/api/documents/", {"page_size": 10, "ordering": "-created"}, timeout=30)
                results = data.get("results") or []
            for doc in results:
                if document_matches_upload(doc, original_name, queued_name, upload_started_at):
                    if not doc.get("id"):
                        return {"status": "failed", "error": "paperless_document_missing_id", "document": doc}
                    has_archive = bool(doc.get("archive_filename") or doc.get("archived_file_name"))
                    has_ocr = bool(doc.get("content") or doc.get("checksum") or doc.get("archive_serial_number") or has_archive)
                    status = "completed" if has_ocr else "processing"
                    return {"status": status, "document": doc, "ocr_verified": has_ocr, "archive_verified": has_archive}
        except Exception as exc:
            last_error = str(exc)[:200]
        time.sleep(5)
    return {"status": "processing", "error": last_error}


def paperless_document_url(doc):
    doc_id = doc.get("id")
    if not doc_id:
        return ""
    base = PAPERLESS_PUBLIC_URL or PAPERLESS_API_URL
    return f"{base}/documents/{doc_id}/details"


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


def safe_filename(name):
    cleaned = re.sub(r"[^A-Za-z0-9._ -]+", "_", name or "telegram-upload")
    cleaned = cleaned.strip(" ._-") or "telegram-upload"
    return cleaned[:180]


def telegram_file_info(file_id):
    file_info = telegram_api("getFile", {"file_id": file_id})
    if not file_info.get("ok"):
        raise RuntimeError(file_info.get("description") or "Telegram getFile failed")
    return file_info["result"]


def download_telegram_file(file_id):
    info = telegram_file_info(file_id)
    file_path = info["file_path"]
    suffix = Path(file_path).suffix or ".ogg"
    download_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
    with urllib.request.urlopen(download_url, timeout=120) as response:
        data = response.read()
    return data, file_path, suffix


def ingest_document(chat_id, document):
    file_size = int(document.get("file_size") or 0)
    if file_size and file_size > MAX_DOCUMENT_BYTES:
        return f"That file is too large for Telegram ingest right now ({file_size} bytes)."

    data, file_path, suffix = download_telegram_file(document["file_id"])
    if len(data) > MAX_DOCUMENT_BYTES:
        return f"That file is too large for Telegram ingest right now ({len(data)} bytes)."

    PAPERLESS_CONSUME_DIR.mkdir(parents=True, exist_ok=True)
    original_name = document.get("file_name") or Path(file_path).name or f"telegram-upload{suffix}"
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    upload_started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    target = PAPERLESS_CONSUME_DIR / f"{timestamp}-chat-{chat_id}-{safe_filename(original_name)}"
    target.write_bytes(data)
    target_size = target.stat().st_size if target.exists() else 0
    queued = target.exists() and target_size == len(data)
    picked_up = False
    if queued:
        deadline = time.time() + max(0, PAPERLESS_PICKUP_WAIT_SECONDS)
        while time.time() < deadline:
            if not target.exists():
                picked_up = True
                break
            time.sleep(1)
    lines = [
        "Paperless status: queued" if queued else "Paperless status: failed",
        (
            "Verified Paperless picked up document for OCR/import."
            if picked_up
            else "Verified queued for Paperless; pickup is still pending."
            if queued
            else "Queue verification failed."
        ),
        f"File: {target.name}\n"
        f"Bytes queued: {target_size}/{len(data)}"
    ]
    if queued or picked_up:
        result = wait_for_paperless_document(original_name, target.name, upload_started_at)
        if result.get("status") == "completed":
            doc = result.get("document") or {}
            title = doc.get("title") or original_name
            lines.extend(
                [
                    "",
                    "Paperless status: completed",
                    "Verified Paperless import completed.",
                    f"Document ID: {doc.get('id')}",
                    f"Title: {title}",
                    f"OCR verified: {bool(result.get('ocr_verified'))}",
                    f"Archive verified: {bool(result.get('archive_verified'))}",
                ]
            )
            url = paperless_document_url(doc)
            if url:
                lines.append(f"Link: {url}")
        elif result.get("status") == "api_not_configured":
            lines.extend(["", "Paperless status: api_not_configured", "Paperless API verification is not configured."])
        elif result.get("status") == "failed":
            lines.extend(["", "Paperless status: failed", f"Paperless verification failed: {result.get('error') or 'unknown error'}"])
        else:
            lines.extend(["", "Paperless status: processing", "Paperless import is still processing. I verified the handoff, but OCR/import has not appeared in the API yet."])
    return "\n".join(lines)


def transcribe_telegram_file(file_id):
    audio_bytes, file_path, suffix = download_telegram_file(file_id)

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


def handle_transcribed_voice(chat_id, update_id, media):
    try:
        text = transcribe_telegram_file(media["file_id"])
    except Exception as exc:
        print(f"telegram voice transcription error: {exc}", flush=True)
        send_message(chat_id, f"I could not transcribe that voice note: {exc}")
        return
    if not text:
        send_message(chat_id, "I could not make out that voice note.")
        return
    send_message(chat_id, f"Heard: {text}")
    try:
        job_id = enqueue_job(update_id, chat_id, text)
    except Exception as exc:
        print(f"telegram voice enqueue error: {exc}", flush=True)
        send_message(chat_id, f"I heard it, but could not queue the Jarvis request: {exc}")
        return
    if job_id:
        send_message(chat_id, "Working on it...")
    else:
        send_message(chat_id, "I already queued that voice note.")


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


def build_briefing(chat_id, kind="morning"):
    kind = "evening" if str(kind).lower().startswith("even") else "morning"
    try:
        data = core_get(f"/api/v1/daily-brief?kind={urllib.parse.quote(kind)}", timeout=240)
        text = data.get("text") or f"{kind.title()} brief built."
        remember(chat_id, "assistant", text)
        return text
    except Exception as exc:
        print(f"telegram core briefing fallback: {exc}", flush=True)
    payload = {
        "request": "Build evening recap and tomorrow prep" if kind == "evening" else "Build morning daily briefing",
        "source": "telegram",
        "capability": "daily_briefing",
        "inputs": {
            "telegram_chat_id": str(chat_id),
            "conversation_context": conversation_context(chat_id),
        },
        "limits": {"maximum_runtime_seconds": 1800, "maximum_cost_usd": 0},
        "permissions": {"may_execute": False, "may_publish": False},
    }
    planned = post_json(ORCHESTRATOR_URL + "/requests", payload)
    action = (planned.get("actions") or [{}])[0]
    if not action.get("permissions", {}).get("may_execute"):
        return summarize_plan(planned)
    executed = execute_action(action["action_id"])
    result = (executed.get("action") or {}).get("result") or {}
    text = result.get("text") or result.get("summary") or "Briefing built."
    remember(chat_id, "assistant", text)
    return text


def save_core_briefing(kind="morning"):
    kind = "evening" if str(kind).lower().startswith("even") else "morning"
    data = core_get(f"/api/v1/daily-brief?kind={urllib.parse.quote(kind)}&save=true", timeout=240)
    return data.get("text") or f"{kind.title()} brief saved."


def send_briefing(chat_id, kind="morning"):
    text = build_briefing(chat_id, kind)
    send_message(chat_id, text)
    send_voice_briefing(chat_id, text)


def get_profile():
    return get_json(ORCHESTRATOR_URL + "/profile", headers={"Authorization": f"Bearer {ORCHESTRATOR_TOKEN}"}, timeout=60)


def update_profile(updates):
    return post_json(ORCHESTRATOR_URL + "/profile", {"updates": updates})


def profile_note(operation, **payload):
    return post_json(ORCHESTRATOR_URL + "/profile/notes", {"operation": operation, **payload})


def profile_summary(profile):
    repos = profile.get("watched_repos") or []
    projects = profile.get("active_projects") or []
    return "\n".join(
        [
            f"City: {profile.get('current_city') or 'Gainesville'}",
            "Watched repos: " + (", ".join(repos) if repos else "none"),
            "Active projects: " + (", ".join(projects[:5]) if projects else "none"),
            f"Brief notes: {len(profile.get('notes') or [])}",
        ]
    )


def parse_brief_time(value):
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", str(value or "").strip())
    if not match:
        return 7, 30
    hour = min(max(int(match.group(1)), 0), 23)
    minute = min(max(int(match.group(2)), 0), 59)
    return hour, minute


def briefing_targets():
    targets = BRIEFING_CHAT_IDS or ALLOWED_CHAT_IDS
    return sorted(targets)


def briefing_scheduler():
    sent = set()
    while True:
        try:
            if BRIEFING_ENABLED:
                now_local = datetime.now(LOCAL_TZ)
                schedule = {
                    "morning": parse_brief_time(BRIEFING_MORNING_TIME),
                    "evening": parse_brief_time(BRIEFING_EVENING_TIME),
                }
                for kind, (hour, minute) in schedule.items():
                    key = (kind, now_local.date().isoformat(), hour, minute)
                    if now_local.hour == hour and now_local.minute == minute and key not in sent:
                        try:
                            save_core_briefing(kind)
                        except Exception as exc:
                            print(f"telegram scheduled core briefing fallback: {exc}", flush=True)
                            for chat_id in briefing_targets():
                                if allowed(chat_id):
                                    send_briefing(chat_id, kind)
                        sent.add(key)
                if len(sent) > 20:
                    today = now_local.date().isoformat()
                    sent = {item for item in sent if item[1] == today}
        except Exception as exc:
            print(f"telegram briefing scheduler error: {exc}", flush=True)
        time.sleep(30)


def summarize_plan(planned):
    request = planned.get("request") or {}
    actions = planned.get("actions") or []
    action = actions[0] if actions else {}
    workflow = action.get("workflow_level") or {}
    lines = [
        request.get("summary") or "I created a Jarvis action.",
        "",
        f"Capability: {request.get('capability', 'unknown')}",
        f"Actions: {len(actions)}",
        f"Status: {request.get('status', action.get('status', 'unknown'))}",
        f"Level: {workflow.get('level', '?')} - {workflow.get('name', 'unknown')}",
    ]
    for item in actions:
        lines.append(f"{item.get('sequence', '?')}. {item.get('capability')} via {item.get('worker')} - {item.get('status')}")
    approval_actions = [item for item in actions if item.get("requires_approval")]
    if approval_actions:
        lines.extend(
            [
                "",
                "Approval required before I do anything else for:",
            ]
        )
        lines.extend(f"/approve {item.get('action_id')}" for item in approval_actions)
    return "\n".join(lines)


def handle_request(chat_id, text):
    remember(chat_id, "user", text)
    if openwebui_configured():
        response = openwebui_response(chat_id, text)
        remember(chat_id, "assistant", response)
        return response
    planned = plan_request(chat_id, text)
    responses = []
    approval_needed = []
    for action in planned.get("actions") or []:
        if action.get("permissions", {}).get("may_execute"):
            executed = execute_action(action["action_id"])
            result = (executed.get("action") or {}).get("result") or {}
            responses.append(result.get("text") or result.get("summary") or "Done.")
        else:
            approval_needed.append(action)
    if responses or approval_needed:
        if approval_needed:
            responses.append(summarize_plan({**planned, "actions": approval_needed}))
        response = "\n\n".join(responses)
        remember(chat_id, "assistant", response)
        return response
    response = summarize_plan(planned)
    remember(chat_id, "assistant", response)
    return response


def process_due_jobs():
    now = int(time.time())
    with queue_connection() as connection:
        rows = connection.execute(
            "SELECT id, chat_id, text, attempts FROM jobs WHERE status='queued' AND next_attempt_at <= ? ORDER BY created_at LIMIT 1",
            (now,),
        ).fetchall()
        if not rows:
            return
        job_id, chat_id, text, attempts = rows[0]
        connection.execute("UPDATE jobs SET status='running' WHERE id=?", (job_id,))

    try:
        response = handle_request(chat_id, text)
        send_message(chat_id, response)
        with queue_connection() as connection:
            connection.execute("UPDATE jobs SET status='completed' WHERE id=?", (job_id,))
    except Exception as exc:
        attempts += 1
        retry_delay = min(600, 30 * (2 ** min(attempts - 1, 5)))
        if attempts >= 12:
            send_message(chat_id, "Jarvis could not complete the queued request after repeated retries. Please try again later.")
            status = "failed"
        else:
            status = "queued"
        with queue_connection() as connection:
            connection.execute(
                "UPDATE jobs SET status=?, attempts=?, next_attempt_at=?, last_error=? WHERE id=?",
                (status, attempts, int(time.time()) + retry_delay, str(exc)[:500], job_id),
            )


def queue_worker():
    while True:
        try:
            process_due_jobs()
        except Exception as exc:
            print(f"telegram queue error: {exc}", flush=True)
        time.sleep(2)


def notification_worker():
    while True:
        try:
            deliver_core_notifications()
        except Exception as exc:
            print(f"telegram notification worker error: {exc}", flush=True)
        time.sleep(max(10, NOTIFICATION_POLL_SECONDS))


def handle_command(chat_id, text):
    command, _, rest = text.partition(" ")
    if command in {"/start", "/help"}:
        return (
            "Jarvis Telegram is online.\n\n"
            "Send text, including Telegram voice typing.\n"
            "For audio files, use Open WebUI transcription first.\n"
            "For approval-gated actions, I will give you an /approve command.\n"
            "Use /notifications to read pending Jarvis Core notifications.\n"
            "Use /brief, /brief morning, or /brief evening for Calendar/Gmail/Tasks briefing.\n"
            "Use /city, /setcity, /watchrepo, /unwatchrepo, /briefprefs, /rememberbrief, and /forgetbrief to manage briefing context.\n"
            "Use /forget to clear this chat's memory."
        )
    if command == "/health":
        data = get_json(ORCHESTRATOR_URL + "/health", timeout=60)
        return f"Jarvis Core OK: {data.get('ok')} | capabilities: {data.get('capabilities')}"
    if command == "/notifications":
        data = core_get("/api/v1/notifications?channel=telegram&status=pending", timeout=60)
        items = data.get("notifications") or []
        if not items:
            return "No pending Jarvis Core notifications."
        for item in items:
            core_post(
                f"/api/v1/notifications/{item.get('id')}/delivery",
                {"status": "delivered", "delivered_by": "telegram-command"},
                timeout=60,
            )
        return "\n\n".join(notification_text(item) for item in items[:10])
    if command == "/approve":
        action_id = rest.strip()
        if not action_id:
            return "Usage: /approve act-..."
        executed = approve_and_execute(action_id)
        result = (executed.get("action") or {}).get("result") or {}
        return result.get("text") or result.get("summary") or "Approved and executed."
    if command == "/brief":
        kind = "evening" if rest.strip().lower().startswith("even") else "morning"
        text = build_briefing(chat_id, kind)
        send_voice_briefing(chat_id, text)
        return text
    if command == "/city":
        data = get_profile()
        profile = data.get("profile") or {}
        return f"Current briefing city: {profile.get('current_city') or 'Gainesville'}"
    if command == "/setcity":
        city = rest.strip()
        if not city:
            return "Usage: /setcity Gainesville"
        data = update_profile({"current_city": city})
        profile = data.get("profile") or {}
        return f"Current briefing city set to {profile.get('current_city') or city}."
    if command == "/briefprefs":
        data = get_profile()
        return profile_summary(data.get("profile") or {})
    if command == "/watchrepo":
        repo = rest.strip()
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo or ""):
            return "Usage: /watchrepo owner/repo"
        profile = (get_profile().get("profile") or {})
        repos = list(dict.fromkeys((profile.get("watched_repos") or []) + [repo]))
        update_profile({"watched_repos": repos})
        return f"Watching GitHub repo: {repo}"
    if command == "/unwatchrepo":
        repo = rest.strip()
        if not repo:
            return "Usage: /unwatchrepo owner/repo"
        profile = (get_profile().get("profile") or {})
        repos = [item for item in (profile.get("watched_repos") or []) if item.lower() != repo.lower()]
        update_profile({"watched_repos": repos})
        return f"Removed GitHub repo from briefing watchlist: {repo}"
    if command == "/rememberbrief":
        note = rest.strip()
        if not note:
            return "Usage: /rememberbrief MCAT is the top project this week"
        data = profile_note("add", note=note)
        return f"Saved briefing note #{(data.get('note') or {}).get('id', '?')}."
    if command == "/forgetbrief":
        target = rest.strip()
        if not target:
            return "Usage: /forgetbrief note-id-or-text"
        payload = {"id": int(target)} if target.isdigit() else {"text": target}
        profile_note("delete", **payload)
        return "Removed matching briefing note."
    if command == "/forget":
        forget(chat_id)
        return "Forgot this Telegram chat's recent Jarvis context."
    return handle_request(chat_id, text)


def handle_update(update):
    update_id = update.get("update_id")
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
    if not text and (message.get("voice") or message.get("audio")):
        send_message(chat_id, "Transcribing voice note...")
        handle_transcribed_voice(chat_id, update_id, message.get("voice") or message.get("audio"))
        return
    elif not text and message.get("document"):
        send_message(chat_id, "Sending document to Paperless...")
        send_message(chat_id, ingest_document(chat_id, message["document"]))
        return

    if not text:
        send_message(chat_id, "Send me text or a voice note.")
        return

    if text.startswith("/"):
        send_message(chat_id, handle_command(chat_id, text))
        return
    if enqueue_job(update_id, chat_id, text):
        send_message(chat_id, "Working on it...")


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not BOT_TOKEN or BOT_TOKEN.startswith("CHANGE_ME"):
        print("Telegram bridge disabled: set JARVIS_TELEGRAM_BOT_TOKEN to enable polling.", flush=True)
        while True:
            time.sleep(3600)

    offset = None
    print("Jarvis Telegram bridge polling.", flush=True)
    threading.Thread(target=queue_worker, daemon=True).start()
    threading.Thread(target=briefing_scheduler, daemon=True).start()
    threading.Thread(target=notification_worker, daemon=True).start()
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
