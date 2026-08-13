#!/usr/bin/env python3
import json
import os
import urllib.error
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = "0.0.0.0"
PORT = int(os.environ.get("JARVIS_OPENWEBUI_TOOLS_PORT", "18400"))
ORCHESTRATOR_URL = os.environ.get("AI_ORCHESTRATOR_URL", "http://ai-orchestrator:8095").rstrip("/")
ORCHESTRATOR_TOKEN = os.environ.get("AI_ORCHESTRATOR_TOKEN", "")
JARVIS_CORE_URL = os.environ.get("JARVIS_CORE_URL", "http://jarvis-core:8097").rstrip("/")
JARVIS_CORE_TOKEN = os.environ.get("JARVIS_CORE_TOKEN", ORCHESTRATOR_TOKEN)
DEFAULT_RUNTIME_SECONDS = int(os.environ.get("JARVIS_OPENWEBUI_DEFAULT_RUNTIME_SECONDS", "1800"))
DEFAULT_COST_USD = float(os.environ.get("JARVIS_OPENWEBUI_DEFAULT_COST_USD", "0"))


def json_response(handler, status, payload):
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(raw)))
    handler.end_headers()
    handler.wfile.write(raw)


def read_json(handler):
    length = int(handler.headers.get("Content-Length", "0") or "0")
    raw = handler.rfile.read(length) if length else b"{}"
    return json.loads(raw.decode("utf-8") or "{}")


def orchestrator_headers():
    headers = {"Content-Type": "application/json"}
    if ORCHESTRATOR_TOKEN:
        headers["Authorization"] = f"Bearer {ORCHESTRATOR_TOKEN}"
    return headers


def call_orchestrator(method, path, payload=None, timeout=240):
    body = json.dumps(payload or {}).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        ORCHESTRATOR_URL + path,
        data=body,
        method=method,
        headers=orchestrator_headers(),
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8") or "{}"
            return response.status, json.loads(raw)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8") or "{}"
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {"ok": False, "error": raw or str(exc)}
        return exc.code, data


def core_headers():
    headers = {"Content-Type": "application/json"}
    if JARVIS_CORE_TOKEN:
        headers["Authorization"] = f"Bearer {JARVIS_CORE_TOKEN}"
    return headers


def call_core(method, path, payload=None, timeout=240):
    body = json.dumps(payload or {}).encode("utf-8") if method in {"POST", "PATCH"} else None
    req = urllib.request.Request(JARVIS_CORE_URL + path, data=body, method=method, headers=core_headers())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8") or "{}"
            return response.status, json.loads(raw)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8") or "{}"
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {"ok": False, "error": raw or str(exc)}
        return exc.code, data


def summarize_action(action):
    result = action.get("result") or {}
    return {
        "action_id": action.get("action_id"),
        "request_id": action.get("request_id"),
        "capability": action.get("capability"),
        "worker": action.get("worker"),
        "tool": action.get("tool"),
        "status": action.get("status"),
        "requires_approval": action.get("requires_approval"),
        "workflow_level": action.get("workflow_level"),
        "summary": result.get("summary") or action.get("summary"),
        "text": result.get("text") or result.get("summary") or "",
        "artifacts": result.get("artifacts") or [],
    }


def planned_response(planned, executed=None):
    request = planned.get("request") or {}
    actions = planned.get("actions") or []
    action = actions[0] if actions else {}
    executed_actions = executed.get("actions") if isinstance(executed, dict) else None
    response = {
        "ok": planned.get("ok", False),
        "request_id": request.get("request_id"),
        "request_status": request.get("status"),
        "capability": request.get("capability"),
        "worker": request.get("worker"),
        "route": request.get("route"),
        "authorization": (request.get("next_actions") or [{}])[0].get("authorization"),
        "action": summarize_action(action),
        "actions": [summarize_action(item) for item in (executed_actions or actions)],
        "message": request.get("summary") or "Jarvis created an action.",
    }
    if executed_actions:
        response["request_status"] = executed.get("request_status") or response["request_status"]
        messages = []
        approval = []
        for item in executed_actions:
            summary = summarize_action(item)
            if summary.get("requires_approval") or item.get("status") == "awaiting_approval":
                approval.append(summary.get("action_id"))
            elif summary.get("text"):
                messages.append(summary["text"])
        if approval:
            messages.append("Approval required for: " + ", ".join(approval))
        response["message"] = "\n\n".join(messages) or response["message"]
    elif executed:
        executed_action = (executed.get("action") or {})
        response["request_status"] = executed_action.get("status") or response["request_status"]
        response["action"] = summarize_action(executed_action)
        result = executed_action.get("result") or {}
        response["message"] = result.get("text") or result.get("summary") or response["message"]
    elif action.get("requires_approval") or not action.get("permissions", {}).get("may_execute"):
        response["message"] = (
            "Approval required before Jarvis executes this action. "
            f"Ask me to approve action {action.get('action_id')} when ready."
        )
    return response


