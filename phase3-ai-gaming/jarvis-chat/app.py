#!/usr/bin/env python3
import hashlib
import html
import json
import os
import urllib.error
import urllib.request
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

HOST = os.environ.get("JARVIS_CHAT_HOST", "0.0.0.0")
PORT = int(os.environ.get("JARVIS_CHAT_PORT", "8096"))
ORCHESTRATOR_URL = os.environ.get("AI_ORCHESTRATOR_URL", "http://ai-orchestrator:8095").rstrip("/")
ORCHESTRATOR_TOKEN = os.environ.get("AI_ORCHESTRATOR_TOKEN", "")
JARVIS_CORE_URL = os.environ.get("JARVIS_CORE_URL", "http://jarvis-core:8097").rstrip("/")
JARVIS_CORE_TOKEN = os.environ.get("JARVIS_CORE_TOKEN", ORCHESTRATOR_TOKEN)
CODEX_WORKER_URL = os.environ.get("CODEX_WORKER_URL", "http://codex-worker:18300").rstrip("/")
CODEX_WORKER_TOKEN = os.environ.get("CODEX_WORKER_TOKEN", ORCHESTRATOR_TOKEN)
WHISPER_WORKER_URL = os.environ.get("WHISPER_WORKER_URL", "http://whisper-worker:8099").rstrip("/")
WHISPER_WORKER_TOKEN = os.environ.get("WHISPER_WORKER_TOKEN", "")
TTS_WORKER_URL = os.environ.get("JARVIS_TTS_WORKER_URL", "http://tts-worker:8101").rstrip("/")
TTS_WORKER_TOKEN = os.environ.get("JARVIS_TTS_TOKEN", "")
TTS_VOICE = os.environ.get("JARVIS_TTS_VOICE", "default")
SPANISH_COACH_URL = os.environ.get("SPANISH_COACH_URL", "http://spanish-coach:8120").rstrip("/")
SPANISH_COACH_TOKEN = os.environ.get("SPANISH_COACH_TOKEN", "")
CHAT_TOKEN = os.environ.get("JARVIS_CHAT_TOKEN", "")
USER_TIMEZONE = os.environ.get("JARVIS_USER_TIMEZONE", "America/New_York")


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


def wants_core_voice(text):
    lowered = str(text or "").lower()
    terms = (
        "daily brief",
        "morning brief",
        "evening recap",
        "add task",
        "create task",
        "new task",
        "to do",
        "todo",
        "capture",
        "evidence",
        "portfolio",
        "maintenance",
        "homelab",
        "media automation",
        "media automations",
        "arr stack",
        "torrent status",
        "drive inventory",
        "google drive inventory",
        "drive migration",
        "google drive migration",
        "service health",
        "complete task",
        "reopen task",
        "update task",
        "resolve maintenance",
        "reopen maintenance",
        "what are my tasks",
        "list tasks",
        "codex",
        "coding task",
        "codex dashboard",
        "codex tasks",
        "code task",
        "fix code",
        "implement",
        "debug",
        "refactor",
        "write tests",
        "pending approvals",
        "what approvals",
        "notifications",
        "read notifications",
        "what notifications",
        "approve ",
    )
    return any(term in lowered for term in terms)


def wants_spanish_voice(text):
    lowered = str(text or "").lower()
    terms = ("spanish practice", "morning spanish", "spanish follow up", "spanish follow-up", "learn spanish")
    return any(term in lowered for term in terms)


