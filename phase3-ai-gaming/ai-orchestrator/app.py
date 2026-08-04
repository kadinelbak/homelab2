#!/usr/bin/env python3
import json
import hashlib
import os
import re
import threading
import time
import uuid
import urllib.error
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

TOKEN = os.environ.get("AI_ORCHESTRATOR_TOKEN", "")
HOST = os.environ.get("AI_ORCHESTRATOR_HOST", "0.0.0.0")
PORT = int(os.environ.get("AI_ORCHESTRATOR_PORT", "8095"))
DATA_DIR = Path(os.environ.get("AI_ORCHESTRATOR_DATA_DIR", "/data"))
STATE_PATH = DATA_DIR / "requests.json"
OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://ollama:11434").rstrip("/")
OLLAMA_ROUTER_MODEL = os.environ.get("AI_ORCHESTRATOR_ROUTER_MODEL", os.environ.get("OLLAMA_MODEL", "llama3.1"))
OLLAMA_ROUTER_ENABLED = os.environ.get("AI_ORCHESTRATOR_USE_OLLAMA_ROUTER", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
OLLAMA_ROUTER_TIMEOUT = float(os.environ.get("AI_ORCHESTRATOR_ROUTER_TIMEOUT", "12"))
ROUTER_PROFILE = os.environ.get("AI_ORCHESTRATOR_ROUTER_PROFILE", "local")
LLM_TIMEOUT = float(os.environ.get("AI_ORCHESTRATOR_LLM_TIMEOUT", "120"))
CALENDAR_CONTRACT_CACHE_TTL = int(os.environ.get("CALENDAR_CONTRACT_CACHE_TTL", "120"))
CALENDAR_CONTRACT_CACHE = {}
CALENDAR_CONTRACT_CACHE_LOCK = threading.Lock()
GMAIL_CONTRACT_CACHE_TTL = int(os.environ.get("GMAIL_CONTRACT_CACHE_TTL", "120"))
GMAIL_CONTRACT_CACHE = {}
GMAIL_CONTRACT_CACHE_LOCK = threading.Lock()
TASKS_CONTRACT_CACHE = {}
TASKS_CONTRACT_CACHE_LOCK = threading.Lock()
CONTACTS_CONTRACT_CACHE = {}
CONTACTS_CONTRACT_CACHE_LOCK = threading.Lock()
GOOGLE_TOOLS_URL = os.environ.get("GOOGLE_TOOLS_URL", "http://google-tools-worker:18200").rstrip("/")
GOOGLE_TOOLS_TOKEN = os.environ.get("GOOGLE_TOOLS_TOKEN", TOKEN)
CODEX_WORKER_URL = os.environ.get("CODEX_WORKER_URL", "http://codex-worker:18300").rstrip("/")
CODEX_WORKER_TOKEN = os.environ.get("CODEX_WORKER_TOKEN", TOKEN)
TTS_WORKER_URL = os.environ.get("JARVIS_TTS_WORKER_URL", "http://tts-worker:8101").rstrip("/")
LLM_PROFILES = {
    "local": {
        "profile": "local",
        "provider": "ollama",
        "model": os.environ.get("OLLAMA_MODEL", "llama3.1:latest"),
        "base_url": OLLAMA_URL,
        "configured": True,
        "use_for": "cheap routing, quick local fallback, private low-stakes tasks",
    },
    "fast_70b": {
        "profile": "fast_70b",
        "provider": os.environ.get("JARVIS_FAST_LLM_PROVIDER", "external_openai_compatible"),
        "model": os.environ.get("JARVIS_FAST_LLM_MODEL", "llama-3.1-70b-instruct"),
        "base_url": os.environ.get("JARVIS_FAST_LLM_BASE_URL", ""),
        "configured": bool(os.environ.get("JARVIS_FAST_LLM_API_KEY") and os.environ.get("JARVIS_FAST_LLM_BASE_URL")),
        "use_for": "general assistant answers, drafting, summarization, normal planning",
    },
    "deep_120b": {
        "profile": "deep_120b",
        "provider": os.environ.get("JARVIS_DEEP_LLM_PROVIDER", "external_openai_compatible"),
        "model": os.environ.get("JARVIS_DEEP_LLM_MODEL", "nemotron-3-super-120b-a12b"),
        "base_url": os.environ.get("JARVIS_DEEP_LLM_BASE_URL", ""),
        "configured": bool(os.environ.get("JARVIS_DEEP_LLM_API_KEY") and os.environ.get("JARVIS_DEEP_LLM_BASE_URL")),
        "use_for": "complex reasoning, architecture, coding plans, multi-step decomposition",
    },
}

CAPABILITIES = [
    {
        "capability": "general_assistant",
        "worker": "llm_worker",
        "adapter_type": "local_llm",
        "cost_class": "local",
        "requires_approval": False,
        "execution_requires_approval": False,
        "tools": ["ollama.chat"],
        "description": "Conversational help, brainstorming, writing, drafting, planning, and general questions.",
    },
    {
        "capability": "draft_email",
        "worker": "llm_worker",
        "adapter_type": "local_llm",
        "cost_class": "local",
        "requires_approval": False,
        "execution_requires_approval": False,
        "tools": ["ollama.draft_email"],
        "description": "Write email drafts, replies, outreach notes, and editable message text without sending.",
    },
    {
        "capability": "manage_tasks",
        "worker": "tasks_worker",
        "adapter_type": "google_tools_worker",
        "cost_class": "local",
        "requires_approval": False,
        "execution_requires_approval": False,
        "tools": ["google.tasks"],
        "description": "Create, update, complete, delete, or list personal tasks and to-dos.",
    },
    {
        "capability": "manage_calendar",
        "worker": "calendar_worker",
        "adapter_type": "google_tools_worker",
        "cost_class": "local",
        "requires_approval": False,
        "execution_requires_approval": True,
        "tools": ["google.calendar"],
        "description": "Plan, create, reschedule, cancel, or inspect calendar events and availability.",
    },
    {
        "capability": "manage_email",
        "worker": "email_worker",
        "adapter_type": "google_tools_worker",
        "cost_class": "local",
        "requires_approval": True,
        "execution_requires_approval": True,
        "tools": ["google.gmail"],
        "description": "Prepare email actions such as send, reply, label, search, summarize, or fetch.",
    },
    {
        "capability": "manage_contacts",
        "worker": "contacts_worker",
        "adapter_type": "google_tools_worker",
        "cost_class": "local",
        "requires_approval": False,
        "execution_requires_approval": False,
        "tools": ["google.contacts"],
        "description": "Find, create, update, or summarize contact information.",
    },
    {
        "capability": "daily_briefing",
        "worker": "briefing_worker",
        "adapter_type": "google_tools_worker",
        "cost_class": "local",
        "requires_approval": False,
        "execution_requires_approval": False,
        "tools": ["jarvis.daily_briefing"],
        "description": "Build a morning or evening briefing from Calendar, Gmail, and Tasks.",
    },
    {
        "capability": "briefing_profile",
        "worker": "profile_worker",
        "adapter_type": "google_tools_worker",
        "cost_class": "local",
        "requires_approval": False,
        "execution_requires_approval": False,
        "tools": ["jarvis.briefing_profile"],
        "description": "Read or update durable Jarvis briefing profile settings.",
    },
    {
        "capability": "github_digest",
        "worker": "github_tools_worker",
        "adapter_type": "github_app",
        "cost_class": "local",
        "requires_approval": False,
        "execution_requires_approval": False,
        "tools": ["github.digest"],
        "description": "Summarize watched GitHub repositories for briefing context.",
    },
    {
        "capability": "text_to_speech",
        "worker": "tts_worker",
        "adapter_type": "local_application",
        "cost_class": "local",
        "requires_approval": False,
        "execution_requires_approval": False,
        "tools": ["tts.synthesize"],
        "description": "Synthesize text into local audio for Telegram delivery.",
    },
    {
        "capability": "track_expense",
        "worker": "finance_worker",
        "adapter_type": "local_llm_fallback",
        "cost_class": "local",
        "requires_approval": False,
        "execution_requires_approval": True,
        "tools": ["expenses.local_proposal"],
        "description": "Log, categorize, inspect, or summarize personal expenses and budgets.",
    },
    {
        "capability": "transcribe_speech",
        "worker": "whisper_worker",
        "adapter_type": "local_application",
        "cost_class": "local",
        "requires_approval": False,
        "execution_requires_approval": False,
        "tools": ["whisper.transcribe"],
        "description": "Transcribe or translate uploaded audio into text using a local Whisper worker.",
    },
    {
        "capability": "edit_repository",
        "worker": "coding_worker",
        "adapter_type": "cli_worker",
        "cost_class": "metered",
        "requires_approval": False,
        "execution_requires_approval": True,
        "tools": ["codex_cli", "opencode", "aider"],
        "description": "Modify, inspect, test, or review code repositories and developer projects.",
    },
    {
        "capability": "generate_3d_concept",
        "worker": "meshy",
        "adapter_type": "rest_api",
        "cost_class": "paid",
        "requires_approval": True,
        "execution_requires_approval": True,
        "tools": ["meshy.text_to_3d", "meshy.image_to_3d"],
        "description": "Generate organic or concept 3D models with a paid external 3D generation service.",
    },
    {
        "capability": "generate_parametric_part",
        "worker": "cad_worker",
        "adapter_type": "local_application",
        "cost_class": "local",
        "requires_approval": False,
        "execution_requires_approval": True,
        "tools": ["cadquery.generate", "openscad.render", "blender.preview"],
        "description": "Generate precise CAD, STEP, STL, OpenSCAD, or CadQuery parametric parts.",
    },
    {
        "capability": "manage_smart_home",
        "worker": "homeassistant",
        "adapter_type": "rest_api",
        "cost_class": "local",
        "requires_approval": True,
        "execution_requires_approval": True,
        "tools": ["homeassistant.call_service"],
        "description": "Control Home Assistant devices, scenes, lights, climate, or other smart-home state.",
    },
    {
        "capability": "organize_media",
        "worker": "media_adapter",
        "adapter_type": "rest_api",
        "cost_class": "local",
        "requires_approval": True,
        "execution_requires_approval": True,
        "tools": ["radarr.add_movie", "sonarr.add_series", "paperless.search"],
        "description": "Organize movies, TV, documents, Paperless, Radarr, Sonarr, or media libraries.",
    },
]


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def load_state():
    if not STATE_PATH.exists():
        return {"requests": {}, "actions": {}}
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def save_state(state):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = STATE_PATH.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(STATE_PATH)


def capability_by_name(name):
    for capability in CAPABILITIES:
        if capability["capability"] == name:
            return capability
    return None


def request_text(payload):
    direct = " ".join(
        str(payload.get(key, ""))
        for key in ("request", "instruction", "prompt", "goal", "natural_language")
    ).strip()
    if direct:
        return direct
    inputs = payload.get("inputs") or {}
    return " ".join(
        str(inputs.get(key, ""))
        for key in ("request", "instruction", "prompt", "goal", "natural_language")
    ).strip()


def calendar_intent(payload):
    text = request_text(payload).lower()
    context = " ".join(
        str(turn.get("text", "")).lower()
        for turn in (payload.get("inputs") or {}).get("conversation_context", [])
        if isinstance(turn, dict)
    )
    action_words = (
        "create", "make", "add", "schedule", "delete", "remove", "cancel",
        "reschedule", "move", "shift", "push", "change", "update",
    )
    lookup_words = ("what", "when", "show", "list", "available")
    if any(word in text for word in ("calendar", "appointment", "meeting", "schedule")):
        return True
    if "event" in text and (any(word in text for word in action_words) or any(word in text for word in lookup_words)):
        return True
    return any(
        phrase in text
        for phrase in (
            "delete that", "remove that", "cancel that", "delete it", "remove it", "cancel it",
            "move that", "shift that", "push that", "move it", "shift it", "push it",
        )
    ) and "calendar event" in context


def calendar_mutation_intent(payload):
    text = request_text(payload).lower()
    mutation_terms = (
        "create", "make", "add", "schedule", "delete", "remove", "cancel",
        "reschedule", "move", "change", "update", "invite",
    )
    if any(term in text for term in mutation_terms):
        return True
    readonly_terms = (
        "show", "list", "what", "what's", "whats", "when", "check", "find",
        "available", "tell me", "everything", "anything", "agenda", "look up",
    )
    if any(term in text for term in readonly_terms):
        return False
    return False


def calendar_readonly_intent(payload):
    text = request_text(payload).lower()
    if not any(term in text for term in ("calendar", "schedule", "agenda", "appointment", "meeting", "events")):
        return False
    return not calendar_mutation_intent(payload)


def calendar_readonly_list_contract(payload):
    text = request_text(payload).lower()
    current_time = datetime.now().astimezone().replace(second=0, microsecond=0)
    start = current_time.replace(hour=0, minute=0)
    days = 1
    if "tomorrow" in text:
        start = start + timedelta(days=1)
    elif "week" in text:
        days = 7
    elif "month" in text:
        days = 31
    end = start + timedelta(days=days)
    return validate_calendar_contract(
        {
            "operation": "list",
            "search_window": {"start": start.isoformat(), "end": end.isoformat()},
            "allow_search_fallback": False,
            "requires_clarification": False,
        }
    )


def route_with_keywords(payload):
    text = request_text(payload).lower()

    routes = [
        (("briefing profile", "briefing preference", "current city", "set city", "where i live", "watch repo", "watched repo", "rememberbrief", "remember for brief"), "briefing_profile"),
        (("repo", "code", "commit", "pull request", "github issue", "branch", "test", "lint", "coding task", "summarize repo"), "edit_repository"),
        (("daily brief", "briefing", "morning brief", "evening recap", "tomorrow prep"), "daily_briefing"),
        (("gmail draft", "draft in gmail", "create draft", "make a draft", "save draft"), "manage_email"),
        (("draft email", "email draft", "draft reply", "write an email", "write email"), "draft_email"),
        (("send email", "reply to", "gmail", "inbox", "label email", "search email"), "manage_email"),
        (("calendar", "schedule", "meeting", "appointment", "reschedule", "availability"), "manage_calendar"),
        (("task", "todo", "to-do", "remind me", "complete task", "delete task"), "manage_tasks"),
        (("contact", "phone number", "address book"), "manage_contacts"),
        (("expense", "budget", "receipt", "spending", "spent", "cost me"), "track_expense"),
        (("3d", "meshy", "organic model", "concept model", "glb", "obj"), "generate_3d_concept"),
        (("cad", "step", "stl", "openscad", "cadquery", "parametric", "dimension"), "generate_parametric_part"),
        (("light", "thermostat", "home assistant", "smart home", "scene"), "manage_smart_home"),
        (("movie", "series", "paperless", "document", "radarr", "sonarr", "media"), "organize_media"),
        (("transcribe", "transcription", "audio", "voice", "whisper", "speech"), "transcribe_speech"),
        (("draft", "write", "brainstorm", "idea", "plan", "summarize", "explain"), "general_assistant"),
    ]
    for keywords, capability in routes:
        if any(keyword in text for keyword in keywords):
            return capability_by_name(capability), {
                "router": "keyword",
                "rationale": f"Matched keyword route for {capability}.",
            }

    return capability_by_name("general_assistant"), {
        "router": "keyword",
        "rationale": "No specific tool keywords matched; using general assistant.",
    }


def parse_json_object(text):
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("no JSON object found")
    return json.loads(text[start : end + 1])


def verified_calendar_artifacts(payload):
    chat_id = str((payload.get("inputs") or {}).get("telegram_chat_id") or "")
    artifacts = []
    if not chat_id:
        return artifacts
    state = load_state()
    requests = state.get("requests", {})
    actions = sorted(state.get("actions", {}).values(), key=lambda item: item.get("created_at", ""), reverse=True)
    for action in actions:
        request = requests.get(action.get("request_id"), {})
        original_inputs = (request.get("original") or {}).get("inputs") or {}
        if str(original_inputs.get("telegram_chat_id") or "") != chat_id:
            continue
        if action.get("capability") != "manage_calendar" or action.get("status") != "completed":
            continue
        for artifact in (action.get("result") or {}).get("artifacts") or []:
            if artifact.get("type") == "calendar_event" and isinstance(artifact.get("item"), dict):
                item = artifact["item"]
                operation = ((action.get("inputs") or {}).get("calendar_contract") or {}).get("operation")
                artifacts.append({
                    "event_id": item.get("id"), "title": item.get("summary"),
                    "start": calendar_artifact_time(item.get("start")),
                    "end": calendar_artifact_time(item.get("end")),
                    "status": "rescheduled_verified" if operation == "reschedule" else "created_verified",
                })
            elif artifact.get("type") == "calendar_deleted":
                deleted = artifact.get("item") or []
                if isinstance(deleted, dict):
                    deleted = deleted.get("deleted") or []
                for item in deleted:
                    if not isinstance(item, dict):
                        continue
                    artifacts.append({
                        "event_id": item.get("id"), "title": item.get("summary"),
                        "start": calendar_artifact_time(item.get("start")), "status": "deleted_verified",
                    })
        if len(artifacts) >= 10:
            break
    return artifacts[:10]


def verified_gmail_artifacts(payload):
    chat_id = str((payload.get("inputs") or {}).get("telegram_chat_id") or "")
    artifacts = []
    state = load_state()
    requests = state.get("requests", {})
    actions = sorted(state.get("actions", {}).values(), key=lambda item: item.get("created_at", ""), reverse=True)
    for action in actions:
        if action.get("capability") != "manage_email" or action.get("status") != "completed":
            continue
        if chat_id:
            request = requests.get(action.get("request_id"), {})
            original_inputs = (request.get("original") or {}).get("inputs") or {}
            if str(original_inputs.get("telegram_chat_id") or "") != chat_id:
                continue
        for artifact in (action.get("result") or {}).get("artifacts") or []:
            if artifact.get("type") == "gmail_draft" and isinstance(artifact.get("item"), dict):
                item = artifact["item"]
                artifacts.append({
                    "type": "gmail_draft",
                    "draft_id": item.get("id"),
                    "message_id": item.get("message_id"),
                    "thread_id": item.get("thread_id"),
                    "to": item.get("to"),
                    "subject": item.get("subject"),
                    "status": "draft_verified" if item.get("verified") else "draft_unverified",
                })
            elif artifact.get("type") in {"gmail_message", "gmail_sent_message"} and isinstance(artifact.get("item"), dict):
                item = artifact["item"]
                artifacts.append({
                    "type": artifact.get("type"),
                    "message_id": item.get("id"),
                    "thread_id": item.get("thread_id"),
                    "from": item.get("from"),
                    "to": item.get("to"),
                    "subject": item.get("subject"),
                    "snippet": item.get("snippet"),
                })
            elif artifact.get("type") == "gmail_messages":
                for item in artifact.get("items") or []:
                    if not isinstance(item, dict):
                        continue
                    artifacts.append({
                        "type": "gmail_message",
                        "message_id": item.get("id"),
                        "thread_id": item.get("thread_id"),
                        "from": item.get("from"),
                        "to": item.get("to"),
                        "subject": item.get("subject"),
                        "snippet": item.get("snippet"),
                    })
        if len(artifacts) >= 10:
            break
    return artifacts[:10]


def verified_task_artifacts(payload):
    chat_id = str((payload.get("inputs") or {}).get("telegram_chat_id") or "")
    artifacts = []
    state = load_state()
    requests = state.get("requests", {})
    actions = sorted(state.get("actions", {}).values(), key=lambda item: item.get("created_at", ""), reverse=True)
    for action in actions:
        if action.get("capability") != "manage_tasks" or action.get("status") != "completed":
            continue
        if chat_id:
            request = requests.get(action.get("request_id"), {})
            original_inputs = (request.get("original") or {}).get("inputs") or {}
            if str(original_inputs.get("telegram_chat_id") or "") != chat_id:
                continue
        for artifact in (action.get("result") or {}).get("artifacts") or []:
            items = artifact.get("items") if artifact.get("type") == "tasks" else [artifact.get("item")]
            for item in items or []:
                if not isinstance(item, dict):
                    continue
                artifacts.append({
                    "task_id": item.get("id"),
                    "tasklist_id": item.get("tasklist_id"),
                    "title": item.get("title"),
                    "status": item.get("status"),
                    "due": item.get("due"),
                })
        if len(artifacts) >= 10:
            break
    return artifacts[:10]


def verified_contact_artifacts(payload):
    chat_id = str((payload.get("inputs") or {}).get("telegram_chat_id") or "")
    artifacts = []
    state = load_state()
    requests = state.get("requests", {})
    actions = sorted(state.get("actions", {}).values(), key=lambda item: item.get("created_at", ""), reverse=True)
    for action in actions:
        if action.get("capability") != "manage_contacts" or action.get("status") != "completed":
            continue
        if chat_id:
            request = requests.get(action.get("request_id"), {})
            original_inputs = (request.get("original") or {}).get("inputs") or {}
            if str(original_inputs.get("telegram_chat_id") or "") != chat_id:
                continue
        for artifact in (action.get("result") or {}).get("artifacts") or []:
            items = artifact.get("items") if artifact.get("type") == "contacts" else [artifact.get("item")]
            for item in items or []:
                if not isinstance(item, dict):
                    continue
                artifacts.append({
                    "resource_name": item.get("resource_name"),
                    "names": item.get("names") or [],
                    "emails": item.get("emails") or [],
                    "phones": item.get("phones") or [],
                })
        if len(artifacts) >= 10:
            break
    return artifacts[:10]


def calendar_artifact_time(value):
    if isinstance(value, dict):
        return value.get("dateTime") or value.get("date")
    return value


def _parse_contract_time(value, field, required=False):
    if not value:
        if required:
            raise ValueError(f"{field}_required")
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"{field}_timezone_required")
    return parsed