def jarvis_request(payload):
    request_text = str(payload.get("request") or payload.get("message") or "").strip()
    if not request_text:
        return HTTPStatus.BAD_REQUEST, {"ok": False, "error": "request is required"}
    body = {
        "request": request_text,
        "source": "open-webui",
        "capability": payload.get("capability") or "",
        "inputs": payload.get("inputs") or {},
        "limits": {
            "maximum_runtime_seconds": payload.get("maximum_runtime_seconds", DEFAULT_RUNTIME_SECONDS),
            "maximum_cost_usd": payload.get("maximum_cost_usd", DEFAULT_COST_USD),
        },
        "permissions": {"may_execute": False, "may_publish": False},
    }
    if not body["capability"]:
        body.pop("capability")
    status, planned = call_orchestrator("POST", "/requests", body, timeout=240)
    if status >= 400:
        return status, planned
    executed_actions = []
    for action in planned.get("actions") or []:
        if action.get("permissions", {}).get("may_execute"):
            execute_status, executed = call_orchestrator(
                "POST",
                f"/actions/{action['action_id']}/execute",
                {},
                timeout=int(body["limits"]["maximum_runtime_seconds"]) + 30,
            )
            if execute_status >= 400:
                return execute_status, executed
            executed_actions.append(executed.get("action") or action)
        else:
            executed_actions.append(action)
    return HTTPStatus.OK, planned_response(planned, {"actions": executed_actions})


def jarvis_core_capture(payload):
    text = str(payload.get("text") or payload.get("request") or "").strip()
    if not text:
        return HTTPStatus.BAD_REQUEST, {"ok": False, "error": "text is required"}
    return call_core("POST", "/api/v1/capture", {"text": text, "idempotency_key": payload.get("idempotency_key")}, timeout=120)


def jarvis_core_daily_brief(payload):
    kind = str(payload.get("kind") or "morning").strip().lower()
    save = "true" if payload.get("save", True) else "false"
    return call_core("GET", f"/api/v1/daily-brief?kind={kind}&save={save}", None, timeout=240)


def jarvis_core_diagnostics(payload):
    return call_core("GET", "/api/v1/homelab/diagnostics", None, timeout=60)


def jarvis_core_media_automations(payload):
    return call_core("GET", "/api/v1/media/automations/status", None, timeout=60)


def jarvis_core_drive_inventory(payload):
    return call_core("POST", "/api/v1/drive/inventory", payload or {}, timeout=120)


def jarvis_core_drive_migration_plan(payload):
    return call_core("POST", "/api/v1/drive/migration-plan", payload or {}, timeout=120)


def jarvis_core_drive_folders(payload):
    return call_core("POST", "/api/v1/drive/folders", payload or {}, timeout=120)


def jarvis_core_drive_staging_copy_propose(payload):
    return call_core("POST", "/api/v1/drive/staging-copy/propose", payload or {}, timeout=120)


def jarvis_core_drive_staging_status(payload):
    return call_core("POST", "/api/v1/drive/staging-status", payload or {}, timeout=120)


def jarvis_core_codex_task(payload):
    request_text = str(payload.get("request") or "").strip()
    if not request_text:
        return HTTPStatus.BAD_REQUEST, {"ok": False, "error": "request is required"}
    return call_core("POST", "/api/v1/codex/tasks", {"request": request_text, "idempotency_key": payload.get("idempotency_key")}, timeout=120)


def jarvis_core_codex_dashboard(payload):
    status = str(payload.get("status") or "").strip()
    suffix = f"?status={status}" if status else ""
    return call_core("GET", "/api/v1/codex/tasks" + suffix, None, timeout=120)


