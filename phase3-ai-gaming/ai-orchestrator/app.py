#!/usr/bin/env python3
import json
import os
import time
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

TOKEN = os.environ.get("AI_ORCHESTRATOR_TOKEN", "")
HOST = os.environ.get("AI_ORCHESTRATOR_HOST", "0.0.0.0")
PORT = int(os.environ.get("AI_ORCHESTRATOR_PORT", "8095"))
DATA_DIR = Path(os.environ.get("AI_ORCHESTRATOR_DATA_DIR", "/data"))
STATE_PATH = DATA_DIR / "requests.json"

CAPABILITIES = [
    {
        "capability": "edit_repository",
        "worker": "coding_worker",
        "adapter_type": "cli_worker",
        "cost_class": "metered",
        "requires_approval": False,
        "execution_requires_approval": True,
        "tools": ["codex_cli", "opencode", "aider"],
    },
    {
        "capability": "generate_3d_concept",
        "worker": "meshy",
        "adapter_type": "rest_api",
        "cost_class": "paid",
        "requires_approval": True,
        "execution_requires_approval": True,
        "tools": ["meshy.text_to_3d", "meshy.image_to_3d"],
    },
    {
        "capability": "generate_parametric_part",
        "worker": "cad_worker",
        "adapter_type": "local_application",
        "cost_class": "local",
        "requires_approval": False,
        "execution_requires_approval": True,
        "tools": ["cadquery.generate", "openscad.render", "blender.preview"],
    },
    {
        "capability": "manage_smart_home",
        "worker": "homeassistant",
        "adapter_type": "rest_api",
        "cost_class": "local",
        "requires_approval": True,
        "execution_requires_approval": True,
        "tools": ["homeassistant.call_service"],
    },
    {
        "capability": "organize_media",
        "worker": "media_adapter",
        "adapter_type": "rest_api",
        "cost_class": "local",
        "requires_approval": True,
        "execution_requires_approval": True,
        "tools": ["radarr.add_movie", "sonarr.add_series", "paperless.search"],
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


def route_request(payload):
    requested = payload.get("capability") or payload.get("requested_capability")
    if requested:
        matched = capability_by_name(str(requested))
        if matched:
            return matched

    text = " ".join(
        str(payload.get(key, ""))
        for key in ("request", "instruction", "prompt", "goal", "natural_language")
    ).lower()

    routes = [
        (("repo", "code", "commit", "pull request", "github", "branch"), "edit_repository"),
        (("3d", "meshy", "model", "glb", "obj"), "generate_3d_concept"),
        (("cad", "step", "stl", "openscad", "cadquery", "parametric"), "generate_parametric_part"),
        (("light", "thermostat", "home assistant", "smart home", "scene"), "manage_smart_home"),
        (("movie", "series", "paperless", "document", "radarr", "sonarr"), "organize_media"),
    ]
    for keywords, capability in routes:
        if any(keyword in text for keyword in keywords):
            return capability_by_name(capability)

    return capability_by_name("edit_repository")


def make_action(request_id, payload, capability):
    action_id = f"act-{uuid.uuid4().hex[:12]}"
    permissions = payload.get("permissions") or {}
    limits = payload.get("limits") or {}
    requires_approval = capability["execution_requires_approval"]
    may_execute = bool(permissions.get("may_execute", not requires_approval))

    return {
        "action_id": action_id,
        "request_id": request_id,
        "tool": capability["tools"][0],
        "worker": capability["worker"],
        "adapter_type": capability["adapter_type"],
        "status": "approved" if may_execute else "awaiting_approval",
        "requires_approval": requires_approval,
        "created_at": now(),
        "approved_at": now() if may_execute else None,
        "inputs": payload.get("inputs") or {
            "request": payload.get("request")
            or payload.get("instruction")
            or payload.get("prompt")
            or payload.get("goal")
            or payload.get("natural_language")
            or ""
        },
        "limits": {
            "maximum_cost_usd": limits.get("maximum_cost_usd", 0),
            "maximum_runtime_seconds": limits.get("maximum_runtime_seconds", 1800),
        },
        "permissions": {
            "may_execute": may_execute,
            "may_publish": bool(permissions.get("may_publish", False)),
        },
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

            capability = route_request(payload)
            request_id = payload.get("request_id") or f"req-{uuid.uuid4().hex[:12]}"
            action = make_action(request_id, payload, capability)
            request = {
                "request_id": request_id,
                "status": "planned",
                "created_at": now(),
                "capability": capability["capability"],
                "worker": capability["worker"],
                "summary": f"Routed request to {capability['capability']} via {capability['worker']}.",
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

            action["status"] = "queued_for_worker"
            action["result"] = {
                "request_id": action["request_id"],
                "tool": action["tool"],
                "status": "queued_for_worker",
                "summary": "Action contract is approved and ready for the dedicated worker adapter.",
                "artifacts": [],
                "cost": {"estimated_usd": 0},
                "next_actions": [],
            }
            state["requests"][action["request_id"]]["status"] = "action_queued"
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
