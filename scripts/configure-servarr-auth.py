#!/usr/bin/env python3
"""Configure Servarr app authentication mode.

Use Forms for per-app logins, or External when the apps are protected by a
trusted reverse proxy such as authentik Proxy Provider.
"""

from __future__ import annotations

import argparse
import os
import xml.etree.ElementTree as ET
from pathlib import Path


APPS = ("prowlarr", "sonarr", "radarr", "lidarr", "readarr")
AUTH_METHODS = ("Forms", "External", "None")


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key] = value.strip().split(" #", 1)[0].strip().strip("\"'")
    return values


def set_text(root: ET.Element, tag: str, value: str) -> None:
    node = root.find(tag)
    if node is None:
        node = ET.SubElement(root, tag)
    node.text = value


def configure_app(data_path: Path, app: str, method: str, required: str, dry_run: bool) -> None:
    config = data_path / f"phase2-media/data/{app}/config.xml"
    tree = ET.parse(config)
    root = tree.getroot()
    set_text(root, "AuthenticationMethod", method)
    set_text(root, "AuthenticationRequired", required)
    if dry_run:
        print(f"{app}: would set AuthenticationMethod={method}, AuthenticationRequired={required}")
        return
    backup = config.with_suffix(".xml.bak")
    if not backup.exists():
        backup.write_bytes(config.read_bytes())
    tmp = config.with_suffix(".xml.tmp")
    tree.write(tmp, encoding="utf-8", xml_declaration=True)
    os.replace(tmp, config)
    os.chmod(config, 0o600)
    print(f"{app}: AuthenticationMethod={method}, AuthenticationRequired={required}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default=".env")
    parser.add_argument(
        "--method",
        choices=AUTH_METHODS,
        default="Forms",
        help="AuthenticationMethod to write to config.xml. Use External behind authentik.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate selected app config files without changing them.",
    )
    parser.add_argument(
        "--required",
        choices=("Enabled", "DisabledForLocalAddresses"),
        default="Enabled",
        help="AuthenticationRequired value to write to config.xml.",
    )
    parser.add_argument("apps", nargs="*", choices=APPS)
    args = parser.parse_args()

    env = load_env(Path(args.env_file))
    data_path = Path(env["DATA_PATH"])
    apps = args.apps or list(APPS)
    for app in apps:
        configure_app(data_path, app, args.method, args.required, args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