def validate_calendar_contract(raw):
    if not isinstance(raw, dict):
        raise ValueError("calendar_contract_must_be_object")
    allowed_fields = {
        "operation", "title", "start", "end", "target_event_id", "search_window",
        "allow_search_fallback", "requires_clarification", "clarification", "attendees",
    }
    unknown_fields = sorted(set(raw) - allowed_fields)
    if unknown_fields:
        raise ValueError("calendar_contract_unknown_fields:" + ",".join(unknown_fields))
    operation = str(raw.get("operation") or "").lower()
    requires_clarification = raw.get("requires_clarification") is True
    if requires_clarification and operation not in {"create", "delete", "list", "reschedule"}:
        operation = "clarify"
    if operation not in {"create", "delete", "list", "reschedule", "clarify"}:
        raise ValueError("calendar_contract_operation_invalid")
    contract = {
        "version": 1,
        "operation": operation,
        "title": str(raw.get("title") or "").strip()[:200] or None,
        "start": raw.get("start") or None,
        "end": raw.get("end") or None,
        "target_event_id": str(raw.get("target_event_id") or "").strip() or None,
        "search_window": raw.get("search_window") if isinstance(raw.get("search_window"), dict) else None,
        "allow_search_fallback": raw.get("allow_search_fallback") is True,
        "requires_clarification": requires_clarification,
        "clarification": str(raw.get("clarification") or "").strip()[:500] or None,
        "attendees": raw.get("attendees") if isinstance(raw.get("attendees"), list) else [],
    }
    if contract["target_event_id"] and not re.fullmatch(r"[A-Za-z0-9_-]{5,256}", contract["target_event_id"]):
        raise ValueError("calendar_contract_event_id_invalid")
    if contract["requires_clarification"]:
        if not contract["clarification"]:
            raise ValueError("calendar_contract_clarification_required")
        return contract
    if operation in {"create", "reschedule"}:
        start = _parse_contract_time(contract["start"], "start", True)
        end = _parse_contract_time(contract["end"], "end", True)
        duration = end - start
        if duration < timedelta(minutes=1) or duration > timedelta(days=7):
            raise ValueError("calendar_contract_duration_invalid")
        if operation == "create" and not contract["title"]:
            raise ValueError("calendar_contract_title_required")
        if operation == "reschedule" and not contract["target_event_id"]:
            raise ValueError("calendar_contract_event_id_required")
    if operation == "delete" and not contract["target_event_id"]:
        window = contract["search_window"] or {}
        if not contract["allow_search_fallback"] or not contract["title"]:
            raise ValueError("calendar_contract_delete_target_ambiguous")
        window_start = _parse_contract_time(window.get("start"), "search_window_start", True)
        window_end = _parse_contract_time(window.get("end"), "search_window_end", True)
        if window_end <= window_start or window_end - window_start > timedelta(days=7):
            raise ValueError("calendar_contract_delete_search_window_invalid")
    for attendee in contract["attendees"]:
        if not isinstance(attendee, str) or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", attendee):
            raise ValueError("calendar_contract_attendee_invalid")
    if operation == "list":
        window = contract["search_window"] or {}
        window_start = _parse_contract_time(window.get("start"), "search_window_start", True)
        window_end = _parse_contract_time(window.get("end"), "search_window_end", True)
        if window_end <= window_start or window_end - window_start > timedelta(days=31):
            raise ValueError("calendar_contract_search_window_invalid")
    return contract