def jarvis_core_list(payload, resource):
    query = ""
    if resource in {"approvals", "executions", "audit"}:
        params = []
        for key in ("status", "q", "event_type", "tool_name"):
            if payload.get(key):
                import urllib.parse

                params.append(f"{key}={urllib.parse.quote(str(payload[key]))}")
        query = "?" + "&".join(params) if params else ""
    return call_core("GET", f"/api/v1/{resource}{query}", None, timeout=120)


def jarvis_core_daily_brief_action(payload):
    return call_core("POST", "/api/v1/daily-brief/actions", payload, timeout=120)


def jarvis_core_approve_by_title(payload):
    import urllib.parse

    q = str(payload.get("q") or payload.get("title") or "").strip()
    if not q:
        return HTTPStatus.BAD_REQUEST, {"ok": False, "error": "q is required"}
    approved = bool(payload.get("approved", True))
    return call_core("POST", f"/api/v1/approvals/decide-by-title?q={urllib.parse.quote(q)}", {"approved": approved, "decided_by": "open-webui"}, timeout=240)


def jarvis_get_request(payload):
    request_id = str(payload.get("request_id") or "").strip()
    if not request_id:
        return HTTPStatus.BAD_REQUEST, {"ok": False, "error": "request_id is required"}
    status, data = call_orchestrator("GET", f"/requests/{request_id}", None, timeout=60)
    return status, data


def jarvis_approve_action(payload):
    action_id = str(payload.get("action_id") or "").strip()
    if not action_id:
        return HTTPStatus.BAD_REQUEST, {"ok": False, "error": "action_id is required"}
    status, approved = call_orchestrator("POST", f"/actions/{action_id}/approve", {}, timeout=60)
    if status >= 400:
        return status, approved
    status, executed = call_orchestrator("POST", f"/actions/{action_id}/execute", {}, timeout=DEFAULT_RUNTIME_SECONDS + 30)
    if status >= 400:
        return status, executed
    action = executed.get("action") or {}
    result = action.get("result") or {}
    return HTTPStatus.OK, {
        "ok": True,
        "action": summarize_action(action),
        "message": result.get("text") or result.get("summary") or "Approved and executed.",
    }


def capabilities():
    return call_orchestrator("GET", "/capabilities", None, timeout=60)


def bridge_health():
    status, data = call_orchestrator("GET", "/health", None, timeout=30)
    core_status, core_data = call_core("GET", "/api/v1/health", None, timeout=30)
    return HTTPStatus.OK, {
        "ok": status < 400 and data.get("ok") is True and core_status < 400 and core_data.get("ok") is True,
        "service": "jarvis-openwebui-tools",
        "orchestrator_status": status,
        "orchestrator": data,
        "core_status": core_status,
        "core": core_data,
    }


