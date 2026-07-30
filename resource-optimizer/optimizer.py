#!/usr/bin/env python3
"""
Compatibility entrypoint for the old resource-optimizer container.

The real capacity governor is scripts/homelabctl.py. This wrapper intentionally
does not contain separate scheduling logic, so the homelab has one admission
control implementation.
"""

import os
import subprocess
import sys
from pathlib import Path


def main():
    repo_root = Path(os.environ.get("HOMELAB_REPO_ROOT", "/repo"))
    controller = repo_root / "scripts" / "homelabctl.py"
    if not controller.exists():
        print(f"ERROR: homelabctl not found at {controller}", file=sys.stderr)
        return 1

    interval = os.environ.get("HOMELAB_SCHEDULER_INTERVAL", "300")
    cmd = [sys.executable, str(controller), "schedule", "--loop", "--interval", interval]
    return subprocess.call(cmd, cwd=repo_root)


if __name__ == "__main__":
    raise SystemExit(main())
