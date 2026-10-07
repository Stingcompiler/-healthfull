#!/usr/bin/env bash
# Cron-like loop for the backup sidecar: a nightly backup and a monthly restore test.
# Logs to stdout (docker compose logs backup). A failed job is logged and recorded in the status
# JSONL by the job itself; the loop keeps running so the next night still gets a backup.
#
# Catch-up (like systemd's Persistent=true): when the server was off or rebooting at the slot,
# the missed job runs as soon as the scheduler starts or next wakes up:
#   * a backup when the last ok/partial backup in status/backup-runs.jsonl finished more than
#     BACKUP_CATCHUP_HOURS ago (or there is none);
#   * a restore test when RESTORE_TEST_DAY has passed this month and no restore test in
#     status/restore-tests.jsonl succeeded this month.
#
# Jobs run as child processes that the loop waits on; a stop signal (docker stop) is passed
# on to the running job so it can clean up (give the service a long stop_grace_period).
#
# Environment (defaults in brackets; times are the container's local time, TZ):
#   BACKUP_TIME [02:30]            daily backup time, HH:MM
#   RESTORE_TEST_DAY [1]           day of month for the restore test (1-28), 0 disables it
#   RESTORE_TEST_TIME [04:00]      restore test time, HH:MM
#   BACKUP_CATCHUP_HOURS [24]      catch-up threshold for a missed backup, 0 disables catch-up
#   BACKUP_ON_START [false]        always run one backup right after the container starts
#   BACKUP_SCHEDULER [sidecar]     "off" idles the loop when host cron/systemd runs the jobs
# plus everything backup-nightly.sh and restore-test.sh read (BACKUP_DIR for the status files).
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
BACKUP_CATCHUP_HOURS="${BACKUP_CATCHUP_HOURS:-24}"
BACKUP_DIR="${BACKUP_DIR:-/backups}"
BACKUP_STATUS="$BACKUP_DIR/status/backup-runs.jsonl"
RESTORE_STATUS="${RESTORE_TEST_LOG:-$BACKUP_DIR/status/restore-tests.jsonl}"

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

job_pid=""
sleeper=""

run_job() {
  # run_job NAME CMD...: run in the background and wait, so a stop signal reaches this shell
  # (and is forwarded to the job by on_stop) instead of waiting for the job to end.
  local name="$1" rc=0
  shift
  log "starting $name"
  "$@" &
  job_pid=$!
  wait "$job_pid" || rc=$?
  job_pid=""
  if [[ $rc -eq 0 ]]; then
    log "$name finished ok"
  else
    log "$name finished with exit $rc (see status log)"
  fi
}

on_stop() {
  log "stopping"
  [[ -n "$sleeper" ]] && kill "$sleeper" 2>/dev/null
  if [[ -n "$job_pid" ]]; then
    log "passing the stop signal to the running job (pid $job_pid) and waiting for it"
    kill -TERM "$job_pid" 2>/dev/null || true
    wait "$job_pid" 2>/dev/null || true
  fi
  exit 0
}

backup_due() {
  # backup_due NOW_EPOCH: a backup was missed (none ok/partial within BACKUP_CATCHUP_HOURS).
  local now="$1" last epoch
  [[ "$BACKUP_CATCHUP_HOURS" -gt 0 ]] || return 1
  last="$(last_success "$BACKUP_STATUS" backup 'ok|partial')"
  [[ -n "$last" ]] || return 0
  epoch="$(iso_to_epoch "$last")" || return 0
  [[ $((now - epoch)) -ge $((BACKUP_CATCHUP_HOURS * 3600)) ]]
}

restore_test_due() {
  # restore_test_due DAY_OF_MONTH YYYY-MM: this month's test day has come and none passed yet.
  local day="$1" month="$2" last
  [[ "$RESTORE_TEST_DAY" -ne 0 && "$day" -ge "$RESTORE_TEST_DAY" ]] || return 1
  last="$(last_success "$RESTORE_STATUS" restore_test 'ok')"
  [[ "${last:0:7}" != "$month" ]]
}

catch_up() {
  if backup_due "$(date +%s)"; then
    log "catch-up: no successful backup in the last ${BACKUP_CATCHUP_HOURS}h"
    run_job "catch-up backup" "$SCRIPT_DIR/backup-nightly.sh" >/dev/null
  fi
  if restore_test_due "$((10#$(date +%d)))" "$(date -u +%Y-%m)"; then
    log "catch-up: no successful restore test this month"
    run_job "catch-up restore test" "$SCRIPT_DIR/restore-test.sh"
  fi
}

# `scheduler.sh --next BACKUP_SECS RESTORE_SECS NOW_SECS` prints the next job; used by tests.
if [[ "${1:-}" == "--next" ]]; then
  b="$(seconds_until "$2" "$4")"
  r="$(seconds_until "$3" "$4")"
  if [[ $b -le $r ]]; then echo "backup $b"; else echo "restore $r"; fi
  exit 0
fi

# `scheduler.sh --due NOW_EPOCH DAY_OF_MONTH YYYY-MM` prints which catch-up jobs are due
# from the status files; used by tests.
if [[ "${1:-}" == "--due" ]]; then
  require_uint BACKUP_CATCHUP_HOURS "$BACKUP_CATCHUP_HOURS"
  due=""
  backup_due "$2" && due="backup"
  restore_test_due "$3" "$4" && due="${due:+$due }restore"
  echo "${due:-none}"
  exit 0
fi

backup_at="$(parse_hhmm BACKUP_TIME "$BACKUP_TIME")"
restore_at="$(parse_hhmm RESTORE_TEST_TIME "$RESTORE_TEST_TIME")"
require_uint RESTORE_TEST_DAY "$RESTORE_TEST_DAY"
require_uint BACKUP_CATCHUP_HOURS "$BACKUP_CATCHUP_HOURS"
[[ "$RESTORE_TEST_DAY" -le 28 ]] || die "RESTORE_TEST_DAY must be 0..28 (28 exists in every month)"
[[ "$backup_at" -ne "$restore_at" ]] || die "BACKUP_TIME and RESTORE_TEST_TIME must differ"

trap on_stop INT TERM

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
  run_job "backup" "$SCRIPT_DIR/backup-nightly.sh" >/dev/null
fi
catch_up

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
  # A long sleep can be cut short by a suspend or a clock change: re-check for missed jobs.
  catch_up
  # Never fire the same slot twice within one minute.
  sleep 61 &
  sleeper=$!
  wait "$sleeper" || true
  sleeper=""
done