def calendar_contract_prompt(payload, artifacts):
    current_time = datetime.now().astimezone().replace(second=0, microsecond=0)
    return json.dumps({
        "current_time": current_time.isoformat(),
        "timezone": str(current_time.tzinfo),
        "request": request_text(payload),
        "recent_conversation": ((payload.get("inputs") or {}).get("conversation_context") or [])[-12:],
        "verified_calendar_artifacts": artifacts,
        "contract": {
            "operation": "create|delete|list|reschedule|clarify", "title": "string|null",
            "start": "ISO-8601 with offset|null", "end": "ISO-8601 with offset|null",
            "target_event_id": "verified event id|null",
            "search_window": {"start": "ISO-8601 with offset", "end": "ISO-8601 with offset"},
            "allow_search_fallback": False, "requires_clarification": False, "clarification": None,
            "attendees": [],
        },
    }, separators=(",", ":"))


def validate_calendar_contract_semantics(payload, contract, artifacts):
    request = request_text(payload)
    title = contract.get("title") or ""
    if contract.get("operation") == "create" and re.search(r"\b(?:titled|called|named)\b", request, re.IGNORECASE):
        if re.search(r"\bfor\s+\d+(?:\.\d+)?\s*(?:minutes?|hours?)\b", title, re.IGNORECASE):
            raise ValueError("calendar_contract_title_contains_duration_clause")

    if contract.get("operation") != "reschedule" or not contract.get("target_event_id"):
        return contract
    relative = re.search(
        r"\b(?:by\s+)?(\d+(?:\.\d+)?)\s*(minutes?|hours?)\s+(later|earlier)\b",
        request,
        re.IGNORECASE,
    )
    if not relative:
        return contract
    artifact = next(
        (
            item for item in artifacts
            if item.get("event_id") == contract["target_event_id"] and item.get("status") != "deleted_verified"
        ),
        None,
    )
    if not artifact or not artifact.get("start") or not artifact.get("end"):
        raise ValueError("calendar_contract_relative_move_missing_verified_artifact")
    amount = float(relative.group(1))
    delta = timedelta(hours=amount) if relative.group(2).lower().startswith("hour") else timedelta(minutes=amount)
    if relative.group(3).lower() == "earlier":
        delta = -delta
    expected_start = _parse_contract_time(artifact["start"], "artifact_start", True) + delta
    expected_end = _parse_contract_time(artifact["end"], "artifact_end", True) + delta
    actual_start = _parse_contract_time(contract.get("start"), "start", True)
    actual_end = _parse_contract_time(contract.get("end"), "end", True)
    if actual_start != expected_start or actual_end != expected_end:
        raise ValueError("calendar_contract_relative_move_incorrect")
    return contract


def build_calendar_contract(payload):
    if calendar_readonly_intent(payload):
        return calendar_readonly_list_contract(payload), "deterministic_readonly_list"
    artifacts = verified_calendar_artifacts(payload)
    prompt_text = calendar_contract_prompt(payload, artifacts)
    cache_key = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()
    with CALENDAR_CONTRACT_CACHE_LOCK:
        cached = CALENDAR_CONTRACT_CACHE.get(cache_key)
        if cached and time.time() - cached[0] < CALENDAR_CONTRACT_CACHE_TTL:
            return dict(cached[1]), "nemotron_cache"
    profile = LLM_PROFILES["deep_120b"]
    system = (
        "You translate natural-language Calendar requests into exactly one strict JSON action contract. "
        "Use only verified_calendar_artifacts for target_event_id. Resolve references like 'it' to the most recent non-deleted verified event. "
        "Never invent an event ID. For ambiguous requests set requires_clarification=true and ask one concise question. "
        "Use operation='clarify' when requires_clarification=true. "
        "A title introduced by titled/called/named ends before unquoted scheduling clauses such as 'for 30 minutes', 'at 8 PM', or 'on Monday'; those clauses are not part of the title. "
        "For relative reschedules such as 'move it 1 hour later', select the latest matching verified event, shift both start and end by exactly that amount, and preserve its duration and title. "
        "For delete without a verified ID, allow_search_fallback may be true only when title and a narrow explicit search window are known. "
        "Return JSON only and preserve the user's title exactly."
    )
    validation_error = None
    contract = None
    for attempt in range(2):
        attempt_prompt = prompt_text
        if validation_error:
            attempt_prompt += "\nThe previous contract was rejected with: " + validation_error + ". Return a corrected full contract."
        try:
            output = call_profile_assistant(attempt_prompt, profile, system)
            contract = validate_calendar_contract(parse_json_object(output))
            validate_calendar_contract_semantics(payload, contract, artifacts)
            break
        except Exception as exc:
            validation_error = str(exc)[:300]
            if attempt == 1:
                raise
    with CALENDAR_CONTRACT_CACHE_LOCK:
        CALENDAR_CONTRACT_CACHE[cache_key] = (time.time(), dict(contract))
        if len(CALENDAR_CONTRACT_CACHE) > 256:
            oldest = min(CALENDAR_CONTRACT_CACHE, key=lambda key: CALENDAR_CONTRACT_CACHE[key][0])
            CALENDAR_CONTRACT_CACHE.pop(oldest, None)
    return contract, "nemotron_retry" if validation_error else "nemotron"


def _clean_email(value, field):
    value = str(value or "").strip()
    if value and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
        raise ValueError(f"{field}_invalid")
    return value or None


def validate_contacts_contract(raw):
    if not isinstance(raw, dict):
        raise ValueError("contacts_contract_must_be_object")
    allowed_fields = {
        "operation", "query", "name", "email", "phone", "resource_name",
        "requires_clarification", "clarification", "max_results",
    }
    unknown_fields = sorted(set(raw) - allowed_fields)
    if unknown_fields:
        raise ValueError("contacts_contract_unknown_fields:" + ",".join(unknown_fields))
    operation = str(raw.get("operation") or "").lower()
    requires_clarification = raw.get("requires_clarification") is True
    if requires_clarification and operation not in {"search", "resolve_recipient", "create", "update"}:
        operation = "clarify"
    if operation not in {"search", "resolve_recipient", "create", "update", "clarify"}:
        raise ValueError("contacts_contract_operation_invalid")
    contract = {
        "version": 1,
        "operation": operation,
        "query": str(raw.get("query") or "").strip()[:200] or None,
        "name": str(raw.get("name") or "").strip()[:200] or None,
        "email": _clean_email(raw.get("email"), "contacts_contract_email"),
        "phone": str(raw.get("phone") or "").strip()[:80] or None,
        "resource_name": str(raw.get("resource_name") or "").strip()[:200] or None,
        "requires_clarification": requires_clarification,
        "clarification": str(raw.get("clarification") or "").strip()[:500] or None,
        "max_results": min(max(int(raw.get("max_results") or 10), 1), 25),
    }
    if contract["requires_clarification"]:
        if not contract["clarification"]:
            raise ValueError("contacts_contract_clarification_required")
        return contract
    if operation in {"search", "resolve_recipient"} and not contract["query"]:
        raise ValueError("contacts_contract_query_required")
    if operation == "create" and not (contract["name"] and (contract["email"] or contract["phone"])):
        raise ValueError("contacts_contract_create_incomplete")
    if operation == "update" and not contract["resource_name"]:
        raise ValueError("contacts_contract_update_resource_required")
    return contract


def contacts_contract_prompt(payload, artifacts):
    return json.dumps({
        "request": request_text(payload),
        "recent_conversation": ((payload.get("inputs") or {}).get("conversation_context") or [])[-12:],
        "verified_contact_artifacts": artifacts,
        "contract": {
            "operation": "search|resolve_recipient|create|update|clarify",
            "query": "search text|null",
            "name": "display name|null",
            "email": "email address|null",
            "phone": "phone number|null",
            "resource_name": "verified People API resource name|null",
            "requires_clarification": False,
            "clarification": None,
            "max_results": 10,
        },
    }, separators=(",", ":"))


def build_contacts_contract(payload):
    artifacts = verified_contact_artifacts(payload)
    prompt_text = contacts_contract_prompt(payload, artifacts)
    cache_key = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()
    with CONTACTS_CONTRACT_CACHE_LOCK:
        cached = CONTACTS_CONTRACT_CACHE.get(cache_key)
        if cached and time.time() - cached[0] < GMAIL_CONTRACT_CACHE_TTL:
            return dict(cached[1]), "nemotron_cache"
    profile = LLM_PROFILES["deep_120b"]
    system = (
        "You translate natural-language Google Contacts requests into one strict JSON contract. "
        "Use verified_contact_artifacts for resource_name when updating an existing contact. "
        "Use resolve_recipient when the user wants to email or refer to a named person. "
        "Create and update are allowed but require approval outside this contract. "
        "If the target contact or write details are ambiguous, return requires_clarification=true. Return JSON only."
    )
    validation_error = None
    contract = None
    for attempt in range(2):
        attempt_prompt = prompt_text
        if validation_error:
            attempt_prompt += "\nThe previous contract was rejected with: " + validation_error + ". Return a corrected full contract."
        try:
            output = call_profile_assistant(attempt_prompt, profile, system)
            contract = validate_contacts_contract(parse_json_object(output))
            break
        except Exception as exc:
            validation_error = str(exc)[:300]
            if attempt == 1:
                raise
    with CONTACTS_CONTRACT_CACHE_LOCK:
        CONTACTS_CONTRACT_CACHE[cache_key] = (time.time(), dict(contract))
    return contract, "nemotron_retry" if validation_error else "nemotron"


