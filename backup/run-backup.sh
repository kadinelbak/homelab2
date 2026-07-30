#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-loop}"

DATA_ROOT="${DATA_ROOT:-/data}"
REPO_ROOT="${REPO_ROOT:-/repo}"
STATE_DIR="${STATE_DIR:-/backup/state}"
METRICS_DIR="${METRICS_DIR:-/metrics}"
EXCLUDE_FILE="${EXCLUDE_FILE:-/etc/homelab-backup/exclude-list}"
LOCK_FILE="${LOCK_FILE:-/backup/state/backup.lock}"
VERIFY_DIR="${VERIFY_DIR:-/backup/verify}"
BACKUP_INTERVAL_SECONDS="${BACKUP_INTERVAL_SECONDS:-86400}"

POSTGRES_HOST="${POSTGRES_HOST:-homelab_postgres}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_USER="${POSTGRES_USER:?POSTGRES_USER is required}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"

RESTIC_REPOSITORY="${RESTIC_REPOSITORY:-/backup/repo}"
RESTIC_PASSWORD="${RESTIC_PASSWORD:?RESTIC_PASSWORD is required}"
RESTIC_KEEP_DAILY="${RESTIC_KEEP_DAILY:-14}"
RESTIC_KEEP_WEEKLY="${RESTIC_KEEP_WEEKLY:-8}"
RESTIC_KEEP_MONTHLY="${RESTIC_KEEP_MONTHLY:-12}"
RESTIC_COMPRESSION="${RESTIC_COMPRESSION:-auto}"

export PGPASSWORD="$POSTGRES_PASSWORD"
export RESTIC_REPOSITORY
export RESTIC_PASSWORD
export RESTIC_COMPRESSION

mkdir -p "$STATE_DIR/db-dumps" "$METRICS_DIR" "$VERIFY_DIR"

log() {
  printf '%s %s\n' "$(date -Iseconds)" "$*"
}

write_metrics() {
  local status="$1"
  local started="$2"
  local ended="$3"
  local size_bytes="$4"
  local verify_status="$5"
  local metrics_tmp="${METRICS_DIR}/homelab_backup.prom.tmp"
  local metrics_file="${METRICS_DIR}/homelab_backup.prom"

  {
    printf '# HELP homelab_backup_last_success_timestamp_seconds Unix timestamp of the last successful backup.\n'
    printf '# TYPE homelab_backup_last_success_timestamp_seconds gauge\n'
    if [[ "$status" == "success" ]]; then
      printf 'homelab_backup_last_success_timestamp_seconds %s\n' "$ended"
    elif [[ -f "$metrics_file" ]]; then
      awk '/^homelab_backup_last_success_timestamp_seconds / {print; found=1} END {if (!found) print "homelab_backup_last_success_timestamp_seconds 0"}' "$metrics_file"
    else
      printf 'homelab_backup_last_success_timestamp_seconds 0\n'
    fi

    printf '# HELP homelab_backup_last_failure_timestamp_seconds Unix timestamp of the last failed backup.\n'
    printf '# TYPE homelab_backup_last_failure_timestamp_seconds gauge\n'
    if [[ "$status" == "failure" ]]; then
      printf 'homelab_backup_last_failure_timestamp_seconds %s\n' "$ended"
    elif [[ -f "$metrics_file" ]]; then
      awk '/^homelab_backup_last_failure_timestamp_seconds / {print; found=1} END {if (!found) print "homelab_backup_last_failure_timestamp_seconds 0"}' "$metrics_file"
    else
      printf 'homelab_backup_last_failure_timestamp_seconds 0\n'
    fi

    printf '# HELP homelab_backup_last_duration_seconds Duration of the last backup attempt.\n'
    printf '# TYPE homelab_backup_last_duration_seconds gauge\n'
    printf 'homelab_backup_last_duration_seconds %s\n' "$((ended - started))"

    printf '# HELP homelab_backup_last_size_bytes Restic repository size after the last backup attempt.\n'
    printf '# TYPE homelab_backup_last_size_bytes gauge\n'
    printf 'homelab_backup_last_size_bytes %s\n' "$size_bytes"

    printf '# HELP homelab_backup_last_verify_status Latest restore verification status, 1 success and 0 failure.\n'
    printf '# TYPE homelab_backup_last_verify_status gauge\n'
    printf 'homelab_backup_last_verify_status %s\n' "$verify_status"
  } > "$metrics_tmp"

  mv "$metrics_tmp" "$metrics_file"
}

