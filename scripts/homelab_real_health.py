#!/usr/bin/env python3
"""Generate real homelab health metrics for Prometheus node_exporter.

This script is intended to run on the Docker host. It writes:
  - homelab_real_health.prom for node_exporter's textfile collector
  - homelab_real_health.json for quick human inspection

It avoids secrets and uses only local Docker/host state plus a few HTTPS probes.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_AUTH_PORTS = [
    3000,
    3100,
    30030,
    5055,
    5678,
    6767,
    7878,
    7912,
    8086,
    8087,
    8089,
    8090,
    8092,
    8097,
    8686,
    8787,
    8989,
    9090,
    9093,
    9696,
    9999,
    18080,
    18104,
]

SERVICE_URLS = {
    "authentik": "http://127.0.0.1:9001/-/health/live/",
    "uptime_kuma": "http://127.0.0.1:3001/",
    "ntfy": "http://127.0.0.1:8085/",
    "vaultwarden": "http://127.0.0.1:7070/",
    "portainer": "http://127.0.0.1:9000/",
    "jellyfin": "http://127.0.0.1:8096/",
    "immich": "http://127.0.0.1:2283/",
    "actual_budget": "https://127.0.0.1:5006/",
    "game_server": "http://127.0.0.1:8093/health",
    "hearts_mp": "http://127.0.0.1:8094/",
}

PRIVATE_IP_PREFIXES = (
    "10.",
    "127.",
    "169.254.",
    "172.16.",
    "172.17.",
    "172.18.",
    "172.19.",
    "172.20.",
    "172.21.",
    "172.22.",
    "172.23.",
    "172.24.",
    "172.25.",
    "172.26.",
    "172.27.",
    "172.28.",
    "172.29.",
    "172.30.",
    "172.31.",
    "192.168.",
)


@dataclass
class Metric:
    name: str
    value: int | float
    labels: dict[str, str] | None = None
    help_text: str | None = None
    metric_type: str = "gauge"


def run(cmd: list[str], timeout: int = 20) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        values[key.strip()] = value
    return values


def prom_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def metric_line(metric: Metric) -> str:
    labels = metric.labels or {}
    if labels:
        rendered = ",".join(f'{key}="{prom_escape(str(value))}"' for key, value in sorted(labels.items()))
        return f"{metric.name}{{{rendered}}} {metric.value}"
    return f"{metric.name} {metric.value}"


def write_metrics(metrics: list[Metric], metrics_dir: Path) -> None:
    metrics_dir.mkdir(parents=True, exist_ok=True)
    tmp = metrics_dir / "homelab_real_health.prom.tmp"
    final = metrics_dir / "homelab_real_health.prom"

    seen_help: set[str] = set()
    lines: list[str] = []
    for metric in metrics:
        if metric.name not in seen_help:
            if metric.help_text:
                lines.append(f"# HELP {metric.name} {metric.help_text}")
            lines.append(f"# TYPE {metric.name} {metric.metric_type}")
            seen_help.add(metric.name)
        lines.append(metric_line(metric))
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(final)


def write_json(report: dict[str, Any], metrics_dir: Path) -> None:
    tmp = metrics_dir / "homelab_real_health.json.tmp"
    final = metrics_dir / "homelab_real_health.json"
    tmp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(final)


def docker_json(args: list[str]) -> Any:
    proc = run(["docker", *args])
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "docker command failed")
    return json.loads(proc.stdout)


def add_docker_metrics(metrics: list[Metric], report: dict[str, Any]) -> None:
    raw = run(["docker", "ps", "-a", "--format", "{{json .}}"])
    if raw.returncode != 0:
        raise RuntimeError(raw.stderr.strip() or raw.stdout.strip() or "docker ps failed")
    rows = [json.loads(line) for line in raw.stdout.splitlines() if line.strip()]

    running = [row for row in rows if row.get("State") == "running"]
    restarting = [row for row in rows if row.get("State") == "restarting"]
    exited = [row for row in rows if row.get("State") == "exited"]

    unhealthy: list[str] = []
    health_starting: list[str] = []
    for row in rows:
        status = row.get("Status", "")
        name = row.get("Names") or row.get("Name") or ""
        if "unhealthy" in status:
            unhealthy.append(name)
        if "health: starting" in status:
            health_starting.append(name)

    report["docker"] = {
        "running": len(running),
        "restarting": [row.get("Names") or row.get("Name") for row in restarting],
        "exited": [row.get("Names") or row.get("Name") for row in exited],
        "unhealthy": unhealthy,
        "health_starting": health_starting,
    }
    common = "Docker container state from docker ps."
    metrics.extend(
        [
            Metric("homelab_docker_containers_running", len(running), help_text=common),
            Metric("homelab_docker_containers_restarting", len(restarting), help_text=common),
            Metric("homelab_docker_containers_exited", len(exited), help_text=common),
            Metric("homelab_docker_containers_unhealthy", len(unhealthy), help_text=common),
            Metric("homelab_docker_containers_health_starting", len(health_starting), help_text=common),
        ]
    )


def add_disk_metrics(metrics: list[Metric], report: dict[str, Any], paths: list[Path]) -> None:
    disks: dict[str, Any] = {}
    for path in paths:
        if not path.exists():
            metrics.append(
                Metric(
                    "homelab_disk_path_exists",
                    0,
                    {"path": str(path)},
                    "Whether an important disk path exists.",
                )
            )
            disks[str(path)] = {"exists": False}
            continue
        usage = shutil.disk_usage(path)
        free_pct = usage.free / usage.total * 100 if usage.total else 0
        used_pct = usage.used / usage.total * 100 if usage.total else 0
        disks[str(path)] = {
            "exists": True,
            "total_bytes": usage.total,
            "used_bytes": usage.used,
            "free_bytes": usage.free,
            "free_percent": round(free_pct, 2),
        }
        labels = {"path": str(path)}
        metrics.extend(
            [
                Metric("homelab_disk_path_exists", 1, labels, "Whether an important disk path exists."),
                Metric("homelab_disk_free_percent", free_pct, labels, "Percent free on important disk paths."),
                Metric("homelab_disk_used_percent", used_pct, labels, "Percent used on important disk paths."),
                Metric("homelab_disk_free_bytes", usage.free, labels, "Free bytes on important disk paths."),
            ]
        )
    report["disks"] = disks


def http_status(url: str, timeout: int = 8, ignore_tls: bool = False) -> tuple[int, str]:
    context = ssl._create_unverified_context() if ignore_tls else None
    request = urllib.request.Request(url, headers={"User-Agent": "homelab-real-health"})
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            return int(response.status), "ok"
    except urllib.error.HTTPError as exc:
        return int(exc.code), f"http_{exc.code}"
    except Exception as exc:  # noqa: BLE001 - report health errors compactly
        return 0, f"{type(exc).__name__}: {str(exc)[:160]}"


def add_service_metrics(metrics: list[Metric], report: dict[str, Any], tail_ip: str) -> None:
    results: dict[str, Any] = {}
    for name, url in SERVICE_URLS.items():
        ignore_tls = name == "actual_budget"
        status, message = http_status(url, ignore_tls=ignore_tls)
        ok = 200 <= status < 400
        results[name] = {"url": url, "status": status, "ok": ok, "message": message}
        metrics.extend(
            [
                Metric(
                    "homelab_service_ready",
                    1 if ok else 0,
                    {"service": name, "url": url},
                    "Service-specific readiness probe result.",
                ),
                Metric(
                    "homelab_service_http_status",
                    status,
                    {"service": name, "url": url},
                    "HTTP status from service-specific readiness probes.",
                ),
            ]
        )

    for port in DEFAULT_AUTH_PORTS:
        url = f"https://{tail_ip}:{port}/"
        status, message = http_status(url, ignore_tls=True)
        ok = 200 <= status < 400
        service = f"authentik_tls_edge_{port}"
        results[service] = {"url": url, "status": status, "ok": ok, "message": message}
        metrics.append(
            Metric(
                "homelab_authentik_tls_edge_ready",
                1 if ok else 0,
                {"port": str(port)},
                "HTTPS Authentik edge port returns a non-error status.",
            )
        )
    report["services"] = results


def public_ip_from_url(url: str, timeout: int = 12) -> str | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            text = response.read(200).decode("utf-8", errors="replace").strip()
    except Exception:
        return None
    match = re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", text)
    return match.group(0) if match else None


def gluetun_public_ip() -> str | None:
    command = (
        "for u in https://api.ipify.org https://ifconfig.me/ip https://icanhazip.com; do "
        "wget -qO- -T 10 $u 2>/dev/null && exit 0; "
        "curl -fsS --max-time 10 $u 2>/dev/null && exit 0; "
        "done; exit 1"
    )
    proc = run(["docker", "exec", "gluetun", "sh", "-lc", command], timeout=35)
    if proc.returncode != 0:
        return None
    match = re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", proc.stdout)
    return match.group(0) if match else None


def docker_inspect(name: str) -> dict[str, Any] | None:
    proc = run(["docker", "inspect", name])
    if proc.returncode != 0:
        return None
    try:
        values = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    return values[0] if values else None


def add_vpn_metrics(metrics: list[Metric], report: dict[str, Any]) -> None:
    gluetun = docker_inspect("gluetun")
    qbittorrent = docker_inspect("qbittorrent")
    host_ip = public_ip_from_url("https://api.ipify.org")
    vpn_ip = gluetun_public_ip() if gluetun else None

    gluetun_running = bool(gluetun and gluetun.get("State", {}).get("Running"))
    qbit_running = bool(qbittorrent and qbittorrent.get("State", {}).get("Running"))
    qbit_net_mode = (qbittorrent or {}).get("HostConfig", {}).get("NetworkMode", "")
    gluetun_id = (gluetun or {}).get("Id", "")
    qbit_uses_gluetun = (
        qbit_net_mode in {"service:gluetun", "container:gluetun"}
        or "gluetun" in qbit_net_mode
        or bool(gluetun_id and qbit_net_mode == f"container:{gluetun_id}")
        or bool(gluetun_id and qbit_net_mode == f"container:{gluetun_id[:12]}")
    )
    vpn_ip_public = bool(vpn_ip and not vpn_ip.startswith(PRIVATE_IP_PREFIXES))
    host_vpn_same = bool(host_ip and vpn_ip and host_ip == vpn_ip)
    leak_safe = bool(gluetun_running and qbit_running and qbit_uses_gluetun and vpn_ip_public and not host_vpn_same)

    report["vpn"] = {
        "gluetun_running": gluetun_running,
        "qbittorrent_running": qbit_running,
        "qbittorrent_network_mode": qbit_net_mode,
        "qbittorrent_uses_gluetun": qbit_uses_gluetun,
        "host_public_ip_seen": bool(host_ip),
        "vpn_public_ip_seen": bool(vpn_ip),
        "vpn_ip_differs_from_host": bool(host_ip and vpn_ip and host_ip != vpn_ip),
        "leak_safe": leak_safe,
    }
    metrics.extend(
        [
            Metric("homelab_vpn_gluetun_running", int(gluetun_running), help_text="Whether gluetun is running."),
            Metric("homelab_vpn_qbittorrent_running", int(qbit_running), help_text="Whether qBittorrent is running."),
            Metric(
                "homelab_vpn_qbittorrent_uses_gluetun",
                int(qbit_uses_gluetun),
                help_text="Whether qBittorrent is using gluetun's network namespace.",
            ),
            Metric("homelab_vpn_public_ip_detected", int(vpn_ip_public), help_text="Whether gluetun has a public egress IP."),
            Metric(
                "homelab_vpn_public_ip_differs_from_host",
                int(bool(host_ip and vpn_ip and host_ip != vpn_ip)),
                help_text="Whether gluetun egress IP differs from host WAN IP.",
            ),
            Metric("homelab_vpn_leak_safe", int(leak_safe), help_text="1 when torrent traffic appears VPN-contained."),
        ]
    )


def cert_days_remaining(host: str, connect_host: str, port: int, timeout: int = 8) -> tuple[float, str]:
    context = ssl.create_default_context()
    try:
        with socket.create_connection((connect_host, port), timeout=timeout) as sock:
            with context.wrap_socket(sock, server_hostname=host) as tls:
                cert = tls.getpeercert()
    except Exception as exc:  # noqa: BLE001
        return -1, f"{type(exc).__name__}: {str(exc)[:160]}"

    not_after = cert.get("notAfter")
    if not not_after:
        return -1, "certificate missing notAfter"
    expires = ssl.cert_time_to_seconds(not_after)
    return (expires - time.time()) / 86400, "ok"


def add_cert_metrics(metrics: list[Metric], report: dict[str, Any], domain: str, tail_ip: str, ports: list[int]) -> None:
    certs: dict[str, Any] = {}
    for port in ports:
        days, message = cert_days_remaining(domain, tail_ip, port)
        ok = days >= 14
        certs[str(port)] = {"days_remaining": round(days, 2), "ok": ok, "message": message}
        metrics.extend(
            [
                Metric(
                    "homelab_tls_cert_days_remaining",
                    days,
                    {"domain": domain, "port": str(port)},
                    "TLS certificate days remaining for homelab HTTPS ports.",
                ),
                Metric(
                    "homelab_tls_cert_valid",
                    int(days > 0),
                    {"domain": domain, "port": str(port)},
                    "Whether TLS certificate validation succeeded and is not expired.",
                ),
            ]
        )
    report["certificates"] = certs


def add_backup_readiness(metrics: list[Metric], report: dict[str, Any], backup_path: Path, metrics_dir: Path) -> None:
    backup_prom = metrics_dir / "homelab_backup.prom"
    target_exists = backup_path.exists()
    # The Docker collector intentionally mounts backup storage read-only. The
    # backup job itself owns write access, so this collector can only verify
    # that the expected target is present and readable.
    target_readable = os.access(backup_path, os.R_OK) if target_exists else False
    last_success = 0.0
    if backup_prom.exists():
        for line in backup_prom.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("homelab_backup_last_success_timestamp_seconds "):
                try:
                    last_success = float(line.split()[-1])
                except ValueError:
                    last_success = 0.0
                break
    age = time.time() - last_success if last_success > 0 else -1
    configured = target_exists and target_readable
    report["backup"] = {
        "target": str(backup_path),
        "target_exists": target_exists,
        "target_readable": target_readable,
        "configured": configured,
        "metrics_present": backup_prom.exists(),
        "last_success_age_seconds": age,
        "note": "Backup drive/repository is not mounted or readable." if not configured else "",
    }
    metrics.extend(
        [
            Metric("homelab_backup_target_configured", int(configured), help_text="Whether the backup target path exists and is readable by the collector."),
            Metric("homelab_backup_target_exists", int(target_exists), help_text="Whether the backup target path exists."),
            Metric("homelab_backup_target_readable", int(target_readable), help_text="Whether the backup target path is readable by the collector."),
            Metric("homelab_backup_last_success_age_seconds", age, help_text="Seconds since last successful backup, or -1 when unknown."),
        ]
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate homelab real health metrics")
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[1]), help="Homelab repo path")
    parser.add_argument("--env-file", default=None, help="Path to .env")
    parser.add_argument("--metrics-dir", default=None, help="Prometheus textfile collector directory")
    parser.add_argument("--backup-path", default="/mnt/backups/homelab-backup", help="Expected backup target path")
    parser.add_argument("--disk-path", action="append", default=[], help="Additional important disk path to check")
    parser.add_argument("--quiet", action="store_true", help="Write metrics without printing the full JSON report")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    repo = Path(args.repo)
    env = load_env(Path(args.env_file) if args.env_file else repo / ".env")

    data_path = Path(env.get("DATA_PATH", "/mnt/nvme/homelab2"))
    domain = env.get("DOMAIN", "kadin-main-sys.tail00cf0e.ts.net")
    tail_ip = env.get("TAILSCALE_HOST_IP", "100.79.132.39")
    metrics_dir = Path(args.metrics_dir or data_path / "phase1-core/data/node-exporter/textfile_collector")

    metrics: list[Metric] = [
        Metric("homelab_real_health_last_run_timestamp_seconds", int(time.time()), help_text="Last successful run timestamp for real health checks."),
    ]
    report: dict[str, Any] = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "repo": str(repo),
        "domain": domain,
        "tailscale_ip": tail_ip,
    }

    failures: list[str] = []
    checks = [
        ("docker", lambda: add_docker_metrics(metrics, report)),
        (
            "disk",
            lambda: add_disk_metrics(
                metrics,
                report,
                [Path("/"), data_path, Path("/var/lib/docker"), *[Path(p) for p in args.disk_path]],
            ),
        ),
        ("services", lambda: add_service_metrics(metrics, report, tail_ip)),
        ("vpn", lambda: add_vpn_metrics(metrics, report)),
        ("certificates", lambda: add_cert_metrics(metrics, report, domain, tail_ip, DEFAULT_AUTH_PORTS)),
        ("backup", lambda: add_backup_readiness(metrics, report, Path(args.backup_path), metrics_dir)),
    ]

    for name, func in checks:
        try:
            func()
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{name}: {type(exc).__name__}: {exc}")
            metrics.append(Metric("homelab_real_health_check_error", 1, {"check": name}, "Health collector check errors."))

    report["collector_errors"] = failures
    metrics.append(Metric("homelab_real_health_collector_ok", 0 if failures else 1, help_text="Whether the health collector completed all checks."))

    write_metrics(metrics, metrics_dir)
    write_json(report, metrics_dir)

    if args.quiet:
        print(
            "homelab_real_health "
            f"errors={len(failures)} "
            f"unhealthy={report.get('docker', {}).get('unhealthy', [])} "
            f"vpn_safe={report.get('vpn', {}).get('leak_safe')} "
            f"backup_configured={report.get('backup', {}).get('configured')}"
        )
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    # Per-check failures are represented by metrics and should not cause the
    # long-running container to restart continuously. Unexpected exceptions
    # before metrics are written still terminate the process and make the
    # freshness alert fire.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
