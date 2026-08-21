#!/usr/bin/env python3
import argparse
import audioop
import hashlib
import json
import logging
import mimetypes
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
import wave
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from urllib.parse import urlparse

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")


def load_dotenv(path):
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


@dataclass
class VoiceConfig:
    chat_url: str = "http://100.79.132.39:18100"
    chat_token: str = ""
    wake_phrase: str = "hey_jarvis"
    greeting: str = "Hey Kad, what do you need?"
    sample_rate: int = 16000
    wake_threshold: float = 0.98
    wake_consecutive_hits: int = 4
    wake_inference_framework: str = "onnx"
    wake_cooldown_seconds: float = 30.0
    post_turn_cooldown_seconds: float = 10.0
    enable_wake_word: bool = True
    enable_push_to_talk: bool = True
    push_to_talk_hotkey: str = "ctrl+alt+j"
    suppress_wake_while_speaking: bool = True
    log_dir: str = "logs"
    spoken_response_max_chars: int = 900
    tunnel_server: str = "kadin@100.79.132.39"
    tunnel_local_port: int = 18100
    tunnel_remote_port: int = 18100
    record_max_seconds: float = 18.0
    record_start_timeout_seconds: float = 5.0
    record_min_seconds: float = 1.0
    record_silence_seconds: float = 1.8
    record_rms_threshold: int = 450
    tts_voice: str = "af_heart"
    desktop_worker_enabled: bool = True
    desktop_worker_id: str = "kadin-laptop"
    desktop_worker_display_name: str = "Kadin Laptop"
    desktop_worker_type: str = "desktop"
    desktop_worker_heartbeat_seconds: float = 15.0
    desktop_worker_claim_seconds: float = 5.0
    desktop_worker_allowed_roots: str = ""
    desktop_worker_quarantine: str = ""
    desktop_enable_files: bool = True
    desktop_enable_notify: bool = True
    desktop_enable_open_url: bool = True
    instance_lock_port: int = 18191

    @classmethod
    def from_env(cls):
        return cls(
            chat_url=os.environ.get("JARVIS_CHAT_URL", cls.chat_url).rstrip("/"),
            chat_token=os.environ.get("JARVIS_CHAT_TOKEN", ""),
            wake_phrase=os.environ.get("JARVIS_WAKE_PHRASE", cls.wake_phrase),
            greeting=os.environ.get("JARVIS_GREETING", cls.greeting),
            sample_rate=int(os.environ.get("JARVIS_SAMPLE_RATE", cls.sample_rate)),
            wake_threshold=float(os.environ.get("JARVIS_WAKE_THRESHOLD", cls.wake_threshold)),
            wake_consecutive_hits=int(os.environ.get("JARVIS_WAKE_CONSECUTIVE_HITS", cls.wake_consecutive_hits)),
            wake_inference_framework=os.environ.get("JARVIS_WAKE_INFERENCE_FRAMEWORK", cls.wake_inference_framework),
            wake_cooldown_seconds=float(os.environ.get("JARVIS_WAKE_COOLDOWN_SECONDS", cls.wake_cooldown_seconds)),
            post_turn_cooldown_seconds=float(os.environ.get("JARVIS_POST_TURN_COOLDOWN_SECONDS", cls.post_turn_cooldown_seconds)),
            enable_wake_word=env_bool("JARVIS_ENABLE_WAKE_WORD", cls.enable_wake_word),
            enable_push_to_talk=env_bool("JARVIS_ENABLE_PUSH_TO_TALK", cls.enable_push_to_talk),
            push_to_talk_hotkey=os.environ.get("JARVIS_PUSH_TO_TALK_HOTKEY", cls.push_to_talk_hotkey),
            suppress_wake_while_speaking=env_bool("JARVIS_SUPPRESS_WAKE_WHILE_SPEAKING", cls.suppress_wake_while_speaking),
            log_dir=os.environ.get("JARVIS_LOG_DIR", cls.log_dir),
            spoken_response_max_chars=int(os.environ.get("JARVIS_SPOKEN_RESPONSE_MAX_CHARS", cls.spoken_response_max_chars)),
            tunnel_server=os.environ.get("JARVIS_TUNNEL_SERVER", cls.tunnel_server),
            tunnel_local_port=int(os.environ.get("JARVIS_TUNNEL_LOCAL_PORT", cls.tunnel_local_port)),
            tunnel_remote_port=int(os.environ.get("JARVIS_TUNNEL_REMOTE_PORT", cls.tunnel_remote_port)),
            record_max_seconds=float(os.environ.get("JARVIS_RECORD_MAX_SECONDS", cls.record_max_seconds)),
            record_start_timeout_seconds=float(os.environ.get("JARVIS_RECORD_START_TIMEOUT_SECONDS", cls.record_start_timeout_seconds)),
            record_min_seconds=float(os.environ.get("JARVIS_RECORD_MIN_SECONDS", cls.record_min_seconds)),
            record_silence_seconds=float(os.environ.get("JARVIS_RECORD_SILENCE_SECONDS", cls.record_silence_seconds)),
            record_rms_threshold=int(os.environ.get("JARVIS_RECORD_RMS_THRESHOLD", cls.record_rms_threshold)),
            tts_voice=os.environ.get("JARVIS_TTS_VOICE", cls.tts_voice),
            desktop_worker_enabled=env_bool("JARVIS_DESKTOP_WORKER_ENABLED", cls.desktop_worker_enabled),
            desktop_worker_id=os.environ.get("JARVIS_DESKTOP_WORKER_ID", cls.desktop_worker_id),
            desktop_worker_display_name=os.environ.get("JARVIS_DESKTOP_WORKER_DISPLAY_NAME", cls.desktop_worker_display_name),
            desktop_worker_type=os.environ.get("JARVIS_DESKTOP_WORKER_TYPE", cls.desktop_worker_type),
            desktop_worker_heartbeat_seconds=float(os.environ.get("JARVIS_DESKTOP_HEARTBEAT_SECONDS", cls.desktop_worker_heartbeat_seconds)),
            desktop_worker_claim_seconds=float(os.environ.get("JARVIS_DESKTOP_CLAIM_SECONDS", cls.desktop_worker_claim_seconds)),
            desktop_worker_allowed_roots=os.environ.get("JARVIS_DESKTOP_ALLOWED_ROOTS", cls.desktop_worker_allowed_roots),
            desktop_worker_quarantine=os.environ.get("JARVIS_DESKTOP_QUARANTINE", cls.desktop_worker_quarantine),
            desktop_enable_files=env_bool("JARVIS_DESKTOP_ENABLE_FILES", cls.desktop_enable_files),
            desktop_enable_notify=env_bool("JARVIS_DESKTOP_ENABLE_NOTIFY", cls.desktop_enable_notify),
            desktop_enable_open_url=env_bool("JARVIS_DESKTOP_ENABLE_OPEN_URL", cls.desktop_enable_open_url),
            instance_lock_port=int(os.environ.get("JARVIS_INSTANCE_LOCK_PORT", cls.instance_lock_port)),
        )


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return bool(default)
    return value.strip().lower() in {"1", "true", "yes", "on"}