repo_size_bytes() {
  if [[ "$RESTIC_REPOSITORY" == /* && -d "$RESTIC_REPOSITORY" ]]; then
    du -sb "$RESTIC_REPOSITORY" 2>/dev/null | awk '{print $1}'
  else
    printf '0\n'
  fi
}

init_repo() {
  if ! restic snapshots >/dev/null 2>&1; then
    log "Initializing restic repository at ${RESTIC_REPOSITORY}"
    restic init
  fi
}

wait_for_postgres() {
  local attempts=30
  local delay=5

  for _ in $(seq 1 "$attempts"); do
    if pg_isready -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" >/dev/null 2>&1; then
      return 0
    fi
    sleep "$delay"
  done

  return 1
}

dump_postgres() {
  local stamp="$1"
  local dump_dir="${STATE_DIR}/db-dumps/${stamp}"
  mkdir -p "$dump_dir"

  log "Creating PostgreSQL global dump"
  wait_for_postgres
  pg_dumpall \
    --host "$POSTGRES_HOST" \
    --port "$POSTGRES_PORT" \
    --username "$POSTGRES_USER" \
    --clean \
    --if-exists \
    --file "${dump_dir}/postgres-all.sql"

  gzip -f "${dump_dir}/postgres-all.sql"
}

run_restic_backup() {
  local stamp="$1"

  log "Running restic backup"
  restic backup \
    --tag homelab \
    --tag "$stamp" \
    --exclude-file "$EXCLUDE_FILE" \
    "$DATA_ROOT" \
    "${STATE_DIR}/db-dumps" \
    "$REPO_ROOT"
}

apply_retention() {
  log "Applying restic retention policy"
  restic forget \
    --tag homelab \
    --keep-daily "$RESTIC_KEEP_DAILY" \
    --keep-weekly "$RESTIC_KEEP_WEEKLY" \
    --keep-monthly "$RESTIC_KEEP_MONTHLY" \
    --prune
}

verify_latest_restore() {
  log "Verifying latest backup can be restored"
  rm -rf "$VERIFY_DIR/latest"
  mkdir -p "$VERIFY_DIR/latest"

  restic restore latest \
    --target "$VERIFY_DIR/latest" \
    --include "/${STATE_DIR#/}/db-dumps/**" \
    --include "${STATE_DIR#/}/db-dumps/**" \
    --include "/repo/phase1-core/docker-compose.yml" \
    --include "repo/phase1-core/docker-compose.yml"

  if ! find "$VERIFY_DIR/latest" -name 'postgres-all.sql.gz' -size +100c -print -quit | grep -q .; then
    log "Verification failed: restored PostgreSQL dump was not found or is empty"
    return 1
  fi

  if ! find "$VERIFY_DIR/latest" -path '*/phase1-core/docker-compose.yml' -size +100c -print -quit | grep -q .; then
    log "Verification failed: restored compose file was not found or is empty"
    return 1
  fi

  log "Verification succeeded"
}

run_once() {
  local started ended size verify_status
  local stamp

  started="$(date +%s)"
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  verify_status=0

  exec 9>"$LOCK_FILE"
  if ! flock -n 9; then
    log "Another backup run is already active"
    exit 0
  fi

  if init_repo && dump_postgres "$stamp" && run_restic_backup "$stamp" && apply_retention && verify_latest_restore; then
    verify_status=1
    ended="$(date +%s)"
    size="$(repo_size_bytes)"
    write_metrics success "$started" "$ended" "$size" "$verify_status"
    log "Backup completed successfully"
  else
    ended="$(date +%s)"
    size="$(repo_size_bytes)"
    write_metrics failure "$started" "$ended" "$size" "$verify_status"
    log "Backup failed"
    return 1
  fi
}

case "$MODE" in
  once)
    run_once
    ;;
  verify)
    init_repo
    verify_latest_restore
    ;;
  loop)
    while true; do
      run_once || true
      sleep "$BACKUP_INTERVAL_SECONDS"
    done
    ;;
  *)
    echo "Usage: run-backup.sh [once|verify|loop]" >&2
    exit 2
    ;;
esac