def openapi_schema():
    return {
        "openapi": "3.1.0",
        "info": {"title": "Jarvis Open WebUI Tools", "version": "1.0.0"},
        "servers": [{"url": "http://jarvis-openwebui-tools:18400"}],
        "paths": {
            "/jarvis/request": {
                "post": {
                    "operationId": "jarvis_request",
                    "summary": "Submit a natural-language request to Jarvis Core.",
                    "requestBody": {"required": True, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/JarvisRequest"}}}},
                    "responses": {"200": {"description": "Jarvis action result or approval request."}},
                }
            },
            "/jarvis/request/status": {
                "post": {
                    "operationId": "jarvis_get_request",
                    "summary": "Fetch a Jarvis request and its actions.",
                    "requestBody": {"required": True, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/JarvisRequestStatus"}}}},
                    "responses": {"200": {"description": "Request status."}},
                }
            },
            "/jarvis/action/approve": {
                "post": {
                    "operationId": "jarvis_approve_action",
                    "summary": "Approve and execute a Jarvis action.",
                    "requestBody": {"required": True, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/JarvisApproveAction"}}}},
                    "responses": {"200": {"description": "Executed action result."}},
                }
            },
            "/jarvis/capabilities": {"get": {"operationId": "jarvis_capabilities", "summary": "List Jarvis capabilities.", "responses": {"200": {"description": "Capabilities."}}}},
            "/jarvis/core/capture": {
                "post": {
                    "operationId": "jarvis_core_capture",
                    "summary": "Capture a task, evidence note, maintenance note, or calendar request in Jarvis Core.",
                    "requestBody": {"required": True, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/JarvisCoreCapture"}}}},
                    "responses": {"200": {"description": "Captured Core item."}},
                }
            },
            "/jarvis/core/daily-brief": {
                "post": {
                    "operationId": "jarvis_core_daily_brief",
                    "summary": "Build a deterministic Jarvis Core daily brief using real Google services and Core state.",
                    "requestBody": {"required": False, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/JarvisDailyBrief"}}}},
                    "responses": {"200": {"description": "Daily brief."}},
                }
            },
            "/jarvis/core/homelab-diagnostics": {
                "post": {
                    "operationId": "jarvis_core_homelab_diagnostics",
                    "summary": "Run read-only allowlisted homelab service health diagnostics.",
                    "requestBody": {"required": False, "content": {"application/json": {"schema": {"type": "object", "additionalProperties": True}}}},
                    "responses": {"200": {"description": "Diagnostics."}},
                }
            },
            "/jarvis/core/media-automations": {
                "post": {
                    "operationId": "jarvis_core_media_automations",
                    "summary": "Run read-only media automation stack reachability checks for Prowlarr, Bazarr, Sonarr, Radarr, Lidarr, Readarr, and qBittorrent.",
                    "requestBody": {"required": False, "content": {"application/json": {"schema": {"type": "object", "additionalProperties": True}}}},
                    "responses": {"200": {"description": "Media automation status."}},
                }
            },
            "/jarvis/core/drive-inventory": {
                "post": {
                    "operationId": "jarvis_core_drive_inventory",
                    "summary": "Create a metadata-only Google Drive inventory for de-Google migration planning.",
                    "requestBody": {"required": False, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/JarvisDriveInventory"}}}},
                    "responses": {"200": {"description": "Drive inventory."}},
                }
            },
            "/jarvis/core/drive-migration-plan": {
                "post": {
                    "operationId": "jarvis_core_drive_migration_plan",
                    "summary": "Create a metadata-only Google Drive migration plan with suggested homelab destinations. Does not download files.",
                    "requestBody": {"required": False, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/JarvisDriveInventory"}}}},
                    "responses": {"200": {"description": "Drive migration plan."}},
                }
            },
            "/jarvis/core/drive-folders": {
                "post": {
                    "operationId": "jarvis_core_drive_folders",
                    "summary": "List Google Drive folders for choosing safe migration scopes. Metadata-only and excludes blocked names by default.",
                    "requestBody": {"required": False, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/JarvisDriveInventory"}}}},
                    "responses": {"200": {"description": "Drive folder list."}},
                }
            },
            "/jarvis/core/drive-staging-copy-propose": {
                "post": {
                    "operationId": "jarvis_core_drive_staging_copy_propose",
                    "summary": "Propose an approval-gated copy-only Google Drive batch into homelab staging. Does not execute until approved.",
                    "requestBody": {"required": False, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/JarvisDriveStagingCopy"}}}},
                    "responses": {"200": {"description": "Drive staging copy proposal."}},
                }
            },
            "/jarvis/core/drive-staging-status": {
                "post": {
                    "operationId": "jarvis_core_drive_staging_status",
                    "summary": "List copied Google Drive staging manifests and local copy status. Read-only.",
                    "requestBody": {"required": False, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/JarvisDriveInventory"}}}},
                    "responses": {"200": {"description": "Drive staging status."}},
                }
            },
            "/jarvis/core/codex-task": {
                "post": {
                    "operationId": "jarvis_core_codex_task",
                    "summary": "Create an approval-gated Codex coding task in Jarvis Core.",
                    "requestBody": {"required": True, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/JarvisCodexTask"}}}},
                    "responses": {"200": {"description": "Approval-gated Codex task proposal."}},
                }
            },
            "/jarvis/core/codex-dashboard": {
                "post": {
                    "operationId": "jarvis_core_codex_dashboard",
                    "summary": "List proposed, running, completed, and failed Codex tasks with worker artifacts.",
                    "requestBody": {"required": False, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/JarvisStatusFilter"}}}},
                    "responses": {"200": {"description": "Codex task dashboard."}},
                }
            },
            "/jarvis/core/approvals": {"post": {"operationId": "jarvis_core_approvals", "summary": "List or search Jarvis Core approvals.", "requestBody": {"required": False, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/JarvisSearchFilter"}}}}, "responses": {"200": {"description": "Approvals."}}}},
            "/jarvis/core/approve-by-title": {"post": {"operationId": "jarvis_core_approve_by_title", "summary": "Approve one pending Jarvis Core action by title or matching text.", "requestBody": {"required": True, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/JarvisApproveByTitle"}}}}, "responses": {"200": {"description": "Approval decision."}}}},
            "/jarvis/core/projects": {"post": {"operationId": "jarvis_core_projects", "summary": "List Jarvis Core projects.", "requestBody": {"required": False, "content": {"application/json": {"schema": {"type": "object", "additionalProperties": True}}}}, "responses": {"200": {"description": "Projects."}}}},
            "/jarvis/core/tasks": {"post": {"operationId": "jarvis_core_tasks", "summary": "List Jarvis Core tasks.", "requestBody": {"required": False, "content": {"application/json": {"schema": {"type": "object", "additionalProperties": True}}}}, "responses": {"200": {"description": "Tasks."}}}},
            "/jarvis/core/evidence": {"post": {"operationId": "jarvis_core_evidence", "summary": "List Jarvis Core evidence records.", "requestBody": {"required": False, "content": {"application/json": {"schema": {"type": "object", "additionalProperties": True}}}}, "responses": {"200": {"description": "Evidence."}}}},
            "/jarvis/core/maintenance": {"post": {"operationId": "jarvis_core_maintenance", "summary": "List Jarvis Core maintenance records.", "requestBody": {"required": False, "content": {"application/json": {"schema": {"type": "object", "additionalProperties": True}}}}, "responses": {"200": {"description": "Maintenance."}}}},
            "/jarvis/core/executions": {"post": {"operationId": "jarvis_core_executions", "summary": "List Jarvis Core executions.", "requestBody": {"required": False, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/JarvisExecutionFilter"}}}}, "responses": {"200": {"description": "Executions."}}}},
            "/jarvis/core/audit": {"post": {"operationId": "jarvis_core_audit", "summary": "Search Jarvis Core audit events.", "requestBody": {"required": False, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/JarvisAuditFilter"}}}}, "responses": {"200": {"description": "Audit events."}}}},
            "/jarvis/core/daily-brief-action": {"post": {"operationId": "jarvis_core_daily_brief_action", "summary": "Turn a daily brief recommendation into a task or approval-gated calendar hold.", "requestBody": {"required": True, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/JarvisDailyBriefAction"}}}}, "responses": {"200": {"description": "Created action."}}}},
            "/health": {"get": {"operationId": "jarvis_health", "summary": "Check Jarvis bridge and core health.", "responses": {"200": {"description": "Health."}}}},
        },
        "components": {
            "schemas": {
                "JarvisRequest": {
                    "type": "object",
                    "properties": {
                        "request": {"type": "string", "description": "Natural-language user request."},
                        "capability": {"type": "string", "description": "Optional Jarvis capability override."},
                        "inputs": {"type": "object", "additionalProperties": True},
                        "maximum_runtime_seconds": {"type": "integer", "default": DEFAULT_RUNTIME_SECONDS},
                        "maximum_cost_usd": {"type": "number", "default": DEFAULT_COST_USD},
                    },
                    "required": ["request"],
                },
                "JarvisRequestStatus": {"type": "object", "properties": {"request_id": {"type": "string"}}, "required": ["request_id"]},
                "JarvisApproveAction": {"type": "object", "properties": {"action_id": {"type": "string"}}, "required": ["action_id"]},
                "JarvisCoreCapture": {"type": "object", "properties": {"text": {"type": "string"}, "request": {"type": "string"}, "idempotency_key": {"type": "string"}}, "required": []},
                "JarvisDailyBrief": {"type": "object", "properties": {"kind": {"type": "string", "enum": ["morning", "evening"], "default": "morning"}, "save": {"type": "boolean", "default": True}}},
                "JarvisDriveInventory": {"type": "object", "properties": {"query": {"type": "string", "default": "trashed = false"}, "max_results": {"type": "integer", "default": 1000, "minimum": 1, "maximum": 1000}, "include_folder_ids": {"type": "array", "items": {"type": "string"}}, "exclude_names": {"type": "array", "items": {"type": "string"}, "default": ["griproot"]}}},
                "JarvisDriveStagingCopy": {"type": "object", "properties": {"query": {"type": "string", "default": "trashed = false"}, "max_results": {"type": "integer", "default": 3, "minimum": 1, "maximum": 100}, "file_ids": {"type": "array", "items": {"type": "string"}}, "include_folder_ids": {"type": "array", "items": {"type": "string"}}, "exclude_names": {"type": "array", "items": {"type": "string"}, "default": ["griproot"]}, "category": {"type": "string"}, "migration_action": {"type": "string", "enum": ["copy_to_homelab", "keep_in_google", "archive", "needs_review"], "default": "copy_to_homelab"}, "idempotency_key": {"type": "string"}}},
                "JarvisCodexTask": {"type": "object", "properties": {"request": {"type": "string"}, "idempotency_key": {"type": "string"}}, "required": ["request"]},
                "JarvisStatusFilter": {"type": "object", "properties": {"status": {"type": "string"}}},
                "JarvisSearchFilter": {"type": "object", "properties": {"status": {"type": "string"}, "q": {"type": "string"}}},
                "JarvisExecutionFilter": {"type": "object", "properties": {"status": {"type": "string"}, "tool_name": {"type": "string"}}},
                "JarvisAuditFilter": {"type": "object", "properties": {"q": {"type": "string"}, "event_type": {"type": "string"}}},
                "JarvisApproveByTitle": {"type": "object", "properties": {"q": {"type": "string"}, "title": {"type": "string"}, "approved": {"type": "boolean", "default": True}}, "required": []},
                "JarvisDailyBriefAction": {"type": "object", "properties": {"title": {"type": "string"}, "action_type": {"type": "string", "enum": ["task", "calendar_hold"], "default": "task"}, "priority": {"type": "integer", "default": 3}, "estimated_minutes": {"type": "integer"}, "when_text": {"type": "string"}, "idempotency_key": {"type": "string"}}, "required": ["title"]},
            }
        },
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "jarvis-openwebui-tools/1.0"

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args), flush=True)

    def do_GET(self):
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path == "/openapi.json":
            json_response(self, HTTPStatus.OK, openapi_schema())
            return
        if path == "/health":
            status, data = bridge_health()
            json_response(self, status, data)
            return
        if path == "/jarvis/capabilities":
            status, data = capabilities()
            json_response(self, status, data)
            return
        json_response(self, HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})

    def do_POST(self):
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        try:
            payload = read_json(self)
        except Exception as exc:
            json_response(self, HTTPStatus.BAD_REQUEST, {"ok": False, "error": f"invalid_json: {exc}"})
            return
        routes = {
            "/jarvis/request": jarvis_request,
            "/jarvis/request/status": jarvis_get_request,
            "/jarvis/action/approve": jarvis_approve_action,
            "/jarvis/core/capture": jarvis_core_capture,
            "/jarvis/core/daily-brief": jarvis_core_daily_brief,
            "/jarvis/core/homelab-diagnostics": jarvis_core_diagnostics,
            "/jarvis/core/media-automations": jarvis_core_media_automations,
            "/jarvis/core/drive-inventory": jarvis_core_drive_inventory,
            "/jarvis/core/drive-migration-plan": jarvis_core_drive_migration_plan,
            "/jarvis/core/drive-folders": jarvis_core_drive_folders,
            "/jarvis/core/drive-staging-copy-propose": jarvis_core_drive_staging_copy_propose,
            "/jarvis/core/drive-staging-status": jarvis_core_drive_staging_status,
            "/jarvis/core/codex-task": jarvis_core_codex_task,
            "/jarvis/core/codex-dashboard": jarvis_core_codex_dashboard,
            "/jarvis/core/approvals": lambda payload: jarvis_core_list(payload, "approvals"),
            "/jarvis/core/approve-by-title": jarvis_core_approve_by_title,
            "/jarvis/core/projects": lambda payload: jarvis_core_list(payload, "projects"),
            "/jarvis/core/tasks": lambda payload: jarvis_core_list(payload, "tasks"),
            "/jarvis/core/evidence": lambda payload: jarvis_core_list(payload, "evidence"),
            "/jarvis/core/maintenance": lambda payload: jarvis_core_list(payload, "maintenance"),
            "/jarvis/core/executions": lambda payload: jarvis_core_list(payload, "executions"),
            "/jarvis/core/audit": lambda payload: jarvis_core_list(payload, "audit"),
            "/jarvis/core/daily-brief-action": jarvis_core_daily_brief_action,
        }
        handler = routes.get(path)
        if not handler:
            json_response(self, HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})
            return
        status, data = handler(payload)
        json_response(self, status, data)


def main():
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Jarvis Open WebUI tools listening on {HOST}:{PORT}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
