#!/usr/bin/env bash
# Bring up every compose stack listed in config/autostart.conf.
# Safe to re-run: `docker compose up -d` leaves running containers alone.
set -uo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
conf="${repo_root}/config/autostart.conf"
failed=0

while read -r dir profiles; do
  [[ -z "$dir" || "$dir" == \#* ]] && continue
  args=()
  for p in $profiles; do args+=(--profile "$p"); done
  echo "==> ${dir}${profiles:+ (profiles: ${profiles})}"
  if ! (cd "${repo_root}/${dir}" && docker compose --env-file ../.env "${args[@]}" up -d); then
    echo "!! ${dir} failed to start" >&2
    failed=1
  fi
done < "$conf"

exit "$failed"