def validate_tasks_contract(raw):
    if not isinstance(raw, dict):
        raise ValueError("tasks_contract_must_be_object")
    allowed_fields = {
        "operation", "query", "task_id", "tasklist_id", "title", "notes", "due",
        "requires_clarification", "clarification", "max_results",
    }
    unknown_fields = sorted(set(raw) - allowed_fields)
    if unknown_fields:
        raise ValueError("tasks_contract_unknown_fields:" + ",".join(unknown_fields))
    operation = str(raw.get("operation") or "").lower()
    requires_clarification = raw.get("requires_clarification") is True
    if requires_clarification and operation not in {"list", "create", "complete", "update", "delete"}:
        operation = "clarify"
    if operation not in {"list", "create", "complete", "update", "delete", "clarify"}:
        raise ValueError("tasks_contract_operation_invalid")
    contract = {
        "version": 1,
        "operation": operation,
        "query": str(raw.get("query") or "").strip()[:300] or None,
        "task_id": str(raw.get("task_id") or "").strip()[:256] or None,
        "tasklist_id": str(raw.get("tasklist_id") or "").strip()[:256] or None,
        "title": str(raw.get("title") or "").strip()[:300] or None,
        "notes": str(raw.get("notes") or "").strip()[:2000] or None,
        "due": str(raw.get("due") or "").strip() or None,
        "requires_clarification": requires_clarification,
        "clarification": str(raw.get("clarification") or "").strip()[:500] or None,
        "max_results": min(max(int(raw.get("max_results") or 20), 1), 50),
    }
    if contract["requires_clarification"]:
        if not contract["clarification"]:
            raise ValueError("tasks_contract_clarification_required")
        return contract
    if operation == "create" and not contract["title"]:
        raise ValueError("tasks_contract_title_required")
    if operation in {"complete", "update", "delete"} and not contract["task_id"]:
        raise ValueError("tasks_contract_task_id_required")
    return contract


def tasks_contract_prompt(payload, artifacts):
    return json.dumps({
        "request": request_text(payload),
        "recent_conversation": ((payload.get("inputs") or {}).get("conversation_context") or [])[-12:],
        "verified_task_artifacts": artifacts,
        "contract": {
            "operation": "list|create|complete|update|delete|clarify",
            "query": "search text|null",
            "task_id": "verified task id|null",
            "tasklist_id": "task list id|null",
            "title": "task title|null",
            "notes": "task notes|null",
            "due": "RFC3339 due timestamp|null",
            "requires_clarification": False,
            "clarification": None,
            "max_results": 20,
        },
    }, separators=(",", ":"))


def build_tasks_contract(payload):
    artifacts = verified_task_artifacts(payload)
    prompt_text = tasks_contract_prompt(payload, artifacts)
    cache_key = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()
    with TASKS_CONTRACT_CACHE_LOCK:
        cached = TASKS_CONTRACT_CACHE.get(cache_key)
        if cached and time.time() - cached[0] < GMAIL_CONTRACT_CACHE_TTL:
            return dict(cached[1]), "nemotron_cache"
    profile = LLM_PROFILES["deep_120b"]
    system = (
        "You translate natural-language Google Tasks requests into one strict JSON contract. "
        "Use only verified_task_artifacts for task_id in follow-ups such as 'mark that done'. "
        "For delete or complete without a verified target, ask for clarification. "
        "Task writes execute without approval, so be precise. Return JSON only."
    )
    validation_error = None
    contract = None
    for attempt in range(2):
        attempt_prompt = prompt_text
        if validation_error:
            attempt_prompt += "\nThe previous contract was rejected with: " + validation_error + ". Return a corrected full contract."
        try:
            output = call_profile_assistant(attempt_prompt, profile, system)
            contract = validate_tasks_contract(parse_json_object(output))
            break
        except Exception as exc:
            validation_error = str(exc)[:300]
            if attempt == 1:
                raise
    with TASKS_CONTRACT_CACHE_LOCK:
        TASKS_CONTRACT_CACHE[cache_key] = (time.time(), dict(contract))
    return contract, "nemotron_retry" if validation_error else "nemotron"


