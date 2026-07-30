#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  scripts/toggle-phase-profile.sh <phase2|phase3|phase4> <profile> <up|down|restart|status>

Examples:
  scripts/toggle-phase-profile.sh phase2 jellyfin up
  scripts/toggle-phase-profile.sh phase2 immich down
  scripts/toggle-phase-profile.sh phase3 open-webui up
  scripts/toggle-phase-profile.sh phase4 nextcloud up
  scripts/toggle-phase-profile.sh phase4 nextcloud down
USAGE
}

if [[ $# -ne 3 ]]; then
  usage
  exit 2
fi

phase="$1"
profile="$2"
action="$3"

case "$phase" in
  phase2|phase2-media)
    compose_dir="phase2-media"
    ;;
  phase3|phase3-ai-gaming)
    compose_dir="phase3-ai-gaming"
    ;;
  phase4|phase4-ondemand)
    compose_dir="phase4-ondemand"
    ;;
  *)
    usage
    exit 2
    ;;
esac

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repo_root}/${compose_dir}"

compose=(docker compose --env-file ../.env --profile "$profile")

case "$action" in
  up)
    "${compose[@]}" up -d
    ;;
  down)
    "${compose[@]}" stop
    ;;
  restart)
    "${compose[@]}" restart
    ;;
  status)
    "${compose[@]}" ps
    ;;
  *)
    usage
    exit 2
    ;;
esac
