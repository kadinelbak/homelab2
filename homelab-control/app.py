#!/usr/bin/env python3
import html
import json
import os
import subprocess
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

REPO_ROOT = Path(os.environ.get("HOMELAB_REPO", "/homelab"))
TOKEN = os.environ.get("HOMELAB_CONTROL_TOKEN", "")
HOST = os.environ.get("HOMELAB_CONTROL_HOST", "0.0.0.0")
PORT = int(os.environ.get("HOMELAB_CONTROL_PORT", "5055"))
TIMEOUT = int(os.environ.get("HOMELAB_CONTROL_TIMEOUT", "420"))


def load_catalog():
    return json.loads((REPO_ROOT / "services.yaml").read_text(encoding="utf-8"))


def docker_ps():
    try:
        out = subprocess.check_output(
            ["docker", "ps", "--format", "{{.Names}}"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=15,
        )
    except Exception:
        return set()
    return {line.strip() for line in out.splitlines() if line.strip()}


def service_state(catalog):
    running = docker_ps()
    return {
        name: "running" if svc.get("container") in running else "stopped"
        for name, svc in catalog["services"].items()
    }


def selectors(catalog):
    return set(catalog["services"])


def authorized(handler):
    if not TOKEN or TOKEN.startswith("CHANGE_ME"):
        return False
    auth = handler.headers.get("Authorization", "")
    if auth == f"Bearer {TOKEN}":
        return True
    cookie = handler.headers.get("Cookie", "")
    if f"homelab_control_token={TOKEN}" in cookie:
        return True
    parsed = urlparse(handler.path)
    return parse_qs(parsed.query).get("token", [""])[0] == TOKEN


def run_controller(action, selector):
    cmd = ["python3", "scripts/homelabctl.py", action, selector]
    if action == "up":
        cmd.append("--force")
    started = time.time()
    proc = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        timeout=TIMEOUT,
    )
    output = (proc.stdout or "") + (proc.stderr or "")
    return {
        "ok": proc.returncode == 0,
        "code": proc.returncode,
        "seconds": round(time.time() - started, 1),
        "output": output[-12000:],
    }


def esc(value):
    return html.escape(str(value), quote=True)


