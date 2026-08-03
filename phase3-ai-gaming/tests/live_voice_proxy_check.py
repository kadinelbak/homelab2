#!/usr/bin/env python3
import json
import os
import sys
import urllib.request
from pathlib import Path


def env_value(path, key):
    if not path.exists():
        return ""
    for line in path.read_text().splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip()
    return ""


def main():
    base_url = os.environ.get("JARVIS_CHAT_URL", "http://127.0.0.1:18100").rstrip("/")
    env_path = Path(os.environ.get("JARVIS_ENV_PATH", str(Path.home() / "homelab2" / ".env")))
    token = os.environ.get("JARVIS_CHAT_TOKEN") or env_value(env_path, "JARVIS_CHAT_TOKEN")
    headers = {"Content-Type": "application/json"}
    if token and not token.startswith("CHANGE_ME"):
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(
        base_url + "/api/voice/synthesize",
        data=json.dumps({"text": "Jarvis voice proxy test."}).encode("utf-8"),
        method="POST",
        headers=headers,
    )
    with urllib.request.urlopen(req, timeout=120) as response:
        audio = response.read()
        content_type = response.headers.get("Content-Type", "")
    print(json.dumps({"status": response.status, "content_type": content_type, "bytes": len(audio)}))
    if response.status != 200 or "audio" not in content_type or len(audio) < 1000:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
