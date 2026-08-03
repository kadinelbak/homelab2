#!/usr/bin/env python3
import html
import json
import os
import urllib.error
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

HOST = os.environ.get("JARVIS_CHAT_HOST", "0.0.0.0")
PORT = int(os.environ.get("JARVIS_CHAT_PORT", "8096"))
ORCHESTRATOR_URL = os.environ.get("AI_ORCHESTRATOR_URL", "http://ai-orchestrator:8095").rstrip("/")
ORCHESTRATOR_TOKEN = os.environ.get("AI_ORCHESTRATOR_TOKEN", "")
WHISPER_WORKER_URL = os.environ.get("WHISPER_WORKER_URL", "http://whisper-worker:8099").rstrip("/")
WHISPER_WORKER_TOKEN = os.environ.get("WHISPER_WORKER_TOKEN", "")
TTS_WORKER_URL = os.environ.get("JARVIS_TTS_WORKER_URL", "http://tts-worker:8101").rstrip("/")
TTS_WORKER_TOKEN = os.environ.get("JARVIS_TTS_TOKEN", "")
TTS_VOICE = os.environ.get("JARVIS_TTS_VOICE", "default")
CHAT_TOKEN = os.environ.get("JARVIS_CHAT_TOKEN", "")


def configured_token():
    token = CHAT_TOKEN
    if not token or token.startswith("CHANGE_ME"):
        return ""
    return token


def escape_json(value):
    return html.escape(json.dumps(value), quote=False)


def summarize_voice_plan(planned):
    request = planned.get("request") or {}
    actions = planned.get("actions") or []
    if not actions:
        return request.get("summary") or "Jarvis created a request, but no action was returned."
    approval = [action for action in actions if action.get("requires_approval") or not action.get("permissions", {}).get("may_execute")]
    if approval:
        names = ", ".join(action.get("capability") or action.get("tool") or "action" for action in approval[:3])
        return f"Approval is required before I can continue with {names}."
    return request.get("summary") or "Jarvis is ready to handle that."


def result_text(data):
    result = (data.get("action") or {}).get("result") or {}
    return result.get("text") or result.get("summary") or data.get("summary") or ""


