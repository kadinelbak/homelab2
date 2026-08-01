#!/usr/bin/env python3
"""Create ARR directories without changing existing media ownership."""

from __future__ import annotations

import os
from pathlib import Path


ROOT = Path("/data")


def main() -> int:
    new_config_dirs = [
        ROOT / "phase2-media/data/sonarr",
        ROOT / "phase2-media/data/radarr",
        ROOT / "phase2-media/data/lidarr",
        ROOT / "phase2-media/data/readarr",
    ]
    shared_dirs = [
        ROOT / "shared/media/tv",
        ROOT / "shared/media/movies",
        ROOT / "shared/media/music",
        ROOT / "shared/media/books",
        ROOT / "shared/downloads/complete",
        ROOT / "shared/downloads/incomplete",
    ]
    for path in new_config_dirs + shared_dirs:
        path.mkdir(parents=True, exist_ok=True)
    for path in new_config_dirs:
        os.chown(path, 1000, 1000)
    print("ARR directories ensured")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