def render():
    catalog = load_catalog()
    states = service_state(catalog)
    by_phase = {}
    for name, svc in catalog["services"].items():
        by_phase.setdefault(svc["phase"], []).append((name, svc))

    phase_order = sorted(
        by_phase,
        key=lambda phase: catalog["phases"].get(phase, {}).get("order", 999),
    )

    cards = []
    for phase in phase_order:
        phase_services = sorted(by_phase[phase], key=lambda item: item[0])
        cards.append(f"<section><h2>{esc(phase)}</h2><div class='grid'>")
        for name, svc in phase_services:
            state = states[name]
            profiles = ", ".join(svc.get("profiles", []))
            deps = ", ".join(svc.get("dependencies", [])) or "none"
            classes = f"card {state} {esc(svc.get('tier', ''))}"
            cards.append(
                f"""
                <article class="{classes}">
                  <div class="row">
                    <h3>{esc(name)}</h3>
                    <span class="state">{esc(state)}</span>
                  </div>
                  <p>{esc(svc.get("tier", "service"))} &middot; {esc(svc.get("ram_mb", 0))} MB &middot; {esc(svc.get("schedule", "manual"))}</p>
                  <p class="meta">Profiles: {esc(profiles)}<br>Depends: {esc(deps)}</p>
                  <div class="actions">
                    <button data-action="up" data-selector="{esc(name)}">Start</button>
                    <button data-action="down" data-selector="{esc(name)}">Stop</button>
                  </div>
                </article>
                """
            )
        cards.append("</div></section>")

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Homelab Control</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #111827;
      --panel: #1f2937;
      --panel2: #253044;
      --text: #f8fafc;
      --muted: #aeb8c8;
      --ok: #3ddc84;
      --off: #7c8798;
      --line: #3b4659;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--text);
    }}
    header {{
      position: sticky;
      top: 0;
      z-index: 2;
      display: flex;
      gap: 16px;
      align-items: center;
      justify-content: space-between;
      padding: 16px 24px;
      border-bottom: 1px solid var(--line);
      background: rgba(17, 24, 39, 0.96);
    }}
    h1 {{ margin: 0; font-size: 22px; }}
    h2 {{ margin: 28px 0 12px; font-size: 18px; color: #dbeafe; }}
    h3 {{ margin: 0; font-size: 16px; }}
    main {{ max-width: 1440px; margin: 0 auto; padding: 18px 24px 48px; }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
      gap: 12px;
    }}
    .card, .profile {{
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 8px;
      padding: 14px;
    }}
    .running {{ border-color: rgba(61, 220, 132, 0.6); }}
    .row, .actions, .profile, .tokenbar {{
      display: flex;
      align-items: center;
      gap: 8px;
    }}
    .row {{ justify-content: space-between; }}
    p {{ color: var(--muted); margin: 8px 0; line-height: 1.35; }}
    .meta {{ font-size: 12px; }}
    .state {{
      border-radius: 999px;
      padding: 3px 8px;
      font-size: 12px;
      background: var(--off);
      color: #07111f;
      font-weight: 700;
    }}
    .running .state {{ background: var(--ok); }}
    button {{
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--panel2);
      color: var(--text);
      padding: 8px 10px;
      cursor: pointer;
      min-width: 64px;
    }}
    button:hover {{ border-color: #93c5fd; }}
    input {{
      min-width: 260px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #0b1220;
      color: var(--text);
      padding: 8px 10px;
    }}
    .profiles {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
      gap: 8px;
      margin-top: 10px;
    }}
    .profile {{ justify-content: space-between; padding: 10px; }}
    #result {{
      position: fixed;
      right: 18px;
      bottom: 18px;
      width: min(640px, calc(100vw - 36px));
      max-height: 48vh;
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #050a14;
      padding: 12px;
      white-space: pre-wrap;
      display: none;
    }}
    @media (max-width: 760px) {{
      header {{ align-items: stretch; flex-direction: column; }}
      .tokenbar {{ align-items: stretch; flex-direction: column; }}
      input, button {{ width: 100%; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>Homelab Control</h1>
    <div class="tokenbar">
      <button onclick="location.href='http://kadin-main-sys.tail00cf0e.ts.net:3000/'">Homepage</button>
      <input id="token" type="password" placeholder="Control token">
      <button id="saveToken">Unlock</button>
      <button id="refresh">Refresh</button>
    </div>
  </header>
  <main>
    {"".join(cards)}
  </main>
  <pre id="result"></pre>
  <script>
    const result = document.getElementById("result");
    const token = document.getElementById("token");
    token.value = localStorage.getItem("homelabControlToken") || "";
    document.getElementById("saveToken").onclick = () => {{
      localStorage.setItem("homelabControlToken", token.value);
      document.cookie = "homelab_control_token=" + encodeURIComponent(token.value) + "; SameSite=Lax";
    }};
    document.getElementById("refresh").onclick = () => location.reload();
    async function run(action, selector) {{
      localStorage.setItem("homelabControlToken", token.value);
      result.style.display = "block";
      result.textContent = `${{action}} ${{selector}}...`;
      const response = await fetch("/api/action", {{
        method: "POST",
        headers: {{
          "Content-Type": "application/json",
          "Authorization": "Bearer " + token.value
        }},
        body: JSON.stringify({{action, selector}})
      }});
      const payload = await response.json();
      result.textContent = `${{payload.ok ? "OK" : "FAILED"}} ${{action}} ${{selector}} in ${{payload.seconds || "?"}}s\\n\\n${{payload.output || payload.error || ""}}`;
      if (payload.ok) setTimeout(() => location.reload(), 1200);
    }}
    document.querySelectorAll("button[data-action]").forEach((button) => {{
      button.onclick = () => run(button.dataset.action, button.dataset.selector);
    }});
  </script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "homelab-control/1.0"

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args), flush=True)

    def write(self, status, body, content_type="text/html; charset=utf-8"):
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def write_json(self, status, payload):
        self.write(status, json.dumps(payload, separators=(",", ":")), "application/json")

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self.write_json(HTTPStatus.OK, {"ok": True, "repo": str(REPO_ROOT)})
            return
        if parsed.path == "/":
            self.write(HTTPStatus.OK, render())
            return
        self.write_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_POST(self):
        if urlparse(self.path).path != "/api/action":
            self.write_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        if not authorized(self):
            self.write_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return
        length = int(self.headers.get("Content-Length", "0") or "0")
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            action = payload["action"]
            selector = payload["selector"]
            catalog = load_catalog()
            if action not in {"up", "down"}:
                raise ValueError("action must be up or down")
            if selector not in selectors(catalog):
                raise ValueError("unknown selector")
        except Exception as exc:
            self.write_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        try:
            self.write_json(HTTPStatus.OK, run_controller(action, selector))
        except subprocess.TimeoutExpired:
            self.write_json(HTTPStatus.REQUEST_TIMEOUT, {"ok": False, "error": "command timed out"})
        except Exception as exc:
            self.write_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": str(exc)})


def main():
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Homelab Control listening on {HOST}:{PORT}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
