#!/usr/bin/env python3
import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CATALOG_FILE = REPO_ROOT / "services.yaml"
ENV_FILE = REPO_ROOT / ".env"


def die(message, code=1):
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(code)


def load_env(path=ENV_FILE):
    env = {}
    if not path.exists():
        return env
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        env[key.strip()] = value
    return env


def load_catalog():
    try:
        return json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        die(f"{CATALOG_FILE} must be JSON-compatible YAML: {exc}")


def have_docker():
    return shutil.which("docker") is not None


def run(cmd, dry_run=False, capture=False):
    printable = " ".join(str(part) for part in cmd)
    if dry_run:
        print(f"DRY-RUN: {printable}")
        return ""
    if capture:
        return subprocess.check_output(cmd, cwd=REPO_ROOT, text=True, stderr=subprocess.DEVNULL)
    subprocess.check_call(cmd, cwd=REPO_ROOT)
    return ""


class HomelabCtl:
    def __init__(self, dry_run=False):
        self.catalog = load_catalog()
        self.env = {**os.environ, **load_env()}
        self.services = self.catalog["services"]
        self.phases = self.catalog["phases"]
        self.dry_run = dry_run

    def env_int(self, key, default):
        try:
            return int(self.env.get(key, default))
        except ValueError:
            die(f"{key} must be an integer")

    @property
    def ram_limit_mb(self):
        key = self.catalog["server"].get("ram_limit_mb_env", "HOMELAB_RAM_LIMIT_MB")
        return self.env_int(key, 16384)

    @property
    def reserved_ram_mb(self):
        key = self.catalog["server"].get("reserved_ram_mb_env", "HOMELAB_RESERVED_RAM_MB")
        return self.env_int(key, 2048)

    @property
    def vram_limit_mb(self):
        key = self.catalog["server"].get("vram_limit_mb_env", "HOMELAB_VRAM_LIMIT_MB")
        return self.env_int(key, 0)

    @property
    def admission_mode(self):
        key = self.catalog["server"].get("admission_mode_env", "HOMELAB_ADMISSION_MODE")
        mode = self.env.get(key, "warn").lower()
        if mode not in {"warn", "enforce"}:
            die(f"{key} must be 'warn' or 'enforce'")
        return mode

    def docker_compose(self, phase, extra):
        phase_info = self.phases[phase]
        cmd = [
            "docker",
            "compose",
            "--env-file",
            str(ENV_FILE),
            "-f",
            str(REPO_ROOT / phase_info["compose"]),
            "--project-name",
            phase_info["project"],
        ]
        return cmd + extra

    def running_containers(self):
        if not have_docker() or self.dry_run:
            return set()
        try:
            out = run(["docker", "ps", "--format", "{{.Names}}"], capture=True)
            return {line.strip() for line in out.splitlines() if line.strip()}
        except Exception:
            return set()

    def running_services(self):
        containers = self.running_containers()
        return {
            name
            for name, svc in self.services.items()
            if svc.get("container") in containers
        }

    def selectors_to_services(self, selectors, include_dependencies=True):
        if not selectors:
            selectors = ["always-on"]

        selected = set()
        unknown = []
        for selector in selectors:
            if selector in self.services:
                selected.add(selector)
                continue
            profile_matches = {
                name for name, svc in self.services.items()
                if selector in svc.get("profiles", [])
            }
            if profile_matches:
                selected.update(profile_matches)
            else:
                unknown.append(selector)

        if unknown:
            die(f"Unknown service/profile selector(s): {', '.join(unknown)}")

        if include_dependencies:
            selected = self.with_dependencies(selected)
        return selected

    def with_dependencies(self, selected):
        expanded = set(selected)
        changed = True
        while changed:
            changed = False
            for service in list(expanded):
                for dep in self.services[service].get("dependencies", []):
                    if dep not in self.services:
                        die(f"{service} depends on unknown service {dep}")
                    if dep not in expanded:
                        expanded.add(dep)
                        changed = True
        return expanded

    def phase_order(self, services):
        return sorted(
            {self.services[name]["phase"] for name in services},
            key=lambda phase: self.phases[phase]["order"],
        )

    def services_for_phase(self, services, phase):
        return sorted(name for name in services if self.services[name]["phase"] == phase)

    def resource_totals(self, services):
        ram = sum(int(self.services[name].get("ram_mb", 0)) for name in services)
        vram = sum(int(self.services[name].get("vram_mb", 0)) for name in services)
        cpu = sum(float(self.services[name].get("cpu", 0)) for name in services)
        return ram, vram, cpu

    def host_available_ram_mb(self):
        meminfo = Path("/proc/meminfo")
        if not meminfo.exists():
            return None
        for line in meminfo.read_text(encoding="utf-8").splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) // 1024
        return None

    def host_available_vram_mb(self):
        if not shutil.which("nvidia-smi"):
            return None
        try:
            out = run(
                ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
                capture=True,
            )
            values = [int(line.strip()) for line in out.splitlines() if line.strip()]
            return sum(values) if values else None
        except Exception:
            return None

    def admission(self, requested):
        running = self.running_services()
        projected = running | requested
        requested_new = requested - running

        projected_ram, projected_vram, projected_cpu = self.resource_totals(projected)
        new_ram, new_vram, _ = self.resource_totals(requested_new)
        budget_ram = self.ram_limit_mb - self.reserved_ram_mb
        budget_vram = self.vram_limit_mb

        available_host_ram = self.host_available_ram_mb()
        available_host_vram = self.host_available_vram_mb()

        problems = []
        if projected_ram > budget_ram:
            problems.append(
                f"projected catalog RAM {projected_ram} MB exceeds budget {budget_ram} MB "
                f"({self.ram_limit_mb} total - {self.reserved_ram_mb} reserved)"
            )
        if budget_vram and projected_vram > budget_vram:
            problems.append(f"projected catalog VRAM {projected_vram} MB exceeds budget {budget_vram} MB")
        if available_host_ram is not None and new_ram > max(0, available_host_ram - self.reserved_ram_mb):
            problems.append(
                f"requested new RAM {new_ram} MB exceeds host available headroom "
                f"{max(0, available_host_ram - self.reserved_ram_mb)} MB"
            )
        if available_host_vram is not None and new_vram > available_host_vram:
            problems.append(f"requested new VRAM {new_vram} MB exceeds available GPU memory {available_host_vram} MB")

        return {
            "running": running,
            "projected": projected,
            "requested_new": requested_new,
            "projected_ram": projected_ram,
            "projected_vram": projected_vram,
            "projected_cpu": projected_cpu,
            "budget_ram": budget_ram,
            "budget_vram": budget_vram,
            "available_host_ram": available_host_ram,
            "available_host_vram": available_host_vram,
            "problems": problems,
        }

    def print_plan(self, services):
        admission = self.admission(services)
        print("Plan")
        print(f"  Services: {', '.join(sorted(services))}")
        print(f"  New services: {', '.join(sorted(admission['requested_new'])) or 'none detected'}")
        print(f"  Projected RAM: {admission['projected_ram']} MB / {admission['budget_ram']} MB budget")
        vram_budget = admission["budget_vram"] or "unconfigured"
        print(f"  Projected VRAM: {admission['projected_vram']} MB / {vram_budget} MB budget")
        print(f"  Projected CPU estimate: {admission['projected_cpu']:.1f} cores")
        if admission["available_host_ram"] is not None:
            print(f"  Host MemAvailable: {admission['available_host_ram']} MB")
        if admission["available_host_vram"] is not None:
            print(f"  GPU memory free: {admission['available_host_vram']} MB")
        if admission["problems"]:
            print("  Admission:")
            for problem in admission["problems"]:
                print(f"    - {problem}")
        else:
            print("  Admission: OK")

        print("  Compose batches:")
        for phase in self.phase_order(services):
            phase_services = self.services_for_phase(services, phase)
            print(f"    {phase}: {' '.join(phase_services)}")
        return admission

    def enforce_admission(self, admission, force=False):
        if not admission["problems"]:
            return
        if force:
            print("WARN: admission problems ignored because --force was supplied")
            return
        if self.admission_mode == "enforce":
            for problem in admission["problems"]:
                print(f"DENY: {problem}", file=sys.stderr)
            raise SystemExit(1)
        for problem in admission["problems"]:
            print(f"WARN: {problem}", file=sys.stderr)

    def up(self, services, force=False):
        admission = self.print_plan(services)
        self.enforce_admission(admission, force=force)
        for phase in self.phase_order(services):
            phase_services = self.services_for_phase(services, phase)
            cmd = self.docker_compose(phase, ["up", "-d"] + phase_services)
            run(cmd, dry_run=self.dry_run)

    def down(self, services):
        for phase in reversed(self.phase_order(services)):
            phase_services = self.services_for_phase(services, phase)
            cmd = self.docker_compose(phase, ["stop"] + phase_services)
            run(cmd, dry_run=self.dry_run)

    def status(self, services=None):
        services = services or set(self.services)
        running = self.running_services()
        print(f"{'SERVICE':28} {'STATE':10} {'TIER':11} {'RAM_MB':>7} {'SCHEDULE':14} PROFILES")
        for name in sorted(services):
            svc = self.services[name]
            state = "running" if name in running else "stopped"
            print(
                f"{name:28} {state:10} {svc['tier']:11} {int(svc['ram_mb']):7} "
                f"{svc['schedule']:14} {','.join(svc.get('profiles', []))}"
            )

    def schedule_active(self, schedule_name, now=None):
        schedule = self.catalog["schedules"][schedule_name]
        kind = schedule["kind"]
        now = now or dt.datetime.now()
        if kind == "always":
            return True
        if kind == "manual":
            return False

        def minute(value):
            hour, minute_ = value.split(":", 1)
            return int(hour) * 60 + int(minute_)

        current = now.hour * 60 + now.minute
        start = minute(schedule["start"])
        end = minute(schedule["end"])
        in_window = start <= current < end if start < end else current >= start or current < end
        if kind == "window":
            return in_window
        if kind == "weekly-window":
            return now.weekday() in schedule["days"] and in_window
        die(f"Unknown schedule kind {kind}")

    def scheduled_sets(self):
        desired_up = set()
        desired_down = set()
        for name, svc in self.services.items():
            schedule = svc.get("schedule", "manual")
            if schedule == "manual":
                continue
            if self.schedule_active(schedule):
                desired_up.add(name)
            elif svc["tier"] == "background":
                desired_down.add(name)
        return self.with_dependencies(desired_up), desired_down

    def schedule(self, once=True, interval=300, force=False):
        while True:
            desired_up, desired_down = self.scheduled_sets()
            print(f"Scheduler tick: up={len(desired_up)} down={len(desired_down)}")
            if desired_up:
                self.up(desired_up, force=force)
            if desired_down:
                protected = desired_up | {name for name, svc in self.services.items() if svc["tier"] == "critical"}
                stoppable = desired_down - protected
                if stoppable:
                    self.down(stoppable)
            if once:
                return
            time.sleep(interval)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Homelab capacity governor and Compose controller")
    parser.add_argument("--dry-run", action="store_true", help="print docker commands without executing them")
    sub = parser.add_subparsers(dest="command", required=True)

    p_plan = sub.add_parser("plan", help="show capacity and Compose plan")
    p_plan.add_argument("selectors", nargs="*", help="service names or profile names")

    p_up = sub.add_parser("up", help="start services or profiles after admission control")
    p_up.add_argument("selectors", nargs="+", help="service names or profile names")
    p_up.add_argument("--force", action="store_true", help="ignore admission warnings/errors")

    p_down = sub.add_parser("down", help="stop services or profiles")
    p_down.add_argument("selectors", nargs="+", help="service names or profile names")

    p_status = sub.add_parser("status", help="show catalog status")
    p_status.add_argument("selectors", nargs="*", help="service names or profile names")

    p_schedule = sub.add_parser("schedule", help="apply schedule policy")
    p_schedule.add_argument("--loop", action="store_true", help="run forever")
    p_schedule.add_argument("--interval", type=int, default=300, help="loop interval seconds")
    p_schedule.add_argument("--force", action="store_true", help="ignore admission warnings/errors")

    args = parser.parse_args(argv)
    ctl = HomelabCtl(dry_run=args.dry_run)

    if args.command == "plan":
        services = ctl.selectors_to_services(args.selectors)
        ctl.print_plan(services)
    elif args.command == "up":
        services = ctl.selectors_to_services(args.selectors)
        ctl.up(services, force=args.force)
    elif args.command == "down":
        services = ctl.selectors_to_services(args.selectors, include_dependencies=False)
        ctl.down(services)
    elif args.command == "status":
        services = ctl.selectors_to_services(args.selectors, include_dependencies=False) if args.selectors else set(ctl.services)
        ctl.status(services)
    elif args.command == "schedule":
        ctl.schedule(once=not args.loop, interval=args.interval, force=args.force)


if __name__ == "__main__":
    main()
