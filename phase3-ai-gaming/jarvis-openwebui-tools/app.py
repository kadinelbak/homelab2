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
    return HTTPStatus.OK, {
        "ok": status < 400 and data.get("ok") is True,
        "service": "jarvis-openwebui-tools",
        "orchestrator_status": status,
        "orchestrator": data,
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
