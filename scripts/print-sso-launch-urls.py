#!/usr/bin/env python3
"""Print expanded non-secret Authentik launch URLs for debugging."""

from __future__ import annotations

import json
import re
from pathlib import Path


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        value = value.strip()
        if value and value[0] in "\"'":
            quote = value[0]
            end = value.find(quote, 1)
            value = value[1:end] if end != -1 else value[1:]
        else:
            value = value.split(" #", 1)[0].strip()
        values[key.strip()] = value
    return values


env = parse_env(Path(".env"))
spec = json.loads(Path("config/authentik/providers.json").read_text(encoding="utf-8"))
for app in spec["applications"]:
    url = re.sub(r"\$\{DOMAIN\}", env.get("DOMAIN", ""), app["launch_url"])
    print(f"{app['slug']}: {url!r}")