def core_voice_text(data):
    if data.get("status") == "confirmation_required":
        return data.get("text") or "Please confirm that action."
    if data.get("status") == "ambiguous":
        names = []
        for item in data.get("matches") or []:
            action = item.get("action") or {}
            names.append((action.get("preview") or {}).get("summary") or action.get("tool_name") or item.get("id"))
        return "I found multiple matching approvals: " + "; ".join(names[:5]) + ". Please be more specific."
    if data.get("text"):
        return data["text"]
    if data.get("approvals") is not None:
        approvals = data.get("approvals") or []
        if not approvals:
            return "There are no matching pending approvals."
        names = []
        for item in approvals[:5]:
            action = item.get("action") or {}
            names.append((action.get("preview") or {}).get("summary") or action.get("tool_name") or item.get("id"))
        return "Pending approvals: " + "; ".join(names) + "."
    if data.get("notifications") is not None:
        notifications = data.get("notifications") or []
        if not notifications:
            return "There are no pending Jarvis notifications."
        lines = []
        for item in notifications[:5]:
            payload = item.get("payload") or {}
            title = payload.get("title") or "Jarvis notification"
            body = payload.get("body") or ""
            lines.append(f"{title}: {body}".strip(": "))
        return "Pending notifications: " + "; ".join(lines) + "."
    if data.get("checks") is not None and data.get("preview"):
        failed = [item.get("label") or item.get("name") for item in data.get("checks") or [] if not item.get("ok")]
        if failed:
            return f"{data.get('preview')}. Needs attention: " + ", ".join(failed[:5]) + "."
        return str(data.get("preview")) + "."
    if data.get("total") is not None and data.get("items") is not None:
        destinations = data.get("by_destination") or {}
        return f"{data.get('summary')}. Suggested destinations: " + "; ".join(f"{k}: {v}" for k, v in list(destinations.items())[:5]) + "."
    if data.get("plan") is not None and data.get("inventory") is not None:
        plan = data.get("plan") or {}
        inventory = data.get("inventory") or {}
        batches = plan.get("suggested_batches") or []
        return f"{inventory.get('summary')}. {plan.get('summary')} Suggested batches: " + "; ".join(f"{b.get('destination')}: {b.get('count')}" for b in batches[:5]) + "."
    if data.get("status") == "approved":
        action = data.get("action") or {}
        return f"Approved {action.get('tool_name', 'the action')}."
    if data.get("task") and data.get("operation"):
        return f"{data.get('operation').replace('_', ' ').title()}: {data['task'].get('title')}."
    if data.get("maintenance") and data.get("operation"):
        item = data["maintenance"]
        return f"{data.get('operation').replace('_', ' ').title()} maintenance for {item.get('service_name')}: {item.get('summary')}."
    if data.get("type") == "task" and data.get("task"):
        return f"Captured task: {data['task'].get('title')}"
    if data.get("type") == "evidence" and data.get("evidence"):
        return f"Captured evidence: {data['evidence'].get('title')}"
    if data.get("type") == "maintenance" and data.get("maintenance"):
        item = data["maintenance"]
        return f"Captured maintenance note for {item.get('service_name')}: {item.get('summary')}"
    if data.get("tasks") is not None:
        tasks = data.get("tasks") or []
        if not tasks:
            return "You do not have open Jarvis Core tasks."
        names = "; ".join(item.get("title", "task") for item in tasks[:5])
        return f"Top Jarvis Core tasks: {names}."
    if data.get("codex_tasks") is not None:
        tasks = data.get("codex_tasks") or []
        if not tasks:
            return "There are no Codex tasks yet."
        names = []
        for item in tasks[:5]:
            names.append(f"{item.get('status')}: {item.get('request')}")
        return "Codex tasks: " + "; ".join(names) + "."
    if data.get("request") and data.get("actions"):
        action = data["actions"][0]
        return f"Approval is required for {action.get('tool_name', 'that action')}."
    return "Jarvis Core handled that."


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
    .nav {{
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
    }}
    .nav a {{
      display: inline-flex;
      align-items: center;
      min-height: 40px;
      border: 1px solid rgba(94, 234, 212, 0.75);
      border-radius: 6px;
      background: #102521;
      color: var(--text);
      padding: 9px 12px;
      font-weight: 700;
      text-decoration: none;
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
      .nav {{ width: 100%; }}
      .nav a {{ justify-content: center; width: 100%; }}
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
      <nav class="nav" aria-label="Jarvis navigation">
        <a href="/core" title="Open Core approvals, Codex jobs, diagnostics, tasks, evidence, maintenance, and daily briefs">Core Console</a>
        <button id="refresh" title="Refresh health and current request">Refresh</button>
      </nav>
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
        <button id="openCore" type="button">Open Core Console</button>
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

    document.getElementById('openCore').onclick = () => {{
      window.location.href = '/core';
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


def core_console_page():
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Jarvis Core Console</title>
  <style>
    :root { color-scheme: dark; --bg:#0f141b; --panel:#161d26; --line:#344150; --text:#f5f7fb; --muted:#aeb9c7; --accent:#5eead4; --warn:#fbbf24; --danger:#fb7185; }
    * { box-sizing: border-box; }
    body { margin:0; background:var(--bg); color:var(--text); font-family:Inter, ui-sans-serif, system-ui, Segoe UI, sans-serif; }
    main { width:min(1180px, calc(100vw - 28px)); margin:0 auto; padding:22px 0 44px; }
    header { display:flex; justify-content:space-between; align-items:center; gap:12px; margin-bottom:16px; }
    h1 { margin:0; font-size:24px; letter-spacing:0; }
    h2 { margin:0 0 10px; font-size:16px; letter-spacing:0; }
    button, select { border:1px solid var(--line); border-radius:6px; background:#1f2935; color:var(--text); padding:9px 11px; }
    button { cursor:pointer; font-weight:650; }
    .grid { display:grid; grid-template-columns:repeat(2, minmax(0,1fr)); gap:12px; }
    .panel { border:1px solid var(--line); background:var(--panel); border-radius:8px; padding:12px; min-height:120px; }
    .full { grid-column:1 / -1; }
    .item { border-top:1px solid var(--line); padding:9px 0; }
    .item:first-child { border-top:0; }
    .muted { color:var(--muted); }
    .ok { color:var(--accent); }
    .bad { color:var(--danger); }
    .warn { color:var(--warn); }
    pre { white-space:pre-wrap; overflow-wrap:anywhere; margin:6px 0 0; font-size:12px; line-height:1.4; color:#d8dee9; }
    a { color:var(--accent); }
    @media (max-width: 780px) { .grid { grid-template-columns:1fr; } header { align-items:flex-start; flex-direction:column; } }
  </style>
</head>
<body>
<main>
  <header>
    <div>
      <h1>Jarvis Core Console</h1>
      <div class="muted" id="status">Loading Core state...</div>
    </div>
    <div>
      <button onclick="loadAll()">Refresh</button>
      <a href="/" style="margin-left:10px;">Chat</a>
    </div>
  </header>
  <section class="grid">
    <div class="panel"><h2>Approvals</h2><div id="approvals"></div></div>
    <div class="panel"><h2>Diagnostics</h2><div id="diagnostics"></div></div>
    <div class="panel full"><h2>Codex Jobs</h2><div id="codex"></div></div>
    <div class="panel"><h2>Tasks</h2><div id="tasks"></div></div>
    <div class="panel"><h2>Evidence</h2><div id="evidence"></div></div>
    <div class="panel"><h2>Maintenance</h2><div id="maintenance"></div></div>
    <div class="panel"><h2>Daily Brief</h2><div id="brief"></div></div>
    <div class="panel"><h2>Drive Inventory</h2><div id="drive"></div></div>
    <div class="panel"><h2>Drive Staging</h2><div id="driveStaging"></div></div>
    <div class="panel"><h2>Smart Destinations</h2><div id="driveDestinations"></div></div>
    <div class="panel"><h2>Notifications</h2><div id="notifications"></div></div>
    <div class="panel"><h2>Audit</h2><div id="audit"></div></div>
  </section>
</main>
<script>
async function get(path) {
  const res = await fetch(path);
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || data.detail?.error || `HTTP ${res.status}`);
  return data;
}
function esc(value) { return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function item(html) { return `<div class="item">${html}</div>`; }
function renderApprovals(data) {
  const rows = data.approvals || [];
  approvals.innerHTML = rows.length ? rows.slice(0,8).map(a => {
    const action = a.action || {};
    const title = action.preview?.summary || action.tool_name || a.id;
    return item(`<b>${esc(title)}</b><br><span class="muted">${esc(a.status)} · ${esc(a.reason)}</span>`);
  }).join('') : '<span class="muted">No pending approvals.</span>';
}
function renderDiagnostics(data) {
  diagnostics.innerHTML = (data.checks || []).map(c => item(`<span class="${c.ok ? 'ok' : 'bad'}">${c.ok ? 'OK' : 'FAIL'}</span> <b>${esc(c.name)}</b><br><span class="muted">${esc(c.summary || c.error || c.status)}</span>`)).join('');
}
function renderCodex(data) {
  const tasks = data.codex_tasks || [];
  codex.innerHTML = tasks.length ? tasks.slice(0,12).map(t => {
    const artifacts = (t.artifacts || []).map(a => `${a.kind || a.name}: ${a.path || ''}`).join('\\n');
    return item(`<b>${esc(t.status)}</b> ${esc(t.request)}<br><span class="muted">Action ${esc(t.action_id)}</span><pre>${esc(artifacts || 'No worker artifacts yet.')}</pre>`);
  }).join('') : '<span class="muted">No Codex tasks yet.</span>';
}
function renderCodexWorker(data) {
  const jobs = data.jobs || [];
  if (!jobs.length) return;
  codex.innerHTML += item(`<b>Worker job files</b>` + jobs.slice(0,8).map(j => `<pre>${esc(j.job_id)} · ${esc(j.status)}\\n${esc(j.summary)}</pre>`).join(''));
}
function renderList(target, key, data, titleField) {
  const rows = data[key] || [];
  target.innerHTML = rows.length ? rows.slice(0,8).map(r => item(`<b>${esc(r[titleField] || r.title || r.summary || r.event_type || r.id)}</b><br><span class="muted">${esc(r.status || r.service_name || r.evidence_type || r.created_at || '')}</span>`)).join('') : '<span class="muted">No records.</span>';
}
async function loadAll() {
  status.textContent = 'Refreshing...';
  const [ap, diag, cx, jobs, task, ev, maint, br, au] = await Promise.all([
    get('/api/core/approvals?status=pending'),
    get('/api/core/diagnostics'),
    get('/api/core/codex/tasks'),
    get('/api/codex/jobs'),
    get('/api/core/tasks'),
    get('/api/core/evidence'),
    get('/api/core/maintenance'),
    get('/api/core/daily-brief?kind=morning'),
    get('/api/core/audit?q=codex')
  ]);
  renderApprovals(ap); renderDiagnostics(diag); renderCodex(cx); renderCodexWorker(jobs);
  renderList(tasks, 'tasks', task, 'title');
  renderList(evidence, 'evidence', ev, 'title');
  renderList(maintenance, 'maintenance', maint, 'summary');
  brief.innerHTML = `<pre>${esc(br.text || JSON.stringify(br, null, 2))}</pre>`;
  renderList(audit, 'events', au, 'event_type');
  status.textContent = 'Ready.';
}
loadAll().catch(err => { status.textContent = err.message; });
</script>
</body>
</html>"""


def interactive_core_console_page():
    return r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Jarvis Core Console</title>
  <style>
    :root { color-scheme: dark; --bg:#0b1017; --panel:#141b24; --panel2:#1d2632; --line:#2b3948; --text:#f6f8fb; --muted:#9aa8b8; --accent:#5eead4; --warn:#fbbf24; --danger:#fb7185; --soft:#0f1720; }
    * { box-sizing: border-box; }
    body { margin:0; background:var(--bg); color:var(--text); font-family:Inter, ui-sans-serif, system-ui, Segoe UI, sans-serif; }
    main { width:min(1360px, calc(100vw - 32px)); margin:0 auto; padding:22px 0 44px; }
    header { display:flex; justify-content:space-between; align-items:center; gap:14px; margin-bottom:14px; }
    h1 { margin:0; font-size:22px; letter-spacing:0; }
    h2 { margin:0; font-size:14px; letter-spacing:0; }
    button, select { border:1px solid var(--line); border-radius:7px; background:var(--panel2); color:var(--text); padding:8px 10px; }
    button { cursor:pointer; font-weight:650; }
    button.primary { border-color:rgba(94,234,212,.8); background:#12302d; }
    button.danger { border-color:rgba(251,113,133,.8); }
    button.ghost { background:transparent; }
    .brand { display:flex; align-items:center; gap:12px; min-width:0; }
    .mark { display:grid; place-items:center; width:38px; height:38px; border:1px solid rgba(94,234,212,.45); border-radius:8px; background:#102521; color:var(--accent); font-weight:900; }
    .top-actions { display:flex; gap:8px; align-items:center; flex-wrap:wrap; justify-content:flex-end; }
    .icon-button { display:inline-grid; place-items:center; width:36px; height:36px; padding:0; border-radius:999px; text-decoration:none; border:1px solid var(--line); background:var(--panel2); color:var(--text); font-size:18px; line-height:1; }
    .icon-button:hover { border-color:rgba(94,234,212,.55); background:#121d28; }
    .status-line { display:flex; align-items:center; gap:7px; color:var(--muted); font-size:13px; margin-top:2px; }
    .pulse { width:8px; height:8px; border-radius:999px; background:var(--accent); box-shadow:0 0 18px rgba(94,234,212,.7); }
    .overview { display:flex; align-items:center; gap:8px; flex-wrap:wrap; margin-bottom:12px; }
    .metric { display:inline-flex; align-items:center; gap:8px; border:1px solid var(--line); background:var(--soft); border-radius:999px; padding:6px 10px; min-height:34px; }
    button.metric { cursor:pointer; color:var(--text); }
    button.metric:hover { border-color:rgba(94,234,212,.55); background:#121d28; }
    .metric b { display:inline; font-size:14px; }
    .metric span { color:var(--muted); font-size:12px; }
    .metric.attn { border-color:rgba(251,191,36,.42); background:#1f1b12; }
    .metric.bad { border-color:rgba(251,113,133,.42); background:#21141b; }
    .grid { display:grid; grid-template-columns:repeat(12, minmax(0,1fr)); column-gap:24px; row-gap:22px; align-items:start; }
    .panel { grid-column:span 4; border:0; background:transparent; border-radius:0; padding:0; min-height:0; overflow:visible; }
    .span-6 { grid-column:span 6; }
    .span-8 { grid-column:span 8; }
    .span-12, .full { grid-column:1 / -1; }
    .panel-head { display:flex; align-items:center; justify-content:space-between; gap:10px; padding:0 2px 8px; border-bottom:0; }
    .panel-title { display:flex; align-items:center; gap:9px; min-width:0; }
    .sigil { display:grid; place-items:center; width:28px; height:28px; border:1px solid rgba(94,234,212,.28); border-radius:7px; background:#101923; color:var(--accent); font-size:11px; font-weight:900; flex:0 0 auto; }
    .panel-body { border:1px solid rgba(43,57,72,.72); background:rgba(20,27,36,.78); border-radius:8px; padding:8px 12px; }
    .brief-body { padding:14px; }
    .brief-layout { display:grid; grid-template-columns:minmax(0,1.35fr) minmax(280px,.65fr); gap:16px; align-items:start; }
    .brief-text { white-space:pre-wrap; line-height:1.55; color:#dce5ef; margin:0; font-size:14px; }
    .brief-stack { display:grid; gap:10px; }
    .brief-section { border:1px solid rgba(43,57,72,.62); border-radius:8px; padding:10px; background:rgba(15,23,32,.54); }
    .brief-section b { display:block; margin-bottom:7px; }
    .brief-section button { width:100%; text-align:left; border:0; border-top:1px solid rgba(43,57,72,.54); border-radius:0; background:transparent; padding:8px 0; }
    .brief-section button:first-of-type { border-top:0; }
    .brief-section .quick-action { width:30px; height:30px; padding:0; text-align:center; border:1px solid var(--line); border-radius:999px; background:var(--panel2); }
    .count { color:var(--muted); font-size:12px; white-space:nowrap; }
    .item { border-top:1px solid var(--line); padding:9px 0; }
    .item:first-child { border-top:0; }
    .item-button { display:block; width:100%; text-align:left; border:0; border-top:1px solid rgba(43,57,72,.56); border-radius:0; background:transparent; padding:10px 0; color:var(--text); }
    .item-button:first-child { border-top:0; }
    .item-button:hover { background:rgba(94,234,212,.045); }
    .compact-line { display:flex; align-items:center; justify-content:space-between; gap:10px; min-width:0; }
    .compact-title { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-weight:700; }
    .compact-sub { color:var(--muted); font-size:12px; margin-top:3px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .quick-actions { display:flex; align-items:center; gap:6px; margin-left:8px; flex:0 0 auto; }
    .quick-action { width:30px; height:30px; padding:0; display:inline-grid; place-items:center; border-radius:999px; font-size:15px; line-height:1; }
    .quick-action.approve { border-color:rgba(94,234,212,.75); color:var(--accent); }
    .quick-action.reject { border-color:rgba(251,113,133,.72); color:var(--danger); }
    .muted { color:var(--muted); }
    .ok { color:var(--accent); }
    .bad { color:var(--danger); }
    .warn { color:var(--warn); }
    .pill { display:inline-flex; align-items:center; border:1px solid rgba(43,57,72,.8); border-radius:999px; padding:2px 8px; color:var(--muted); font-size:12px; margin-right:6px; margin-bottom:6px; background:rgba(15,23,32,.62); }
    button.pill { font-family:inherit; cursor:pointer; appearance:none; }
    button.pill:hover { color:var(--accent); border-color:rgba(94,234,212,.56); background:rgba(94,234,212,.08); }
    .drawer-backdrop { position:fixed; inset:0; background:rgba(0,0,0,.48); opacity:0; pointer-events:none; transition:opacity .16s ease; }
    .drawer { position:fixed; top:0; right:0; width:min(760px, 100vw); height:100vh; background:#111821; border-left:1px solid var(--line); padding:18px; transform:translateX(100%); transition:transform .16s ease; overflow:auto; box-shadow:-20px 0 48px rgba(0,0,0,.32); }
    body.drawer-open .drawer-backdrop { opacity:1; pointer-events:auto; }
    body.drawer-open .drawer { transform:translateX(0); }
    .drawer-header { display:flex; justify-content:space-between; gap:12px; align-items:flex-start; margin-bottom:14px; }
    .drawer h2 { font-size:20px; margin:0 0 6px; }
    .actions { display:flex; gap:8px; flex-wrap:wrap; margin:12px 0; }
    .field { border-top:1px solid var(--line); padding:10px 0; }
    .field b { display:block; margin-bottom:4px; }
    .hub-grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(250px,1fr)); gap:10px; }
    .hub-card { border:1px solid rgba(43,57,72,.72); background:rgba(15,23,32,.55); border-radius:8px; padding:10px; min-width:0; }
    .hub-card-head { display:flex; justify-content:space-between; align-items:center; gap:8px; margin-bottom:8px; }
    .hub-card h3 { margin:0; font-size:13px; }
    .mail-row { border-top:1px solid rgba(43,57,72,.56); padding:8px 0; min-width:0; }
    .mail-row:first-of-type { border-top:0; }
    .mail-from, .mail-subject { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .mail-from { color:var(--muted); font-size:12px; margin-top:2px; }
    .automation-card { display:grid; gap:8px; border:1px solid rgba(43,57,72,.72); background:rgba(15,23,32,.55); border-radius:8px; padding:10px; }
    .automation-meta { display:grid; grid-template-columns:repeat(2, minmax(0,1fr)); gap:7px; color:var(--muted); font-size:12px; }
    .automation-output { color:#d8dee9; font-size:12px; line-height:1.4; max-height:4.2em; overflow:hidden; }
    .drive-shell { border:1px solid var(--line); border-radius:8px; overflow:hidden; background:#0f1720; }
    .drive-bar { display:flex; align-items:center; justify-content:space-between; gap:10px; padding:10px 12px; border-bottom:1px solid var(--line); background:#151f2a; }
    .drive-crumbs { display:flex; align-items:center; gap:6px; min-width:0; flex-wrap:wrap; }
    .drive-crumb { border:0; background:transparent; padding:4px 6px; color:var(--text); max-width:180px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .drive-crumb:hover { background:rgba(94,234,212,.08); }
    .drive-meta { display:flex; gap:6px; flex-wrap:wrap; justify-content:flex-end; }
    .drive-table { width:100%; padding:8px; }
    .drive-row { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:10px; align-items:center; padding:10px; border:1px solid transparent; border-radius:7px; min-height:56px; }
    .drive-row:last-child { border-bottom:0; }
    .drive-row:hover { background:rgba(94,234,212,.055); border-color:rgba(94,234,212,.16); }
    .drive-row.selected { background:rgba(94,234,212,.11); border-color:rgba(94,234,212,.42); }
    .drive-name { display:flex; align-items:center; gap:10px; min-width:0; }
    .drive-name button { border:0; background:transparent; padding:3px; text-align:left; min-width:0; flex:1; }
    .drive-title { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-weight:750; color:var(--text); }
    .drive-subtitle { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:var(--muted); font-size:12px; margin-top:2px; }
    .drive-icon { display:inline-grid; place-items:center; width:30px; height:30px; border:1px solid var(--line); border-radius:6px; background:#1f2935; color:var(--accent); font-size:11px; font-weight:800; flex:0 0 auto; }
    .drive-icon.file { color:#d8dee9; }
    .drive-check { width:32px; height:32px; padding:0; display:inline-grid; place-items:center; border-radius:999px; }
    .drive-row.selected .drive-check { border-color:rgba(94,234,212,.8); color:var(--accent); }
    .drive-empty { padding:18px 12px; color:var(--muted); }
    .drive-section { border-top:1px solid var(--line); }
    .drive-section-title { padding:9px 12px; color:var(--muted); font-size:12px; font-weight:750; text-transform:uppercase; }
    pre { white-space:pre-wrap; overflow-wrap:anywhere; margin:6px 0 0; font-size:12px; line-height:1.4; color:#d8dee9; }
    a { color:var(--accent); }
    @media (max-width: 980px) { .panel, .span-6, .span-8 { grid-column:1 / -1; } .brief-layout { grid-template-columns:1fr; } }
    @media (max-width: 780px) { main { width:min(100vw - 22px, 1360px); } .grid { grid-template-columns:1fr; } header { align-items:flex-start; flex-direction:column; } .top-actions { width:100%; justify-content:flex-start; } .drive-row { grid-template-columns:minmax(0,1fr) auto; } }
  </style>
</head>
<body>
<main>
  <header>
    <div class="brand">
      <span class="mark">J</span>
      <div>
        <h1>Jarvis Core</h1>
        <div class="status-line"><span class="pulse"></span><span id="status">Loading Core state...</span></div>
      </div>
    </div>
    <div class="top-actions">
      <button class="icon-button" title="Refresh" aria-label="Refresh" onclick="loadAll()">&#8635;</button>
      <a class="icon-button" href="/" title="Chat" aria-label="Chat">&#128172;</a>
    </div>
  </header>
  <section class="overview" id="overview"></section>
  <section class="grid">
    <div class="panel span-12"><div class="panel-head"><div class="panel-title"><span class="sigil">DB</span><h2>Daily Brief</h2></div><span class="count" id="briefCount"></span></div><div class="panel-body brief-body" id="brief"></div></div>
  </section>
</main>
<div class="drawer-backdrop" onclick="closeDrawer()"></div>
<aside class="drawer" aria-live="polite">
  <div class="drawer-header">
    <div>
      <h2 id="drawerTitle">Details</h2>
      <div class="muted" id="drawerSubtitle"></div>
    </div>
    <button class="icon-button" title="Close" aria-label="Close" onclick="closeDrawer()">&#215;</button>
  </div>
  <div class="actions" id="drawerActions"></div>
  <div id="drawerBody"></div>
</aside>
<script>
const state = { approvals: [], diagnostics: [], codexTasks: [], codexJobs: [], runs: [], workers: [], downloads: [], downloadsDestinationPlan: {}, tasks: [], evidence: [], maintenance: [], brief: {}, notifications: [], automations: [], audit: [], gmailCleanup: {}, drive: {}, drivePlan: {}, drivePlanLoaded: false, driveFolders: [], driveFoldersLoaded: false, selectedDriveFolders: [], driveTrail: [], driveChildren: {}, driveStaging: {}, driveDestinations: {} };
async function get(path) {
  const res = await fetch(path);
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || data.detail?.error || `HTTP ${res.status}`);
  return data;
}
async function send(method, path, body) {
  const res = await fetch(path, { method, headers: {'Content-Type':'application/json'}, body: body ? JSON.stringify(body) : undefined });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || data.detail?.error || `HTTP ${res.status}`);
  return data;
}
function esc(value) { return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function row(label, value) {
  if (value === undefined || value === null || value === '') return '';
  const rendered = typeof value === 'object' ? `<pre>${esc(JSON.stringify(value, null, 2))}</pre>` : esc(value);
  return `<div class="field"><b>${esc(label)}</b>${rendered}</div>`;
}
function itemButton(kind, idx, html) {
  return `<button class="item-button" onclick="openItem('${kind}', ${idx})">${html}</button>`;
}
function pillButton(label, action, tone = '') {
  return `<button class="pill ${tone}" type="button" onclick="${action}">${esc(label)}</button>`;
}
function enc(value) {
  return encodeURIComponent(String(value ?? ''));
}
function setCount(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}
function compactButton(kind, idx, title, subtitle = '', badge = '') {
  return itemButton(kind, idx, `<div class="compact-line"><span class="compact-title">${esc(title)}</span>${badge ? `<span class="pill">${esc(badge)}</span>` : ''}</div>${subtitle ? `<div class="compact-sub">${esc(subtitle)}</div>` : ''}`);
}
function approvalButton(a, idx) {
  const action = a.action || {};
  const title = displayTitle(action.preview?.summary || action.tool_name || a.id);
  const subtitle = a.reason || action.tool_name || '';
  const badge = action.risk_level || a.status || '';
  return `<div class="item-button approval-row" role="button" tabindex="0" onclick="openApprovalById('${esc(a.id)}')">
    <div class="compact-line">
      <span class="compact-title">${esc(title)}</span>
      <span class="quick-actions">
        ${badge ? `<span class="pill">${esc(badge)}</span>` : ''}
        <button class="quick-action approve" title="Approve" aria-label="Approve" onclick="approveApproval(event, '${esc(a.id)}')">&#10003;</button>
        <button class="quick-action reject" title="Reject" aria-label="Reject" onclick="rejectApproval(event, '${esc(a.id)}')">&#215;</button>
      </span>
    </div>
    ${subtitle ? `<div class="compact-sub">${esc(subtitle)}</div>` : ''}
  </div>`;
}
function emptyState(text) {
  return `<span class="muted">${esc(text)}</span>`;
}
function displayTitle(value) {
  let text = String(value || '').trim();
  text = text.replace(/^add task\s+/i, '');
  text = text.replace(/^codex coding task:\s*/i, '');
  text = text.replace(/^homelab maintenance note:\s*/i, '');
  text = text.replace(/^capture evidence:\s*/i, '');
  text = text.replace(/^Jarvis evidence packet$/i, 'Portfolio evidence packet');
  text = text.replace(/^notif_[a-z0-9]+$/i, 'Jarvis notification');
  text = text.replace(/\s+/g, ' ');
  if (!text) return 'Untitled';
  return text.charAt(0).toUpperCase() + text.slice(1);
}
function notificationTitle(n) {
  const payload = n.payload || {};
  return displayTitle(payload.title || payload.summary || payload.body || n.id);
}
function notificationSubtitle(n) {
  const payload = n.payload || {};
  return payload.body || payload.summary || `${n.channel || 'notification'} / ${n.status || ''}`;
}
function linkedApprovalForNotification(n) {
  const payload = n?.payload || {};
  const actionId = payload.action_id || payload.proposed_action_id;
  const approvalId = payload.approval_id;
  return state.approvals.find(item =>
    (approvalId && item.id === approvalId) ||
    (actionId && (item.action?.id === actionId || item.proposed_action_id === actionId))
  );
}
function notificationButton(n, idx) {
  const approval = linkedApprovalForNotification(n);
  const badge = approval ? (approval.action?.risk_level || 'approval') : (n.status || '');
  const decisionActions = approval ? `
        <button class="quick-action approve" title="Approve request" aria-label="Approve request" onclick="approveNotification(event, '${esc(n.id)}')">&#10003;</button>
        <button class="quick-action reject" title="Reject request" aria-label="Reject request" onclick="rejectNotification(event, '${esc(n.id)}')">&#215;</button>` : '';
  const dismissAction = `<button class="quick-action reject" title="Dismiss" aria-label="Dismiss" onclick="dismissNotification(event, '${esc(n.id)}')">&#215;</button>`;
  return `<div class="item-button approval-row" role="button" tabindex="0" onclick="openItem('notifications', ${idx})">
    <div class="compact-line">
      <span class="compact-title">${esc(notificationTitle(n))}</span>
      <span class="quick-actions">
        ${badge ? `<span class="pill">${esc(badge)}</span>` : ''}
        ${decisionActions}
        ${dismissAction}
      </span>
    </div>
    <div class="compact-sub">${esc(notificationSubtitle(n))}</div>
  </div>`;
}
function maintenanceTitle(m) {
  return displayTitle(m.summary || m.service_name || 'Maintenance item');
}
function evidenceTitle(e) {
  return displayTitle(e.title || e.summary || 'Evidence');
}
function usefulRows(key, rows) {
  if (key === 'evidence') {
    const nonPackets = rows.filter(item => item.evidence_type !== 'packet');
    return nonPackets.length ? nonPackets : rows;
  }
  if (key === 'notifications') {
    return rows.filter(item => !['delivered', 'dismissed'].includes(String(item.status || '').toLowerCase()));
  }
  return rows;
}
function renderOverview(data) {
  const failed = (data.diag.checks || []).filter(c => !c.ok && !c.optional).length;
  const running = (data.cx.codex_tasks || []).filter(t => ['proposed','running','queued'].includes(String(t.status || '').toLowerCase())).length;
  const due = (data.task.tasks || []).length;
  const maintenance = (data.maint.maintenance || []).filter(m => m.status !== 'resolved').length;
  const approvals = (data.ap.approvals || []).length;
  const notifications = usefulRows('notifications', data.notif.notifications || []).length;
  const automations = (data.auto.automations || []).filter(a => ['scheduled_or_on_demand','continuous','event_driven'].includes(String(a.mode || ''))).length;
  const gmail = (data.gm.needs_reply || []).length + (data.gm.likely_newsletters || []).length;
  const runs = (data.runs.runs || []).filter(r => !['completed','failed','cancelled'].includes(String(r.status || '').toLowerCase())).length;
  const workers = (data.workers.workers || []).filter(w => w.status === 'online').length;
  const downloads = (data.downloads.scans || []).length ? ((data.downloads.scans[0].preview || {}).file_count || 0) : 0;
  const selectedDrive = state.selectedDriveFolders.length;
  overview.innerHTML = [
    metric('AP', approvals, 'approvals', approvals ? 'attn' : '', 'openApprovalsHub()'),
    metric('DX', failed, 'diagnostics', failed ? 'bad' : '', 'openDiagnosticsHub()'),
    metric('RN', runs, 'runs', runs ? 'attn' : '', 'openRunsHub()'),
    metric('WK', workers, 'workers', workers ? '' : 'bad', 'openWorkersHub()'),
    metric('DL', downloads, 'downloads', downloads ? 'attn' : '', 'openDownloadsHub()'),
    metric('CX', running, 'codex', running ? 'attn' : '', 'openCodexHub()'),
    metric('CA', briefEventCount(data.br), 'calendar', '', 'openCalendarHub()'),
    metric('DR', selectedDrive, 'drive', selectedDrive ? 'attn' : '', 'openDrive()'),
    metric('GM', gmail, 'gmail', gmail ? 'attn' : '', 'openGmailCleanupHub()'),
    metric('AT', automations, 'automations', automations ? '' : '', 'openAutomationsHub()'),
    metric('MT', maintenance, 'maintenance', maintenance ? 'attn' : '', 'openMaintenanceHub()'),
    metric('IN', notifications, 'inbox', notifications ? 'attn' : '', 'openNotificationsHub()')
  ].join('');
}
function briefEventCount(br) {
  return (br?.google?.calendar?.events || br?.calendar_events || []).length || 0;
}
function metric(code, value, label, tone = '', action = '') {
  return `<button class="metric ${tone}" onclick="${action}" title="${esc(label)}"><span>${esc(code)}</span><b>${esc(value)}</b><span>${esc(label)}</span></button>`;
}
function closeDrawer() { document.body.classList.remove('drawer-open'); }
function openDrawer(title, subtitle, body, actions = '') {
  drawerTitle.textContent = title || 'Details';
  drawerSubtitle.textContent = subtitle || '';
  drawerBody.innerHTML = body || '';
  drawerActions.innerHTML = actions || '';
  document.body.classList.add('drawer-open');
}
async function guarded(label, fn, warning = '') {
  const suffix = warning ? `\n\n${warning}` : '';
  if (!confirm(`${label}?${suffix}`)) return;
  try {
    status.textContent = `${label}...`;
    await fn();
    await loadAll();
    closeDrawer();
    status.textContent = 'Ready.';
  } catch (err) {
    status.textContent = err.message;
  }
}
async function approveApproval(event, approvalId) {
  if (event) event.stopPropagation();
  const approval = state.approvals.find(item => item.id === approvalId);
  const risk = approval?.action?.risk_level || '';
  const warning = ['DESTRUCTIVE', 'SENSITIVE'].includes(String(risk).toUpperCase()) || approval?.action?.tool_name === 'codex.run_task'
    ? 'This can run code or perform a high-risk action.'
    : '';
  await guarded('Approve this action', () => send('POST', `/api/core/approvals/${approvalId}/decision`, {approved:true, decided_by:'jarvis-core-console'}), warning);
}
async function rejectApproval(event, approvalId) {
  if (event) event.stopPropagation();
  await guarded('Reject this action', () => send('POST', `/api/core/approvals/${approvalId}/decision`, {approved:false, decided_by:'jarvis-core-console'}));
}
async function dismissNotification(event, notificationId) {
  if (event) event.stopPropagation();
  try {
    status.textContent = 'Dismissing...';
    await send('POST', `/api/core/notifications/${encodeURIComponent(notificationId)}/dismiss`, {delivered_by:'jarvis-core-console'});
    state.notifications = state.notifications.map(item => item.id === notificationId ? {...item, status:'dismissed'} : item);
    renderOverview({ap:{approvals:state.approvals}, diag:{checks:state.diagnostics}, cx:{codex_tasks:state.codexTasks}, runs:{runs:state.runs}, workers:{workers:state.workers}, downloads:{scans:state.downloads}, task:{tasks:state.tasks}, maint:{maintenance:state.maintenance}, notif:{notifications:state.notifications}, auto:{automations:state.automations}, gm:state.gmailCleanup, br:state.brief});
    if (document.body.classList.contains('drawer-open') && drawerTitle.textContent === 'Inbox') openNotificationsHub();
    status.textContent = 'Dismissed.';
  } catch (err) {
    status.textContent = err.message;
  }
}
async function dismissAllNotifications() {
  const rows = usefulRows('notifications', state.notifications);
  if (!rows.length) return;
  if (!confirm(`Dismiss ${rows.length} active notification(s)?`)) return;
  try {
    status.textContent = 'Dismissing notifications...';
    for (const item of rows) {
      await send('POST', `/api/core/notifications/${encodeURIComponent(item.id)}/dismiss`, {delivered_by:'jarvis-core-console'});
    }
    await loadAll();
    openNotificationsHub();
    status.textContent = `Dismissed ${rows.length} notification(s).`;
  } catch (err) {
    status.textContent = err.message;
  }
}
async function approveNotification(event, notificationId) {
  if (event) event.stopPropagation();
  const notification = state.notifications.find(item => item.id === notificationId);
  const approval = linkedApprovalForNotification(notification);
  if (!approval) {
    status.textContent = 'No linked approval found for this notification.';
    return;
  }
  const risk = approval?.action?.risk_level || '';
  const warning = ['DESTRUCTIVE', 'SENSITIVE'].includes(String(risk).toUpperCase()) || approval?.action?.tool_name === 'codex.run_task'
    ? 'This can run code or perform a high-risk action.'
    : '';
  await guarded('Approve this request', async () => {
    await send('POST', `/api/core/approvals/${approval.id}/decision`, {approved:true, decided_by:'jarvis-core-console'});
    await send('POST', `/api/core/notifications/${encodeURIComponent(notificationId)}/dismiss`, {delivered_by:'jarvis-core-console', reason:'approval_approved'}).catch(() => {});
  }, warning);
}
async function rejectNotification(event, notificationId) {
  if (event) event.stopPropagation();
  const notification = state.notifications.find(item => item.id === notificationId);
  const approval = linkedApprovalForNotification(notification);
  if (!approval) {
    status.textContent = 'No linked approval found for this notification.';
    return;
  }
  await guarded('Reject this request', async () => {
    await send('POST', `/api/core/approvals/${approval.id}/decision`, {approved:false, decided_by:'jarvis-core-console'});
    await send('POST', `/api/core/notifications/${encodeURIComponent(notificationId)}/dismiss`, {delivered_by:'jarvis-core-console', reason:'approval_rejected'}).catch(() => {});
  });
}
function renderApprovals(data) {
  state.approvals = data.approvals || [];
}
function renderDiagnostics(data) {
  state.diagnostics = data.checks || [];
}
function renderCodex(data) {
  state.codexTasks = data.codex_tasks || [];
}
function renderCodexWorker(data) {
  state.codexJobs = data.jobs || [];
}
function renderList(target, key, data, titleField) {
  const rows = data[key] || [];
  state[key] = rows;
  const kind = key === 'tasks' ? 'task' : key === 'evidence' ? 'evidence' : key === 'maintenance' ? 'maintenance' : key === 'notifications' ? 'notifications' : 'audit';
  const countIds = {tasks: 'tasksCount', evidence: 'evidenceCount', maintenance: 'maintenanceCount', notifications: 'notificationsCount', events: 'auditCount'};
  if (!target) return;
  const visibleRows = usefulRows(key, rows);
  setCount(countIds[key], `${visibleRows.length}`);
  target.innerHTML = visibleRows.length ? visibleRows.slice(0,5).map((r) => {
    const idx = rows.indexOf(r);
    if (key === 'tasks') return compactButton(kind, idx, displayTitle(r.title), r.status || '', r.priority ? `P${r.priority}` : '');
    if (key === 'evidence') return compactButton(kind, idx, evidenceTitle(r), r.evidence_type || '');
    if (key === 'maintenance') return compactButton(kind, idx, maintenanceTitle(r), r.service_name || r.status || '', r.status || '');
    if (key === 'notifications') return notificationButton(r, idx);
    return compactButton(kind, idx, displayTitle(r[titleField] || r.title || r.summary || r.event_type || r.id), r.created_at || '');
  }).join('') : emptyState('No records.');
}
function renderBrief(data) {
  state.brief = data || {};
  const taskCount = (data.tasks_due_soon || []).length;
  const approvalsCount = (data.pending_approvals || []).length;
  const maintCount = (data.open_maintenance || []).length;
  setCount('briefCount', data.kind || 'brief');
  const actions = (data.recommended_actions || []).slice(0,4).map((title, idx) => `<button onclick="makeBriefTaskFromRecommendation(${idx})"><span class="compact-title">${esc(displayTitle(title))}</span></button>`).join('') || `<span class="muted">No recommendations yet.</span>`;
  const taskRows = (data.tasks_due_soon || []).slice(0,5).map((task) => `<button onclick="openTaskById('${esc(task.id)}')"><span class="compact-title">${esc(displayTitle(task.title))}</span><span class="compact-sub">${esc(task.due_at || task.status || '')}</span></button>`).join('') || `<span class="muted">No task pressure.</span>`;
  const approvalRows = (data.pending_approvals || []).slice(0,4).map((approval) => approvalButton(approval)).join('') || `<span class="muted">No pending approvals.</span>`;
  const maintenanceRows = (data.open_maintenance || []).slice(0,4).map((m) => `<button onclick="openMaintenanceById('${esc(m.id)}')"><span class="compact-title">${esc(maintenanceTitle(m))}</span><span class="compact-sub">${esc(m.service_name || m.status || '')}</span></button>`).join('') || `<span class="muted">No open maintenance.</span>`;
  brief.innerHTML = `<div>${pillButton(`${taskCount} tasks`, 'openTasksHub()')}${pillButton(`${approvalsCount} approvals`, 'openApprovalsHub()')}${pillButton(`${maintCount} maint`, 'openMaintenanceHub()')}<button class="quick-action" title="Brief details" aria-label="Brief details" onclick="openBrief()">&#8942;</button></div><div class="brief-layout"><pre class="brief-text">${esc(data.text || 'No brief text yet.')}</pre><div class="brief-stack"><div class="brief-section"><b>Next</b>${actions}</div><div class="brief-section"><b>Tasks</b>${taskRows}</div><div class="brief-section"><b>Approvals</b>${approvalRows}</div><div class="brief-section"><b>Maintenance</b>${maintenanceRows}</div></div></div>`;
}
function renderDrive(data) {
  state.drive = data || {};
  const rows = data.items || [];
  setCount('driveCount', `${state.selectedDriveFolders.length} selected`);
  const staged = state.driveStaging?.total || 0;
  drive.innerHTML = `<div class="actions"><button class="quick-action approve" title="Open Drive browser" aria-label="Open Drive browser" onclick="openDrive()">&#128193;</button><button class="quick-action" title="Propose staging copy" aria-label="Propose staging copy" onclick="proposeDriveStagingCopy()">&#8681;</button><button class="quick-action" title="Scan metadata inventory" aria-label="Scan metadata inventory" onclick="loadFullDriveInventory()">&#128269;</button></div>` +
    `<button class="item-button" onclick="openItem('drive', 0)"><div class="compact-line"><span class="compact-title">${esc(data.summary || 'Drive ready')}</span><span class="pill">${staged} staged</span></div><div class="compact-sub">Browse root folders, select directories, then propose an approval-gated copy batch.</div></button>` +
    (rows.length ? rows.slice(0,4).map((item, idx) => compactButton('driveItem', idx, item.name, `${item.life_category_label || item.life_category || 'Needs Review'} / ${item.migration_action || item.suggested_action || 'needs_review'}`)).join('') : '');
}
function renderDriveStaging(data) {
  state.driveStaging = data || {};
  const manifests = data.manifests || [];
  driveStaging.innerHTML = `<button class="item-button" onclick="openItem('driveStaging', 0)"><b>${esc(data.summary || 'No staged Drive items')}</b><br><span class="muted">${esc(data.total_bytes || 0)} bytes &middot; ${esc(JSON.stringify(data.by_category || {}))}</span></button>` +
    (manifests.length ? manifests.slice(0,6).map((item, idx) => itemButton('stagedDriveItem', idx, `<b>${esc(item.name || item.file_id)}</b><br><span class="muted">${esc(item.category || '')} &middot; ${esc(item.destination || '')} &middot; ${esc(item.staged_relative_path || '')}</span>`)).join('') : '<span class="muted">No staged files yet.</span>');
}
function renderDriveDestinations(data) {
  state.driveDestinations = data || {};
  const services = data.services || {};
  const staged = data.staged_items || [];
  const serviceRows = Object.values(services).map(s => `<span class="${s.ready ? 'ok' : 'bad'}">${s.ready ? 'OK' : 'WAIT'}</span> ${esc(s.label)}`).join('<br>');
  driveDestinations.innerHTML = `<button class="item-button" onclick="openItem('driveDestinations', 0)"><b>${esc(data.summary || 'Destination readiness')}</b><br><span class="muted">${serviceRows}</span></button>` +
    (staged.length ? staged.slice(0,6).map((item, idx) => itemButton('smartDestinationItem', idx, `<b>${esc(item.name)}</b><br><span class="muted">${esc(item.destination)} &middot; ${item.ready ? 'ready' : 'waiting'}</span>`)).join('') : '<span class="muted">No staged destination decisions yet.</span>');
}
function approvalActions(a) {
  const risk = String(a.action?.risk_level || '').toUpperCase();
  const warning = ['DESTRUCTIVE', 'SENSITIVE'].includes(risk) || a.action?.tool_name === 'codex.run_task' ? 'This can run code or perform a high-risk action.' : '';
  return `<button class="quick-action approve" title="Approve" aria-label="Approve" onclick="guarded('Approve this action', () => send('POST','/api/core/approvals/${esc(a.id)}/decision',{approved:true,decided_by:'jarvis-core-console'}), '${esc(warning)}')">&#10003;</button>
    <button class="quick-action reject" title="Reject" aria-label="Reject" onclick="guarded('Reject this action', () => send('POST','/api/core/approvals/${esc(a.id)}/decision',{approved:false,decided_by:'jarvis-core-console'}))">&#215;</button>`;
}
function openApproval(a) {
  const action = a.action || {};
  openDrawer(action.preview?.summary || action.tool_name || a.id, `Approval ${a.status}`, [
    row('Reason', a.reason), row('Risk level', action.risk_level), row('Tool', action.tool_name),
    row('Preview', action.preview), row('Action id', action.id), row('Approval id', a.id),
    row('Decided by', a.decided_by), row('Decided at', a.decided_at)
  ].join(''), a.status === 'pending' ? approvalActions(a) : '');
}
function openTask(t) {
  const actions = t.status === 'completed'
    ? `<button class="quick-action approve" title="Reopen task" aria-label="Reopen task" onclick="guarded('Reopen task', () => send('PATCH','/api/core/tasks/${esc(t.id)}',{status:'open'}))">&#8634;</button>`
    : `<button class="quick-action approve" title="Complete task" aria-label="Complete task" onclick="guarded('Complete task', () => send('POST','/api/core/tasks/${esc(t.id)}/complete'))">&#10003;</button>`;
  openDrawer(t.title || t.id, `Task ${t.status || ''}`, [
    row('Priority', t.priority), row('Due', t.due_at), row('Estimated minutes', t.estimated_minutes),
    row('Effort', t.effort_level), row('Project id', t.project_id), row('Source', t.source),
    row('Tags', t.tags), row('Score', t.score), row('Created', t.created_at),
    row('Updated', t.updated_at), row('Completed', t.completed_at), row('Task id', t.id)
  ].join(''), actions);
}
function openEvidence(e) {
  const uri = e.uri ? `<a href="${esc(e.uri)}" target="_blank" rel="noreferrer">${esc(e.uri)}</a>` : '';
  openDrawer(e.title || e.id, `Evidence ${e.evidence_type || ''}`, [
    row('Summary', e.summary), row('URI', uri), row('Project id', e.project_id),
    row('Tags', e.tags), row('Captured', e.captured_at), row('Evidence id', e.id)
  ].join(''));
}
function openMaintenance(m) {
  const actions = m.status === 'resolved'
    ? `<button class="quick-action approve" title="Reopen maintenance" aria-label="Reopen maintenance" onclick="guarded('Reopen maintenance record', () => send('PATCH','/api/core/maintenance/${esc(m.id)}',{status:'open',resolved:false}))">&#8634;</button>`
    : `<button class="quick-action approve" title="Resolve maintenance" aria-label="Resolve maintenance" onclick="guarded('Resolve maintenance record', () => send('PATCH','/api/core/maintenance/${esc(m.id)}',{resolved:true}))">&#10003;</button>`;
  openDrawer(m.summary || m.service_name || m.id, `Maintenance ${m.status || ''}`, [
    row('Service', m.service_name), row('Type', m.record_type), row('Details', m.details),
    row('Next check', m.next_check_at), row('Resolved', m.resolved_at), row('Created', m.created_at),
    row('Updated', m.updated_at), row('Record id', m.id)
  ].join(''), actions);
}
function openTasksHub() {
  const rows = state.tasks || [];
  const openRows = rows.filter(task => task.status !== 'completed');
  const visibleRows = openRows.length ? openRows : rows;
  openDrawer('Tasks', `${visibleRows.length} visible`, visibleRows.length ? visibleRows.slice(0,30).map((task) => {
    const idx = state.tasks.indexOf(task);
    return compactButton('task', idx, displayTitle(task.title), task.due_at || task.status || '', task.priority ? `P${task.priority}` : '');
  }).join('') : emptyState('No tasks surfaced right now.'));
}
function openEvidenceHub() {
  const rows = usefulRows('evidence', state.evidence || []);
  openDrawer('Evidence', `${rows.length} item(s)`, rows.length ? rows.slice(0,30).map((item) => {
    const idx = state.evidence.indexOf(item);
    return compactButton('evidence', idx, evidenceTitle(item), item.evidence_type || item.source || '');
  }).join('') : emptyState('No evidence surfaced right now.'));
}
function openMaintenanceHub() {
  const rows = state.maintenance.filter(m => m.status !== 'resolved');
  openDrawer('Maintenance', `${rows.length} open`, rows.length ? rows.slice(0,12).map((m, idx) => compactButton('maintenance', state.maintenance.indexOf(m), maintenanceTitle(m), m.service_name || m.status || '', m.status || '')).join('') : emptyState('No open maintenance records.'));
}
function openApprovalsHub() {
  openDrawer('Approvals', `${state.approvals.length} pending`, state.approvals.length ? state.approvals.slice(0,12).map((a, idx) => {
    return approvalButton(a, idx);
  }).join('') : emptyState('No pending approvals.'));
}
function openDiagnosticsHub() {
  const failed = state.diagnostics.filter(c => !c.ok && !c.optional);
  const rows = failed.length ? failed : state.diagnostics;
  const maintenance = state.maintenance.filter(m => m.status !== 'resolved');
  const body = (maintenance.length ? compactButton('maintenanceHub', 0, 'Maintenance', `${maintenance.length} open records`, 'open') : '') +
    (rows.length ? rows.slice(0,12).map((c) => {
      const idx = state.diagnostics.indexOf(c);
      return compactButton('diagnostic', idx, c.name, c.summary || c.error || c.status || '', c.ok ? 'OK' : 'FAIL');
    }).join('') : emptyState('No diagnostics returned.'));
  openDrawer('Diagnostics', failed.length ? `${failed.length} need attention` : `${state.diagnostics.length} OK`, body);
}
function openCodexHub() {
  const coreRows = state.codexTasks.slice(0,8).map((t, idx) => compactButton('codexTask', idx, displayTitle(t.request || 'Coding task'), 'Core task', t.status || 'task')).join('');
  const workerRows = state.codexJobs.slice(0,6).map((j, idx) => {
    const summary = (j.summary || '').includes('--ask-for-approval') ? 'Historical failed job from old Codex CLI flag. Current worker uses the corrected flag.' : (j.summary || '');
    return compactButton('codexJob', idx, 'Worker artifact', summary, j.status || 'job');
  }).join('');
  openDrawer('Codex', `${state.codexTasks.length} core / ${state.codexJobs.length} worker`, coreRows + workerRows || emptyState('No Codex activity yet.'));
}
function openRunsHub() {
  const rows = state.runs || [];
  openDrawer('Runs', `${rows.length} durable`, rows.length ? rows.slice(0,12).map((r, idx) => compactButton('run', idx, displayTitle(r.user_request || r.id), r.source || r.created_at || '', r.status || '')).join('') : emptyState('No durable orchestration runs yet.'));
}
function openWorkersHub() {
  const rows = state.workers || [];
  const actions = `<button class="quick-action approve" title="Scan Downloads" aria-label="Scan Downloads" onclick="requestDownloadsScan()">&#128269;</button>`;
  openDrawer('Workers', `${rows.length} registered`, rows.length ? rows.map((w, idx) => compactButton('worker', idx, displayTitle(w.display_name || w.id), `${w.worker_type || 'worker'} / ${(w.capabilities || []).length} capabilities`, w.status || '')).join('') : emptyState('No workers registered yet.'), actions);
}
function openDownloadsHub() {
  const scans = state.downloads || [];
  const actions = `<button class="quick-action approve" title="Scan Downloads" aria-label="Scan Downloads" onclick="requestDownloadsScan()">&#128269;</button><button class="quick-action" title="Plan destinations" aria-label="Plan destinations" onclick="planDownloadsDestinations()">&#9873;</button><button class="quick-action" title="Propose cleanup" aria-label="Propose cleanup" onclick="proposeDownloadsCleanup()">&#128193;</button><button class="icon-button" title="Refresh" aria-label="Refresh" onclick="loadAll().then(openDownloadsHub)">&#8635;</button>`;
  const body = scans.length ? scans.slice(0,8).map((scan, idx) => {
    const preview = scan.preview || {};
    const title = scan.run?.user_request || 'Downloads scan';
    const subtitle = `${preview.file_count || 0} files / ${preview.directory_count || 0} dirs`;
    return compactButton('downloadScan', idx, title, subtitle, scan.status || scan.run?.status || '');
  }).join('') : emptyState('No Downloads scans yet.');
  openDrawer('Downloads', 'Read-only janitor preview', body, actions);
}
async function requestDownloadsScan() {
  await send('POST', '/api/core/desktop/downloads/scan', {max_items: 1000, recursive: false, idempotency_key: `downloads-scan-${Date.now()}`});
  await loadAll();
  openDownloadsHub();
  status.textContent = 'Downloads scan queued. Keep Jarvis Desktop worker running to complete it.';
}
async function proposeDownloadsCleanup() {
  const latest = (state.downloads || [])[0];
  const payload = {scan_run_id: latest?.run?.id, auto_approve_low_risk: true, include_quarantine: true, idempotency_key: `downloads-cleanup-${Date.now()}`};
  await send('POST', '/api/core/desktop/downloads/propose-cleanup', payload);
  await loadAll();
  openDownloadsHub();
  status.textContent = 'Downloads cleanup proposed. Low-risk category moves are queued; quarantine awaits approval.';
}
async function planDownloadsDestinations() {
  const latest = (state.downloads || [])[0];
  status.textContent = 'Planning Downloads destinations...';
  state.downloadsDestinationPlan = await send('POST', '/api/core/desktop/downloads/destination-plan', {scan_run_id: latest?.run?.id, max_items: 200});
  openDownloadsDestinationPlan();
  status.textContent = 'Downloads destination plan ready.';
}
function openDownloadsDestinationPlan() {
  const data = state.downloadsDestinationPlan || {};
  const items = data.items || [];
  const counts = `<div class="actions">${pillButton(`${items.length} files`, 'openDownloadsDestinationPlan()')}${Object.entries(data.by_destination || {}).map(([k,v]) => pillButton(`${k} ${v}`, `openDownloadsDestinationBucket('${enc(k)}')`)).join('')}</div>`;
  const tags = Object.entries(data.by_tag || {}).slice(0,12).map(([k,v]) => pillButton(`${k} ${v}`, `openDownloadsTagBucket('${enc(k)}')`)).join('');
  const serviceRows = Object.entries(data.services || {}).filter(([key]) => ['paperless','nextcloud','needs_review'].includes(key)).map(([key, svc]) => pillButton(`${svc.label || key} ${svc.ready ? 'ready' : 'wait'}`, `openDownloadsService('${enc(key)}')`, svc.ready ? 'ok' : 'warn')).join('');
  const rows = items.length ? items.slice(0,40).map((item, idx) => itemButton('downloadDestinationItem', idx, `<b>${esc(item.name)}</b><br><span class="muted">${esc(item.destination)} &middot; ${esc((item.tags || []).join(', '))}</span>`)).join('') : emptyState('No destination plan yet.');
  openDrawer('Downloads Destinations', data.summary || 'Plan long-term filing', `${counts}<div class="compact-sub">${serviceRows}</div><div class="compact-sub">${tags}</div><div class="hub-card">${rows}</div>`, `<button class="icon-button" title="Refresh" aria-label="Refresh" onclick="planDownloadsDestinations()">&#8635;</button>`);
}
function openDownloadsDestinationBucket(encodedDestination) {
  const destination = decodeURIComponent(encodedDestination);
  const items = (state.downloadsDestinationPlan.items || []).filter(item => item.destination === destination);
  const rows = items.length ? items.slice(0,80).map((item) => {
    const idx = (state.downloadsDestinationPlan.items || []).indexOf(item);
    return itemButton('downloadDestinationItem', idx, `<b>${esc(item.name)}</b><br><span class="muted">${esc((item.tags || []).join(', ')) || esc(item.reason || '')}</span>`);
  }).join('') : emptyState('No files in this destination.');
  openDrawer(destination, `${items.length} planned file(s)`, rows, `<button class="icon-button" title="Back" aria-label="Back" onclick="openDownloadsDestinationPlan()">&#8592;</button>`);
}
function openDownloadsTagBucket(encodedTag) {
  const tag = decodeURIComponent(encodedTag);
  const items = (state.downloadsDestinationPlan.items || []).filter(item => (item.tags || []).includes(tag));
  const rows = items.length ? items.slice(0,80).map((item) => {
    const idx = (state.downloadsDestinationPlan.items || []).indexOf(item);
    return itemButton('downloadDestinationItem', idx, `<b>${esc(item.name)}</b><br><span class="muted">${esc(item.destination)} &middot; ${esc(item.reason || '')}</span>`);
  }).join('') : emptyState('No files with this tag.');
  openDrawer(`#${tag}`, `${items.length} planned file(s)`, rows, `<button class="icon-button" title="Back" aria-label="Back" onclick="openDownloadsDestinationPlan()">&#8592;</button>`);
}
function openDownloadsService(encodedKey) {
  const key = decodeURIComponent(encodedKey);
  const svc = (state.downloadsDestinationPlan.services || {})[key] || {};
  openDrawer(svc.label || key, svc.ready ? 'Ready' : 'Needs attention', [
    row('Ready', svc.ready),
    row('Import root', svc.import_root),
    row('Consume root', svc.consume_root),
    row('Reason', svc.reason),
    row('Service', svc)
  ].join(''), `<button class="icon-button" title="Back" aria-label="Back" onclick="openDownloadsDestinationPlan()">&#8592;</button>`);
}
function openCalendarHub() {
  const br = state.brief || {};
  const calendar = br.google?.calendar || {};
  const events = calendar.events || br.calendar_events || [];
  const rows = events.length ? events.slice(0,12).map((event) => `<div class="mail-row"><div class="mail-subject">${esc(displayTitle(event.summary || event.title || event.name || 'Calendar event'))}</div><div class="mail-from">${esc(event.start || event.starts_at || event.when || '')}</div></div>`).join('') : emptyState('No calendar events surfaced in the current brief.');
  openDrawer('Calendar', br.kind || 'current brief', `<div class="hub-card">${rows}</div>${row('Summary', calendar.text || br.google?.text || '')}`);
}
function openNotificationsHub() {
  const rows = usefulRows('notifications', state.notifications);
  const actions = rows.length ? `<button class="quick-action reject" title="Dismiss all active" aria-label="Dismiss all active" onclick="dismissAllNotifications()">&#215;</button><button class="icon-button" title="Refresh" aria-label="Refresh" onclick="loadAll().then(openNotificationsHub)">&#8635;</button>` : `<button class="icon-button" title="Refresh" aria-label="Refresh" onclick="loadAll().then(openNotificationsHub)">&#8635;</button>`;
  openDrawer('Inbox', `${rows.length} active`, rows.length ? rows.slice(0,12).map((n) => notificationButton(n, state.notifications.indexOf(n))).join('') : emptyState('No active notifications.'), actions);
}
function openAuditHub() {
  const rows = state.audit || [];
  openDrawer('Audit', `${rows.length} recent`, rows.length ? rows.slice(0,40).map((item) => {
    const idx = state.audit.indexOf(item);
    return compactButton('audit', idx, displayTitle(item.event_type || item.id), item.created_at || '', item.actor || '');
  }).join('') : emptyState('No audit events surfaced right now.'));
}
function automationTitle(a) {
  return displayTitle(a.name || 'Automation');
}
function automationSubtitle(a) {
  return [a.schedule, a.mode].filter(Boolean).join(' / ');
}
function openAutomationsHub() {
  const rows = state.automations || [];
  const active = rows.filter(a => a.status !== 'disabled').length;
  const body = rows.length ? `<div class="hub-grid">${rows.map((a, idx) => automationCard(a, idx)).join('')}</div>` : emptyState('No automation inventory available.');
  const actions = `<button class="quick-action approve" title="Create automation" aria-label="Create automation" onclick="createAutomation()">+</button><button class="icon-button" title="Refresh" aria-label="Refresh" onclick="loadAll().then(openAutomationsHub)">&#8635;</button>`;
  openDrawer('Automations', `${active} available`, body, actions);
}
function automationCard(a, idx) {
  const visibleStatus = a.last_status || a.status || 'available';
  const statusClass = String(visibleStatus).includes('fail') || String(visibleStatus).includes('error') ? 'bad' : a.status === 'attention' ? 'warn' : 'ok';
  const output = typeof a.last_output === 'object' ? JSON.stringify(a.last_output) : (a.last_output || a.summary || '');
  return `<button class="automation-card" onclick="openItem('automation', ${idx})">
    <div class="compact-line"><span class="compact-title">${esc(automationTitle(a))}</span><span class="pill ${statusClass}">${esc(visibleStatus)}</span></div>
    <div class="automation-meta"><span title="${esc(a.last_run || '')}">last ${esc(shortWhen(a.last_run))}</span><span title="${esc(a.next_run || '')}">next ${esc(shortWhen(a.next_run))}</span></div>
    <div class="compact-sub">${esc(a.schedule || a.mode || '')}</div>
    <div class="automation-output">${esc(output || 'No output yet.')}</div>
  </button>`;
}
function shortWhen(value) {
  if (!value) return 'not recorded';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString([], {month:'short', day:'numeric', hour:'numeric', minute:'2-digit'});
}
function openGmailCleanupHub() {
  const data = state.gmailCleanup || {};
  const counts = data.counts || {};
  const actions = `<button class="icon-button" title="Refresh" onclick="loadAll().then(openGmailCleanupHub)">&#8635;</button><button class="quick-action approve" title="Classify with Jarvis labels" onclick="proposeGmailCleanup('label_classifications')" aria-label="Classify">&#9873;</button><button class="quick-action" title="Archive newsletters" onclick="proposeGmailCleanup('archive_newsletters')" aria-label="Archive newsletters">&#128230;</button><button class="quick-action" title="Mark old unread read" onclick="proposeGmailCleanup('mark_old_unread_read')" aria-label="Mark read">&#10003;</button><button class="quick-action" title="Star needs-reply" onclick="proposeGmailCleanup('star_needs_reply')" aria-label="Star needs-reply">&#9733;</button>`;
  const summary = `<div class="actions">${pillButton(`${counts.needs_reply_candidates || 0} reply candidates`, "openGmailBucket('needs_reply')")}${pillButton(`${counts.medical_school || 0} medical school`, "openGmailBucket('medical_school')")}${pillButton(`${counts.admissions || 0} admissions`, "openGmailBucket('admissions')")}${pillButton(`${counts.finance_receipts || 0} finance`, "openGmailBucket('finance_receipts')")}${pillButton(`${counts.promotions || 0} promotions auto-filed`, "openGmailBucket('promotions')")}${pillButton(`${counts.low_value_updates || 0} updates auto-filed`, "openGmailBucket('low_value_updates')")}${pillButton(`${counts.old_unread || 0} old unread`, "openGmailBucket('old_unread')")}</div>`;
  const senders = (data.top_senders || []).slice(0,8).map(s => pillButton(`${s.sender} ${s.sample_count}`, `openGmailSender('${enc(s.sender)}')`)).join('') || emptyState('No senders sampled.');
  const body = summary + `<div class="hub-grid">
    ${gmailBucketSection('Medical school', data.medical_school, 'medical_school')}
    ${gmailBucketSection('Admissions', data.admissions, 'admissions')}
    ${gmailBucketSection('Needs reply', data.needs_reply, 'needs_reply')}
    ${gmailBucketSection('Finance / receipts', data.finance_receipts, 'finance_receipts')}
    ${gmailBucketSection('Old unread', data.old_unread, 'old_unread')}
    <div class="hub-card"><div class="hub-card-head"><h3>Top senders</h3></div>${senders}</div>
  </div>`;
  openDrawer('Gmail', 'Read-only scan; changes require approval', body, actions);
}
function gmailBucketSection(title, rows, key) {
  const items = (rows || []).slice(0,5).map((item, idx) => mailPreview(item, key, idx)).join('') || emptyState('No matches.');
  const count = (rows || []).length;
  return `<div class="hub-card"><div class="hub-card-head"><h3>${esc(title)}</h3>${pillButton(count, `openGmailBucket('${key}')`)}</div>${items}</div>`;
}
function mailPreview(item, key, idx) {
  return `<button class="item-button" onclick="openGmailMessage('${key}', ${idx})"><div class="mail-subject">${esc(displayTitle(item.subject || item.snippet || 'Message'))}</div><div class="mail-from">${esc(item.from || '')}</div></button>`;
}
function gmailRowsFor(key) {
  const data = state.gmailCleanup || {};
  return data[key] || [];
}
function openGmailBucket(key) {
  const labels = {
    medical_school: 'Medical School',
    admissions: 'Admissions',
    needs_reply: 'Needs Reply',
    finance_receipts: 'Finance / Receipts',
    old_unread: 'Old Unread',
    promotions: 'Promotions',
    low_value_updates: 'Updates'
  };
  const rows = gmailRowsFor(key);
  const body = rows.length ? rows.slice(0,80).map((item, idx) => mailPreview(item, key, idx)).join('') : emptyState('No messages in this group.');
  openDrawer(labels[key] || displayTitle(key), `${rows.length} message(s)`, body, `<button class="icon-button" title="Back" aria-label="Back" onclick="openGmailCleanupHub()">&#8592;</button>`);
}
function openGmailSender(encodedSender) {
  const sender = decodeURIComponent(encodedSender);
  const keys = ['medical_school','admissions','needs_reply','finance_receipts','old_unread','promotions','low_value_updates','likely_newsletters'];
  const matches = [];
  keys.forEach(key => gmailRowsFor(key).forEach((item, idx) => {
    if (String(item.from || '').includes(sender)) matches.push({key, idx, item});
  }));
  const body = matches.length ? matches.slice(0,80).map(match => mailPreview(match.item, match.key, match.idx)).join('') : row('Sender', sender);
  openDrawer(sender, `${matches.length} sampled message(s)`, body, `<button class="icon-button" title="Back" aria-label="Back" onclick="openGmailCleanupHub()">&#8592;</button>`);
}
function openGmailMessage(key, idx) {
  const item = gmailRowsFor(key)[idx];
  if (!item) return;
  openDrawer(displayTitle(item.subject || item.snippet || 'Message'), displayTitle(key), [
    row('From', item.from),
    row('Date', item.date || item.internal_date),
    row('Snippet', item.snippet),
    row('Suggested labels', item.suggested_labels || item.labels),
    row('Reason', item.reason),
    row('Thread id', item.thread_id),
    row('Message id', item.id || item.message_id),
    row('Raw', item)
  ].join(''), `<button class="icon-button" title="Back" aria-label="Back" onclick="openGmailBucket('${key}')">&#8592;</button>`);
}
async function proposeGmailCleanup(actionType, maxResults = 25) {
  await send('POST', '/api/core/gmail/cleanup/propose', {action_type: actionType, max_results: maxResults, idempotency_key: `gmail-cleanup-${actionType}-${Date.now()}`});
  await loadAll();
  status.textContent = 'Gmail cleanup proposed for approval.';
}
function openAutomation(a) {
  const key = esc(a.key || '');
  const canSchedule = Boolean(a.job_type);
  const actions = a.key ? [
    `<button class="quick-action approve" title="Run now" aria-label="Run now" onclick="runAutomation('${key}')">&#9654;</button>`,
    canSchedule ? `<button class="quick-action" title="Edit schedule" aria-label="Edit schedule" onclick="editAutomation('${key}')">&#9998;</button>` : '',
    canSchedule && a.status === 'enabled' ? `<button class="quick-action reject" title="Pause schedule" aria-label="Pause schedule" onclick="pauseAutomation('${key}')">&#10074;&#10074;</button>` : '',
    canSchedule && a.status !== 'enabled' ? `<button class="quick-action approve" title="Resume schedule" aria-label="Resume schedule" onclick="resumeAutomation('${key}')">&#9654;</button>` : ''
  ].filter(Boolean).join('') : '';
  openDrawer(automationTitle(a), a.status || 'Automation', [
    row('Category', a.category), row('Job', a.job_type), row('Mode', a.mode), row('Schedule', a.schedule),
    row('Last run', a.last_run || 'Not recorded'), row('Next run', a.next_run || 'Not scheduled by Core'),
    row('Last status', a.last_status), row('Channels', a.channels), row('Parameters', a.parameters), row('Summary', a.summary), row('Last output', a.last_output)
  ].join(''), actions);
}
async function runAutomation(key) {
  await guarded('Run automation now', () => send('POST', `/api/core/automations/${encodeURIComponent(key)}/run`, {}));
}
async function pauseAutomation(key) {
  await guarded('Pause automation', () => send('POST', `/api/core/automations/${encodeURIComponent(key)}/pause`, {}));
}
async function resumeAutomation(key) {
  await guarded('Resume automation', () => send('POST', `/api/core/automations/${encodeURIComponent(key)}/propose-update`, {status:'enabled', idempotency_key:`automation-resume-${key}-${Date.now()}`}));
  status.textContent = 'Resume proposed for approval.';
}
async function editAutomation(key) {
  const item = (state.automations || []).find(a => a.key === key);
  if (!item) return;
  const current = item.schedule_spec || {};
  const hour = prompt('Hour, 0-23', current.hour ?? '8');
  if (hour === null) return;
  const minute = prompt('Minute, 0-59', current.minute ?? '0');
  if (minute === null) return;
  const kind = prompt('Schedule kind: daily, weekly, or manual', current.schedule_kind || 'daily') || 'daily';
  const payload = {
    schedule: {schedule_kind: kind, hour: Number(hour), minute: Number(minute), weekdays: current.weekdays || []},
    idempotency_key: `automation-edit-${key}-${Date.now()}`
  };
  await send('POST', `/api/core/automations/${encodeURIComponent(key)}/propose-update`, payload);
  await loadAll();
  status.textContent = 'Automation edit proposed for approval.';
}
async function createAutomation() {
  const jobType = prompt('Job type: daily_brief, gmail_needs_reply_scan, gmail_cleanup_proposal, drive_inventory_scan, downloads_cleanup_proposal, homelab_health_check, pihole_health_check', 'daily_brief');
  if (!jobType) return;
  const name = prompt('Automation name', displayTitle(jobType));
  if (!name) return;
  const hour = prompt('Hour, 0-23', '8');
  if (hour === null) return;
  const minute = prompt('Minute, 0-59', '0');
  if (minute === null) return;
  const parameters = jobType === 'daily_brief' ? {kind: prompt('Brief kind: morning or evening', 'morning') || 'morning'} : {};
  await send('POST', '/api/core/automations/propose-create', {
    name,
    job_type: jobType,
    schedule: {schedule_kind:'daily', hour:Number(hour), minute:Number(minute), weekdays:[]},
    parameters,
    channels:['Homepage','Telegram'],
    idempotency_key:`automation-create-${Date.now()}`
  });
  await loadAll();
  status.textContent = 'Automation proposed for approval.';
}
function openDiagnostic(d) {
  const name = String(d.name || '').toLowerCase();
  const related = state.maintenance.filter(m => {
    const svc = String(m.service_name || '').toLowerCase();
    return svc && (svc.includes(name) || name.includes(svc));
  });
  openDrawer(d.name || 'Diagnostic', d.ok ? 'OK' : 'Needs attention', [
    row('Summary', d.summary), row('Status', d.status), row('Error', d.error),
    row('Raw check', d), row('Related maintenance', related.map(m => `${m.status}: ${m.summary}`).join('\n') || 'No related maintenance records.')
  ].join(''));
}
async function openCodexJob(j) {
  openDrawer(j.job_id, j.status || 'Codex worker job', '<span class="muted">Loading artifacts...</span>');
  const jobId = encodeURIComponent(j.job_id);
  const [detail, request, stdout, stderr] = await Promise.all([
    get(`/api/codex/jobs/${jobId}`),
    get(`/api/codex/jobs/${jobId}/artifact?name=request.json`).catch(err => ({error: err.message})),
    get(`/api/codex/jobs/${jobId}/artifact?name=stdout.txt`).catch(err => ({error: err.message})),
    get(`/api/codex/jobs/${jobId}/artifact?name=stderr.txt`).catch(err => ({error: err.message}))
  ]);
  const job = detail.job || detail;
  openDrawer(j.job_id, job.status || 'Codex worker job', [
    row('Summary', job.summary), row('Request path', request.path), row('Request preview', request.content || request.preview || request.error),
    row('Changed files', job.changed_files), row('Test results', job.test_results),
    row('Stdout path', stdout.path), row('Stdout preview', stdout.content || stdout.preview || stdout.error),
    row('Stderr path', stderr.path), row('Stderr preview', stderr.content || stderr.preview || stderr.error), row('Job metadata', job)
  ].join(''));
}
function openCodexTask(t) {
  openDrawer(t.request || t.action_id || 'Codex task', `Core status ${t.status || ''}`, [
    row('Action id', t.action_id || t.id), row('Status', t.status), row('Request', t.request),
    row('Artifacts', t.artifacts), row('Execution', t.execution), row('Approval', t.approval), row('Raw task', t)
  ].join(''));
}
function openRun(r) {
  openDrawer(displayTitle(r.user_request || r.id), r.status || 'Run', [
    row('Source', r.source), row('Priority', r.priority), row('Risk', r.risk_level), row('Requested by', r.requested_by),
    row('Summary', r.result_summary), row('Error', r.error_message), row('Context', r.request_context),
    row('Created', r.created_at), row('Run id', r.id)
  ].join(''));
}
function openWorker(w) {
  openDrawer(displayTitle(w.display_name || w.id), w.status || 'Worker', [
    row('Type', w.worker_type), row('Host', w.hostname), row('OS', w.os), row('Version', w.version),
    row('Last heartbeat', w.last_heartbeat_at), row('Capabilities', w.capabilities), row('Metadata', w.metadata),
    row('Worker id', w.id)
  ].join(''));
}
function openDownloadScan(scan) {
  const preview = scan.preview || {};
  const sample = Object.entries(preview.sample || {}).map(([name, items]) => {
    const rows = (items || []).slice(0,6).map(item => `<div class="mail-row"><div class="mail-subject">${esc(item.name || 'file')}</div><div class="mail-from">${esc(item.extension || '')} ${esc(item.size || '')}</div></div>`).join('');
    return `<div class="hub-card"><div class="hub-card-head"><h3>${esc(name)}</h3><span class="pill">${esc((items || []).length)}</span></div>${rows || emptyState('No sample')}</div>`;
  }).join('');
  openDrawer('Downloads Preview', scan.status || scan.run?.status || 'scan', [
    row('Mode', preview.mode), row('Root', preview.root), row('Files', preview.file_count), row('Directories', preview.directory_count),
    row('By category', preview.by_category), row('Duplicate candidates', preview.duplicates),
    `<div class="hub-grid">${sample}</div>`,
    row('Next step', preview.next_step), row('Run id', scan.run?.id), row('Job id', scan.job?.id)
  ].join(''));
}
async function makeBriefAction(actionType) {
  const title = prompt(actionType === 'calendar_hold' ? 'Calendar hold title' : 'Task title');
  if (!title) return;
  const minutes = Number(prompt('Estimated minutes', '30') || 30);
  const payload = { title, action_type: actionType, estimated_minutes: minutes, priority: 3, idempotency_key: `console-${actionType}-${Date.now()}` };
  if (actionType === 'calendar_hold') payload.when_text = prompt('When should Jarvis look for time?', 'tomorrow morning') || 'tomorrow morning';
  await send('POST', '/api/core/daily-brief/actions', payload);
  await loadAll();
  status.textContent = actionType === 'calendar_hold' ? 'Calendar hold proposed for approval.' : 'Task created from daily brief.';
}
async function makeBriefTaskFromRecommendation(idx) {
  const title = (state.brief.recommended_actions || [])[idx];
  if (!title) return;
  await send('POST', '/api/core/daily-brief/actions', {title: displayTitle(title), action_type: 'task', estimated_minutes: 30, priority: 3, idempotency_key: `console-rec-${Date.now()}-${idx}`});
  await loadAll();
  status.textContent = 'Task created from daily brief.';
}
function openTaskById(id) {
  const item = state.tasks.find(task => task.id === id);
  if (item) openTask(item);
}
function openApprovalById(id) {
  const item = state.approvals.find(approval => approval.id === id);
  if (item) openApproval(item);
}
function openMaintenanceById(id) {
  const item = state.maintenance.find(record => record.id === id);
  if (item) openMaintenance(item);
}
function openBriefEvidence(idx) {
  const item = (state.briefEvidence || [])[idx];
  if (item) openEvidence(item);
}
function openBrief() {
  const br = state.brief || {};
  state.briefEvidence = br.recent_evidence || [];
  const actions = `<button class="quick-action approve" title="Create task" aria-label="Create task" onclick="makeBriefAction('task')">+</button><button class="quick-action" title="Create calendar hold" aria-label="Create calendar hold" onclick="makeBriefAction('calendar_hold')">&#128197;</button>`;
  const google = br.google || {};
  const googleSummary = google.text || [
    google.calendar?.events ? `${google.calendar.events.length} calendar events` : '',
    google.gmail?.messages ? `${google.gmail.messages.length} mail items` : '',
    google.news?.items ? `${google.news.items.length} news items` : ''
  ].filter(Boolean).join(' / ');
  const taskRows = (br.tasks_due_soon || []).slice(0,8).map(task => `<button class="item-button" onclick="openTaskById('${esc(task.id)}')"><b>${esc(displayTitle(task.title))}</b><br><span class="muted">${esc(task.due_at || task.status || '')}</span></button>`).join('') || emptyState('No tasks surfaced.');
  const approvalRows = (br.pending_approvals || []).slice(0,8).map(approvalButton).join('') || emptyState('No approvals surfaced.');
  const maintenanceRows = (br.open_maintenance || []).slice(0,8).map(item => `<button class="item-button" onclick="openMaintenanceById('${esc(item.id)}')"><b>${esc(maintenanceTitle(item))}</b><br><span class="muted">${esc(item.service_name || item.status || '')}</span></button>`).join('') || emptyState('No maintenance surfaced.');
  const evidenceRows = state.briefEvidence.slice(0,8).map((item, idx) => `<button class="item-button" onclick="openBriefEvidence(${idx})"><b>${esc(evidenceTitle(item))}</b><br><span class="muted">${esc(item.evidence_type || item.source || '')}</span></button>`).join('') || emptyState('No evidence surfaced.');
  const googleActions = `<div class="actions">${pillButton('Calendar', 'openCalendarHub()')}${pillButton('Gmail', 'openGmailCleanupHub()')}</div>`;
  openDrawer('Daily Brief', br.kind || 'morning', [
    row('Brief', br.text),
    `<div class="hub-grid"><div class="hub-card"><div class="hub-card-head"><h3>Tasks</h3>${pillButton((br.tasks_due_soon || []).length, 'openTasksHub()')}</div>${taskRows}</div><div class="hub-card"><div class="hub-card-head"><h3>Approvals</h3>${pillButton((br.pending_approvals || []).length, 'openApprovalsHub()')}</div>${approvalRows}</div><div class="hub-card"><div class="hub-card-head"><h3>Maintenance</h3>${pillButton((br.open_maintenance || []).length, 'openMaintenanceHub()')}</div>${maintenanceRows}</div><div class="hub-card"><div class="hub-card-head"><h3>Evidence</h3>${pillButton(state.briefEvidence.length, 'openEvidenceHub()')}</div>${evidenceRows}</div></div>`,
    row('Google', `${googleSummary || 'No Google summary returned.'}`),
    googleActions
  ].join(''), actions);
}
function briefList(items, mapper) {
  const rows = (items || []).slice(0, 6).map(mapper).filter(Boolean);
  return rows.length ? rows.map(item => `- ${item}`).join('\n') : 'None';
}
async function openDrive() {
  const hasInventory = Boolean(state.drive.total);
  let plan = {mode: 'folder_selection'};
  if (hasInventory && !state.drivePlanLoaded) {
    plan = await send('POST', '/api/core/drive/migration-plan', {max_results: 100, include_paths: false});
    state.drivePlan = plan.plan || {};
    state.drivePlanLoaded = true;
  }
  if (!state.driveFoldersLoaded) await loadDriveFolders();
  const current = currentDriveFolder();
  if (current && !state.driveChildren[current.id]) await loadDriveChildren(current.id);
  const actions = driveBrowserActions(current);
  const subtitle = current ? driveTrailLabel() : 'My Drive roots';
  openDrawer('Drive', subtitle, driveBrowser(), actions);
}
async function loadDriveFolders() {
  const data = await send('POST', '/api/core/drive/folders', {max_results: 10000, my_drive_only: true, top_level_only: true, root_topics_only: true});
  state.driveFolders = data.folders || [];
  state.driveFoldersLoaded = true;
  return data;
}
async function refreshDriveFolders() {
  state.driveFoldersLoaded = false;
  state.driveChildren = {};
  await loadDriveFolders();
  await openDrive();
}
function selectedDriveFolderNames() {
  return state.selectedDriveFolders.map(id => driveFolderName(id) || id).join('\n') || 'No folders selected.';
}
function toggleDriveFolder(folderId) {
  const set = new Set(state.selectedDriveFolders);
  if (set.has(folderId)) set.delete(folderId); else set.add(folderId);
  state.selectedDriveFolders = Array.from(set);
  openDrive().catch(err => { status.textContent = err.message; });
}
function currentDriveFolder() {
  return state.driveTrail.length ? state.driveTrail[state.driveTrail.length - 1] : null;
}
function driveTrailLabel() {
  return state.driveTrail.map(folder => folder.name).join(' / ');
}
function driveFolderName(folderId) {
  const root = state.driveFolders.find(folder => folder.id === folderId);
  if (root) return root.name;
  for (const page of Object.values(state.driveChildren)) {
    const found = (page.folders || []).find(folder => folder.id === folderId);
    if (found) return found.name;
  }
  return '';
}
function driveBrowserActions(current) {
  const selected = state.selectedDriveFolders.length;
  const back = current ? `<button title="Back" onclick="driveBack()">&#8592;</button>` : '';
  const select = current ? `<button title="Select current folder" onclick="toggleDriveFolder('${esc(current.id)}')">${state.selectedDriveFolders.includes(current.id) ? '&#9745;' : '&#9744;'}</button>` : '';
  return `${back}${select}<button title="Refresh" aria-label="Refresh" onclick="refreshDriveFolders()">&#8635;</button><button class="quick-action approve" title="Propose staging copy" aria-label="Propose staging copy" onclick="proposeDriveStagingCopy()">&#8681;</button><button class="quick-action" title="Propose Nextcloud import" aria-label="Propose Nextcloud import" onclick="proposeNextcloudImport()">&#8680;</button><button class="quick-action" title="Propose Paperless import" aria-label="Propose Paperless import" onclick="proposePaperlessImport()">&#128196;</button><span class="pill">${selected}</span>`;
}
async function openDriveFolderAt(idx) {
  const current = currentDriveFolder();
  const folders = current ? ((state.driveChildren[current.id] || {}).folders || []) : (state.driveFolders || []);
  const folder = folders[idx];
  if (!folder) return;
  state.driveTrail.push({id: folder.id, name: folder.name});
  await loadDriveChildren(folder.id);
  await openDrive();
}
async function driveBack() {
  state.driveTrail.pop();
  await openDrive();
}
async function loadDriveChildren(folderId) {
  const data = await send('POST', '/api/core/drive/children', {folder_id: folderId, max_results: 500, my_drive_only: true});
  state.driveChildren[folderId] = data;
  return data;
}
function driveBrowser() {
  const current = currentDriveFolder();
  const selected = selectedDriveFolderNames();
  const folders = current ? ((state.driveChildren[current.id] || {}).folders || []) : (state.driveFolders || []);
  const files = current ? ((state.driveChildren[current.id] || {}).files || []) : [];
  const crumbs = `<div class="drive-crumbs"><button class="drive-crumb" title="My Drive roots" onclick="state.driveTrail=[]; openDrive()">My Drive</button>${state.driveTrail.map((folder, idx) => `<span class="muted">/</span><button class="drive-crumb" onclick="driveJump(${idx})" title="${esc(folder.name)}">${esc(folder.name)}</button>`).join('')}</div>`;
  const folderRows = folders.length ? folders.map((folder, idx) => driveFolderRow(folder, idx)).join('') : '<div class="drive-empty">No child folders.</div>';
  const fileRows = current ? (files.length ? files.map((file, idx) => driveFileRow(file, idx, current.id)).join('') : '<div class="drive-empty">No files at this level.</div>') : '';
  return `<div class="drive-shell"><div class="drive-bar">${crumbs}<div class="drive-meta"><span class="pill">${folders.length} dirs</span><span class="pill">${files.length} files</span><span class="pill" title="${esc(selected)}">${state.selectedDriveFolders.length} sel</span></div></div><div class="drive-table">${folderRows}${current ? `<div class="drive-section"><div class="drive-section-title">Files</div>${fileRows}</div>` : ''}</div></div>`;
}
function driveFolderRow(folder, idx) {
  const selected = state.selectedDriveFolders.includes(folder.id);
  const checked = selected ? '&#10003;' : '';
  return `<div class="drive-row ${selected ? 'selected' : ''}"><div class="drive-name"><span class="drive-icon">DIR</span><button title="Open folder" onclick="openDriveFolderAt(${idx})"><span class="drive-title">${esc(folder.name)}</span><span class="drive-subtitle">Folder</span></button></div><button class="drive-check" title="Select folder" onclick="toggleDriveFolder('${esc(folder.id)}')">${checked}</button></div>`;
}
function driveFileRow(file, idx, folderId) {
  return `<div class="drive-row"><div class="drive-name"><span class="drive-icon file">${esc(driveFileIcon(file))}</span><button title="Open file details" onclick="openDriveChildFile('${esc(folderId)}', ${idx})"><span class="drive-title">${esc(file.name)}</span><span class="drive-subtitle">${esc(file.life_category_label || file.life_category || 'Needs Review')} &middot; ${esc(file.migration_action || 'needs_review')}</span></button></div><span></span></div>`;
}
function driveFileIcon(file) {
  const mime = String(file.mime_type || '').toLowerCase();
  const kind = String(file.kind || '').toLowerCase();
  if (mime.includes('spreadsheet') || kind.includes('sheet')) return 'SHT';
  if (mime.includes('presentation') || kind.includes('slide')) return 'SLD';
  if (mime.includes('pdf')) return 'PDF';
  if (mime.includes('image')) return 'IMG';
  if (mime.includes('video')) return 'VID';
  if (mime.includes('document') || kind.includes('doc')) return 'DOC';
  return 'FIL';
}
async function driveJump(index) {
  state.driveTrail = state.driveTrail.slice(0, index + 1);
  await openDrive();
}
function openDriveChildFile(folderId, idx) {
  const file = ((state.driveChildren[folderId] || {}).files || [])[idx];
  if (file) openDriveItem(file);
}
async function loadFullDriveInventory() {
  status.textContent = 'Loading full Drive inventory...';
  const data = await send('POST', '/api/core/drive/inventory', {max_results: 10000, include_paths: true, top_level_only: true, root_topics_only: true, my_drive_only: true});
  data.full_inventory_loaded = true;
  renderDrive(data);
  state.drivePlanLoaded = false;
  await openDrive();
  status.textContent = 'Full Drive inventory loaded.';
}
async function proposeDriveStagingCopy() {
  const category = '';
  const maxResults = 20;
  const payload = {max_results: maxResults, migration_action: 'copy_to_homelab', include_folder_ids: state.selectedDriveFolders, exclude_names: ['griproot', 'grip', 'assistive device', 'hands team'], my_drive_only: true, idempotency_key: `drive-stage-${Date.now()}`};
  if (category.trim()) payload.category = category.trim();
  await send('POST', '/api/core/drive/staging-copy/propose', payload);
  await loadAll();
  status.textContent = 'Drive staging copy proposed for approval.';
}
async function proposeNextcloudImport() {
  const nextcloudItems = (state.driveDestinations.staged_items || []).filter(item => item.local_path || item.manifest_path);
  const count = Math.min(Math.max(nextcloudItems.length, 0), 50);
  if (!count) return;
  const payload = {
    max_results: count,
    manifest_paths: nextcloudItems.slice(0, count).map(item => item.manifest_path).filter(Boolean),
    idempotency_key: `drive-nextcloud-${Date.now()}`
  };
  await send('POST', '/api/core/drive/nextcloud-import/propose', payload);
  await loadAll();
  status.textContent = 'Nextcloud import proposed for approval.';
}
async function proposePaperlessImport() {
  const paperlessItems = (state.driveDestinations.staged_items || []).filter(item => item.service === 'paperless' && (item.local_path || item.manifest_path));
  const count = Math.min(Math.max(paperlessItems.length, 0), 50);
  if (!count) return;
  const payload = {
    max_results: count,
    manifest_paths: paperlessItems.slice(0, count).map(item => item.manifest_path).filter(Boolean),
    idempotency_key: `drive-paperless-${Date.now()}`
  };
  await send('POST', '/api/core/drive/paperless-import/propose', payload);
  await loadAll();
  status.textContent = 'Paperless import proposed for approval.';
}
function openDriveItem(item) {
  const link = item.web_view_link ? `<a href="${esc(item.web_view_link)}" target="_blank" rel="noreferrer">${esc(item.web_view_link)}</a>` : '';
  openDrawer(item.name || item.id, item.suggested_destination || 'Drive item', [
    row('Kind', item.kind), row('MIME type', item.mime_type), row('Modified', item.modified_time),
    row('Google Drive path', item.google_drive_path), row('Google folder', item.google_drive_folder_path),
    row('Category', item.life_category_label || item.life_category), row('Migration action', item.migration_action || item.suggested_action),
    row('This would go here', item.recommended_home || item.suggested_destination), row('Secondary home', item.secondary_home),
    row('Jarvis relationship', item.relationship_home), row('Why', item.routing_reason),
    row('Migration pathway', item.migration_pathway), row('Current action', item.suggested_action),
    row('Link', link), row('Drive id', item.id)
  ].join(''));
}
function openDriveStaging() {
  const data = state.driveStaging || {};
  openDrawer('Drive Staging', data.summary || 'Staged copies', [
    row('Staging root', data.staging_root), row('Total files', data.total), row('Total bytes', data.total_bytes),
    row('By category', data.by_category), row('By destination', data.by_destination), row('Manifests', data.manifests)
  ].join(''));
}
function openStagedDriveItem(item) {
  openDrawer(item.name || item.file_id, item.destination || 'Staged Drive item', [
    row('Local staged path', item.path), row('Relative path', item.staged_relative_path), row('File exists', item.file_exists),
    row('Manifest path', item.manifest_path), row('Bytes', item.bytes), row('Category', item.category),
    row('Destination', item.destination), row('Export type', item.export_type), row('Content type', item.content_type),
    row('Google source', item.web_view_link), row('Drive id', item.file_id), row('Modified', item.modified_time),
    row('Action id', item.action_id)
  ].join(''));
}
function openDriveDestinations() {
  const data = state.driveDestinations || {};
  const actions = `<button title="Refresh" onclick="loadAll().then(openDriveDestinations)">&#8635;</button><button class="primary" title="Propose Nextcloud import" onclick="proposeNextcloudImport()">&#8680;</button>`;
  openDrawer('Smart Destinations', data.summary || 'Destination readiness', [
    row('Services', data.services), row('Nextcloud visibility check', data.services?.nextcloud?.import_check), row('Paperless import check', data.services?.paperless?.import_check), row('Pathway', data.pathway), row('Staged items', data.staged_items)
  ].join(''), actions);
}
function openSmartDestinationItem(item) {
  openDrawer(item.name || 'Destination item', item.ready ? 'Destination ready' : 'Destination waiting', [
    row('Destination', item.destination), row('Service', item.service), row('Ready', item.ready),
    row('Next action', item.next_action), row('Reason', item.reason),
    row('Local path', item.local_path), row('Manifest path', item.manifest_path)
  ].join(''));
}
function openAudit(a) {
  openDrawer(a.event_type || a.id, a.created_at || 'Audit event', [
    row('Actor', a.actor), row('Subject id', a.subject_id), row('Correlation id', a.correlation_id),
    row('Payload', a.payload), row('Raw event', a)
  ].join(''));
}
function openItem(kind, idx) {
  if (kind === 'approval') return openApproval(state.approvals[idx]);
  if (kind === 'diagnostic') return openDiagnostic(state.diagnostics[idx]);
  if (kind === 'codexTask') return openCodexTask(state.codexTasks[idx]);
  if (kind === 'codexJob') return openCodexJob(state.codexJobs[idx]);
  if (kind === 'run') return openRun(state.runs[idx]);
  if (kind === 'worker') return openWorker(state.workers[idx]);
  if (kind === 'downloadScan') return openDownloadScan(state.downloads[idx]);
  if (kind === 'downloadDestinationItem') return openDownloadDestinationItem((state.downloadsDestinationPlan.items || [])[idx]);
  if (kind === 'task') return openTask(state.tasks[idx]);
  if (kind === 'evidence') return openEvidence(state.evidence[idx]);
  if (kind === 'maintenance') return openMaintenance(state.maintenance[idx]);
  if (kind === 'maintenanceHub') return openMaintenanceHub();
  if (kind === 'brief') return openBrief();
  if (kind === 'drive') return openDrive();
  if (kind === 'driveItem') return openDriveItem((state.drive.items || [])[idx]);
  if (kind === 'driveStaging') return openDriveStaging();
  if (kind === 'stagedDriveItem') return openStagedDriveItem((state.driveStaging.manifests || [])[idx]);
  if (kind === 'driveDestinations') return openDriveDestinations();
  if (kind === 'smartDestinationItem') return openSmartDestinationItem((state.driveDestinations.staged_items || [])[idx]);
  if (kind === 'notifications') return openNotification(state.notifications[idx]);
  if (kind === 'automation') return openAutomation(state.automations[idx]);
  if (kind === 'audit') return openAudit(state.audit[idx]);
}
function openNotification(n) {
  const approval = linkedApprovalForNotification(n);
  const actions = [
    approval ? `<button class="quick-action approve" title="Approve request" aria-label="Approve request" onclick="approveNotification(event, '${esc(n.id)}')">&#10003;</button>` : '',
    approval ? `<button class="quick-action reject" title="Reject request" aria-label="Reject request" onclick="rejectNotification(event, '${esc(n.id)}')">&#215;</button>` : '',
    !['dismissed', 'delivered'].includes(String(n.status || '').toLowerCase()) ? `<button class="quick-action" title="Dismiss" aria-label="Dismiss" onclick="dismissNotification(event, '${esc(n.id)}')">&#8722;</button>` : ''
  ].filter(Boolean).join('');
  openDrawer(notificationTitle(n), `${n.channel} ${n.status}`, [
    row('Body', n.payload?.body), row('Severity', n.payload?.severity),
    row('Linked approval', approval ? `${approval.action?.tool_name || 'approval'} / ${approval.action?.risk_level || approval.status || ''}` : ''),
    row('Created', n.created_at), row('Payload', n.payload)
  ].join(''), actions);
}
function openDownloadDestinationItem(item) {
  if (!item) return;
  openDrawer(item.name || 'Download item', item.destination || 'Destination', [
    row('This would go here', item.suggested_folder),
    row('Destination', item.destination),
    row('Action', item.action),
    row('Tags', item.tags),
    row('Why', item.reason),
    row('Ready', item.ready),
    row('Category', item.life_category_label || item.life_category),
    row('Kind', item.kind),
    row('Modified', item.modified_at),
    row('Path', item.path)
  ].join(''));
}
function currentBriefKind() {
  const hour = new Date().getHours();
  return hour >= 17 || hour < 4 ? 'evening' : 'morning';
}
async function loadAll() {
  status.textContent = 'Refreshing...';
  const briefKind = currentBriefKind();
  const [ap, diag, cx, jobs, runs, workers, downloads, task, ev, maint, br, notif, auto, gm, ds, dd] = await Promise.all([
    get('/api/core/approvals?status=pending'),
    get('/api/core/diagnostics'),
    get('/api/core/codex/tasks'),
    get('/api/codex/jobs'),
    get('/api/core/runs'),
    get('/api/core/workers'),
    get('/api/core/desktop/downloads/scans'),
    get('/api/core/tasks'),
    get('/api/core/evidence'),
    get('/api/core/maintenance'),
    get(`/api/core/daily-brief?kind=${briefKind}`),
    get('/api/core/notifications'),
    get('/api/core/automations'),
    get('/api/core/gmail/cleanup-summary?max_results=50').catch(err => ({ok:false, error:err.message, text:'Gmail cleanup summary unavailable.'})),
    send('POST', '/api/core/drive/staging-status', {max_results: 20}),
    send('POST', '/api/core/drive/destinations', {max_results: 20})
  ]);
  const dr = state.drive.total
    ? state.drive
    : {ok: true, summary: 'Drive inventory loads on demand', total: 0, items: [], by_category: {}, by_action: {}, lazy: true};
  state.evidence = ev.evidence || [];
  state.maintenance = maint.maintenance || [];
  state.notifications = notif.notifications || [];
  state.runs = runs.runs || [];
  state.workers = workers.workers || [];
  state.downloads = downloads.scans || [];
  state.automations = auto.automations || [];
  state.gmailCleanup = gm || {};
  state.driveStaging = ds || {};
  state.driveDestinations = dd || {};
  renderOverview({ap, diag, cx, runs, workers, downloads, task, maint, notif, auto, gm, br});
  renderApprovals(ap); renderDiagnostics(diag); renderCodex(cx); renderCodexWorker(jobs);
  state.tasks = task.tasks || [];
  setCount('tasksCount', `${state.tasks.length}`);
  renderBrief(br);
  state.audit = [];
  status.textContent = 'Ready.';
}
loadAll().catch(err => { status.textContent = err.message; });
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

    def core_proxy(self, method, path, payload=None, timeout=180):
        body = json.dumps(payload or {}).encode("utf-8") if method in {"POST", "PATCH"} else None
        req = urllib.request.Request(
            JARVIS_CORE_URL + path,
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {JARVIS_CORE_TOKEN}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.status, json.loads(response.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            try:
                data = json.loads(exc.read().decode("utf-8") or "{}")
            except Exception:
                data = {"error": str(exc)}
            return exc.code, data
        except Exception as exc:
            return HTTPStatus.BAD_GATEWAY, {"ok": False, "error": str(exc)}

    def spanish_proxy(self, method, path, payload=None, timeout=180):
        body = json.dumps(payload or {}).encode("utf-8") if method in {"POST", "PATCH"} else None
        headers = {"Content-Type": "application/json"}
        if SPANISH_COACH_TOKEN and not SPANISH_COACH_TOKEN.startswith("CHANGE_ME"):
            headers["Authorization"] = f"Bearer {SPANISH_COACH_TOKEN}"
        req = urllib.request.Request(SPANISH_COACH_URL + path, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.status, json.loads(response.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            try:
                data = json.loads(exc.read().decode("utf-8") or "{}")
            except Exception:
                data = {"error": str(exc)}
            return exc.code, data
        except Exception as exc:
            return HTTPStatus.BAD_GATEWAY, {"ok": False, "error": str(exc)}

    def codex_proxy(self, method, path, payload=None, timeout=120):
        body = json.dumps(payload or {}).encode("utf-8") if method in {"POST", "PATCH"} else None
        headers = {"Content-Type": "application/json"}
        if CODEX_WORKER_TOKEN:
            headers["Authorization"] = f"Bearer {CODEX_WORKER_TOKEN}"
        req = urllib.request.Request(CODEX_WORKER_URL + path, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.status, json.loads(response.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            try:
                data = json.loads(exc.read().decode("utf-8") or "{}")
            except Exception:
                data = {"error": str(exc)}
            return exc.code, data
        except Exception as exc:
            return HTTPStatus.BAD_GATEWAY, {"ok": False, "error": str(exc)}

    def core_voice_request(self, text):
        lowered = text.lower()
        if "morning brief" in lowered:
            return self.core_proxy("GET", "/api/v1/daily-brief?kind=morning&save=true", timeout=240)
        if "evening recap" in lowered:
            return self.core_proxy("GET", "/api/v1/daily-brief?kind=evening&save=true", timeout=240)
        if "daily brief" in lowered:
            hour = datetime.now(ZoneInfo(USER_TIMEZONE)).hour
            kind = "evening" if hour >= 17 or hour < 4 else "morning"
            return self.core_proxy("GET", f"/api/v1/daily-brief?kind={kind}&save=true", timeout=240)
        if "pending approvals" in lowered or "what approvals" in lowered:
            return self.core_proxy("GET", "/api/v1/approvals?status=pending")
        if "media automation" in lowered or "media automations" in lowered or "arr stack" in lowered or "torrent status" in lowered:
            return self.core_proxy("GET", "/api/v1/media/automations/status")
        if "drive migration" in lowered or "google drive migration" in lowered:
            return self.core_proxy("POST", "/api/v1/drive/migration-plan", {"max_results": 50}, timeout=120)
        if "drive inventory" in lowered or "google drive inventory" in lowered:
            return self.core_proxy("POST", "/api/v1/drive/inventory", {"max_results": 50}, timeout=120)
        if "notification" in lowered:
            status, data = self.core_proxy("GET", "/api/v1/notifications?channel=voice&status=pending")
            if status >= 400:
                return status, data
            delivered = []
            for item in data.get("notifications") or []:
                delivery_status, _ = self.core_proxy(
                    "POST",
                    f"/api/v1/notifications/{item.get('id')}/delivery",
                    {"status": "delivered", "delivered_by": "jarvis-chat-voice"},
                    timeout=60,
                )
                delivered.append({"id": item.get("id"), "status": delivery_status})
            data["delivered"] = delivered
            return status, data
        if lowered.startswith("approve ") or " approve " in lowered:
            import urllib.parse

            confirmed = lowered.startswith("confirm approve ") or " confirm approve " in lowered
            q = lowered.split("approve", 1)[1].strip(" .")
            status, matches = self.core_proxy("GET", f"/api/v1/approvals?status=pending&q={urllib.parse.quote(q)}")
            if status >= 400:
                return status, matches
            risky = []
            for approval in matches.get("approvals") or []:
                action = approval.get("action") or {}
                if action.get("tool_name") == "codex.run_task" or action.get("risk_level") in {"destructive", "sensitive"}:
                    risky.append(approval)
            if risky and not confirmed:
                return HTTPStatus.OK, {
                    "ok": True,
                    "text": f"That approval may run code or a high-risk action. To confirm, say: confirm approve {q}.",
                    "approval_required": True,
                    "approvals": risky,
                }
            return self.core_proxy("POST", f"/api/v1/approvals/decide-by-title?q={urllib.parse.quote(q)}", {"approved": True, "decided_by": "hey-jarvis"}, timeout=240)
        if any(lowered.startswith(prefix) or f" {prefix}" in lowered for prefix in ("complete task ", "reopen task ")):
            operation = "complete_task" if "complete task" in lowered else "reopen_task"
            phrase = "complete task" if operation == "complete_task" else "reopen task"
            confirmed = lowered.startswith(f"confirm {phrase} ") or f" confirm {phrase} " in lowered
            q = lowered.split(phrase, 1)[1].strip(" .")
            return self.core_voice_edit_task(q, operation, confirmed)
        if any(prefix in lowered for prefix in ("resolve maintenance ", "reopen maintenance ")):
            operation = "resolve_maintenance" if "resolve maintenance" in lowered else "reopen_maintenance"
            phrase = "resolve maintenance" if operation == "resolve_maintenance" else "reopen maintenance"
            confirmed = lowered.startswith(f"confirm {phrase} ") or f" confirm {phrase} " in lowered
            q = lowered.split(phrase, 1)[1].strip(" .")
            return self.core_voice_edit_maintenance(q, operation, confirmed)
        if "what are my tasks" in lowered or "list tasks" in lowered:
            return self.core_proxy("GET", "/api/v1/tasks")
        if "codex dashboard" in lowered or "codex tasks" in lowered:
            return self.core_proxy("GET", "/api/v1/codex/tasks")
        if any(term in lowered for term in ("codex", "coding task", "code task", "fix code", "implement", "debug", "refactor", "write tests")):
            return self.core_proxy("POST", "/api/v1/codex/tasks", {"request": text, "idempotency_key": f"voice-codex-{hashlib.sha256(text.encode('utf-8')).hexdigest()[:24]}"})
        if "complete task" in lowered:
            return HTTPStatus.OK, {"ok": True, "text": "Tell me the exact task id in Jarvis Chat for now, and I can mark it complete."}
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]
        return self.core_proxy("POST", "/api/v1/capture", {"text": text, "idempotency_key": f"voice-{digest}"})

    def core_voice_edit_task(self, q, operation, confirmed):
        status, data = self.core_proxy("GET", "/api/v1/tasks")
        if status >= 400:
            return status, data
        matches = [item for item in data.get("tasks") or [] if q.casefold() in (item.get("title") or "").casefold()]
        if not matches:
            return HTTPStatus.NOT_FOUND, {"ok": False, "error": "task_not_found"}
        if len(matches) > 1:
            return HTTPStatus.OK, {"ok": True, "status": "ambiguous", "matches": [{"action": {"preview": {"summary": item.get("title")}, "tool_name": "task.update"}, "id": item.get("id")} for item in matches[:5]]}
        task = matches[0]
        phrase = "complete task" if operation == "complete_task" else "reopen task"
        if not confirmed:
            return HTTPStatus.OK, {"ok": True, "status": "confirmation_required", "text": f"To {phrase} {task.get('title')}, say: confirm {phrase} {q}.", "task": task, "operation": operation}
        if operation == "complete_task":
            status, updated = self.core_proxy("POST", f"/api/v1/tasks/{task['id']}/complete", {}, timeout=120)
        else:
            status, updated = self.core_proxy("PATCH", f"/api/v1/tasks/{task['id']}", {"status": "open"}, timeout=120)
        if status < 400:
            updated = {"ok": True, "task": updated, "operation": operation}
        return status, updated

    def core_voice_edit_maintenance(self, q, operation, confirmed):
        status, data = self.core_proxy("GET", "/api/v1/maintenance")
        if status >= 400:
            return status, data
        def haystack(item):
            return " ".join(str(item.get(key) or "") for key in ("service_name", "summary", "record_type"))
        matches = [item for item in data.get("maintenance") or [] if q.casefold() in haystack(item).casefold()]
        if not matches:
            return HTTPStatus.NOT_FOUND, {"ok": False, "error": "maintenance_not_found"}
        if len(matches) > 1:
            return HTTPStatus.OK, {"ok": True, "status": "ambiguous", "matches": [{"action": {"preview": {"summary": item.get("summary")}, "tool_name": "maintenance.update"}, "id": item.get("id")} for item in matches[:5]]}
        item = matches[0]
        phrase = "resolve maintenance" if operation == "resolve_maintenance" else "reopen maintenance"
        if not confirmed:
            return HTTPStatus.OK, {"ok": True, "status": "confirmation_required", "text": f"To {phrase} {item.get('summary')}, say: confirm {phrase} {q}.", "maintenance": item, "operation": operation}
        payload = {"resolved": True} if operation == "resolve_maintenance" else {"status": "open", "resolved": False}
        status, updated = self.core_proxy("PATCH", f"/api/v1/maintenance/{item['id']}", payload, timeout=120)
        if status < 400:
            updated = {"ok": True, "maintenance": updated, "operation": operation}
        return status, updated

    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/") or "/"
        parsed = urlparse(self.path)
        query = parsed.query
        if path == "/":
            self.write(HTTPStatus.OK, page(), "text/html; charset=utf-8")
            return
        if path == "/core":
            self.write(HTTPStatus.OK, interactive_core_console_page(), "text/html; charset=utf-8")
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
        if path == "/api/core/notifications/summary":
            suffix = f"?{query}" if query else "?channel=homepage&limit=5"
            status, data = self.core_proxy("GET", "/api/v1/notifications/summary" + suffix)
            self.write_json(status, data)
            return
        if path == "/api/media/automations/summary":
            status, data = self.core_proxy("GET", "/api/v1/media/automations/status")
            if status < 400:
                data = {"preview": data.get("preview") or "Media automation status unavailable", "count": len(data.get("checks") or []), "items": data.get("checks") or []}
            self.write_json(status, data)
            return
        core_get_routes = {
            "/api/core/approvals": "/api/v1/approvals",
            "/api/core/diagnostics": "/api/v1/homelab/diagnostics",
            "/api/core/media/automations": "/api/v1/media/automations/status",
            "/api/core/codex/tasks": "/api/v1/codex/tasks",
            "/api/core/tasks": "/api/v1/tasks",
            "/api/core/evidence": "/api/v1/evidence",
            "/api/core/maintenance": "/api/v1/maintenance",
            "/api/core/daily-brief": "/api/v1/daily-brief",
            "/api/core/audit": "/api/v1/audit",
            "/api/core/executions": "/api/v1/executions",
            "/api/core/notifications": "/api/v1/notifications",
            "/api/core/automations": "/api/v1/automations",
            "/api/core/runs": "/api/v1/runs",
            "/api/core/workers": "/api/v1/workers",
            "/api/core/desktop/downloads/scans": "/api/v1/desktop/downloads/scans",
            "/api/core/gmail/cleanup-summary": "/api/v1/gmail/cleanup-summary",
            "/api/core/drive/nextcloud-status": "/api/v1/drive/nextcloud-status",
            "/api/core/drive/paperless-status": "/api/v1/drive/paperless-status",
        }
        if path in core_get_routes:
            if not self.authorized():
                self.write_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
                return
            suffix = f"?{query}" if query else ""
            status, data = self.core_proxy("GET", core_get_routes[path] + suffix)
            self.write_json(status, data)
            return
        if path.startswith("/api/core/runs/") or path.startswith("/api/core/jobs/") or path.startswith("/api/core/workers/"):
            if not self.authorized():
                self.write_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
                return
            core_path = path.replace("/api/core", "/api/v1", 1)
            suffix = f"?{query}" if query else ""
            status, data = self.core_proxy("GET", core_path + suffix)
            self.write_json(status, data)
            return
        if path == "/api/codex/jobs":
            if not self.authorized():
                self.write_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
                return
            status, data = self.codex_proxy("GET", "/jobs")
            self.write_json(status, data)
            return
        if path.startswith("/api/codex/jobs/"):
            if not self.authorized():
                self.write_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
                return
            codex_path = path.replace("/api/codex", "", 1)
            suffix = f"?{query}" if query else ""
            status, data = self.codex_proxy("GET", codex_path + suffix)
            self.write_json(status, data)
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

        if path.startswith("/api/core/approvals/") and path.endswith("/decision"):
            parts = path.split("/")
            if len(parts) == 6:
                status, data = self.core_proxy("POST", f"/api/v1/approvals/{parts[4]}/decision", self.read_json(), timeout=240)
                self.write_json(status, data)
                return

        if path.startswith("/api/core/tasks/") and path.endswith("/complete"):
            parts = path.split("/")
            if len(parts) == 6:
                status, data = self.core_proxy("POST", f"/api/v1/tasks/{parts[4]}/complete", {}, timeout=120)
                self.write_json(status, data)
                return

        if path == "/api/core/daily-brief/actions":
            status, data = self.core_proxy("POST", "/api/v1/daily-brief/actions", self.read_json(), timeout=240)
            self.write_json(status, data)
            return

        if path == "/api/core/runs":
            status, data = self.core_proxy("POST", "/api/v1/runs", self.read_json(), timeout=120)
            self.write_json(status, data)
            return

        if path == "/api/core/desktop/downloads/scan":
            status, data = self.core_proxy("POST", "/api/v1/desktop/downloads/scan", self.read_json(), timeout=120)
            self.write_json(status, data)
            return

        if path == "/api/core/desktop/downloads/propose-cleanup":
            status, data = self.core_proxy("POST", "/api/v1/desktop/downloads/propose-cleanup", self.read_json(), timeout=240)
            self.write_json(status, data)
            return

        if path == "/api/core/desktop/downloads/destination-plan":
            status, data = self.core_proxy("POST", "/api/v1/desktop/downloads/destination-plan", self.read_json(), timeout=120)
            self.write_json(status, data)
            return

        if path.startswith("/api/core/runs/") and path.endswith("/jobs"):
            parts = path.split("/")
            if len(parts) == 6:
                status, data = self.core_proxy("POST", f"/api/v1/runs/{parts[4]}/jobs", self.read_json(), timeout=120)
                self.write_json(status, data)
                return

        if path.startswith("/api/core/runs/") and path.endswith("/cancel"):
            parts = path.split("/")
            if len(parts) == 6:
                status, data = self.core_proxy("POST", f"/api/v1/runs/{parts[4]}/cancel", self.read_json(), timeout=120)
                self.write_json(status, data)
                return

        if path.startswith("/api/core/jobs/") and path.endswith("/retry"):
            parts = path.split("/")
            if len(parts) == 6:
                status, data = self.core_proxy("POST", f"/api/v1/jobs/{parts[4]}/retry", self.read_json(), timeout=120)
                self.write_json(status, data)
                return

        if path == "/api/core/workers/register":
            status, data = self.core_proxy("POST", "/api/v1/workers/register", self.read_json(), timeout=120)
            self.write_json(status, data)
            return

        if path.startswith("/api/core/workers/"):
            suffix = path.replace("/api/core/workers", "/api/v1/workers", 1)
            status, data = self.core_proxy("POST", suffix, self.read_json(), timeout=120)
            self.write_json(status, data)
            return

        if path.startswith("/api/core/automations/") and path.endswith("/run"):
            parts = path.split("/")
            if len(parts) == 6:
                status, data = self.core_proxy("POST", f"/api/v1/automations/{parts[4]}/run", self.read_json(), timeout=240)
                self.write_json(status, data)
                return

        if path == "/api/core/automations/propose-create":
            status, data = self.core_proxy("POST", "/api/v1/automations/propose-create", self.read_json(), timeout=120)
            self.write_json(status, data)
            return

        if path.startswith("/api/core/automations/") and path.endswith("/propose-update"):
            parts = path.split("/")
            if len(parts) == 6:
                status, data = self.core_proxy("POST", f"/api/v1/automations/{parts[4]}/propose-update", self.read_json(), timeout=120)
                self.write_json(status, data)
                return

        if path.startswith("/api/core/automations/") and path.endswith("/pause"):
            parts = path.split("/")
            if len(parts) == 6:
                status, data = self.core_proxy("POST", f"/api/v1/automations/{parts[4]}/pause", self.read_json(), timeout=120)
                self.write_json(status, data)
                return

        if path.startswith("/api/core/notifications/") and path.endswith("/dismiss"):
            parts = path.split("/")
            if len(parts) == 6:
                payload = self.read_json()
                status, data = self.core_proxy(
                    "POST",
                    f"/api/v1/notifications/{parts[4]}/delivery",
                    {"status": "dismissed", "delivered_by": payload.get("delivered_by") or "jarvis-core-console"},
                    timeout=120,
                )
                self.write_json(status, data)
                return

        if path == "/api/core/evidence/packet":
            status, data = self.core_proxy("POST", "/api/v1/evidence/packet", self.read_json(), timeout=240)
            self.write_json(status, data)
            return

        if path == "/api/core/drive/inventory":
            status, data = self.core_proxy("POST", "/api/v1/drive/inventory", self.read_json(), timeout=240)
            self.write_json(status, data)
            return

        if path == "/api/core/drive/migration-plan":
            status, data = self.core_proxy("POST", "/api/v1/drive/migration-plan", self.read_json(), timeout=120)
            self.write_json(status, data)
            return

        if path == "/api/core/drive/folders":
            status, data = self.core_proxy("POST", "/api/v1/drive/folders", self.read_json(), timeout=240)
            self.write_json(status, data)
            return

        if path == "/api/core/drive/children":
            status, data = self.core_proxy("POST", "/api/v1/drive/children", self.read_json(), timeout=240)
            self.write_json(status, data)
            return

        if path == "/api/core/drive/staging-copy/propose":
            status, data = self.core_proxy("POST", "/api/v1/drive/staging-copy/propose", self.read_json(), timeout=120)
            self.write_json(status, data)
            return

        if path == "/api/core/drive/nextcloud-import/propose":
            status, data = self.core_proxy("POST", "/api/v1/drive/nextcloud-import/propose", self.read_json(), timeout=120)
            self.write_json(status, data)
            return

        if path == "/api/core/drive/paperless-import/propose":
            status, data = self.core_proxy("POST", "/api/v1/drive/paperless-import/propose", self.read_json(), timeout=120)
            self.write_json(status, data)
            return

        if path == "/api/core/gmail/cleanup/propose":
            status, data = self.core_proxy("POST", "/api/v1/gmail/cleanup/propose", self.read_json(), timeout=120)
            self.write_json(status, data)
            return

        if path == "/api/core/drive/staging-status":
            status, data = self.core_proxy("POST", "/api/v1/drive/staging-status", self.read_json(), timeout=120)
            self.write_json(status, data)
            return

        if path == "/api/core/drive/destinations":
            status, data = self.core_proxy("POST", "/api/v1/drive/destinations", self.read_json(), timeout=120)
            self.write_json(status, data)
            return

        if path == "/api/core/notifications":
            status, data = self.core_proxy("POST", "/api/v1/notifications", self.read_json(), timeout=120)
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
            if wants_spanish_voice(text):
                status, data = self.spanish_proxy("GET", "/api/jarvis/morning-spanish", timeout=240)
                if status >= 400:
                    self.write_json(status, data)
                    return
                self.write_json(HTTPStatus.OK, {"ok": True, "text": data.get("text") or "Spanish practice is ready.", "spanish": data})
                return
            if wants_core_voice(text):
                status, data = self.core_voice_request(text)
                if status >= 400:
                    self.write_json(status, data)
                    return
                self.write_json(
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "text": core_voice_text(data),
                        "core": data,
                        "approval_required": bool(data.get("approval_required") or data.get("actions")),
                        "approval_actions": data.get("actions") or [],
                    },
                )
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

    def do_PATCH(self):
        path = urlparse(self.path).path.rstrip("/") or "/"
        if not self.authorized():
            self.write_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
            return

        if path.startswith("/api/core/tasks/"):
            parts = path.split("/")
            if len(parts) == 5:
                status, data = self.core_proxy("PATCH", f"/api/v1/tasks/{parts[4]}", self.read_json(), timeout=120)
                self.write_json(status, data)
                return

        if path.startswith("/api/core/maintenance/"):
            parts = path.split("/")
            if len(parts) == 5:
                status, data = self.core_proxy("PATCH", f"/api/v1/maintenance/{parts[4]}", self.read_json(), timeout=120)
                self.write_json(status, data)
                return

        self.write_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})


def main():
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Jarvis Chat listening on {HOST}:{PORT}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
