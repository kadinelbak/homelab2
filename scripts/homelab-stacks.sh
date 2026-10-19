#!/usr/bin/env bash
# Run one action over every compose stack listed in config/autostart.conf.
#
#   start   Start missing or stopped containers. --no-recreate leaves existing
#           containers alone, so boot never redeploys. (homelab-autostart.service)
#   update  Pull newer images for services labelled
#           com.centurylinklabs.watchtower.enable=true and redeploy them through
#           compose, so containers keep matching the repo. (homelab-update.timer)
#   check   Send an ntfy alert if a container of a listed stack is not running
#           or is unhealthy. (homelab-check.timer)
set -uo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
conf="${repo_root}/config/autostart.conf"
ntfy_url="${HOMELAB_NTFY_URL:-http://127.0.0.1:8085/watchtower}"
action="${1:-}"
problems=()

# stack_compose <entry> [compose args...]
# A relative entry is a phase directory in this repo and uses the repo .env.
# An absolute entry is a compose file elsewhere and uses that project's own .env.
stack_compose() {
  local entry="$1"; shift
  if [[ "$entry" == /* ]]; then
    (cd "$(dirname "$entry")" && docker compose -f "$(basename "$entry")" "$@")
  else
    (cd "${repo_root}/${entry}" && docker compose --env-file ../.env "$@")
  fi
}

notify() {
  curl -fsS -m 10 -H "Title: homelab: $1" -d "$2" "$ntfy_url" >/dev/null || true
}

case "$action" in
  start|update|check) ;;
  *) echo "usage: $0 start|update|check" >&2; exit 2 ;;
esac

while read -r entry profiles; do
  [[ -z "$entry" || "$entry" == \#* ]] && continue
  args=()
  for p in $profiles; do args+=(--profile "$p"); done
  echo "==> ${entry}${profiles:+ (profiles: ${profiles})}"

  case "$action" in
    start)
      stack_compose "$entry" "${args[@]}" up -d --no-recreate || problems+=("${entry}: failed to start")
      ;;
    update)
      mapfile -t svcs < <(stack_compose "$entry" "${args[@]}" config --format json |
        jq -r '.services | to_entries[] | select(.value.labels["com.centurylinklabs.watchtower.enable"] == "true") | .key')
      (( ${#svcs[@]} )) || continue
      stack_compose "$entry" "${args[@]}" pull --quiet --ignore-buildable --ignore-pull-failures "${svcs[@]}" ||
        problems+=("${entry}: pull failed")
      stack_compose "$entry" "${args[@]}" up -d --no-deps --no-build "${svcs[@]}" ||
        problems+=("${entry}: redeploy failed")
      ;;
    check)
      # One-shot jobs that exited cleanly are fine.
      while read -r name state code health; do
        [[ "$state" == running && "$health" != unhealthy ]] && continue
        [[ "$state" == exited && "$code" == 0 ]] && continue
        problems+=("${name}: ${state} ${health}")
      done < <(stack_compose "$entry" "${args[@]}" ps -a --format '{{.Name}} {{.State}} {{.ExitCode}} {{.Health}}')
      ;;
  esac
done < "$conf"

[[ "$action" == update ]] && docker image prune -f >/dev/null

if (( ${#problems[@]} )); then
  printf '!! %s\n' "${problems[@]}" >&2
  notify "${action} found problems" "$(printf '%s\n' "${problems[@]}")"
  exit 1
fi
echo "ok"
