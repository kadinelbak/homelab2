#!/usr/bin/env python3
"""Validate homelab env files, secret files, and Compose config before restarts."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

PHASES = {
    "phase1-core": {
        "compose": "phase1-core/docker-compose.yml",
        "required": {
            "TZ",
            "PUID",
            "PGID",
            "DOCKER_GID",
            "DATA_PATH",
            "DOMAIN",
            "POSTGRES_USER",
            "POSTGRES_PASSWORD",
            "REDIS_PASSWORD",
            "AUTHENTIK_SECRET_KEY",
            "AUTHENTIK_BOOTSTRAP_PASSWORD",
            "VAULTWARDEN_ADMIN_TOKEN",
            "PIHOLE_WEB_PASSWORD",
        },
    },
    "phase2-media": {
        "compose": "phase2-media/docker-compose.yml",
        "required": {
            "TZ",
            "PUID",
            "PGID",
            "DATA_PATH",
            "DOMAIN",
            "PAPERLESS_ADMIN_PASSWORD",
            "PAPERLESS_SECRET_KEY",
            "IMMICH_DB_USERNAME",
            "IMMICH_DB_PASSWORD",
            "IMMICH_DB_DATABASE_NAME",
        },
        "profiles": {
            "torrent": {"VPN_SERVICE_PROVIDER", "VPN_TYPE", "SERVER_COUNTRIES", "GLUETUN_SECRETS_DIR"},
            "arr": {"VPN_SERVICE_PROVIDER", "VPN_TYPE", "SERVER_COUNTRIES", "GLUETUN_SECRETS_DIR"},
        },
    },
    "phase3-ai-gaming": {
        "compose": "phase3-ai-gaming/docker-compose.yml",
        "required": {
            "TZ",
            "PUID",
            "PGID",
            "DATA_PATH",
            "DOMAIN",
            "POSTGRES_USER",
            "POSTGRES_PASSWORD",
            "REDIS_PASSWORD",
            "AI_ORCHESTRATOR_TOKEN",
            "JARVIS_CORE_TOKEN",
        },
        "profiles": {
            "n8n": {"N8N_ENCRYPTION_KEY", "N8N_USER_MANAGEMENT_JWT_SECRET"},
            "minecraft": {"MINECRAFT_EULA", "MINECRAFT_OPS"},
            "google": {"GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REDIRECT_URI"},
            "telegram": {"JARVIS_TELEGRAM_BOT_TOKEN", "JARVIS_TELEGRAM_ALLOWED_CHAT_IDS"},
        },
    },
    "phase4-ondemand": {
        "compose": "phase4-ondemand/docker-compose.yml",
        "required": {"TZ", "PUID", "PGID", "DATA_PATH", "DOMAIN", "POSTGRES_USER", "POSTGRES_PASSWORD", "REDIS_PASSWORD"},
        "profiles": {
            "nextcloud": {"NEXTCLOUD_ADMIN_USER", "NEXTCLOUD_ADMIN_PASSWORD", "NEXTCLOUD_TRUSTED_DOMAINS"},
            "docmost": {"DOCMOST_APP_SECRET", "POSTGRES_USER", "POSTGRES_PASSWORD", "REDIS_PASSWORD"},
            "guacamole": {"POSTGRES_USER", "POSTGRES_PASSWORD"},
        },
    },
}

PLACEHOLDER_PATTERNS = (
    re.compile(r"CHANGE_ME", re.I),
    re.compile(r"CHANGEME", re.I),
    re.compile(r"<set>", re.I),
    re.compile(r"100\.x\.y\.z", re.I),
    re.compile(r"10\.x\.x\.x", re.I),
    re.compile(r"example\.com", re.I),
)

OPTIONAL_PLACEHOLDER_KEYS = {
    "SMTP_HOST",
    "SMTP_USER",
    "SMTP_PASS",
    "SMTP_FROM",
    "S3_ACCESS_KEY",
    "S3_SECRET_KEY",
    "S3_ENDPOINT",
    "S3_BUCKET",
    "SUPABASE_POSTGRES_PASSWORD",
    "SUPABASE_JWT_SECRET",
    "SUPABASE_ANON_KEY",
    "SUPABASE_SERVICE_ROLE_KEY",
}

DEPRECATED_RAW_SECRET_KEYS = {"WIREGUARD_PRIVATE_KEY", "WIREGUARD_ADDRESSES"}


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        raise FileNotFoundError(path)
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def env_files_from_args(raw_files: list[str]) -> list[Path]:
    if raw_files:
        files = raw_files
    else:
        configured = os.environ.get("HOMELAB_ENV_FILES", ".env")
        files = [item for item in re.split(r"[;,]", configured) if item.strip()]
    return [(REPO_ROOT / item.strip()).resolve() if not Path(item.strip()).is_absolute() else Path(item.strip()) for item in files]


def merged_env(paths: list[Path]) -> tuple[dict[str, str], list[str]]:
    env: dict[str, str] = {}
    problems: list[str] = []
    for path in paths:
        try:
            env.update(parse_env(path))
        except FileNotFoundError:
            problems.append(f"missing env file: {path}")
    return env, problems


def has_placeholder(value: str) -> bool:
    return any(pattern.search(value) for pattern in PLACEHOLDER_PATTERNS)


def validate_required(env: dict[str, str], required: set[str]) -> list[str]:
    problems: list[str] = []
    for key in sorted(required):
        value = env.get(key, "")
        if not value:
            problems.append(f"missing required env: {key}")
        elif key not in OPTIONAL_PLACEHOLDER_KEYS and has_placeholder(value):
            problems.append(f"placeholder value still set: {key}")
    return problems


def validate_general(env: dict[str, str]) -> list[str]:
    problems: list[str] = []
    for key in sorted(DEPRECATED_RAW_SECRET_KEYS & env.keys()):
        if env.get(key):
            problems.append(f"deprecated raw secret in env: {key}; use Docker secret files instead")
    return problems


def validate_vpn_secrets(env: dict[str, str]) -> list[str]:
    if env.get("VPN_TYPE", "").lower() != "wireguard":
        return []
    secrets_dir = Path(env.get("GLUETUN_SECRETS_DIR", "phase2-media/secrets"))
    if not secrets_dir.is_absolute():
        secrets_dir = REPO_ROOT / secrets_dir
    private_key = secrets_dir / "wireguard_private_key"
    addresses = secrets_dir / "wireguard_addresses"
    problems: list[str] = []
    if not private_key.exists():
        problems.append(f"missing WireGuard secret file: {private_key}")
    elif len(private_key.read_text(encoding="utf-8").strip()) < 40:
        problems.append(f"WireGuard private key looks too short: {private_key}")
    if not addresses.exists():
        problems.append(f"missing WireGuard address secret file: {addresses}")
    else:
        value = addresses.read_text(encoding="utf-8").strip()
        if has_placeholder(value) or "/" not in value:
            problems.append(f"WireGuard address looks invalid: {addresses}")
    return problems


def compose_cmd(env_files: list[Path], phase: str, profiles: list[str]) -> list[str]:
    phase_info = PHASES[phase]
    cmd = ["docker", "compose"]
    for env_file in env_files:
        cmd.extend(["--env-file", str(env_file)])
    for profile in profiles:
        cmd.extend(["--profile", profile])
    cmd.extend(["-f", str(REPO_ROOT / phase_info["compose"]), "config", "--quiet"])
    return cmd


def run_compose_check(env_files: list[Path], phase: str, profiles: list[str]) -> list[str]:
    cmd = compose_cmd(env_files, phase, profiles)
    proc = subprocess.run(cmd, cwd=REPO_ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode == 0:
        return []
    detail = (proc.stderr or proc.stdout).strip().splitlines()
    return [f"compose config failed for {phase}: {detail[0] if detail else 'unknown error'}"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Preflight homelab env files and Compose config")
    parser.add_argument("phase", choices=sorted(PHASES), help="phase to validate")
    parser.add_argument("--profile", action="append", default=[], help="Compose profile to include")
    parser.add_argument("--env-file", action="append", default=[], help="env file, repeatable; later files override earlier ones")
    parser.add_argument("--skip-compose", action="store_true", help="skip docker compose config validation")
    args = parser.parse_args(argv)

    env_files = env_files_from_args(args.env_file)
    env, problems = merged_env(env_files)
    phase_info = PHASES[args.phase]
    required = set(phase_info["required"])
    for profile in args.profile:
        required.update(phase_info.get("profiles", {}).get(profile, set()))

    problems.extend(validate_required(env, required))
    problems.extend(validate_general(env))
    if args.phase == "phase2-media" and {"torrent", "arr"} & set(args.profile):
        problems.extend(validate_vpn_secrets(env))
    if not args.skip_compose and not problems:
        problems.extend(run_compose_check(env_files, args.phase, args.profile))

    print(f"phase={args.phase}")
    print("env_files=" + ",".join(str(path) for path in env_files))
    print("profiles=" + (",".join(args.profile) if args.profile else "none"))
    if problems:
        print("status=fail")
        for problem in problems:
            print(f"- {problem}")
        return 1
    print("status=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
