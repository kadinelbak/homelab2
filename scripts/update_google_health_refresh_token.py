#!/usr/bin/env python3
"""Replace GOOGLE_HEALTH_REFRESH_TOKEN in the local, untracked .env safely."""

from __future__ import annotations

import getpass
import os
import sys
from pathlib import Path


KEY = "GOOGLE_HEALTH_REFRESH_TOKEN"
ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


def main() -> int:
    if not ENV_PATH.is_file():
        print(f"error: {ENV_PATH} does not exist", file=sys.stderr)
        return 1
    token = getpass.getpass("Paste the new Google Health refresh token (input is hidden): ").strip()
    if not token:
        print("error: no token entered", file=sys.stderr)
        return 1
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    replacement = f"{KEY}={token}"
    updated = False
    output: list[str] = []
    for line in lines:
        if line.startswith(f"{KEY}="):
            output.append(replacement)
            updated = True
        else:
            output.append(line)
    if not updated:
        output.append(replacement)
    temporary = ENV_PATH.with_name(f".{ENV_PATH.name}.google-health-token.tmp")
    old_mode = ENV_PATH.stat().st_mode & 0o777
    try:
        temporary.write_text("\n".join(output) + "\n", encoding="utf-8")
        os.chmod(temporary, old_mode)
        temporary.replace(ENV_PATH)
    finally:
        temporary.unlink(missing_ok=True)
    print("Google Health refresh token saved to the private .env file.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