class VoiceState(str, Enum):
    DISCONNECTED = "disconnected"
    LISTENING = "listening"
    RECORDING = "recording"
    PROCESSING = "processing"
    SPEAKING = "speaking"
    PAUSED = "paused"
    ERROR = "error"


@dataclass
class VoiceTurn:
    transcript: str = ""
    response_text: str = ""
    approval_required: bool = False
    states: list[str] = field(default_factory=list)


def setup_logging(config):
    log_dir = Path(config.log_dir)
    if not log_dir.is_absolute():
        log_dir = Path.cwd() / log_dir
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=str(log_dir / "jarvis-voice-client.log"),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    return log_dir


_INSTANCE_LOCKS = []


def acquire_instance_lock(config, name="jarvis-voice-client"):
    try:
        lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        lock_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        lock_socket.bind(("127.0.0.1", config.instance_lock_port))
        lock_socket.listen(1)
        _INSTANCE_LOCKS.append(lock_socket)
    except OSError:
        logging.info("%s is already running on lock port %s; exiting duplicate instance", name, config.instance_lock_port)
        return False

    log_dir = Path(config.log_dir)
    if not log_dir.is_absolute():
        log_dir = Path.cwd() / log_dir
    log_dir.mkdir(parents=True, exist_ok=True)
    lock_file = open(log_dir / f"{name}.lock", "a+b")
    try:
        if os.name == "nt":
            import msvcrt

            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock_file.close()
        logging.info("%s is already running; exiting duplicate instance", name)
        return False
    lock_file.seek(0)
    lock_file.truncate()
    lock_file.write(str(os.getpid()).encode("ascii"))
    lock_file.flush()
    _INSTANCE_LOCKS.append(lock_file)
    return True


def normalized_query(text):
    return re.sub(r"[^a-z0-9 ]+", "", str(text or "").lower()).strip()


def easter_egg_response(text):
    if normalized_query(text) == "how fat is zach":
        return "Zach is running in full legendary mode today."
    return None


def display_time_from_iso(match):
    value = match.group(0)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    hour = parsed.hour % 12 or 12
    minute = f":{parsed.minute:02d}" if parsed.minute else ""
    suffix = "AM" if parsed.hour < 12 else "PM"
    return f"{hour}{minute} {suffix}"