def page():
    auth_required = bool(configured_token())
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Jarvis Chat</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #0f141b;
      --panel: #161d26;
      --panel2: #1f2935;
      --line: #344150;
      --text: #f5f7fb;
      --muted: #aeb9c7;
      --accent: #5eead4;
      --warn: #fbbf24;
      --danger: #fb7185;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      background: var(--bg);
      color: var(--text);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    main {{
      width: min(960px, calc(100vw - 28px));
      margin: 0 auto;
      padding: 24px 0 40px;
    }}
    header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 18px;
    }}
    h1 {{ margin: 0; font-size: 24px; letter-spacing: 0; }}
    .status {{ color: var(--muted); font-size: 14px; }}
    .panel {{
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 8px;
      padding: 14px;
      margin-bottom: 14px;
    }}
    textarea, input, select {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #0b1017;
      color: var(--text);
      padding: 10px 12px;
      font: inherit;
    }}
    textarea {{ min-height: 120px; resize: vertical; }}
    label {{ display: block; color: var(--muted); font-size: 13px; margin: 0 0 6px; }}
    .grid {{
      display: grid;
      grid-template-columns: 1fr 180px 180px;
      gap: 10px;
      margin-top: 10px;
    }}
    .row {{
      display: flex;
      gap: 10px;
      align-items: center;
      flex-wrap: wrap;
    }}
    button {{
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--panel2);
      color: var(--text);
      padding: 10px 12px;
      cursor: pointer;
      font-weight: 650;
    }}
    button.primary {{ border-color: rgba(94, 234, 212, 0.8); }}
    button.warn {{ border-color: rgba(251, 191, 36, 0.8); }}
    button:disabled {{ opacity: 0.5; cursor: not-allowed; }}
    pre {{
      margin: 0;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      color: #d8dee9;
      font-size: 13px;
      line-height: 1.45;
    }}
    .chat {{
      display: flex;
      flex-direction: column;
      gap: 10px;
      max-height: 420px;
      overflow: auto;
    }}
    .msg {{
      max-width: 86%;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px 12px;
      white-space: pre-wrap;
      line-height: 1.45;
    }}
    .msg.user {{
      align-self: flex-end;
      background: #14302d;
      border-color: rgba(94, 234, 212, 0.45);
    }}
    .msg.jarvis {{
      align-self: flex-start;
      background: var(--panel2);
    }}
    .muted {{ color: var(--muted); }}
    .hidden {{ display: none; }}
    @media (max-width: 760px) {{
      .grid {{ grid-template-columns: 1fr; }}
      header {{ align-items: flex-start; flex-direction: column; }}
      button {{ width: 100%; }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <h1>Jarvis Chat</h1>
        <div class="status" id="health">Checking orchestrator...</div>
      </div>
      <button id="refresh" title="Refresh health and current request">Refresh</button>
    </header>

    <section class="panel {'hidden' if not auth_required else ''}" id="authPanel">
      <label for="token">Access token</label>
      <div class="row">
        <input id="token" type="password" autocomplete="current-password" placeholder="Paste Jarvis token">
        <button id="saveToken">Save</button>
      </div>
    </section>

    <section class="panel">
      <label>Briefing Profile</label>
      <div class="grid">
        <div>
          <label for="profileCity">Current city</label>
          <input id="profileCity" placeholder="Gainesville">
        </div>
        <div>
          <label for="profileRepos">Watched GitHub repos</label>
          <input id="profileRepos" placeholder="owner/repo, owner/another-repo">
        </div>
      </div>
      <label for="profileProjects">Active projects</label>
      <textarea id="profileProjects" placeholder="One active project per line"></textarea>
      <div class="grid">
        <div>
          <label for="profileSenders">Important senders/domains</label>
          <textarea id="profileSenders" placeholder="professor@example.edu&#10;school.edu"></textarea>
        </div>
        <div>
          <label for="profileIgnored">Ignored topics</label>
          <textarea id="profileIgnored" placeholder="newsletter topic&#10;routine alert"></textarea>
        </div>
      </div>
      <label for="profileNote">Add briefing note</label>
      <textarea id="profileNote" placeholder="MCAT is the top project this week"></textarea>
      <div class="row" style="margin-top: 12px;">
        <button id="loadProfile">Load Profile</button>
        <button class="primary" id="saveProfile">Save Profile</button>
        <button id="addProfileNote">Add Note</button>
      </div>
      <pre id="profileRaw" class="muted">Profile not loaded yet.</pre>
    </section>

    <section class="panel">
      <label>Chat</label>
      <div id="chat" class="chat">
        <div class="msg jarvis">Ready. Ask me for a draft, plan, idea, or a homelab action.</div>
      </div>
    </section>

    <section class="panel">
      <label for="request">Request</label>
      <textarea id="request" placeholder="Message Jarvis..."></textarea>
      <div class="grid">
        <div>
          <label for="capability">Capability</label>
          <select id="capability">
            <option value="">Auto route</option>
            <option value="general_assistant">General assistant</option>
            <option value="edit_repository">Edit repository</option>
            <option value="generate_3d_concept">Generate 3D concept</option>
            <option value="generate_parametric_part">Generate parametric part</option>
            <option value="manage_smart_home">Manage smart home</option>
            <option value="organize_media">Organize media/documents</option>
          </select>
        </div>
        <div>
          <label for="runtime">Max runtime seconds</label>
          <input id="runtime" type="number" min="30" step="30" value="1800">
        </div>
        <div>
          <label for="cost">Max cost USD</label>
          <input id="cost" type="number" min="0" step="0.25" value="0">
        </div>
      </div>
      <div class="row" style="margin-top: 12px;">
        <button class="primary" id="send">Send Request</button>
        <button class="warn" id="approve" disabled>Approve Action</button>
        <button id="execute" disabled>Queue Execution</button>
      </div>
      <div class="row" style="margin-top: 12px;">
        <input id="audio" type="file" accept="audio/*,video/*">
        <button id="transcribe">Transcribe Audio</button>
      </div>
    </section>

    <section class="panel">
      <label>Current plan</label>
      <pre id="plan" class="muted">No request sent yet.</pre>
    </section>

    <section class="panel">
      <label>Raw response</label>
      <pre id="raw" class="muted">Waiting.</pre>
    </section>
  </main>

  <script>
    const authRequired = {str(auth_required).lower()};
    const tokenInput = document.getElementById('token');
    const healthEl = document.getElementById('health');
    const planEl = document.getElementById('plan');
    const rawEl = document.getElementById('raw');
    const chatEl = document.getElementById('chat');
    const approveButton = document.getElementById('approve');
    const executeButton = document.getElementById('execute');
    let currentActionId = '';

    function appendMessage(role, text) {{
      const div = document.createElement('div');
      div.className = `msg ${{role}}`;
      div.textContent = text;
      chatEl.appendChild(div);
      chatEl.scrollTop = chatEl.scrollHeight;
    }}

    tokenInput.value = localStorage.getItem('jarvisChatToken') || '';

    function headers() {{
      const h = {{'Content-Type': 'application/json'}};
      const token = tokenInput.value.trim();
      if (token) h.Authorization = `Bearer ${{token}}`;
      return h;
    }}

    function show(data) {{
      rawEl.textContent = JSON.stringify(data, null, 2);
      if (data.actions && data.actions[0]) {{
        const action = data.actions[0];
        currentActionId = action.action_id;
        approveButton.disabled = action.status !== 'awaiting_approval';
        executeButton.disabled = !action.permissions?.may_execute;
        planEl.textContent = [
          `Request: ${{data.request?.request_id || action.request_id}}`,
          `Capability: ${{data.request?.capability || 'unknown'}}`,
          `Worker: ${{action.worker}}`,
          `Tool: ${{action.tool}}`,
          `Status: ${{action.status}}`,
          `Workflow level: ${{action.workflow_level?.level ?? 'unknown'}} - ${{action.workflow_level?.name || 'unknown'}}`,
          `Router: ${{data.request?.route?.router || 'unknown'}}`,
          `Rationale: ${{data.request?.route?.rationale || 'none'}}`,
          `Model profile: ${{action.execution_profile?.profile || 'unknown'}}`,
          `Model: ${{action.execution_profile?.model || 'unknown'}}`,
          `Requested profile: ${{action.execution_profile?.requested_profile || action.execution_profile?.profile || 'unknown'}}`,
          `Profile note: ${{action.execution_profile?.fallback_reason || action.execution_profile?.use_for || 'none'}}`,
          `Action: ${{action.action_id}}`
        ].join('\\n');
      }} else if (data.action) {{
        currentActionId = data.action.action_id;
        approveButton.disabled = data.action.status !== 'awaiting_approval';
        executeButton.disabled = !data.action.permissions?.may_execute || data.action.status === 'queued_for_worker';
        planEl.textContent = [
          `Request: ${{data.action.request_id}}`,
          `Worker: ${{data.action.worker}}`,
          `Tool: ${{data.action.tool}}`,
          `Status: ${{data.action.status}}`,
          `Workflow level: ${{data.action.workflow_level?.level ?? 'unknown'}} - ${{data.action.workflow_level?.name || 'unknown'}}`,
          `Model profile: ${{data.action.execution_profile?.profile || 'unknown'}}`,
          `Model: ${{data.action.execution_profile?.model || 'unknown'}}`,
          `Requested profile: ${{data.action.execution_profile?.requested_profile || data.action.execution_profile?.profile || 'unknown'}}`,
          `Profile note: ${{data.action.execution_profile?.fallback_reason || data.action.execution_profile?.use_for || 'none'}}`,
          `Action: ${{data.action.action_id}}`
        ].join('\\n');
      }}
    }}

    async function call(path, body) {{
      const res = await fetch(path, {{
        method: 'POST',
        headers: headers(),
        body: JSON.stringify(body || {{}})
      }});
      const data = await res.json();
      show(data);
      if (!res.ok) throw new Error(data.error || `HTTP ${{res.status}}`);
      return data;
    }}

    function listValue(id) {{
      return document.getElementById(id).value
        .split(/[\\n,]/)
        .map(item => item.trim())
        .filter(Boolean);
    }}

    function fillProfile(profile) {{
      document.getElementById('profileCity').value = profile.current_city || 'Gainesville';
      document.getElementById('profileRepos').value = (profile.watched_repos || []).join(', ');
      document.getElementById('profileProjects').value = (profile.active_projects || []).join('\\n');
      document.getElementById('profileSenders').value = (profile.important_senders || []).join('\\n');
      document.getElementById('profileIgnored').value = (profile.ignored_topics || []).join('\\n');
      document.getElementById('profileRaw').textContent = JSON.stringify(profile, null, 2);
    }}

    async function loadProfile() {{
      const res = await fetch('/api/profile', {{headers: headers()}});
      const data = await res.json();
      rawEl.textContent = JSON.stringify(data, null, 2);
      if (!res.ok) throw new Error(data.error || `HTTP ${{res.status}}`);
      fillProfile(data.profile || {{}});
    }}

    async function saveProfile() {{
      const updates = {{
        current_city: document.getElementById('profileCity').value.trim() || 'Gainesville',
        watched_repos: listValue('profileRepos'),
        active_projects: listValue('profileProjects'),
        important_senders: listValue('profileSenders'),
        ignored_topics: listValue('profileIgnored')
      }};
      const data = await call('/api/profile', {{updates}});
      fillProfile(data.profile || {{}});
      healthEl.textContent = 'Briefing profile saved.';
    }}

    async function addProfileNote() {{
      const note = document.getElementById('profileNote').value.trim();
      if (!note) return;
      await call('/api/profile/notes', {{operation: 'add', note}});
      document.getElementById('profileNote').value = '';
      await loadProfile();
      healthEl.textContent = 'Briefing note saved.';
    }}

    async function transcribeAudio() {{
      const file = document.getElementById('audio').files[0];
      if (!file) {{
        healthEl.textContent = 'Choose an audio file first.';
        return;
      }}
      appendMessage('user', `Transcribe: ${{file.name}}`);
      const form = new FormData();
      form.append('audio', file);
      const h = {{}};
      const token = tokenInput.value.trim();
      if (token) h.Authorization = `Bearer ${{token}}`;
      const res = await fetch('/api/transcribe', {{method: 'POST', headers: h, body: form}});
      const data = await res.json();
      rawEl.textContent = JSON.stringify(data, null, 2);
      if (!res.ok) throw new Error(data.error || `HTTP ${{res.status}}`);
      document.getElementById('request').value = data.text || '';
      appendMessage('jarvis', data.text || 'No speech detected.');
    }}

    async function health() {{
      try {{
        const res = await fetch('/health');
        const data = await res.json();
        healthEl.textContent = data.ok && data.orchestrator?.ok
          ? `Ready. Orchestrator has ${{data.orchestrator.capabilities}} capabilities.`
          : 'Jarvis Chat is up, orchestrator not ready.';
      }} catch (err) {{
        healthEl.textContent = `Health check failed: ${{err.message}}`;
      }}
    }}

    document.getElementById('saveToken').onclick = () => {{
      localStorage.setItem('jarvisChatToken', tokenInput.value.trim());
      healthEl.textContent = 'Token saved in this browser.';
    }};

    document.getElementById('loadProfile').onclick = async () => {{
      try {{ await loadProfile(); }} catch (err) {{ healthEl.textContent = err.message; }}
    }};

    document.getElementById('saveProfile').onclick = async () => {{
      try {{ await saveProfile(); }} catch (err) {{ healthEl.textContent = err.message; }}
    }};

    document.getElementById('addProfileNote').onclick = async () => {{
      try {{ await addProfileNote(); }} catch (err) {{ healthEl.textContent = err.message; }}
    }};

    document.getElementById('send').onclick = async () => {{
      try {{
        const request = document.getElementById('request').value.trim();
        if (!request) return;
        appendMessage('user', request);
        const capability = document.getElementById('capability').value;
        const payload = {{
          request,
          limits: {{
            maximum_runtime_seconds: Number(document.getElementById('runtime').value || 1800),
            maximum_cost_usd: Number(document.getElementById('cost').value || 0)
          }},
          permissions: {{may_execute: false, may_publish: false}}
        }};
        if (capability) payload.capability = capability;
        const planned = await call('/api/requests', payload);
        const action = planned.actions?.[0];
        if (action?.permissions?.may_execute && action?.worker === 'llm_worker') {{
          const executed = await call(`/api/actions/${{action.action_id}}/execute`);
          appendMessage('jarvis', executed.action?.result?.text || executed.action?.result?.summary || 'Done.');
        }} else {{
          appendMessage('jarvis', planned.request?.summary || 'I created a plan for approval.');
        }}
        document.getElementById('request').value = '';
      }} catch (err) {{
        healthEl.textContent = err.message;
        appendMessage('jarvis', `Error: ${{err.message}}`);
      }}
    }};

    document.getElementById('transcribe').onclick = async () => {{
      try {{
        await transcribeAudio();
      }} catch (err) {{
        healthEl.textContent = err.message;
        appendMessage('jarvis', `Transcription error: ${{err.message}}`);
      }}
    }};

    approveButton.onclick = async () => {{
      if (currentActionId) await call(`/api/actions/${{currentActionId}}/approve`);
    }};

    executeButton.onclick = async () => {{
      if (currentActionId) {{
        const executed = await call(`/api/actions/${{currentActionId}}/execute`);
        if (executed.action?.result?.text) appendMessage('jarvis', executed.action.result.text);
      }}
    }};

    document.getElementById('refresh').onclick = health;
    health();
  </script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "homelab-jarvis-chat/0.1"

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args), flush=True)

    def write(self, status, body, content_type):
        raw = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def write_json(self, status, payload):
        self.write(status, json.dumps(payload, separators=(",", ":")), "application/json")

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8") or "{}")

    def authorized(self):
        token = configured_token()
        if not token:
            return True
        return self.headers.get("Authorization", "") == f"Bearer {token}"

    def proxy(self, method, path, payload=None):
        body = json.dumps(payload or {}).encode("utf-8") if method == "POST" else None
        req = urllib.request.Request(
            ORCHESTRATOR_URL + path,
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {ORCHESTRATOR_TOKEN}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as response:
                return response.status, json.loads(response.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            try:
                data = json.loads(exc.read().decode("utf-8") or "{}")
            except Exception:
                data = {"error": str(exc)}
            return exc.code, data
        except Exception as exc:
            return HTTPStatus.BAD_GATEWAY, {"ok": False, "error": str(exc)}

    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path == "/":
            self.write(HTTPStatus.OK, page(), "text/html; charset=utf-8")
            return
        if path == "/health":
            status, data = self.proxy("GET", "/health")
            self.write_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "auth_required": bool(configured_token()),
                    "orchestrator_status": status,
                    "orchestrator": data,
                },
            )
            return
        if path == "/api/profile":
            if not self.authorized():
                self.write_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
                return
            status, data = self.proxy("GET", "/profile")
            self.write_json(status, data)
            return
        self.write_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})

    def do_POST(self):
        path = urlparse(self.path).path.rstrip("/") or "/"
        if not self.authorized():
            self.write_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
            return

        if path == "/api/requests":
            status, data = self.proxy("POST", "/requests", self.read_json())
            self.write_json(status, data)
            return

        if path == "/api/transcribe":
            length = int(self.headers.get("Content-Length", "0") or "0")
            body = self.rfile.read(length) if length else b""
            headers = {"Content-Type": self.headers.get("Content-Type", "")}
            if WHISPER_WORKER_TOKEN and not WHISPER_WORKER_TOKEN.startswith("CHANGE_ME"):
                headers["Authorization"] = f"Bearer {WHISPER_WORKER_TOKEN}"
            req = urllib.request.Request(
                WHISPER_WORKER_URL + "/transcribe",
                data=body,
                method="POST",
                headers=headers,
            )
            try:
                with urllib.request.urlopen(req, timeout=300) as response:
                    self.write_json(response.status, json.loads(response.read().decode("utf-8") or "{}"))
            except urllib.error.HTTPError as exc:
                try:
                    data = json.loads(exc.read().decode("utf-8") or "{}")
                except Exception:
                    data = {"ok": False, "error": str(exc)}
                self.write_json(exc.code, data)
            except Exception as exc:
                self.write_json(HTTPStatus.BAD_GATEWAY, {"ok": False, "error": str(exc)})
            return

        if path == "/api/voice/transcribe":
            length = int(self.headers.get("Content-Length", "0") or "0")
            body = self.rfile.read(length) if length else b""
            headers = {"Content-Type": self.headers.get("Content-Type", "")}
            if WHISPER_WORKER_TOKEN and not WHISPER_WORKER_TOKEN.startswith("CHANGE_ME"):
                headers["Authorization"] = f"Bearer {WHISPER_WORKER_TOKEN}"
            req = urllib.request.Request(
                WHISPER_WORKER_URL + "/transcribe",
                data=body,
                method="POST",
                headers=headers,
            )
            try:
                with urllib.request.urlopen(req, timeout=300) as response:
                    self.write_json(response.status, json.loads(response.read().decode("utf-8") or "{}"))
            except urllib.error.HTTPError as exc:
                try:
                    data = json.loads(exc.read().decode("utf-8") or "{}")
                except Exception:
                    data = {"ok": False, "error": str(exc)}
                self.write_json(exc.code, data)
            except Exception as exc:
                self.write_json(HTTPStatus.BAD_GATEWAY, {"ok": False, "error": str(exc)})
            return

        if path == "/api/voice/request":
            try:
                payload = self.read_json()
            except json.JSONDecodeError:
                self.write_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_json"})
                return
            text = str(payload.get("text") or payload.get("request") or "").strip()
            if not text:
                self.write_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "text_required"})
                return
            request_payload = {
                "request": text,
                "source": payload.get("source") or "wake-word-client",
                "inputs": payload.get("inputs") or {"client": "jarvis-voice-client"},
                "limits": payload.get("limits") or {"maximum_runtime_seconds": 1800, "maximum_cost_usd": 0},
                "permissions": payload.get("permissions") or {"may_execute": False, "may_publish": False},
            }
            status, planned = self.proxy("POST", "/requests", request_payload)
            if status >= 400:
                self.write_json(status, planned)
                return
            responses = []
            approval_needed = []
            for action in planned.get("actions") or []:
                if action.get("permissions", {}).get("may_execute"):
                    execute_status, executed = self.proxy("POST", f"/actions/{action.get('action_id')}/execute", {})
                    text_result = result_text(executed)
                    responses.append(text_result or f"Action {action.get('capability') or action.get('action_id')} returned status {execute_status}.")
                else:
                    approval_needed.append(action)
            if approval_needed:
                responses.append(summarize_voice_plan({**planned, "actions": approval_needed}))
            response_text = "\n\n".join(item for item in responses if item).strip() or summarize_voice_plan(planned)
            self.write_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "text": response_text,
                    "planned": planned,
                    "approval_required": bool(approval_needed),
                    "approval_actions": approval_needed,
                },
            )
            return

        if path == "/api/voice/synthesize":
            try:
                payload = self.read_json()
            except json.JSONDecodeError:
                self.write_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_json"})
                return
            text = str(payload.get("text") or "").strip()
            if not text:
                self.write_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "text_required"})
                return
            headers = {"Content-Type": "application/json"}
            if TTS_WORKER_TOKEN and not TTS_WORKER_TOKEN.startswith("CHANGE_ME"):
                headers["Authorization"] = f"Bearer {TTS_WORKER_TOKEN}"
            req = urllib.request.Request(
                TTS_WORKER_URL + "/tts/synthesize",
                data=json.dumps(
                    {
                        "text": text,
                        "voice": payload.get("voice") or TTS_VOICE,
                        "format": payload.get("format") or "ogg",
                    }
                ).encode("utf-8"),
                method="POST",
                headers=headers,
            )
            try:
                with urllib.request.urlopen(req, timeout=240) as response:
                    audio = response.read()
                    self.send_response(response.status)
                    self.send_header("Content-Type", response.headers.get("Content-Type", "audio/ogg"))
                    self.send_header("Content-Length", str(len(audio)))
                    self.end_headers()
                    self.wfile.write(audio)
            except urllib.error.HTTPError as exc:
                try:
                    data = json.loads(exc.read().decode("utf-8") or "{}")
                except Exception:
                    data = {"ok": False, "error": str(exc)}
                self.write_json(exc.code, data)
            except Exception as exc:
                self.write_json(HTTPStatus.BAD_GATEWAY, {"ok": False, "error": str(exc)})
            return

        if path == "/api/profile":
            status, data = self.proxy("POST", "/profile", self.read_json())
            self.write_json(status, data)
            return

        if path == "/api/profile/notes":
            status, data = self.proxy("POST", "/profile/notes", self.read_json())
            self.write_json(status, data)
            return

        if path.startswith("/api/actions/"):
            parts = path.split("/")
            if len(parts) == 5 and parts[4] in {"approve", "execute"}:
                status, data = self.proxy("POST", f"/actions/{parts[3]}/{parts[4]}", {})
                self.write_json(status, data)
                return

        self.write_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})


def main():
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Jarvis Chat listening on {HOST}:{PORT}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
