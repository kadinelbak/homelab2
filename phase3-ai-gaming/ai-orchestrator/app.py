#!/usr/bin/env python3
import json
import os
import time
import uuid
import urllib.error
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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
LLM_TIMEOUT = float(os.environ.get("AI_ORCHESTRATOR_LLM_TIMEOUT", "120"))
GOOGLE_TOOLS_URL = os.environ.get("GOOGLE_TOOLS_URL", "http://google-tools-worker:18200").rstrip("/")
GOOGLE_TOOLS_TOKEN = os.environ.get("GOOGLE_TOOLS_TOKEN", TOKEN)
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
        "model": os.environ.get("JARVIS_FAST_LLM_MODEL", "llama-70b"),
        "base_url": os.environ.get("JARVIS_FAST_LLM_BASE_URL", ""),
        "configured": bool(os.environ.get("JARVIS_FAST_LLM_API_KEY") and os.environ.get("JARVIS_FAST_LLM_BASE_URL")),
        "use_for": "general assistant answers, drafting, summarization, normal planning",
    },
    "deep_120b": {
        "profile": "deep_120b",
        "provider": os.environ.get("JARVIS_DEEP_LLM_PROVIDER", "external_openai_compatible"),
        "model": os.environ.get("JARVIS_DEEP_LLM_MODEL", "nemotron-ultra-120b"),
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
        "adapter_type": "local_llm_fallback",
        "cost_class": "local",
        "requires_approval": False,
        "execution_requires_approval": True,
        "tools": ["tasks.local_proposal"],
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
        "adapter_type": "local_llm_fallback",
        "cost_class": "local",
        "requires_approval": False,
        "execution_requires_approval": True,
        "tools": ["contacts.local_proposal"],
        "description": "Find, create, update, or summarize contact information.",
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
    return " ".join(
        str(payload.get(key, ""))
        for key in ("request", "instruction", "prompt", "goal", "natural_language")
    ).strip()


def route_with_keywords(payload):
    text = request_text(payload).lower()

    routes = [
        (("repo", "code", "commit", "pull request", "github", "branch", "test", "lint"), "edit_repository"),
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


def route_with_ollama(payload):
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
            "You are a strict routing classifier for a personal homelab assistant. "
            "Choose exactly one capability from the provided catalog. "
            "Return only compact JSON with keys capability, confidence, rationale. "
            "Use general_assistant for ordinary chat, drafting, brainstorming, planning, or unclear requests."
        ),
    }
    user = {
        "role": "user",
        "content": json.dumps(
            {
                "catalog": catalog,
                "request": request_text(payload),
                "explicit_inputs": payload.get("inputs") or {},
            },
            separators=(",", ":"),
        ),
    }
    body = json.dumps(
        {
            "model": OLLAMA_ROUTER_MODEL,
            "messages": [prompt, user],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0, "num_predict": 160},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL + "/api/chat",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=OLLAMA_ROUTER_TIMEOUT) as response:
        data = json.loads(response.read().decode("utf-8") or "{}")
    content = data.get("message", {}).get("content", "")
    routed = parse_json_object(content)
    capability_name = routed.get("capability")
    if capability_name not in names:
        raise ValueError(f"unknown capability: {capability_name}")
    return capability_by_name(capability_name), {
        "router": "ollama",
        "model": OLLAMA_ROUTER_MODEL,
        "confidence": routed.get("confidence"),
        "rationale": str(routed.get("rationale", ""))[:500],
    }


def route_request(payload):
    requested = payload.get("capability") or payload.get("requested_capability")
    if requested:
        matched = capability_by_name(str(requested))
        if matched:
            return matched, {
                "router": "explicit",
                "rationale": f"Request specified capability {matched['capability']}.",
            }

    if OLLAMA_ROUTER_ENABLED and request_text(payload):
        try:
            return route_with_ollama(payload)
        except Exception as exc:
            capability, metadata = route_with_keywords(payload)
            metadata["fallback_from"] = "ollama"
            metadata["fallback_error"] = str(exc)[:300]
            return capability, metadata

    return route_with_keywords(payload)


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
    messages = [
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


def google_tools_result(action):
    inputs = action.get("inputs", {}) or {}
    request = inputs.get("request", "")
    google_payload = {
        "request": request,
        "conversation_context": inputs.get("conversation_context") or [],
    }
    if action.get("capability") == "manage_email":
        data = call_google_tools("/gmail/assist", {**google_payload, "max_results": 10})
        return {
            "request_id": action["request_id"],
            "tool": action["tool"],
            "status": "completed",
            "summary": "Fetched Gmail results from Google Tools.",
            "text": data.get("text") or "Fetched Gmail results.",
            "artifacts": [{"type": "gmail_messages", "items": data.get("messages", [])}],
            "cost": {"estimated_usd": 0},
            "next_actions": [],
        }
    if action.get("capability") == "manage_calendar":
        data = call_google_tools("/calendar/assist", google_payload)
        artifacts = []
        if data.get("event"):
            artifacts.append({"type": "calendar_event", "item": data.get("event")})
        else:
            artifacts.append({"type": "calendar_events", "items": data.get("events", [])})
        return {
            "request_id": action["request_id"],
            "tool": action["tool"],
            "status": "completed",
            "summary": "Fetched Calendar results from Google Tools.",
            "text": data.get("text") or "Fetched Calendar results.",
            "artifacts": artifacts,
            "cost": {"estimated_usd": 0},
            "next_actions": [],
        }
    raise ValueError("unsupported_google_tools_capability")


def google_request_requires_approval(payload, capability):
    if capability["capability"] not in {"manage_email", "manage_calendar"}:
        return capability["execution_requires_approval"]
    text = request_text(payload).lower()
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


def fallback_system_prompt(action):
    if action["worker"] == "llm_worker":
        return (
            "You are Jarvis, a concise personal homelab assistant. "
            "Be practical, friendly, and direct. If the user asks for a draft, produce the draft."
        )
    return (
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

    profile = action.get("execution_profile", {})
    model = profile.get("model") or OLLAMA_ROUTER_MODEL
    if profile.get("provider") != "ollama":
        model = LLM_PROFILES["local"]["model"]
    answer = call_ollama_assistant(fallback_prompt(action), model, fallback_system_prompt(action))
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
                        "timeout_seconds": OLLAMA_ROUTER_TIMEOUT,
                    },
                },
            )
            return

        if path == "/capabilities":
            self.write_json(HTTPStatus.OK, {"ok": True, "capabilities": CAPABILITIES})
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

            capability, route = route_request(payload)
            request_id = payload.get("request_id") or f"req-{uuid.uuid4().hex[:12]}"
            action = make_action(request_id, payload, capability)
            request = {
                "request_id": request_id,
                "status": "planned",
                "created_at": now(),
                "capability": capability["capability"],
                "worker": capability["worker"],
                "summary": f"Routed request to {capability['capability']} via {capability['worker']}.",
                "route": route,
                "original": payload,
                "next_actions": [
                    {
                        "action_id": action["action_id"],
                        "tool": action["tool"],
                        "authorization": "approved"
                        if action["status"] == "approved"
                        else "approval_required",
                    }
                ],
            }
            state = load_state()
            state["requests"][request_id] = request
            state["actions"][action["action_id"]] = action
            save_state(state)
            self.write_json(
                HTTPStatus.ACCEPTED,
                {"ok": True, "request": request, "actions": [action]},
            )
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
