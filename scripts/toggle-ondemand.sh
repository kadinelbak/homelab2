#!/usr/bin/env bash
# =============================================================================
# toggle-ondemand.sh – Wake / Sleep the Phase 4 On-Demand stack
#
# Usage:
#   ./scripts/toggle-ondemand.sh up        Start all on-demand services
#   ./scripts/toggle-ondemand.sh down      Stop all on-demand services (no data loss)
#   ./scripts/toggle-ondemand.sh status    Show running containers from Phase 4
#   ./scripts/toggle-ondemand.sh up kiwix  Start ONLY the kiwix service
#   ./scripts/toggle-ondemand.sh down kiwix Stop ONLY the kiwix service
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
COMPOSE_FILE="${REPO_ROOT}/phase4-ondemand/docker-compose.yml"
ENV_FILE="${REPO_ROOT}/.env"

# Verify prerequisites
if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: .env file not found at ${ENV_FILE}"
  echo "       Copy .env.example to .env and fill in your values."
  exit 1
fi
if [[ ! -f "$COMPOSE_FILE" ]]; then
  echo "ERROR: Compose file not found at ${COMPOSE_FILE}"
  exit 1
fi

CMD="${1:-status}"
SERVICE="${2:-}"   # Optional: target a specific service

compose_cmd() {
  docker compose \
    --file "$COMPOSE_FILE" \
    --env-file "$ENV_FILE" \
    --project-name homelab_ondemand \
    "$@"
}

case "$CMD" in
  up)
    echo "==> Waking Phase 4 on-demand services..."
    if [[ -n "$SERVICE" ]]; then
      echo "    (targeting: ${SERVICE})"
      compose_cmd up -d "$SERVICE"
    else
      compose_cmd up -d
    fi
    echo ""
    echo "==> Currently running on-demand containers:"
    compose_cmd ps
    ;;

  down)
    echo "==> Sleeping Phase 4 on-demand services..."
    if [[ -n "$SERVICE" ]]; then
      echo "    (targeting: ${SERVICE})"
      compose_cmd stop "$SERVICE"
      compose_cmd rm -f "$SERVICE"
    else
      compose_cmd down
    fi
    echo "==> Done. Data is preserved. Run 'up' to restore."
    ;;

  status)
    echo "==> Phase 4 on-demand container status:"
    compose_cmd ps
    echo ""
    echo "==> System memory snapshot:"
    free -h
    ;;

  restart)
    echo "==> Restarting Phase 4 on-demand services..."
    if [[ -n "$SERVICE" ]]; then
      compose_cmd restart "$SERVICE"
    else
      compose_cmd restart
    fi
    ;;

  logs)
    # Usage: toggle-ondemand.sh logs <service>
    compose_cmd logs -f --tail=100 ${SERVICE:-}
    ;;

  *)
    echo "Usage: $0 {up|down|status|restart|logs} [service_name]"
    echo ""
    echo "  up [svc]      Start all (or one) on-demand service(s)"
    echo "  down [svc]    Stop and remove all (or one) on-demand service(s)"
    echo "  status        Show container status + memory usage"
    echo "  restart [svc] Restart all (or one) on-demand service(s)"
    echo "  logs [svc]    Follow logs (all or one service)"
    echo ""
    echo "Available services:"
    compose_cmd config --services 2>/dev/null || true
    exit 1
    ;;
esac
