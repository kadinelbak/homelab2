#!/usr/bin/env python3
"""Generate missing SSO environment values from the Authentik provider spec."""

from __future__ import annotations

import argparse
import json
import secrets
import string
from pathlib import Path


PLACEHOLDER_PREFIXES = ("CHANGE_ME", "changeme", "TODO")


def parse_env(path: Path) -> tuple[list[str], dict[str, str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    values: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = clean_env_value(value)
    return lines, values


def clean_env_value(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    if value[0] in "\"'":
        quote = value[0]
        end = value.find(quote, 1)
        return value[1:end] if end != -1 else value[1:]
    return value.split(" #", 1)[0].strip()


def is_missing(value: str | None) -> bool:
    if value is None or value == "":
        return True
    return value.startswith(PLACEHOLDER_PREFIXES)


def random_secret(length: int = 48) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def upsert_env(lines: list[str], updates: dict[str, str]) -> list[str]:
    remaining = dict(updates)
    rendered: list[str] = []
    for line in lines:
        if "=" not in line or line.lstrip().startswith("#"):
            rendered.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in remaining:
            rendered.append(f"{key}={remaining.pop(key)}")
        else:
            rendered.append(line)

    if remaining:
        if rendered and rendered[-1].strip():
            rendered.append("")
        rendered.append("# Generated SSO values")
        for key in sorted(remaining):
            rendered.append(f"{key}={remaining[key]}")

    return rendered


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare .env for declarative Authentik SSO")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--spec-file", default="config/authentik/providers.json")
    parser.add_argument("--write", action="store_true", help="Write changes instead of reporting them")
    args = parser.parse_args()

    env_path = Path(args.env_file)
    spec_path = Path(args.spec_file)
    lines, env = parse_env(env_path)
    spec = json.loads(spec_path.read_text(encoding="utf-8"))

    updates: dict[str, str] = {}
    domain = env.get("DOMAIN", "kadin-main-sys.tail00cf0e.ts.net")
    if is_missing(env.get("AUTHENTIK_URL")):
        updates["AUTHENTIK_URL"] = f"http://{domain}:9001"

    for app in spec.get("applications", []):
        client_id_key = app["client_id_env"]
        client_secret_key = app["client_secret_env"]
        if is_missing(env.get(client_id_key)):
            updates[client_id_key] = f"homelab-{app['slug']}"
        if is_missing(env.get(client_secret_key)):
            updates[client_secret_key] = random_secret()

    if not updates:
        print("SSO env already has required values.")
        return 0

    for key in sorted(updates):
        print(f"{'write' if args.write else 'would write'}: {key}")

    if args.write:
        new_lines = upsert_env(lines, updates)
        env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        env_path.chmod(0o600)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
