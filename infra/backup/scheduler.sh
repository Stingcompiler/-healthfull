#!/usr/bin/env bash
# Cron-like loop for the backup sidecar: a nightly backup and a monthly restore test.
# Logs to stdout (docker compose logs backup). A failed job is logged and recorded in the status
# JSONL by the job itself; the loop keeps running so the next night still gets a backup.
#
# Environment (defaults in brackets; times are the container's local time, TZ):
#   BACKUP_TIME [02:30]            daily backup time, HH:MM
#   RESTORE_TEST_DAY [1]           day of month for the restore test (1-28), 0 disables it
#   RESTORE_TEST_TIME [04:00]      restore test time, HH:MM
#   BACKUP_ON_START [false]        also run one backup right after the container starts
#   BACKUP_SCHEDULER [sidecar]     "off" idles the loop when host cron/systemd runs the jobs
# plus everything backup-nightly.sh and restore-test.sh read.
#
# Host-level alternatives (cron, systemd timers) are in infra/backup/examples/.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=infra/backup/lib.sh
source "$SCRIPT_DIR/lib.sh"
LOG_TAG="scheduler"

BACKUP_TIME="${BACKUP_TIME:-02:30}"
RESTORE_TEST_DAY="${RESTORE_TEST_DAY:-1}"
RESTORE_TEST_TIME="${RESTORE_TEST_TIME:-04:00}"

parse_hhmm() {
  # parse_hhmm NAME VALUE -> seconds after midnight
  local h m
  [[ "$2" =~ ^([01][0-9]|2[0-3]):([0-5][0-9])$ ]] || die "$1 must be HH:MM (got '$2')"
  h="${BASH_REMATCH[1]}"
  m="${BASH_REMATCH[2]}"
  echo $((10#$h * 3600 + 10#$m * 60))
}

seconds_until() {
  # seconds_until TARGET_SECONDS_AFTER_MIDNIGHT NOW_SECONDS_AFTER_MIDNIGHT -> 1..86400
  local delta=$(($1 - $2))
  [[ $delta -le 0 ]] && delta=$((delta + 86400))
  echo "$delta"
}

now_of_day() {
  local h m s
  h="$(date +%H)"
  m="$(date +%M)"
  s="$(date +%S)"
  echo $((10#$h * 3600 + 10#$m * 60 + 10#$s))
}

run_job() {
  local name="$1"
  shift
  log "starting $name"
  if "$@"; then
    log "$name finished ok"
  else
    log "$name finished with exit $? (see status log)"
  fi
}

# `scheduler.sh --next BACKUP_SECS RESTORE_SECS NOW_SECS` prints the next job; used by tests.
if [[ "${1:-}" == "--next" ]]; then
  b="$(seconds_until "$2" "$4")"
  r="$(seconds_until "$3" "$4")"
  if [[ $b -le $r ]]; then echo "backup $b"; else echo "restore $r"; fi
  exit 0
fi

backup_at="$(parse_hhmm BACKUP_TIME "$BACKUP_TIME")"
restore_at="$(parse_hhmm RESTORE_TEST_TIME "$RESTORE_TEST_TIME")"
require_uint RESTORE_TEST_DAY "$RESTORE_TEST_DAY"
[[ "$RESTORE_TEST_DAY" -le 28 ]] || die "RESTORE_TEST_DAY must be 0..28 (28 exists in every month)"
[[ "$backup_at" -ne "$restore_at" ]] || die "BACKUP_TIME and RESTORE_TEST_TIME must differ"

sleeper=""
trap 'log "stopping"; [[ -n "$sleeper" ]] && kill "$sleeper" 2>/dev/null; exit 0' INT TERM

if [[ "${BACKUP_SCHEDULER:-sidecar}" == "off" ]]; then
  log "BACKUP_SCHEDULER=off: jobs are scheduled on the host (infra/backup/examples); idling"
  while true; do
    sleep 86400 &
    sleeper=$!
    wait "$sleeper" || true
  done
fi

log "backup daily at $BACKUP_TIME; restore test $([[ $RESTORE_TEST_DAY -eq 0 ]] && echo disabled || echo "on day $RESTORE_TEST_DAY at $RESTORE_TEST_TIME") (TZ=${TZ:-system})"

if is_true "${BACKUP_ON_START:-false}"; then
  run_job "backup" "$SCRIPT_DIR/backup-nightly.sh"
fi

while true; do
  now="$(now_of_day)"
  b="$(seconds_until "$backup_at" "$now")"
  r="$(seconds_until "$restore_at" "$now")"
  if [[ $b -le $r ]]; then
    job="backup"
    wait_s=$b
  else
    job="restore"
    wait_s=$r
  fi
  # Sleep in the background so a stop signal is handled immediately.
  sleep "$wait_s" &
  sleeper=$!
  wait "$sleeper" || true
  sleeper=""
  if [[ "$job" == "backup" ]]; then
    run_job "nightly backup" "$SCRIPT_DIR/backup-nightly.sh" >/dev/null
  elif [[ "$RESTORE_TEST_DAY" -ne 0 && "$((10#$(date +%d)))" -eq "$RESTORE_TEST_DAY" ]]; then
    run_job "monthly restore test" "$SCRIPT_DIR/restore-test.sh"
  fi
  # Never fire the same slot twice within one minute.
  sleep 61 &
  sleeper=$!
  wait "$sleeper" || true
  sleeper=""
done