def validate_gmail_contract(raw):
    if not isinstance(raw, dict):
        raise ValueError("gmail_contract_must_be_object")
    allowed_fields = {
        "operation", "query", "max_results", "draft_id", "message_ids", "thread_id",
        "to", "cc", "bcc", "subject", "body", "label_ids", "remove_label_ids",
        "requires_clarification", "clarification",
    }
    unknown_fields = sorted(set(raw) - allowed_fields)
    if unknown_fields:
        raise ValueError("gmail_contract_unknown_fields:" + ",".join(unknown_fields))
    operation = str(raw.get("operation") or "").lower()
    requires_clarification = raw.get("requires_clarification") is True
    if requires_clarification and operation not in {
        "search_messages", "summarize_messages", "create_draft", "update_draft", "send_draft", "send_message", "label_messages"
    }:
        operation = "clarify"
    if operation not in {
        "search_messages", "summarize_messages", "create_draft", "update_draft", "send_draft", "send_message", "label_messages", "clarify"
    }:
        raise ValueError("gmail_contract_operation_invalid")
    contract = {
        "version": 1,
        "operation": operation,
        "query": str(raw.get("query") or "").strip()[:500] or None,
        "max_results": int(raw.get("max_results") or 10),
        "draft_id": str(raw.get("draft_id") or "").strip() or None,
        "message_ids": raw.get("message_ids") if isinstance(raw.get("message_ids"), list) else [],
        "thread_id": str(raw.get("thread_id") or "").strip() or None,
        "to": raw.get("to") if isinstance(raw.get("to"), list) else [],
        "cc": raw.get("cc") if isinstance(raw.get("cc"), list) else [],
        "bcc": raw.get("bcc") if isinstance(raw.get("bcc"), list) else [],
        "subject": str(raw.get("subject") or "").strip()[:300] or None,
        "body": str(raw.get("body") or "").strip() or None,
        "label_ids": raw.get("label_ids") if isinstance(raw.get("label_ids"), list) else [],
        "remove_label_ids": raw.get("remove_label_ids") if isinstance(raw.get("remove_label_ids"), list) else [],
        "requires_clarification": requires_clarification,
        "clarification": str(raw.get("clarification") or "").strip()[:500] or None,
    }
    contract["max_results"] = min(max(contract["max_results"], 1), 25)
    for field in ("draft_id", "thread_id"):
        if contract[field] and not re.fullmatch(r"[A-Za-z0-9_-]{3,256}", contract[field]):
            raise ValueError(f"gmail_contract_{field}_invalid")
    clean_ids = []
    for message_id in contract["message_ids"]:
        if not isinstance(message_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{3,256}", message_id):
            raise ValueError("gmail_contract_message_id_invalid")
        clean_ids.append(message_id)
    contract["message_ids"] = clean_ids[:25]
    for field in ("to", "cc", "bcc"):
        cleaned = []
        for address in contract[field]:
            if not isinstance(address, str) or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", address.strip()):
                raise ValueError(f"gmail_contract_{field}_invalid")
            cleaned.append(address.strip())
        contract[field] = cleaned[:25]
    clean_labels = []
    for label_id in contract["label_ids"]:
        if not isinstance(label_id, str) or not label_id.strip():
            raise ValueError("gmail_contract_label_id_invalid")
        clean_labels.append(label_id.strip()[:100])
    contract["label_ids"] = clean_labels[:25]
    clean_remove = []
    for label_id in contract["remove_label_ids"]:
        if not isinstance(label_id, str) or not label_id.strip():
            raise ValueError("gmail_contract_remove_label_id_invalid")
        clean_remove.append(label_id.strip()[:100])
    contract["remove_label_ids"] = clean_remove[:25]
    if contract["requires_clarification"]:
        if not contract["clarification"]:
            raise ValueError("gmail_contract_clarification_required")
        return contract
    if operation in {"search_messages", "summarize_messages"} and not contract["query"]:
        raise ValueError("gmail_contract_query_required")
    if operation == "create_draft" and not contract["body"]:
        raise ValueError("gmail_contract_body_required")
    if operation == "update_draft" and not contract["draft_id"]:
        raise ValueError("gmail_contract_draft_id_required")
    if operation == "send_draft" and not contract["draft_id"]:
        raise ValueError("gmail_contract_send_target_required")
    if operation == "send_message":
        if not contract["to"] or not contract["subject"] or not contract["body"]:
            raise ValueError("gmail_contract_send_message_incomplete")
    if operation == "label_messages":
        if not contract["message_ids"]:
            raise ValueError("gmail_contract_message_ids_required")
        if not contract["label_ids"] and not contract["remove_label_ids"]:
            raise ValueError("gmail_contract_labels_required")
    return contract


def gmail_contract_prompt(payload, artifacts):
    current_time = datetime.now().astimezone().replace(second=0, microsecond=0)
    return json.dumps({
        "current_time": current_time.isoformat(),
        "timezone": str(current_time.tzinfo),
        "request": request_text(payload),
        "recent_conversation": ((payload.get("inputs") or {}).get("conversation_context") or [])[-12:],
        "explicit_inputs": payload.get("inputs") or {},
        "verified_gmail_artifacts": artifacts,
        "contract": {
            "operation": "search_messages|summarize_messages|create_draft|update_draft|send_draft|send_message|label_messages|clarify",
            "query": "Gmail search query|null",
            "max_results": 10,
            "draft_id": "verified draft id|null",
            "message_ids": [],
            "thread_id": "thread id|null",
            "to": [],
            "cc": [],
            "bcc": [],
            "subject": "string|null",
            "body": "string|null",
            "label_ids": [],
            "remove_label_ids": [],
            "requires_clarification": False,
            "clarification": None,
        },
    }, separators=(",", ":"))


def validate_gmail_contract_semantics(payload, contract, artifacts):
    request = request_text(payload)
    inputs = payload.get("inputs") or {}
    input_to = inputs.get("to") if isinstance(inputs.get("to"), list) else []
    input_subject = str(inputs.get("subject") or "").strip()
    input_body = str(inputs.get("body") or "").strip()
    has_explicit_message = bool(input_to and input_subject and input_body)
    if has_explicit_message:
        if contract.get("operation") != "send_message":
            raise ValueError("gmail_contract_explicit_message_must_use_send_message")
        if contract.get("to") != input_to or contract.get("subject") != input_subject or contract.get("body") != input_body:
            raise ValueError("gmail_contract_explicit_message_mismatch")
    if contract.get("operation") == "send_draft":
        draft_id = contract.get("draft_id")
        if not any(item.get("draft_id") == draft_id and item.get("status") == "draft_verified" for item in artifacts):
            raise ValueError("gmail_contract_send_requires_verified_draft")
    if contract.get("operation") == "create_draft":
        lowered = request.lower()
        if re.search(r"\bto\s+[A-Za-z][A-Za-z .'-]{1,40}\b", request) and "@" not in request and not contract.get("to"):
            raise ValueError("gmail_contract_named_recipient_unresolved")
        explicit_no_send = any(term in lowered for term in ("do not send", "don't send", "dont send", "without sending"))
        if not explicit_no_send and any(term in lowered for term in ("send", "send it", "email them", "reply to", "respond to", "forward")):
            raise ValueError("gmail_contract_send_misclassified_as_draft")
    return contract


def named_recipient_from_request(text):
    match = re.search(r"\bto\s+([A-Za-z][A-Za-z .'-]{1,40})(?:\s+(?:about|saying|that|and|with)\b|$)", text or "", re.IGNORECASE)
    if not match:
        return None
    name = match.group(1).strip(" .'-")
    if not name or "@" in name:
        return None
    return name


def resolve_gmail_named_recipient(payload, contract):
    if contract.get("operation") not in {"create_draft", "send_message", "update_draft"}:
        return contract
    if contract.get("to"):
        return contract
    name = named_recipient_from_request(request_text(payload))
    if not name:
        return contract
    try:
        result = call_google_tools(
            "/contacts/execute-contract",
            {"contract": {"version": 1, "operation": "resolve_recipient", "query": name, "max_results": 10}, "approved": False},
        )
    except Exception as exc:
        return {
            **contract,
            "operation": "clarify",
            "requires_clarification": True,
            "clarification": f"I could not verify the contact for {name}. Please provide the email address.",
        }
    if result.get("status") == "completed" and (result.get("resolved_recipient") or {}).get("email"):
        resolved = result["resolved_recipient"]
        return {**contract, "to": [resolved["email"]]}
    return {
        **contract,
        "operation": "clarify",
        "requires_clarification": True,
        "clarification": result.get("text") or f"Which {name} should I use?",
    }


def build_gmail_contract(payload):
    artifacts = verified_gmail_artifacts(payload)
    prompt_text = gmail_contract_prompt(payload, artifacts)
    cache_key = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()
    with GMAIL_CONTRACT_CACHE_LOCK:
        cached = GMAIL_CONTRACT_CACHE.get(cache_key)
        if cached and time.time() - cached[0] < GMAIL_CONTRACT_CACHE_TTL:
            return dict(cached[1]), "nemotron_cache"
    profile = LLM_PROFILES["deep_120b"]
    system = (
        "You translate natural-language Gmail requests into exactly one strict JSON action contract. "
        "If explicit_inputs contains to, subject, and body for an email send, those values are authoritative and operation must be send_message. "
        "Use only verified_gmail_artifacts for draft_id, message_ids, or thread_id. Never invent IDs. "
        "For follow-ups like 'send that draft' use the most recent verified Gmail draft. "
        "For search and summary, produce a real Gmail search query using Gmail search syntax. "
        "For drafts, body must contain the complete email text and subject must be useful. "
        "If a named recipient cannot be resolved to an email address, set requires_clarification=true. "
        "Sending, forwarding, deleting, and label changes are allowed as contracts but will require approval. "
        "Benign romantic or affectionate writing between consenting adults is allowed; refuse only unsafe, coercive, exploitative, or explicit sexual content involving minors by using clarify. "
        "Return JSON only."
    )
    validation_error = None
    contract = None
    for attempt in range(2):
        attempt_prompt = prompt_text
        if validation_error:
            attempt_prompt += "\nThe previous contract was rejected with: " + validation_error + ". Return a corrected full contract."
        try:
            output = call_profile_assistant(attempt_prompt, profile, system)
            contract = validate_gmail_contract(parse_json_object(output))
            contract = resolve_gmail_named_recipient(payload, contract)
            validate_gmail_contract_semantics(payload, contract, artifacts)
            break
        except Exception as exc:
            validation_error = str(exc)[:300]
            if attempt == 1:
                raise
    with GMAIL_CONTRACT_CACHE_LOCK:
        GMAIL_CONTRACT_CACHE[cache_key] = (time.time(), dict(contract))
        if len(GMAIL_CONTRACT_CACHE) > 256:
            oldest = min(GMAIL_CONTRACT_CACHE, key=lambda key: GMAIL_CONTRACT_CACHE[key][0])
            GMAIL_CONTRACT_CACHE.pop(oldest, None)
    return contract, "nemotron_retry" if validation_error else "nemotron"


def route_with_llm(payload):
    names = [capability["capability"] for capability in CAPABILITIES]
    catalog = [
        {
            "capability": capability["capability"],
            "description": capability["description"],
            "requires_approval": capability["requires_approval"],
        }
        for capability in CAPABILITIES
    ]
    prompt = {
        "role": "system",
        "content": (
            "You are the semantic manager agent for a personal homelab assistant. "
            "Choose exactly one capability from the provided catalog. "
            "Return only compact JSON with keys capability, confidence, rationale. "
            "Use general_assistant for ordinary chat, drafting, brainstorming, planning, or unclear requests. "
            "Infer tool follow-ups from recent conversation and verified artifacts, including indirect requests such as "
            "'move it later', 'delete that', or 'reply to them'. The latest request is authoritative. "
            "When a request changes, queries, or removes an object represented by recent_verified_tool_state, "
            "choose that state's owning capability even when the user omits the tool or object name. "
            "For example, after a verified manage_calendar event, 'make it one hour later' routes to manage_calendar. "
            "Verified artifacts are trusted state; conversational claims are context only."
        ),
    }
    calendar_state = verified_calendar_artifacts(payload)
    gmail_state = verified_gmail_artifacts(payload)
    verified_state = []
    if calendar_state:
        verified_state.append({"capability": "manage_calendar", "artifacts": calendar_state})
    if gmail_state:
        verified_state.append({"capability": "manage_email", "artifacts": gmail_state})
    user = {
        "role": "user",
        "content": json.dumps(
            {
                "catalog": catalog,
                "request": request_text(payload),
                "explicit_inputs": payload.get("inputs") or {},
                "conversation_memory": (payload.get("inputs") or {}).get("conversation_context") or [],
                "recent_verified_tool_state": verified_state,
            },
            separators=(",", ":"),
        ),
    }
    profile = LLM_PROFILES.get(ROUTER_PROFILE, LLM_PROFILES["local"])
    external = profile.get("provider") == "external_openai_compatible" and profile.get("configured")
    last_error = None
    for attempt in range(2):
        messages = [prompt, user]
        if attempt:
            messages.append({
                "role": "system",
                "content": "Your previous response was invalid. Return only one JSON object with capability, confidence, and rationale.",
            })
        if external:
            body = json.dumps({
                "model": profile["model"], "messages": messages, "temperature": 0, "max_tokens": 600,
            }).encode("utf-8")
            req = urllib.request.Request(
                profile["base_url"].rstrip("/") + "/chat/completions", data=body, method="POST",
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {profile_api_key(profile)}"},
            )
        else:
            body = json.dumps({
                "model": OLLAMA_ROUTER_MODEL, "messages": messages, "stream": False, "format": "json",
                "options": {"temperature": 0, "num_predict": 300},
            }).encode("utf-8")
            req = urllib.request.Request(OLLAMA_URL + "/api/chat", data=body, method="POST", headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=OLLAMA_ROUTER_TIMEOUT) as response:
                data = json.loads(response.read().decode("utf-8") or "{}")
            content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "") if external else data.get("message", {}).get("content", "")
            routed = parse_json_object(content)
            capability_name = routed.get("capability")
            if capability_name not in names:
                raise ValueError(f"unknown capability: {capability_name}")
            return capability_by_name(capability_name), {
                "router": profile.get("provider", "ollama"),
                "model": profile.get("model", OLLAMA_ROUTER_MODEL),
                "attempts": attempt + 1,
                "confidence": routed.get("confidence"),
                "rationale": str(routed.get("rationale", ""))[:500],
            }
        except Exception as exc:
            last_error = exc
    raise last_error


def route_request(payload):
    requested = payload.get("capability") or payload.get("requested_capability")
    if requested:
        matched = capability_by_name(str(requested))
        if matched:
            return matched, {
                "router": "explicit",
                "rationale": f"Request specified capability {matched['capability']}.",
            }

    text = request_text(payload).lower()
    if OLLAMA_ROUTER_ENABLED and request_text(payload):
        try:
            capability, metadata = route_with_llm(payload)
            if capability["capability"] != "manage_email" and gmail_send_or_publish_intent(text):
                return capability_by_name("manage_email"), {
                    **metadata,
                    "router": "safety_override",
                    "rationale": "Safety override: explicit email send/reply/forward requests must use the approval-gated Gmail path.",
                }
            return capability, metadata
        except Exception as exc:
            capability, metadata = route_with_keywords(payload)
            metadata["fallback_from"] = ROUTER_PROFILE
            metadata["fallback_error"] = str(exc)[:300]
            return capability, metadata

    return route_with_keywords(payload)


def split_multi_command_request(payload):
    text = request_text(payload).strip()
    if not text or payload.get("capability") or payload.get("requested_capability"):
        return [text] if text else []
    if len(text) > 1200:
        return [text]
    normalized = re.sub(r"\s+", " ", text)
    parts = re.split(r"\s*(?:;|\n+|\bthen\b|\band then\b|\balso\b|\bafter that\b)\s*", normalized, flags=re.IGNORECASE)
    commands = [part.strip(" .") for part in parts if part.strip(" .")]
    if len(commands) <= 1:
        return [text]
    command_verbs = (
        "find", "look", "search", "draft", "create", "add", "update", "complete", "mark",
        "delete", "remove", "send", "reply", "schedule", "move", "list", "build", "summarize",
    )
    if sum(1 for command in commands if command.lower().startswith(command_verbs)) < 2:
        return [text]
    return commands[:6]


def payload_for_subrequest(payload, subrequest):
    cloned = dict(payload)
    cloned["request"] = subrequest
    cloned.pop("capability", None)
    cloned.pop("requested_capability", None)
    inputs = dict((payload.get("inputs") or {}))
    inputs["request"] = subrequest
    inputs["parent_request"] = request_text(payload)
    cloned["inputs"] = inputs
    return cloned


def choose_execution_profile(payload, capability):
    text = request_text(payload).lower()
    deep_terms = (
        "architecture",
        "architect",
        "complex",
        "multi-step",
        "decompose",
        "strategy",
        "debug",
        "refactor",
        "repo",
        "code",
        "codex",
        "security",
        "database",
        "orchestration",
    )
    if capability["capability"] in {"edit_repository", "generate_parametric_part"}:
        profile_name = "deep_120b"
    elif any(term in text for term in deep_terms):
        profile_name = "deep_120b"
    elif capability["capability"] == "general_assistant":
        profile_name = "fast_70b"
    else:
        profile_name = "local"

    profile = dict(LLM_PROFILES[profile_name])
    if not profile["configured"] and profile_name != "local":
        fallback = dict(LLM_PROFILES["local"])
        fallback["requested_profile"] = profile_name
        fallback["fallback_reason"] = "External model profile is missing base URL or API key."
        return fallback
    return profile


