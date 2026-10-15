#!/usr/bin/env bash
# Run read-only SQL against the health DB and print CSV.
#   ./health-sql.sh "SELECT metric_type, count(*) FROM metric_samples GROUP BY 1"
#   echo "SELECT 1" | ./health-sql.sh
# Works on the server, or from any machine with `ssh kadin-main-sys` (set HEALTH_SSH_HOST="" to run locally).
set -euo pipefail
host="${HEALTH_SSH_HOST-kadin-main-sys}"
cmd="docker exec -i health_timescaledb psql -X -q -U health_ro -d health -v ON_ERROR_STOP=1 --csv"
sql="${1:-$(cat)}"
if [[ -n "$host" ]]; then
  printf '%s\n' "$sql" | ssh "$host" "$cmd"
else
  printf '%s\n' "$sql" | $cmd
fi