def normalize_response_text(text):
    text = str(text or "").strip()
    text = re.sub(r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:[+-]\d{2}:\d{2}|Z)?\b", display_time_from_iso, text)
    text = re.sub(r"\s*\|\s*", ", ", text)
    text = re.sub(r"\s*->\s*", " to ", text)
    text = re.sub(r"\n(?:Event ID|Task ID|Message ID|Document ID):\s*[A-Za-z0-9_.:-]+", "", text)
    text = re.sub(r"\b[A-Za-z ]+\s+<no-reply@accounts\.google\.com>", "Google Accounts", text)
    text = re.sub(r"\b[A-Za-z ]+\s+<noreply-accounts@google\.com>", "Google Accounts", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


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
MONTH_NAMES = [
    "",
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]


def sentence_text(value):
    value = re.sub(r"\s+", " ", str(value or "")).strip()
    value = value.strip("-* ")
    if not value:
        return ""
    if value[-1] not in ".?!":
        value += "."
    return value


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


def date_from_iso_date(match):
    year, month, day = (int(part) for part in match.groups())
    if 1 <= month <= 12:
        return f"{MONTH_NAMES[month]} {day}, {year}"
    return match.group(0)


def speech_unit_text(text):
    text = str(text or "")

    def money(match):
        amount = match.group("amount")
        suffix = (match.group("suffix") or "").upper()
        scale = {"K": "thousand", "M": "million", "B": "billion", "T": "trillion"}.get(suffix, "")
        parts = [number_words(amount)]
        if scale:
            parts.append(scale)
        parts.append("dollars")
        return " ".join(parts)

    def temp(match):
        amount = str(round(float(match.group("amount").replace(",", ""))))
        unit = match.group("unit").upper()
        return f"{integer_words(amount)} degrees {'fahrenheit' if unit == 'F' else 'celsius'}"

    text = re.sub(r"\$(?P<amount>\d[\d,]*(?:\.\d+)?)\s*(?P<suffix>[KMBT])?\b", money, text, flags=re.I)
    text = re.sub(r"(?P<amount>-?\d[\d,]*(?:\.\d+)?)\s*°?\s*(?P<unit>[FC])\b", temp, text)
    text = re.sub(r"\b(\d[\d,]*(?:\.\d+)?)%", lambda match: f"{number_words(match.group(1))} percent", text)
    text = re.sub(r"\b(\d[\d,]*(?:\.\d+)?)\s*mph\b", lambda match: f"{number_words(match.group(1))} miles per hour", text, flags=re.I)
    text = re.sub(r"\b(\d[\d,]*(?:\.\d+)?)\s*mi\b", lambda match: f"{number_words(match.group(1))} miles", text, flags=re.I)
    text = re.sub(r"\b(\d[\d,]*(?:\.\d+)?)\s*in\b", lambda match: f"{number_words(match.group(1))} inches", text, flags=re.I)
    text = re.sub(r"\b(\d[\d,]*(?:\.\d+)?)\s*hr\b", lambda match: f"{number_words(match.group(1))} hours", text, flags=re.I)
    text = re.sub(r"\b(\d[\d,]*(?:\.\d+)?)\s*min\b", lambda match: f"{number_words(match.group(1))} minutes", text, flags=re.I)
    text = re.sub(r"\bPRs\b", "pull requests", text)
    text = re.sub(r"\bPR\b", "pull request", text)
    text = re.sub(r"\bCI\b", "C I", text)
    text = re.sub(r"\bAPI\b", "A P I", text)
    text = re.sub(r"\bOAuth\b", "O auth", text)
    return text


def regular_numbers_to_words(text):
    placeholders = {}

    def protect(pattern, value):
        def replacement(match):
            key = f"__JARVIS_SPEECH_PROTECT_{len(placeholders)}__"
            placeholders[key] = match.group(0)
            return key

        return re.sub(pattern, replacement, value, flags=re.I | re.M)

    text = protect(r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b", text)
    text = protect(r"\b\d{1,2}(?::\d{2})?\s*(?:A|P)\s*M\b", text)
    text = protect(r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b", text)
    text = protect(r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}\b", text)
    text = protect(r"\b\d{4}-\d{2}-\d{2}\b", text)
    text = re.sub(
        r"(?<![\w:./-])-?\d[\d,]*(?:\.\d+)?(?![\w:./-])",
        lambda match: number_words(match.group(0)),
        text,
    )
    for key, original in placeholders.items():
        text = text.replace(key, original)
    return text


def normalize_speech_text(text):
    text = normalize_response_text(text)
    spoken = []
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
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r"[*_`]+", "", line)
        line = re.sub(r"<([^>]+)>", "", line).strip()
        upper_line = line.upper()
        if upper_line in section_names:
            spoken.append(section_names[upper_line])
            continue
        if upper_line.startswith("MORNING BRIEF"):
            date = line.split("-", 1)[1].strip() if "-" in line else ""
            spoken.append(sentence_text(f"Morning brief for {date}" if date else "Morning brief"))
            continue
        if upper_line.startswith("EVENING BRIEF"):
            date = line.split("-", 1)[1].strip() if "-" in line else ""
            spoken.append(sentence_text(f"Evening brief for {date}" if date else "Evening brief"))
            continue
        line = re.sub(r"\b(\d{4})-(\d{2})-(\d{2})\b", date_from_iso_date, line)
        line = speech_unit_text(line)
        numbered = re.match(r"^(\d+)[.)]\s*(.+)$", line)
        if numbered:
            spoken.append(sentence_text(f"Number {integer_words(numbered.group(1))} is {numbered.group(2)}"))
            continue
        if line.startswith(("- ", "* ")):
            spoken.append(sentence_text(line[2:].strip()))
            continue
        spoken.append(sentence_text(line))
    text = "\n\n".join(spoken)
    text = regular_numbers_to_words(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def speech_response_text(text, max_chars=900, cap=True):
    text = normalize_speech_text(text)
    if not cap or max_chars <= 0 or len(text) <= max_chars:
        return text
    sentences = re.split(r"(?<=[.!?])\s+", text)
    parts = []
    total = 0
    for sentence in sentences:
        if not sentence:
            continue
        if total + len(sentence) + 1 > max_chars:
            break
        parts.append(sentence)
        total += len(sentence) + 1
    spoken = " ".join(parts).strip()
    if not spoken:
        spoken = text[:max_chars].rsplit(" ", 1)[0].strip()
    return spoken.rstrip(".") + ". I put the full answer on screen."


def spoken_response_text(text, max_chars=900):
    return speech_response_text(text, max_chars=max_chars, cap=True)


def full_speech_response(data):
    planned = data.get("planned") or {}
    candidates = []
    request = planned.get("request") or {}
    candidates.extend([request.get("worker"), request.get("summary")])
    original = request.get("original") or planned.get("original") or {}
    candidates.extend([original.get("source"), original.get("capability")])
    for action in planned.get("actions") or []:
        candidates.extend([action.get("capability"), action.get("worker"), action.get("tool")])
        result = action.get("result") or {}
        candidates.extend(artifact.get("type") for artifact in result.get("artifacts") or [])
    candidates.extend(artifact.get("type") for artifact in data.get("artifacts") or [])
    text = " ".join(str(item or "").lower() for item in candidates)
    return any(term in text for term in ("daily_brief", "briefing", "automation", "scheduled"))


def encode_multipart(field_name, filename, content_type, data):
    boundary = "----jarvisvoice" + uuid.uuid4().hex
    body = b"".join(
        [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'.encode(),
            f"Content-Type: {content_type}\r\n\r\n".encode(),
            data,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    return body, f"multipart/form-data; boundary={boundary}"


class JarvisChatClient:
    def __init__(self, config):
        self.config = config

    def headers(self, content_type=None):
        headers = {}
        if content_type:
            headers["Content-Type"] = content_type
        if self.config.chat_token:
            headers["Authorization"] = f"Bearer {self.config.chat_token}"
        return headers

    def request_json(self, path, payload, timeout=180):
        start = time.perf_counter()
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.config.chat_url + path,
            data=data,
            method="POST",
            headers=self.headers("application/json"),
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8") or "{}")
        logging.info("timing request_json path=%s seconds=%.2f", path, time.perf_counter() - start)
        return result

    def transcribe(self, wav_bytes):
        start = time.perf_counter()
        body, content_type = encode_multipart("audio", "request.wav", "audio/wav", wav_bytes)
        req = urllib.request.Request(
            self.config.chat_url + "/api/voice/transcribe",
            data=body,
            method="POST",
            headers=self.headers(content_type),
        )
        try:
            with urllib.request.urlopen(req, timeout=300) as response:
                data = json.loads(response.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(body or "{}")
                detail = payload.get("error") or payload.get("message") or body
            except json.JSONDecodeError:
                detail = body or str(exc)
            raise RuntimeError(f"transcription_failed: {detail}") from exc
        if not data.get("ok"):
            raise RuntimeError(data.get("error") or "transcription_failed")
        logging.info("timing transcribe chars=%s seconds=%.2f", len(data.get("text") or ""), time.perf_counter() - start)
        return (data.get("text") or "").strip()

    def ask(self, text):
        start = time.perf_counter()
        inputs = {
            "client": "jarvis-voice-client",
            "voice_response": True,
            "response_style": "spoken_concise",
        }
        payload = {
            "text": text,
            "source": "wake-word-client",
            "inputs": inputs,
            "limits": {"maximum_runtime_seconds": 180, "maximum_cost_usd": 0},
        }
        data = self.request_json("/api/voice/request", payload, timeout=240)
        logging.info("timing ask chars=%s seconds=%.2f", len(data.get("text") or ""), time.perf_counter() - start)
        return data

    def synthesize(self, text):
        start = time.perf_counter()
        data = json.dumps({"text": text, "voice": self.config.tts_voice, "format": "wav"}).encode("utf-8")
        req = urllib.request.Request(
            self.config.chat_url + "/api/voice/synthesize",
            data=data,
            method="POST",
            headers=self.headers("application/json"),
        )
        with urllib.request.urlopen(req, timeout=240) as response:
            audio = response.read()
            content_type = response.headers.get("Content-Type", "audio/ogg")
        logging.info("timing synthesize chars=%s bytes=%s seconds=%.2f", len(text), len(audio), time.perf_counter() - start)
        return audio, content_type

    def health(self):
        req = urllib.request.Request(self.config.chat_url + "/health", headers=self.headers())
        with urllib.request.urlopen(req, timeout=20) as response:
            return json.loads(response.read().decode("utf-8") or "{}")


def default_desktop_roots():
    home = Path.home()
    return [
        home / "Downloads",
        home / "Documents" / "Jarvis",
        home / "Desktop" / "Jarvis",
    ]


def configured_desktop_roots(config):
    raw = config.desktop_worker_allowed_roots.strip()
    roots = [Path(item.strip()).expanduser() for item in raw.split(";") if item.strip()] if raw else default_desktop_roots()
    return [root.resolve() for root in roots]


def resolve_allowed_path(path, roots):
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = roots[0] / candidate
    resolved = candidate.resolve()
    for root in roots:
        try:
            resolved.relative_to(root)
            return resolved
        except ValueError:
            continue
    raise PermissionError(f"path outside allowed roots: {resolved}")


def file_metadata(path, include_hash=False):
    stat = path.stat()
    item = {
        "name": path.name,
        "path": str(path),
        "kind": "directory" if path.is_dir() else "file",
        "size": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        "extension": path.suffix.lower(),
        "mime_type": mimetypes.guess_type(str(path))[0],
        "hidden": path.name.startswith(".") or (os.name == "nt" and bool(stat.st_file_attributes & 2) if hasattr(stat, "st_file_attributes") else False),
    }
    if include_hash and path.is_file():
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        item["sha256"] = digest.hexdigest()
    return item


def unique_destination(path):
    candidate = path
    counter = 2
    while candidate.exists():
        candidate = path.with_name(f"{path.stem} ({counter}){path.suffix}")
        counter += 1
    return candidate


class JarvisDesktopWorker:
    def __init__(self, config, client=None, speaker=None):
        self.config = config
        self.client = client or JarvisChatClient(config)
        self.speaker = speaker or ConsoleSpeaker()
        self.stop_event = threading.Event()
        self.roots = configured_desktop_roots(config)
        self.capabilities = self.build_capabilities()

    def build_capabilities(self):
        caps = []
        if self.config.desktop_enable_notify:
            caps.append({"name": "desktop.notify", "version": "1", "risk_ceiling": "L1"})
        if self.config.desktop_enable_open_url:
            caps.append({"name": "desktop.open_url", "version": "1", "risk_ceiling": "L2"})
        if self.config.desktop_enable_files:
            caps.extend(
                [
                    {"name": "desktop.files.list", "version": "1", "risk_ceiling": "L1"},
                    {"name": "desktop.files.stat", "version": "1", "risk_ceiling": "L1"},
                    {"name": "desktop.files.hash", "version": "1", "risk_ceiling": "L1"},
                    {"name": "desktop.files.move", "version": "1", "risk_ceiling": "L2"},
                    {"name": "desktop.files.quarantine", "version": "1", "risk_ceiling": "L2"},
                ]
            )
        return caps

    def register(self):
        payload = {
            "worker_id": self.config.desktop_worker_id,
            "display_name": self.config.desktop_worker_display_name,
            "worker_type": self.config.desktop_worker_type,
            "hostname": socket.gethostname(),
            "os": sys.platform,
            "version": "1.0.0",
            "capabilities": self.capabilities,
            "metadata": {
                "allowed_roots": [str(root) for root in self.roots],
                "voice_client": True,
            },
        }
        return self.client.request_json("/api/core/workers/register", payload, timeout=30)

    def heartbeat(self, status="online"):
        return self.client.request_json(
            f"/api/core/workers/{self.config.desktop_worker_id}/heartbeat",
            {"status": status, "capabilities": self.capabilities},
            timeout=30,
        )

    def claim(self):
        return self.client.request_json(
            f"/api/core/workers/{self.config.desktop_worker_id}/claim",
            {"capabilities": [item["name"] for item in self.capabilities], "max_jobs": 1},
            timeout=30,
        ).get("jobs") or []

    def run_forever(self):
        self.register()
        last_heartbeat = 0.0
        while not self.stop_event.is_set():
            now = time.time()
            if now - last_heartbeat >= self.config.desktop_worker_heartbeat_seconds:
                self.heartbeat()
                last_heartbeat = now
            for job in self.claim():
                self.handle_job(job)
            self.stop_event.wait(self.config.desktop_worker_claim_seconds)

    def stop(self):
        self.stop_event.set()
        try:
            self.heartbeat("offline")
        except Exception:
            logging.exception("desktop worker offline heartbeat failed")

    def handle_job(self, job):
        job_id = job["id"]
        start_path = f"/api/core/workers/{self.config.desktop_worker_id}/jobs/{job_id}/start"
        complete_path = f"/api/core/workers/{self.config.desktop_worker_id}/jobs/{job_id}/complete"
        fail_path = f"/api/core/workers/{self.config.desktop_worker_id}/jobs/{job_id}/fail"
        try:
            self.client.request_json(start_path, {}, timeout=30)
            result = self.execute(job.get("capability"), job.get("input") or {})
            self.client.request_json(complete_path, {"output": result, "safe_summary": result.get("summary")}, timeout=30)
        except Exception as exc:
            logging.exception("desktop worker job failed")
            self.client.request_json(fail_path, {"error": {"message": str(exc)}, "safe_summary": str(exc)[:240]}, timeout=30)

    def execute(self, capability, inputs):
        if capability == "desktop.notify":
            return self.cap_notify(inputs)
        if capability == "desktop.open_url":
            return self.cap_open_url(inputs)
        if capability == "desktop.files.list":
            return self.cap_files_list(inputs)
        if capability == "desktop.files.stat":
            return self.cap_files_stat(inputs)
        if capability == "desktop.files.hash":
            return self.cap_files_hash(inputs)
        if capability == "desktop.files.move":
            return self.cap_files_move(inputs, quarantine=False)
        if capability == "desktop.files.quarantine":
            return self.cap_files_move(inputs, quarantine=True)
        raise ValueError(f"unsupported capability: {capability}")

    def cap_notify(self, inputs):
        title = str(inputs.get("title") or "Jarvis")
        body = str(inputs.get("body") or "")
        self.speaker.print_status(f"{title}: {body}".strip())
        logging.info("desktop notify title=%s body=%s", title, body[:240])
        return {"ok": True, "summary": f"Notification shown: {title}"}

    def cap_open_url(self, inputs):
        url = str(inputs.get("url") or "")
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise PermissionError("desktop.open_url allows only http and https URLs")
        opened = webbrowser.open(url)
        return {"ok": bool(opened), "url": url, "summary": f"Opened URL: {url}"}

    def cap_files_list(self, inputs):
        root = resolve_allowed_path(inputs.get("path") or str(self.roots[0]), self.roots)
        if not root.exists():
            raise FileNotFoundError(str(root))
        if not root.is_dir():
            raise NotADirectoryError(str(root))
        recursive = bool(inputs.get("recursive", False))
        max_items = max(1, min(int(inputs.get("max_items") or 1000), 1000))
        iterator = root.rglob("*") if recursive else root.iterdir()
        items = []
        for path in iterator:
            items.append(file_metadata(path))
            if len(items) >= max_items:
                break
        return {"ok": True, "root": str(root), "count": len(items), "items": items, "summary": f"Listed {len(items)} items in {root.name}"}

    def cap_files_stat(self, inputs):
        path = resolve_allowed_path(inputs.get("path") or "", self.roots)
        if not path.exists():
            raise FileNotFoundError(str(path))
        return {"ok": True, "item": file_metadata(path), "summary": f"Read metadata for {path.name}"}

    def cap_files_hash(self, inputs):
        path = resolve_allowed_path(inputs.get("path") or "", self.roots)
        if not path.exists():
            raise FileNotFoundError(str(path))
        if not path.is_file():
            raise IsADirectoryError(str(path))
        return {"ok": True, "item": file_metadata(path, include_hash=True), "summary": f"Hashed {path.name}"}

    def cap_files_move(self, inputs, quarantine=False):
        moves = inputs.get("moves") or []
        if not isinstance(moves, list) or not moves:
            raise ValueError("moves_required")
        max_moves = max(1, min(int(inputs.get("max_moves") or 200), 200))
        moved = []
        for item in moves[:max_moves]:
            source = resolve_allowed_path(item.get("source") or "", self.roots)
            if not source.exists():
                raise FileNotFoundError(str(source))
            if not source.is_file():
                raise IsADirectoryError(str(source))
            destination_dir = item.get("destination_dir")
            if quarantine:
                destination_dir = destination_dir or self.config.desktop_worker_quarantine or str(self.roots[0] / "_Jarvis Quarantine")
            if not destination_dir:
                raise ValueError("destination_dir_required")
            target_dir = resolve_allowed_path(destination_dir, self.roots)
            target_dir.mkdir(parents=True, exist_ok=True)
            destination = unique_destination(target_dir / source.name)
            shutil.move(str(source), str(destination))
            moved.append(
                {
                    "source": str(source),
                    "destination": str(destination),
                    "name": destination.name,
                    "category": item.get("category"),
                    "verified": destination.exists() and not source.exists(),
                }
            )
        verb = "Quarantined" if quarantine else "Moved"
        return {"ok": True, "moved": moved, "count": len(moved), "summary": f"{verb} {len(moved)} file(s)"}


class TunnelManager:
    def __init__(self, config):
        self.config = config
        parsed = urlparse(config.chat_url)
        self.host = parsed.hostname or "127.0.0.1"
        self.port = parsed.port or config.tunnel_local_port
        self.process = None

    def is_connected(self):
        try:
            with socket.create_connection((self.host, self.port), timeout=1.5):
                return True
        except OSError:
            return False

    def ensure(self):
        if self.is_connected():
            return True
        if self.host not in {"127.0.0.1", "localhost"}:
            return False
        args = [
            "ssh",
            "-N",
            "-L",
            f"{self.config.tunnel_local_port}:127.0.0.1:{self.config.tunnel_remote_port}",
            self.config.tunnel_server,
        ]
        try:
            self.process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            logging.warning("tunnel start failed: %s", exc)
            return False
        deadline = time.time() + 6
        while time.time() < deadline:
            if self.is_connected():
                return True
            time.sleep(0.25)
        return False

    def restart(self):
        if self.process and self.process.poll() is None:
            try:
                self.process.terminate()
            except OSError:
                pass
        self.process = None
        return self.ensure()


class JarvisVoiceSession:
    def __init__(self, client, speaker, state_callback=None):
        self.client = client
        self.speaker = speaker
        self.state_callback = state_callback or (lambda state, message="": None)

    def set_state(self, state, message=""):
        self.state_callback(state, message)
        if message:
            logging.info("%s: %s", state.value if isinstance(state, VoiceState) else state, message)

    def speak(self, text):
        try:
            self.set_state(VoiceState.SPEAKING, text[:120])
            audio, content_type = self.client.synthesize(text)
            start = time.perf_counter()
            self.speaker.play_audio(audio, content_type)
            logging.info("timing play_audio bytes=%s seconds=%.2f", len(audio), time.perf_counter() - start)
            return True
        except Exception as exc:
            self.speaker.print_status(f"TTS unavailable: {exc}")
            self.set_state(VoiceState.ERROR, str(exc))
            return False

    def handle_recording(self, wav_bytes, greet=True):
        turn = VoiceTurn(states=["wake", "greet"])
        if greet:
            self.speaker.print_jarvis(self.client.config.greeting)
            self.speak(self.client.config.greeting)
        if not wav_bytes:
            turn.response_text = "I did not hear anything."
            self.speaker.print_jarvis(turn.response_text)
            self.speak(turn.response_text)
            turn.states.append("idle")
            self.set_state(VoiceState.LISTENING)
            return turn
        turn.states.append("transcribe")
        self.set_state(VoiceState.PROCESSING, "Transcribing")
        turn.transcript = self.client.transcribe(wav_bytes)
        if not turn.transcript:
            turn.response_text = "I did not catch that."
            self.speaker.print_jarvis(turn.response_text)
            self.speak(turn.response_text)
            turn.states.append("idle")
            self.set_state(VoiceState.LISTENING)
            return turn
        if hasattr(self.speaker, "print_user"):
            self.speaker.print_user(turn.transcript)
        logging.info("transcript: %s", turn.transcript)
        egg = easter_egg_response(turn.transcript)
        if egg:
            turn.response_text = egg
            turn.states.append("request")
            turn.states.append("speak")
            self.speaker.print_jarvis(turn.response_text)
            self.speak(turn.response_text)
            turn.states.append("idle")
            self.set_state(VoiceState.LISTENING)
            return turn
        turn.states.append("request")
        self.set_state(VoiceState.PROCESSING, "Asking Jarvis")
        start = time.perf_counter()
        data = self.client.ask(turn.transcript)
        logging.info("timing jarvis_request seconds=%.2f", time.perf_counter() - start)
        turn.response_text = normalize_response_text(data.get("text") or "Jarvis returned no response text.")
        turn.approval_required = bool(data.get("approval_required"))
        turn.states.append("speak")
        self.speaker.print_jarvis(turn.response_text)
        speech_text = speech_response_text(
            turn.response_text,
            self.client.config.spoken_response_max_chars,
            cap=not full_speech_response(data),
        )
        self.speak(speech_text)
        turn.states.append("idle")
        self.set_state(VoiceState.LISTENING)
        return turn


class ConsoleSpeaker:
    def print_jarvis(self, text):
        print(f"Jarvis: {text}")

    def print_user(self, text):
        print(f"You: {text}")

    def print_status(self, text):
        print(text)

    def play_audio(self, audio_bytes, content_type):
        suffix = ".wav" if "wav" in (content_type or "") else ".ogg" if "ogg" in (content_type or "") else ".audio"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(audio_bytes)
            path = tmp.name
        try:
            if suffix == ".wav" and os.name == "nt":
                import winsound

                winsound.PlaySound(path, winsound.SND_FILENAME)
                return
            import pygame

            pygame.mixer.init()
            pygame.mixer.music.load(path)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                time.sleep(0.05)
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass


def wav_bytes_from_pcm(frames, sample_rate):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
        path = tmp.name
    try:
        with wave.open(path, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(b"".join(frames))
        return Path(path).read_bytes()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def record_until_silence(config):
    import sounddevice as sd

    block_samples = int(config.sample_rate * 0.1)
    start_blocks = max(1, int(config.record_start_timeout_seconds / 0.1))
    min_voice_blocks = max(1, int(config.record_min_seconds / 0.1))
    silence_blocks_needed = max(1, int(config.record_silence_seconds / 0.1))
    max_blocks = max(1, int(config.record_max_seconds / 0.1))
    frames = []
    pre_voice_blocks = 0
    silent_blocks = 0
    voice_blocks = 0
    heard_speech = False
    with sd.RawInputStream(samplerate=config.sample_rate, channels=1, dtype="int16", blocksize=block_samples) as stream:
        for _ in range(max_blocks):
            data, _ = stream.read(block_samples)
            chunk = bytes(data)
            is_silent = audioop.rms(chunk, 2) < config.record_rms_threshold
            if not heard_speech and is_silent:
                pre_voice_blocks += 1
                if pre_voice_blocks >= start_blocks:
                    break
                continue
            heard_speech = True
            frames.append(chunk)
            if is_silent:
                silent_blocks += 1
                if voice_blocks >= min_voice_blocks and silent_blocks >= silence_blocks_needed:
                    break
            else:
                voice_blocks += 1
                silent_blocks = 0
    if not frames:
        return b""
    return wav_bytes_from_pcm(frames, config.sample_rate)


class VoiceController:
    def __init__(self, config, speaker=None, tunnel=None, recorder=None, client=None):
        self.config = config
        self.speaker = speaker or ConsoleSpeaker()
        self.tunnel = tunnel or TunnelManager(config)
        self.client = client or JarvisChatClient(config)
        self.desktop_worker = JarvisDesktopWorker(config, self.client, self.speaker) if config.desktop_worker_enabled else None
        self.session = JarvisVoiceSession(self.client, self.speaker, self.set_state)
        self.recorder = recorder or record_until_silence
        self.state = VoiceState.DISCONNECTED
        self.state_message = ""
        self.state_lock = threading.Lock()
        self.turn_lock = threading.Lock()
        self.stop_event = threading.Event()
        self.paused = False
        self.suppress_until = 0.0
        self.on_state_change = None

    def set_state(self, state, message=""):
        with self.state_lock:
            self.state = state
            self.state_message = message
        if self.on_state_change:
            self.on_state_change(state, message)

    def should_accept_wake(self):
        if self.stop_event.is_set() or self.paused:
            return False
        if self.config.suppress_wake_while_speaking and self.state in {VoiceState.SPEAKING, VoiceState.RECORDING, VoiceState.PROCESSING}:
            return False
        return time.time() >= self.suppress_until

    def ensure_connected(self):
        if self.tunnel.ensure():
            self.set_state(VoiceState.LISTENING)
            if self.desktop_worker:
                try:
                    self.desktop_worker.register()
                except Exception as exc:
                    logging.warning("desktop worker registration failed: %s", exc)
            return True
        self.set_state(VoiceState.DISCONNECTED, "Jarvis Chat tunnel unavailable")
        self.speaker.print_status("Jarvis Chat tunnel unavailable.")
        return False

    def restart_tunnel(self):
        self.set_state(VoiceState.DISCONNECTED, "Restarting tunnel")
        ok = self.tunnel.restart()
        self.set_state(VoiceState.LISTENING if ok else VoiceState.ERROR, "Tunnel restarted" if ok else "Tunnel restart failed")
        return ok

    def pause(self):
        self.paused = True
        self.set_state(VoiceState.PAUSED)

    def resume(self):
        self.paused = False
        self.set_state(VoiceState.LISTENING)

    def stop(self):
        self.stop_event.set()
        if self.desktop_worker:
            self.desktop_worker.stop()

    def record_turn(self, trigger="wake"):
        if not self.turn_lock.acquire(blocking=False):
            self.speaker.print_status("Jarvis is already handling a request.")
            return None
        try:
            return self._record_turn_locked(trigger)
        finally:
            self.turn_lock.release()

    def _record_turn_locked(self, trigger="wake"):
        if not self.ensure_connected():
            return None
        self.speaker.print_jarvis(self.config.greeting)
        self.session.speak(self.config.greeting)
        self.speaker.print_status("Listening to your request...")
        self.set_state(VoiceState.RECORDING, trigger)
        start = time.perf_counter()
        wav_bytes = self.recorder(self.config)
        logging.info("timing record trigger=%s bytes=%s seconds=%.2f", trigger, len(wav_bytes or b""), time.perf_counter() - start)
        turn = self.session.handle_recording(wav_bytes, greet=False)
        self.suppress_until = time.time() + self.config.post_turn_cooldown_seconds
        self.set_state(VoiceState.LISTENING)
        return turn

    def push_to_talk(self):
        if not self.config.enable_push_to_talk:
            self.speaker.print_status("Push-to-talk is disabled.")
            return None
        if self.paused:
            self.speaker.print_status("Jarvis is paused.")
            return None
        return self.record_turn("push-to-talk")

    def listen_forever(self):
        if not self.config.enable_wake_word:
            self.speaker.print_status("Wake word is disabled.")
            return
        self.ensure_connected()
        self.speaker.print_status(f"Listening for {self.config.wake_phrase}.")
        for score in listen_for_wake(config=self.config, should_listen=self.should_accept_wake):
            if self.stop_event.is_set():
                break
            self.speaker.print_status(f"Wake detected: {score:.2f}")
            self.record_turn("wake")


def listen_for_wake(config, should_listen=None):
    import numpy as np
    import sounddevice as sd
    import openwakeword
    from openwakeword.model import Model

    should_listen = should_listen or (lambda: True)
    openwakeword.utils.download_models(model_names=[config.wake_phrase])
    model = Model(wakeword_models=[config.wake_phrase], inference_framework=config.wake_inference_framework)
    block_samples = 1280
    last_wake = 0.0
    consecutive_hits = 0
    with sd.RawInputStream(samplerate=config.sample_rate, channels=1, dtype="int16", blocksize=block_samples) as stream:
        while True:
            data, _ = stream.read(block_samples)
            if not should_listen():
                consecutive_hits = 0
                time.sleep(0.05)
                continue
            audio = np.frombuffer(bytes(data), dtype=np.int16)
            prediction = model.predict(audio)
            score = max(float(value) for value in prediction.values()) if prediction else 0.0
            now = time.time()
            if score >= config.wake_threshold:
                consecutive_hits += 1
            else:
                consecutive_hits = 0
            if consecutive_hits >= config.wake_consecutive_hits and now - last_wake > config.wake_cooldown_seconds:
                last_wake = now
                consecutive_hits = 0
                yield score


def run_once(config):
    controller = VoiceController(config)
    controller.record_turn("once")


def run_listen(config):
    VoiceController(config).listen_forever()


def run_push_to_talk(config):
    VoiceController(config).push_to_talk()


def run_worker(config):
    setup_logging(config)
    if not acquire_instance_lock(config):
        return
    controller = VoiceController(config)
    if not controller.ensure_connected():
        raise RuntimeError("Jarvis Chat unavailable")
    if not controller.desktop_worker:
        raise RuntimeError("Desktop worker is disabled")
    print(f"Jarvis desktop worker registered as {config.desktop_worker_id}. Press Ctrl+C to stop.")
    try:
        controller.desktop_worker.run_forever()
    except KeyboardInterrupt:
        controller.stop()


def tray_image(state):
    from PIL import Image, ImageDraw

    colors = {
        VoiceState.DISCONNECTED: "#666666",
        VoiceState.LISTENING: "#2ea043",
        VoiceState.RECORDING: "#d29922",
        VoiceState.PROCESSING: "#58a6ff",
        VoiceState.SPEAKING: "#a371f7",
        VoiceState.PAUSED: "#8b949e",
        VoiceState.ERROR: "#f85149",
    }
    image = Image.new("RGB", (64, 64), "#0d1117")
    draw = ImageDraw.Draw(image)
    draw.ellipse((12, 12, 52, 52), fill=colors.get(state, "#666666"))
    draw.ellipse((25, 25, 39, 39), fill="#0d1117")
    return image


def run_threaded(name, target):
    thread = threading.Thread(target=target, name=name, daemon=True)
    thread.start()
    return thread


def run_tray(config):
    log_dir = setup_logging(config)
    if not acquire_instance_lock(config):
        return
    try:
        import pystray
    except ImportError as exc:
        raise RuntimeError("Tray mode needs pystray and Pillow. Run: pip install -r requirements.txt") from exc

    controller = VoiceController(config)
    icon = pystray.Icon("Jarvis", tray_image(controller.state), "Jarvis")

    def refresh(state=None, message=""):
        state = state or controller.state
        icon.icon = tray_image(state)
        icon.title = f"Jarvis: {state.value}"
        if message:
            logging.info("tray: %s", message)
        try:
            icon.update_menu()
        except Exception:
            pass

    controller.on_state_change = refresh

    def threaded_action(action):
        return lambda *_: run_threaded(f"jarvis-{action.__name__}", action)

    def pause_resume(*_):
        if controller.paused:
            controller.resume()
        else:
            controller.pause()

    def diagnostics(*_):
        def run():
            try:
                diagnose(config)
            except Exception as exc:
                logging.exception("diagnostics failed: %s", exc)
                controller.set_state(VoiceState.ERROR, str(exc))

        run_threaded("jarvis-diagnostics", run)

    def open_logs(*_):
        path = log_dir / "jarvis-voice-client.log"
        path.touch(exist_ok=True)
        if os.name == "nt":
            os.startfile(str(path))
        else:
            controller.speaker.print_status(str(path))

    def quit_app(*_):
        controller.stop()
        icon.stop()

    def status_text(_):
        return f"Status: {controller.state.value}"

    def pause_text(_):
        return "Resume" if controller.paused else "Pause"

    icon.menu = pystray.Menu(
        pystray.MenuItem(status_text, None, enabled=False),
        pystray.MenuItem("Push to talk", threaded_action(controller.push_to_talk), enabled=lambda _: config.enable_push_to_talk),
        pystray.MenuItem(pause_text, pause_resume),
        pystray.MenuItem("Restart tunnel", threaded_action(controller.restart_tunnel)),
        pystray.MenuItem("Run diagnostics", diagnostics),
        pystray.MenuItem("Open logs", open_logs),
        pystray.MenuItem("Quit", quit_app),
    )

    if config.enable_push_to_talk:
        try:
            import keyboard

            keyboard.add_hotkey(config.push_to_talk_hotkey, lambda: run_threaded("jarvis-push-to-talk", controller.push_to_talk))
            logging.info("registered hotkey %s", config.push_to_talk_hotkey)
        except Exception as exc:
            logging.warning("push-to-talk hotkey unavailable: %s", exc)
            controller.speaker.print_status(f"Push-to-talk hotkey unavailable: {exc}")

    if config.enable_wake_word:
        run_threaded("jarvis-wake-listener", controller.listen_forever)
    else:
        controller.ensure_connected()
    if controller.desktop_worker:
        run_threaded("jarvis-desktop-worker", controller.desktop_worker.run_forever)
    refresh()
    icon.run()


def diagnose(config):
    print("Jarvis voice client diagnostics")
    print(f"Chat URL: {config.chat_url}")
    print(f"Tunnel target: {config.tunnel_local_port}:127.0.0.1:{config.tunnel_remote_port} via {config.tunnel_server}")
    print(f"Wake word enabled: {config.enable_wake_word}")
    print(f"Push-to-talk enabled: {config.enable_push_to_talk}")
    print(f"Push-to-talk hotkey: {config.push_to_talk_hotkey}")
    print(f"Wake phrase/model: {config.wake_phrase}")
    print(f"Wake inference framework: {config.wake_inference_framework}")
    print(f"Wake threshold: {config.wake_threshold}")
    print(f"Wake consecutive hits: {config.wake_consecutive_hits}")
    print(f"Post-turn cooldown seconds: {config.post_turn_cooldown_seconds}")
    print(f"Sample rate: {config.sample_rate}")
    print(f"Desktop worker enabled: {config.desktop_worker_enabled}")
    print(f"Desktop worker id: {config.desktop_worker_id}")
    print(f"Desktop worker heartbeat seconds: {config.desktop_worker_heartbeat_seconds}")
    print(f"Desktop worker capabilities: {[item['name'] for item in JarvisDesktopWorker(config).capabilities]}")
    print(f"Desktop allowed roots: {[str(root) for root in configured_desktop_roots(config)]}")
    try:
        tunnel = TunnelManager(config)
        print(f"Tunnel/local chat port: connected={tunnel.is_connected()}")
    except Exception as exc:
        print(f"Tunnel/local chat port: failed: {exc}")
    try:
        health = JarvisChatClient(config).health()
        print(f"Jarvis Chat: ok={health.get('ok')} auth_required={health.get('auth_required')}")
    except Exception as exc:
        print(f"Jarvis Chat: failed: {exc}")
    try:
        import sounddevice as sd

        print("Audio devices:")
        print(sd.query_devices())
    except Exception as exc:
        print(f"Audio devices: failed: {exc}")
    try:
        import openwakeword
        from openwakeword.model import Model

        openwakeword.utils.download_models(model_names=[config.wake_phrase])
        model = Model(wakeword_models=[config.wake_phrase], inference_framework=config.wake_inference_framework)
        print(f"Wake model loaded: {list(getattr(model, 'models', {}).keys()) or config.wake_phrase}")
    except Exception as exc:
        print(f"Wake model: failed: {exc}")
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Record one request without wake-word listening.")
    parser.add_argument("--listen", action="store_true", help="Listen continuously for the wake phrase.")
    parser.add_argument("--push-to-talk", action="store_true", help="Record one request through the push-to-talk path.")
    parser.add_argument("--tray", action="store_true", help="Run the Windows tray app.")
    parser.add_argument("--worker", action="store_true", help="Run only the Jarvis desktop worker loop.")
    parser.add_argument("--diagnose", action="store_true", help="Check Jarvis Chat, audio devices, and wake model setup.")
    parser.add_argument("--env", default=".env", help="Path to local env config.")
    args = parser.parse_args()
    load_dotenv(Path(args.env))
    config = VoiceConfig.from_env()
    if args.diagnose:
        diagnose(config)
    elif args.tray:
        run_tray(config)
    elif args.worker:
        run_worker(config)
    elif args.push_to_talk:
        run_push_to_talk(config)
    elif args.listen:
        run_listen(config)
    else:
        run_once(config)


if __name__ == "__main__":
    main()
