#!/usr/bin/env python3
"""Replace GOOGLE_HEALTH_REFRESH_TOKEN in the local, untracked .env safely."""

from __future__ import annotations

import getpass
import os
import sys
from argparse import ArgumentParser
from pathlib import Path


ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


def main() -> int:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--client-secret", action="store_true", help="also replace GOOGLE_HEALTH_CLIENT_SECRET")
    args = parser.parse_args()
    if not ENV_PATH.is_file():
        print(f"error: {ENV_PATH} does not exist", file=sys.stderr)
        return 1
    replacements = {"GOOGLE_HEALTH_REFRESH_TOKEN": getpass.getpass("Paste the new Google Health refresh token (input is hidden): ").strip()}
    if args.client_secret:
        replacements["GOOGLE_HEALTH_CLIENT_SECRET"] = getpass.getpass("Paste the new Google OAuth client secret (input is hidden): ").strip()
    if not all(replacements.values()):
        print("error: no value entered", file=sys.stderr)
        return 1
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    updated = set()
    output: list[str] = []
    for line in lines:
        key = next((candidate for candidate in replacements if line.startswith(f"{candidate}=")), None)
        if key:
            output.append(f"{key}={replacements[key]}")
            updated.add(key)
        else:
            output.append(line)
    for key, value in replacements.items():
        if key not in updated:
            output.append(f"{key}={value}")
    temporary = ENV_PATH.with_name(f".{ENV_PATH.name}.google-health-token.tmp")
    old_mode = ENV_PATH.stat().st_mode & 0o777
    try:
        temporary.write_text("\n".join(output) + "\n", encoding="utf-8")
        os.chmod(temporary, old_mode)
        temporary.replace(ENV_PATH)
    finally:
        temporary.unlink(missing_ok=True)
    print("Google Health OAuth value(s) saved to the private .env file.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