def choose_workflow_level(payload, capability):
    text = request_text(payload).lower()
    inputs = payload.get("inputs") or {}
    publish = bool((payload.get("permissions") or {}).get("may_publish"))
    cost = float((payload.get("limits") or {}).get("maximum_cost_usd", 0) or 0)
    if any(term in text for term in ("delete", "wipe", "format", "factory reset", "disable firewall")):
        return {
            "level": 4,
            "name": "danger_zone",
            "approval": "blocked_until_manual_review",
            "rationale": "Potentially destructive request.",
        }
    if publish or cost > 0 or capability["cost_class"] in {"paid", "metered"}:
        return {
            "level": 3,
            "name": "external_or_spend",
            "approval": "explicit_approval_required",
            "rationale": "External cost, publish, or metered execution may be involved.",
        }
    if capability["capability"] in {"manage_smart_home", "organize_media"}:
        return {
            "level": 2,
            "name": "homelab_state_change",
            "approval": "approval_required",
            "rationale": "Request may change homelab or home state.",
        }
    if inputs.get("draft_mode"):
        return {
            "level": 1,
            "name": "draft_or_plan",
            "approval": "none",
            "rationale": "Draft-only request does not change external state.",
        }
    if capability["capability"] in {"general_assistant", "draft_email"}:
        return {
            "level": 0,
            "name": "answer_only",
            "approval": "none",
            "rationale": "Conversational response does not change external state.",
        }
    return {
        "level": 1,
        "name": "draft_or_plan",
        "approval": "approval_before_execution",
        "rationale": "Produces a plan or draft action contract before worker execution.",
    }


def call_ollama_assistant(prompt_text, model, system_text=None):
    messages = assistant_messages(prompt_text, system_text)
    body = json.dumps(
        {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0.3, "num_predict": 900},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL + "/api/chat",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=LLM_TIMEOUT) as response:
        data = json.loads(response.read().decode("utf-8") or "{}")
    return data.get("message", {}).get("content", "").strip()


def assistant_messages(prompt_text, system_text=None):
    return [
        {
            "role": "system",
            "content": system_text
            or (
                "You are Jarvis, a concise personal homelab assistant. "
                "Be practical, friendly, and direct. If the user asks for a draft, produce the draft."
            ),
        },
        {"role": "user", "content": prompt_text},
    ]


def profile_api_key(profile):
    name = profile.get("profile")
    if name == "fast_70b":
        return os.environ.get("JARVIS_FAST_LLM_API_KEY", "")
    if name == "deep_120b":
        return os.environ.get("JARVIS_DEEP_LLM_API_KEY", "")
    return ""


def call_openai_compatible_assistant(prompt_text, profile, system_text=None):
    base_url = (profile.get("base_url") or "").rstrip("/")
    api_key = profile_api_key(profile)
    if not base_url or not api_key:
        raise RuntimeError("external_profile_missing_base_url_or_api_key")
    body = json.dumps(
        {
            "model": profile.get("model"),
            "messages": assistant_messages(prompt_text, system_text),
            "temperature": 0.3,
            "max_tokens": 1200,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        base_url + "/chat/completions",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=LLM_TIMEOUT) as response:
        data = json.loads(response.read().decode("utf-8") or "{}")
    choices = data.get("choices") or []
    if not choices:
        return ""
    return choices[0].get("message", {}).get("content", "").strip()


def call_profile_assistant(prompt_text, profile, system_text=None):
    if profile.get("provider") == "ollama":
        return call_ollama_assistant(prompt_text, profile.get("model") or OLLAMA_ROUTER_MODEL, system_text)
    if profile.get("provider") == "external_openai_compatible":
        return call_openai_compatible_assistant(prompt_text, profile, system_text)
    return call_ollama_assistant(prompt_text, LLM_PROFILES["local"]["model"], system_text)


def call_google_tools(path, payload):
    body = json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(
        GOOGLE_TOOLS_URL + path,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {GOOGLE_TOOLS_TOKEN}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=90) as response:
        return json.loads(response.read().decode("utf-8") or "{}")


def call_codex_worker(action):
    payload = {
        "action": action,
        "job_id": action.get("action_id"),
        "limits": action.get("limits") or {},
    }
    body = json.dumps(payload).encode("utf-8")
    timeout = int((action.get("limits") or {}).get("maximum_runtime_seconds") or 1800) + 30
    req = urllib.request.Request(
        CODEX_WORKER_URL + "/run",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {CODEX_WORKER_TOKEN}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8") or "{}")


def gmail_send_or_publish_intent(text):
    text = (text or "").lower()
    send_terms = (
        "send",
        "send it",
        "send this",
        "send email",
        "email them",
        "forward",
        "reply to",
        "respond to",
    )
    return any(term in text for term in send_terms)


def gmail_draft_create_intent(text):
    text = (text or "").lower()
    if gmail_send_or_publish_intent(text):
        return False
    if "gmail" in text and any(term in text for term in ("draft", "compose", "write")):
        return True
    return any(term in text for term in ("create draft", "make a draft", "save draft"))


def gmail_draft_prompt(request):
    return (
        "Create a Gmail draft payload from the user's request. "
        "Return only compact JSON with keys to, subject, body. "
        "If the recipient is missing, use an empty string for to. "
        "If the subject is missing, write a short useful subject. "
        "The body must be the complete email draft. "
        "Benign romantic or affectionate writing between consenting adults is allowed; "
        "refuse only unsafe, coercive, exploitative, or explicit sexual content involving minors.\n\n"
        f"User request: {request}"
    )


def create_gmail_draft_from_request(action, request, google_payload):
    profile = action.get("execution_profile") or LLM_PROFILES["local"]
    draft_json = call_profile_assistant(gmail_draft_prompt(request), profile, "You produce Gmail draft JSON only.")
    draft = parse_json_object(draft_json)
    data = call_google_tools(
        "/gmail/create-draft",
        {
            **google_payload,
            "to": draft.get("to", ""),
            "subject": draft.get("subject", ""),
            "body": draft.get("body", ""),
        },
    )
    return {
        "request_id": action["request_id"],
        "tool": action["tool"],
        "status": "completed" if data.get("draft", {}).get("verified") else "verification_incomplete",
        "summary": "Created and verified a Gmail draft." if data.get("draft", {}).get("verified") else "Created a Gmail draft but verification was incomplete.",
        "text": data.get("text") or "Created Gmail draft.",
        "artifacts": [{"type": "gmail_draft", "item": data.get("draft")}],
        "cost": {"estimated_usd": 0},
        "next_actions": [],
    }


def codex_worker_result(action):
    data = call_codex_worker(action)
    status = data.get("status") or ("completed" if data.get("ok") else "failed")
    artifacts = data.get("artifacts") or []
    artifacts.append({
        "type": "codex_job",
        "item": {
            "job_id": data.get("job_id"),
            "status": status,
            "return_code": data.get("return_code"),
            "started_at": data.get("started_at"),
            "finished_at": data.get("finished_at"),
        },
    })
    return {
        "request_id": action["request_id"],
        "tool": action["tool"],
        "status": status,
        "summary": data.get("summary") or "Codex worker returned a result.",
        "text": data.get("text") or data.get("summary") or "",
        "artifacts": artifacts,
        "cost": {"estimated_usd": 0},
        "next_actions": [],
        "worker_result": {
            "job_id": data.get("job_id"),
            "return_code": data.get("return_code"),
            "codex": data.get("codex"),
        },
    }


def google_tools_result(action):
    inputs = action.get("inputs", {}) or {}
    request = inputs.get("request", "")
    google_payload = {
        "request": request,
        "conversation_context": inputs.get("conversation_context") or [],
    }
    if action.get("capability") == "manage_email":
        contract = inputs.get("gmail_contract")
        if contract:
            if contract.get("requires_clarification"):
                return {
                    "request_id": action["request_id"],
                    "tool": action["tool"],
                    "status": "clarification_required",
                    "summary": "Gmail request needs clarification.",
                    "text": contract["clarification"],
                    "artifacts": [{"type": "gmail_action_contract", "item": contract}],
                    "cost": {"estimated_usd": 0},
                    "next_actions": [],
                }
            data = call_google_tools(
                "/gmail/execute-contract",
                {"contract": contract, "approved": bool(action.get("requires_approval") and action.get("permissions", {}).get("may_execute"))},
            )
        elif gmail_draft_create_intent(request):
            return create_gmail_draft_from_request(action, request, google_payload)
        else:
            data = call_google_tools("/gmail/assist", {**google_payload, "max_results": 10})
        artifacts = [{"type": "gmail_action_contract", "item": contract}] if contract else []
        if data.get("draft"):
            artifacts.append({"type": "gmail_draft", "item": data.get("draft")})
        elif data.get("sent_message"):
            artifacts.append({"type": "gmail_sent_message", "item": data.get("sent_message")})
        elif data.get("message"):
            artifacts.append({"type": "gmail_message", "item": data.get("message")})
        else:
            artifacts.append({"type": "gmail_messages", "items": data.get("messages", [])})
        return {
            "request_id": action["request_id"],
            "tool": action["tool"],
            "status": data.get("status") or "completed",
            "summary": "Handled Gmail request with verified Google Tools.",
            "text": data.get("text") or "Handled Gmail request.",
            "artifacts": artifacts,
            "cost": {"estimated_usd": 0},
            "next_actions": [],
        }
    if action.get("capability") == "manage_calendar":
        contract = inputs.get("calendar_contract")
        if contract:
            if contract.get("requires_clarification"):
                return {
                    "request_id": action["request_id"], "tool": action["tool"], "status": "clarification_required",
                    "summary": "Calendar request needs clarification.", "text": contract["clarification"],
                    "artifacts": [{"type": "calendar_action_contract", "item": contract}],
                    "cost": {"estimated_usd": 0}, "next_actions": [],
                }
            data = call_google_tools(
                "/calendar/execute-contract",
                {"contract": contract, "approved": bool(action.get("requires_approval") and action.get("permissions", {}).get("may_execute"))},
            )
        else:
            data = call_google_tools("/calendar/assist", google_payload)
        artifacts = []
        if data.get("event"):
            artifacts.append({"type": "calendar_event", "item": data.get("event")})
        elif data.get("deleted"):
            artifacts.append({"type": "calendar_deleted", "item": data.get("deleted")})
        else:
            artifacts.append({"type": "calendar_events", "items": data.get("events", [])})
        return {
            "request_id": action["request_id"],
            "tool": action["tool"],
            "status": data.get("status") or "completed",
            "summary": "Fetched Calendar results from Google Tools.",
            "text": data.get("text") or "Fetched Calendar results.",
            "artifacts": [{"type": "calendar_action_contract", "item": contract}] + artifacts if contract else artifacts,
            "cost": {"estimated_usd": 0},
            "next_actions": [],
        }
    if action.get("capability") == "manage_contacts":
        contract = inputs.get("contacts_contract")
        if contract:
            if contract.get("requires_clarification"):
                return {
                    "request_id": action["request_id"],
                    "tool": action["tool"],
                    "status": "clarification_required",
                    "summary": "Contacts request needs clarification.",
                    "text": contract.get("clarification") or "Which contact should I use?",
                    "artifacts": [{"type": "contacts_action_contract", "item": contract}],
                    "cost": {"estimated_usd": 0},
                    "next_actions": [],
                }
            data = call_google_tools(
                "/contacts/execute-contract",
                {"contract": contract, "approved": bool(action.get("requires_approval") and action.get("permissions", {}).get("may_execute"))},
            )
        else:
            data = call_google_tools("/contacts/assist", google_payload)
        artifacts = [{"type": "contacts_action_contract", "item": contract}] if contract else []
        if data.get("resolved_recipient"):
            artifacts.append({"type": "resolved_recipient", "item": data.get("resolved_recipient")})
        if data.get("contact"):
            artifacts.append({"type": "contact", "item": data.get("contact")})
        if data.get("contacts") is not None:
            artifacts.append({"type": "contacts", "items": data.get("contacts", [])})
        return {
            "request_id": action["request_id"],
            "tool": action["tool"],
            "status": data.get("status") or "completed",
            "summary": "Handled Contacts request with Google Tools.",
            "text": data.get("text") or "Fetched Contacts results.",
            "artifacts": artifacts,
            "cost": {"estimated_usd": 0},
            "next_actions": [],
        }
    if action.get("capability") == "manage_tasks":
        contract = inputs.get("tasks_contract")
        if contract:
            if contract.get("requires_clarification"):
                return {
                    "request_id": action["request_id"],
                    "tool": action["tool"],
                    "status": "clarification_required",
                    "summary": "Tasks request needs clarification.",
                    "text": contract.get("clarification") or "Which task should I use?",
                    "artifacts": [{"type": "tasks_action_contract", "item": contract}],
                    "cost": {"estimated_usd": 0},
                    "next_actions": [],
                }
            data = call_google_tools("/tasks/execute-contract", {"contract": contract, "approved": True})
        else:
            data = call_google_tools("/tasks/assist", google_payload)
        artifacts = []
        if contract:
            artifacts.append({"type": "tasks_action_contract", "item": contract})
        if data.get("task"):
            artifacts.append({"type": "task", "item": data.get("task")})
        else:
            artifacts.append({"type": "tasks", "items": data.get("tasks", [])})
        return {
            "request_id": action["request_id"],
            "tool": action["tool"],
            "status": "completed",
            "summary": "Handled Tasks request with Google Tools.",
            "text": data.get("text") or "Handled Tasks request.",
            "artifacts": artifacts,
            "cost": {"estimated_usd": 0},
            "next_actions": [],
        }
    if action.get("capability") == "briefing_profile":
        text_lower = request.lower()
        updates = {}
        note = ""
        repo_match = re.search(r"([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)", request)
        city_match = re.search(r"(?:set|update|change).{0,30}(?:city|location|where i live)\s+(?:to\s+)?([A-Za-z .'-]{2,80})", request, re.IGNORECASE)
        if city_match:
            updates["current_city"] = city_match.group(1).strip(" .")
        if repo_match and any(term in text_lower for term in ("watch", "watched", "github", "repo")):
            current = call_google_tools("/profile/get", {}).get("profile") or {}
            repos = list(dict.fromkeys((current.get("watched_repos") or []) + [repo_match.group(1)]))
            updates["watched_repos"] = repos
        if any(term in text_lower for term in ("remember", "note", "preference")) and not updates:
            note = request.strip()
        if updates:
            data = call_google_tools("/profile/update", {"updates": updates})
            summary = "Updated briefing profile."
        elif note:
            data = call_google_tools("/profile/notes", {"operation": "add", "note": note})
            summary = "Saved briefing note."
        else:
            data = call_google_tools("/profile/get", {})
            summary = "Fetched briefing profile."
        return {
            "request_id": action["request_id"],
            "tool": action["tool"],
            "status": data.get("status") or "completed",
            "summary": summary,
            "text": data.get("text") or summary,
            "artifacts": [{"type": "briefing_profile", "item": data.get("profile") or data}],
            "cost": {"estimated_usd": 0},
            "next_actions": [],
        }
    if action.get("capability") == "daily_briefing":
        kind = "evening" if "evening" in request.lower() or "tomorrow prep" in request.lower() else "morning"
        data = call_google_tools("/briefing/build", {"kind": kind})
        artifacts = [{"type": "daily_brief", "item": data}]
        if data.get("profile"):
            artifacts.append({"type": "briefing_profile", "item": data.get("profile")})
        if data.get("weather"):
            artifacts.append({"type": "weather_location", "item": {"location": data.get("weather_location"), "weather": data.get("weather")}})
        if data.get("github"):
            artifacts.append({"type": "github_digest", "item": data.get("github")})
        return {
            "request_id": action["request_id"],
            "tool": action["tool"],
            "status": data.get("status") or "completed",
            "summary": f"Built {kind} briefing.",
            "text": data.get("text") or "Built briefing.",
            "artifacts": artifacts,
            "cost": {"estimated_usd": 0},
            "next_actions": [],
        }
    raise ValueError("unsupported_google_tools_capability")


def google_request_requires_approval(payload, capability):
    if capability["capability"] not in {"manage_email", "manage_calendar", "manage_contacts"}:
        return capability["execution_requires_approval"]
    if capability["capability"] == "manage_contacts":
        text = request_text(payload).lower()
        return any(term in text for term in ("create", "add", "update", "change", "edit", "set phone", "set email"))
    text = request_text(payload).lower()
    if capability["capability"] == "manage_email" and gmail_draft_create_intent(text):
        return False
    outward_terms = (
        "send",
        "send it",
        "send this",
        "send email",
        "email them",
        "forward",
        "reply to",
        "respond to",
        "invite",
        "attendee",
        "attendees",
        "share",
    )
    draft_terms = ("draft", "compose", "write")
    if any(term in text for term in outward_terms):
        if any(term in text for term in draft_terms) and not any(term in text for term in ("send", "forward", "invite", "share")):
            return False
        return True
    return False


def gmail_contract_requires_approval(contract):
    if not contract or contract.get("requires_clarification"):
        return False
    return contract.get("operation") in {"send_draft", "send_message", "label_messages"}


def contacts_contract_requires_approval(contract):
    if not contract or contract.get("requires_clarification"):
        return False
    return contract.get("operation") in {"create", "update"}


def fallback_system_prompt(action):
    inputs = action.get("inputs", {}) or {}
    voice_prefix = ""
    if inputs.get("voice_response") or inputs.get("response_style") == "spoken_concise":
        voice_prefix = (
            "This answer will be spoken aloud. Reply in 2 to 4 short sentences by default. "
            "Avoid markdown, long lists, tables, metadata, and filler. "
            "If the user asks for a detailed explanation, give a concise overview first and offer to go deeper. "
        )
    if action["worker"] == "llm_worker":
        return (
            voice_prefix +
            "You are Jarvis, a concise personal homelab assistant. "
            "Be practical, friendly, and direct. If the user asks for a draft, produce the draft. "
            "Benign romantic or affectionate writing between consenting adults is allowed; refuse only unsafe, coercive, exploitative, or explicit sexual content involving minors."
        )
    return (
        voice_prefix +
        "You are Jarvis Core running in local fallback mode. "
        "A dedicated connector is not wired yet, so do not claim that you changed external systems. "
        "Return the most useful safe result: a draft, checklist, structured action proposal, or next-step plan. "
        "If the request would change external state, clearly label it as a proposal awaiting a real connector."
    )


def fallback_prompt(action):
    inputs = action.get("inputs", {}) or {}
    prompt_text = inputs.get("request", "")
    if inputs.get("draft_mode") or action.get("capability") == "draft_email" or action.get("tool") == "ollama.draft_email":
        return (
            "Create the requested draft now. Do not ask what to help with. "
            "If details are missing, make a useful neutral draft with editable bracketed fields.\n\n"
            f"User request: {prompt_text}"
        )
    if inputs.get("voice_response") or inputs.get("response_style") == "spoken_concise":
        return (
            "Answer for a voice conversation. Keep it short, useful, and natural to hear. "
            "Do not use bullet lists unless the user explicitly asks for a list.\n\n"
            f"User request: {prompt_text}"
        )
    if action["worker"] == "llm_worker":
        return prompt_text
    return json.dumps(
        {
            "user_request": prompt_text,
            "capability": action.get("capability"),
            "worker": action.get("worker"),
            "tool": action.get("tool"),
            "workflow_level": action.get("workflow_level"),
            "instruction": "Generate a local fallback response or action proposal.",
        },
        separators=(",", ":"),
    )


def execute_action(action):
    if action["worker"] == "whisper_worker":
        return {
            "request_id": action["request_id"],
            "tool": action["tool"],
            "status": "queued_for_worker",
            "summary": "Use Jarvis Chat audio upload to execute Whisper transcription.",
            "artifacts": [],
            "cost": {"estimated_usd": 0},
            "next_actions": [],
        }

    if action.get("adapter_type") == "google_tools_worker":
        try:
            return google_tools_result(action)
        except Exception as exc:
            action.setdefault("inputs", {})["google_tools_error"] = str(exc)[:500]

    if action.get("adapter_type") == "cli_worker" and action.get("worker") == "coding_worker":
        try:
            return codex_worker_result(action)
        except Exception as exc:
            action.setdefault("inputs", {})["codex_worker_error"] = str(exc)[:500]

    profile = action.get("execution_profile", {})
    try:
        answer = call_profile_assistant(fallback_prompt(action), profile, fallback_system_prompt(action))
    except Exception as exc:
        action.setdefault("inputs", {})["llm_profile_error"] = str(exc)[:500]
        fallback = dict(LLM_PROFILES["local"])
        fallback["requested_profile"] = profile.get("profile")
        fallback["fallback_reason"] = str(exc)[:300]
        action["execution_profile"] = fallback
        answer = call_profile_assistant(fallback_prompt(action), fallback, fallback_system_prompt(action))
    return {
        "request_id": action["request_id"],
        "tool": action["tool"],
        "status": "completed",
        "summary": "Generated a local Ollama response."
        if action["worker"] == "llm_worker"
        else "Generated a local Ollama fallback action proposal.",
        "text": answer,
        "artifacts": [],
        "cost": {"estimated_usd": 0},
        "next_actions": [],
    }


def make_action(request_id, payload, capability):
    action_id = f"act-{uuid.uuid4().hex[:12]}"
    permissions = payload.get("permissions") or {}
    limits = payload.get("limits") or {}
    requires_approval = capability["execution_requires_approval"]
    if capability["capability"] in {"manage_email", "manage_calendar"}:
        requires_approval = google_request_requires_approval(payload, capability)
    may_execute = True if not requires_approval else bool(permissions.get("may_execute", False))
    action_inputs = dict(payload.get("inputs") or {})
    action_inputs.setdefault("request", request_text(payload))
    if capability["capability"] == "manage_calendar":
        try:
            contract, source = build_calendar_contract(payload)
            action_inputs["calendar_contract"] = contract
            action_inputs["calendar_contract_source"] = source
            if contract.get("attendees"):
                requires_approval = True
                may_execute = bool(permissions.get("may_execute", False))
        except Exception as exc:
            action_inputs["calendar_contract_error"] = str(exc)[:500]
            if calendar_mutation_intent(payload):
                action_inputs["calendar_contract_source"] = "nemotron_validation_guard"
                action_inputs["calendar_contract"] = {
                    "version": 1, "operation": "clarify", "title": None, "start": None,
                    "end": None, "target_event_id": None, "search_window": None,
                    "allow_search_fallback": False, "requires_clarification": True,
                    "clarification": "I could not validate the requested calendar change. Please restate the event, date, time, and action.",
                    "attendees": [],
                }
            else:
                action_inputs["calendar_contract_source"] = "legacy_parser_fallback"
    if capability["capability"] == "manage_email":
        try:
            contract, source = build_gmail_contract(payload)
            action_inputs["gmail_contract"] = contract
            action_inputs["gmail_contract_source"] = source
            if gmail_contract_requires_approval(contract):
                requires_approval = True
                may_execute = bool(permissions.get("may_execute", False))
            elif not contract.get("requires_clarification"):
                requires_approval = False
                may_execute = True
        except Exception as exc:
            action_inputs["gmail_contract_error"] = str(exc)[:500]
            action_inputs["gmail_contract_source"] = "nemotron_validation_guard"
            action_inputs["gmail_contract"] = {
                "version": 1,
                "operation": "clarify",
                "query": None,
                "max_results": 10,
                "draft_id": None,
                "message_ids": [],
                "thread_id": None,
                "to": [],
                "cc": [],
                "bcc": [],
                "subject": None,
                "body": None,
                "label_ids": [],
                "remove_label_ids": [],
                "requires_clarification": True,
                "clarification": "I could not validate the requested Gmail action. Please provide the exact recipient, draft, message, or search you want.",
            }
            requires_approval = False
            may_execute = True
    if capability["capability"] == "manage_contacts":
        try:
            contract, source = build_contacts_contract(payload)
            action_inputs["contacts_contract"] = contract
            action_inputs["contacts_contract_source"] = source
            if contacts_contract_requires_approval(contract):
                requires_approval = True
                may_execute = bool(permissions.get("may_execute", False))
            elif not contract.get("requires_clarification"):
                requires_approval = False
                may_execute = True
        except Exception as exc:
            action_inputs["contacts_contract_error"] = str(exc)[:500]
            action_inputs["contacts_contract_source"] = "nemotron_validation_guard"
            action_inputs["contacts_contract"] = {
                "version": 1,
                "operation": "clarify",
                "query": None,
                "name": None,
                "email": None,
                "phone": None,
                "resource_name": None,
                "requires_clarification": True,
                "clarification": "I could not validate the requested Contacts action. Please provide the exact contact name and change you want.",
                "max_results": 10,
            }
            requires_approval = False
            may_execute = True
    if capability["capability"] == "manage_tasks":
        try:
            contract, source = build_tasks_contract(payload)
            action_inputs["tasks_contract"] = contract
            action_inputs["tasks_contract_source"] = source
            requires_approval = False
            may_execute = True
        except Exception as exc:
            action_inputs["tasks_contract_error"] = str(exc)[:500]
            action_inputs["tasks_contract_source"] = "nemotron_validation_guard"
            action_inputs["tasks_contract"] = {
                "version": 1,
                "operation": "clarify",
                "query": None,
                "task_id": None,
                "tasklist_id": None,
                "title": None,
                "notes": None,
                "due": None,
                "requires_clarification": True,
                "clarification": "I could not validate the requested Google Tasks action. Please provide the exact task or list request.",
                "max_results": 20,
            }
            requires_approval = False
            may_execute = True

    return {
        "action_id": action_id,
        "request_id": request_id,
        "capability": capability["capability"],
        "tool": capability["tools"][0],
        "worker": capability["worker"],
        "adapter_type": capability["adapter_type"],
        "status": "approved" if may_execute else "awaiting_approval",
        "requires_approval": requires_approval,
        "created_at": now(),
        "approved_at": now() if may_execute else None,
        "inputs": action_inputs,
        "limits": {
            "maximum_cost_usd": limits.get("maximum_cost_usd", 0),
            "maximum_runtime_seconds": limits.get("maximum_runtime_seconds", 1800),
        },
        "permissions": {
            "may_execute": may_execute,
            "may_publish": bool(permissions.get("may_publish", False)),
        },
        "workflow_level": choose_workflow_level(payload, capability),
        "execution_profile": choose_execution_profile(payload, capability),
        "result": None,
    }


def error_payload(message):
    return {"ok": False, "error": message}


class Handler(BaseHTTPRequestHandler):
    server_version = "homelab-ai-orchestrator/0.1"

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args), flush=True)

    def write_json(self, status, payload):
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8") or "{}")

    def authorized(self):
        if not TOKEN or TOKEN.startswith("CHANGE_ME"):
            return False
        auth = self.headers.get("Authorization", "")
        if auth == f"Bearer {TOKEN}":
            return True
        parsed = urlparse(self.path)
        return parse_qs(parsed.query).get("token", [""])[0] == TOKEN

    def require_auth(self):
        if self.authorized():
            return True
        self.write_json(HTTPStatus.UNAUTHORIZED, error_payload("unauthorized"))
        return False

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path == "/health":
            self.write_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "configured": bool(TOKEN and not TOKEN.startswith("CHANGE_ME")),
                    "capabilities": len(CAPABILITIES),
                    "router": {
                        "ollama_enabled": OLLAMA_ROUTER_ENABLED,
                        "ollama_url": OLLAMA_URL,
                        "model": OLLAMA_ROUTER_MODEL,
                        "profile": ROUTER_PROFILE,
                        "active_provider": LLM_PROFILES.get(ROUTER_PROFILE, LLM_PROFILES["local"])["provider"],
                        "active_model": LLM_PROFILES.get(ROUTER_PROFILE, LLM_PROFILES["local"])["model"],
                        "timeout_seconds": OLLAMA_ROUTER_TIMEOUT,
                    },
                    "calendar_contract_planner": {
                        "profile": "deep_120b",
                        "provider": LLM_PROFILES["deep_120b"]["provider"],
                        "model": LLM_PROFILES["deep_120b"]["model"],
                        "configured": LLM_PROFILES["deep_120b"]["configured"],
                    },
                    "gmail_contract_planner": {
                        "profile": "deep_120b",
                        "provider": LLM_PROFILES["deep_120b"]["provider"],
                        "model": LLM_PROFILES["deep_120b"]["model"],
                        "configured": LLM_PROFILES["deep_120b"]["configured"],
                    },
                },
            )
            return

        if path == "/capabilities":
            self.write_json(HTTPStatus.OK, {"ok": True, "capabilities": CAPABILITIES})
            return

        if path == "/profile":
            if not self.require_auth():
                return
            try:
                data = call_google_tools("/profile/get", {})
                self.write_json(HTTPStatus.OK, data)
            except Exception as exc:
                self.write_json(HTTPStatus.BAD_GATEWAY, error_payload(str(exc)))
            return

        if path.startswith("/requests/"):
            if not self.require_auth():
                return
            request_id = path.split("/", 2)[2]
            state = load_state()
            request = state["requests"].get(request_id)
            if not request:
                self.write_json(HTTPStatus.NOT_FOUND, error_payload("request_not_found"))
                return
            actions = [
                action
                for action in state["actions"].values()
                if action["request_id"] == request_id
            ]
            self.write_json(HTTPStatus.OK, {"ok": True, "request": request, "actions": actions})
            return

        self.write_json(HTTPStatus.NOT_FOUND, error_payload("not_found"))

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path == "/requests":
            if not self.require_auth():
                return
            try:
                payload = self.read_json()
            except Exception as exc:
                self.write_json(HTTPStatus.BAD_REQUEST, error_payload(f"invalid_json: {exc}"))
                return

            request_id = payload.get("request_id") or f"req-{uuid.uuid4().hex[:12]}"
            subrequests = split_multi_command_request(payload)
            actions = []
            routes = []
            capabilities = []
            for index, subrequest in enumerate(subrequests or [request_text(payload)]):
                sub_payload = payload_for_subrequest(payload, subrequest) if len(subrequests) > 1 else payload
                capability, route = route_request(sub_payload)
                action = make_action(request_id, sub_payload, capability)
                action["sequence"] = index + 1
                action["subrequest"] = subrequest
                actions.append(action)
                routes.append({"sequence": index + 1, "subrequest": subrequest, **route})
                capabilities.append(capability)
            primary = capabilities[0]
            request = {
                "request_id": request_id,
                "status": "planned",
                "created_at": now(),
                "capability": primary["capability"] if len(actions) == 1 else "multi_action",
                "worker": primary["worker"] if len(actions) == 1 else "jarvis_core",
                "summary": f"Planned {len(actions)} Jarvis action(s).",
                "route": routes[0] if len(actions) == 1 else {"router": "multi_command", "steps": routes},
                "original": payload,
                "next_actions": [
                    {
                        "action_id": item["action_id"],
                        "tool": item["tool"],
                        "authorization": "approved"
                        if item["status"] == "approved"
                        else "approval_required",
                    }
                    for item in actions
                ],
            }
            state = load_state()
            state["requests"][request_id] = request
            for action in actions:
                state["actions"][action["action_id"]] = action
            save_state(state)
            self.write_json(
                HTTPStatus.ACCEPTED,
                {"ok": True, "request": request, "actions": actions},
            )
            return

        if path == "/profile":
            if not self.require_auth():
                return
            try:
                data = call_google_tools("/profile/update", self.read_json())
                self.write_json(HTTPStatus.OK, data)
            except Exception as exc:
                self.write_json(HTTPStatus.BAD_GATEWAY, error_payload(str(exc)))
            return

        if path == "/profile/notes":
            if not self.require_auth():
                return
            try:
                data = call_google_tools("/profile/notes", self.read_json())
                self.write_json(HTTPStatus.OK, data)
            except Exception as exc:
                self.write_json(HTTPStatus.BAD_GATEWAY, error_payload(str(exc)))
            return

        if path.startswith("/actions/") and path.endswith("/approve"):
            if not self.require_auth():
                return
            action_id = path.split("/")[2]
            state = load_state()
            action = state["actions"].get(action_id)
            if not action:
                self.write_json(HTTPStatus.NOT_FOUND, error_payload("action_not_found"))
                return
            action["status"] = "approved"
            action["approved_at"] = now()
            action["permissions"]["may_execute"] = True
            save_state(state)
            self.write_json(HTTPStatus.OK, {"ok": True, "action": action})
            return

        if path.startswith("/actions/") and path.endswith("/execute"):
            if not self.require_auth():
                return
            action_id = path.split("/")[2]
            state = load_state()
            action = state["actions"].get(action_id)
            if not action:
                self.write_json(HTTPStatus.NOT_FOUND, error_payload("action_not_found"))
                return
            if not action["permissions"].get("may_execute"):
                self.write_json(HTTPStatus.CONFLICT, error_payload("approval_required"))
                return

            result = execute_action(action)
            action["result"] = result
            action["status"] = result["status"]
            sibling_actions = [
                item for item in state["actions"].values()
                if item["request_id"] == action["request_id"]
            ]
            if any(item.get("status") == "awaiting_approval" for item in sibling_actions):
                state["requests"][action["request_id"]]["status"] = "partial_approval_required"
            elif any(item.get("status") in {"approved", "planned"} for item in sibling_actions):
                state["requests"][action["request_id"]]["status"] = "partial_completed"
            elif all(item.get("status") == "completed" for item in sibling_actions):
                state["requests"][action["request_id"]]["status"] = "completed"
            else:
                state["requests"][action["request_id"]]["status"] = result["status"]
            save_state(state)
            self.write_json(HTTPStatus.ACCEPTED, {"ok": True, "action": action})
            return

        self.write_json(HTTPStatus.NOT_FOUND, error_payload("not_found"))


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"AI orchestrator listening on {HOST}:{PORT}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
