#!/usr/bin/env bash
# Automated restore test (FEATURES 14.1, 13.8): restore the latest dump into a scratch database,
# run sanity queries, record the result as one JSON line, drop the scratch database.
#
# The JSON log is read by the app's ops module (status page): see docs/runbooks/backup-restore.md
# for the record format. A backup that has never been restored is not a backup.
#
# Usage: restore-test.sh [--dump FILE] [--keep]
#   --dump FILE   test this dump instead of the newest one in $BACKUP_DIR/dumps
#   --keep        keep the scratch database for inspection (default: drop it)
#
# Environment (defaults in brackets):
#   PGHOST PGPORT PGUSER PGPASSWORD   libpq connection; the role needs CREATEDB
#   BACKUP_DIR [/backups]
#   RESTORE_TEST_LOG [$BACKUP_DIR/status/restore-tests.jsonl]
#   RESTORE_TEST_REQUIRED [django_migrations]   tables that must exist and be non-empty
#   RESTORE_TEST_TABLES [key tables, see below]  tables whose row counts are recorded if present
#   RESTORE_JOBS [2]                              pg_restore parallel jobs
#   RESTORE_MAINTENANCE_DB [postgres]             database used to create/drop the scratch DB
#
# Exit: 0 passed, 1 failed.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=infra/backup/lib.sh
source "$SCRIPT_DIR/lib.sh"
LOG_TAG="restore-test"

DUMP=""
KEEP=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dump)
      DUMP="${2:-}"
      shift 2
      ;;
    --keep)
      KEEP=1
      shift
      ;;
    -h | --help)
      sed -n '2,23p' "$0"
      exit 0
      ;;
    *) die "unknown argument: $1" ;;
  esac
done

BACKUP_DIR="${BACKUP_DIR:-/backups}"
LOG_FILE="${RESTORE_TEST_LOG:-$BACKUP_DIR/status/restore-tests.jsonl}"
REQUIRED="${RESTORE_TEST_REQUIRED:-django_migrations}"
TABLES="${RESTORE_TEST_TABLES:-django_migrations core_user patients_patient visits_visit billing_invoice billing_invoiceline payments_payment payments_shift ledger_journalentry ledger_journalline pharmacy_stockmove lab_resultversion}"
RESTORE_JOBS="${RESTORE_JOBS:-2}"
MAINT_DB="${RESTORE_MAINTENANCE_DB:-postgres}"
require_uint RESTORE_JOBS "$RESTORE_JOBS"
require_cmd pg_restore psql

# Table lists may be comma- or space-separated.
REQUIRED="${REQUIRED//,/ }"
TABLES="${TABLES//,/ }"
for t in $REQUIRED $TABLES; do
  valid_identifier "$t" || die "invalid table name in RESTORE_TEST_*: '$t'"
done

STARTED_AT="$(iso_now)"
START_EPOCH="$(date +%s)"
SCRATCH="restore_test_$(date -u +%Y%m%d%H%M%S)_$$"
SCRATCH_CREATED=0
STATUS="failed"
ERROR=""
DUMP_SIZE=""
DUMP_SHA=""
TABLES_JSON="{}"
MISSING_JSON="[]"
TABLE_TOTAL=""
ERR_FILE="$(mktemp "${TMPDIR:-/tmp}/restore-test-err.XXXXXX")"
FINALIZED=0

write_result() {
  local now duration
  now="$(date +%s)"
  duration=$((now - START_EPOCH))
  append_json_line "$LOG_FILE" "{\"version\":1,\"type\":\"restore_test\",\"status\":$(json_str "$STATUS"),\"started_at\":$(json_str "$STARTED_AT"),\"finished_at\":$(json_str "$(iso_now)"),\"duration_s\":$duration,\"host\":$(json_str "$(hostname)"),\"dump\":$(json_str_or_null "$DUMP"),\"dump_size_bytes\":${DUMP_SIZE:-null},\"dump_sha256\":$(json_str_or_null "$DUMP_SHA"),\"scratch_db\":$(json_str "$SCRATCH"),\"kept\":$([[ $KEEP -eq 1 ]] && echo true || echo false),\"table_count\":${TABLE_TOTAL:-null},\"tables\":$TABLES_JSON,\"missing_tables\":$MISSING_JSON,\"error\":$(json_str_or_null "$ERROR")}"
}

drop_scratch() {
  [[ $SCRATCH_CREATED -eq 1 && $KEEP -eq 0 ]] || return 0
  psql_q "$MAINT_DB" -c "DROP DATABASE IF EXISTS \"$SCRATCH\" WITH (FORCE)" >/dev/null 2>&1 ||
    log "WARNING: could not drop scratch database $SCRATCH; drop it manually"
}

on_exit() {
  local code=$?
  drop_scratch
  if [[ $FINALIZED -eq 0 ]]; then
    [[ -z "$ERROR" ]] && ERROR="restore test aborted (exit $code)"
    STATUS="failed"
    write_result || true
    log "FAILED: $ERROR"
    [[ $code -eq 0 ]] && code=1
  fi
  rm -f "$ERR_FILE"
  release_lock
  exit "$code"
}
trap on_exit EXIT
trap 'exit 130' INT TERM

fail() {
  ERROR="$*"
  exit 1
}

# ---------------------------------------------------------------- one at a time, then tidy up
# The lock is per backup directory (one per server in production). Holding it means no other
# restore test of ours is running, so scratch databases from a killed run (SIGKILL, power cut:
# the EXIT trap never ran) are leftovers: drop them, they are full copies of production data.
acquire_lock "$BACKUP_DIR/.restore-test.flock" ||
  fail "another restore test holds $BACKUP_DIR/.restore-test.flock ($(lock_holder "$BACKUP_DIR/.restore-test.flock"))"
for stale in $(psql_q "$MAINT_DB" -c "SELECT datname FROM pg_database WHERE datname ~ '^restore_test_[0-9]{14}_[0-9]+\$'" 2>/dev/null || true); do
  # Without FORCE: a database something is still connected to is left alone.
  if psql_q "$MAINT_DB" -c "DROP DATABASE IF EXISTS \"$stale\"" >/dev/null 2>&1; then
    log "dropped leftover scratch database $stale"
  else
    log "WARNING: leftover scratch database $stale is in use; not dropped"
  fi
done

# ---------------------------------------------------------------- choose and verify the dump
if [[ -z "$DUMP" ]]; then
  newest=""
  # Newest first by modification time; names are ours (no spaces or newlines).
  while IFS= read -r f; do
    case "$f" in *.dump) newest="$f" && break ;; esac
  done < <(ls -1t "$BACKUP_DIR/dumps" 2>/dev/null)
  [[ -n "$newest" ]] || fail "no dumps found in $BACKUP_DIR/dumps"
  DUMP="$BACKUP_DIR/dumps/$newest"
fi
[[ -f "$DUMP" ]] || fail "dump not found: $DUMP"
DUMP_SIZE="$(file_size "$DUMP")"
DUMP_SHA="$(sha256_of "$DUMP")"
if [[ -f "$DUMP.sha256" ]]; then
  expected="$(awk '{print $1; exit}' "$DUMP.sha256")"
  [[ "$expected" == "$DUMP_SHA" ]] || fail "checksum mismatch for $DUMP (expected $expected, got $DUMP_SHA)"
else
  log "WARNING: no checksum file for $DUMP"
fi
log "restoring $DUMP ($DUMP_SIZE bytes) into scratch database $SCRATCH"

# ---------------------------------------------------------------- restore
if ! psql_q "$MAINT_DB" -c "CREATE DATABASE \"$SCRATCH\" TEMPLATE template0" >/dev/null 2>"$ERR_FILE"; then
  fail "cannot create scratch database: $(tail -n 3 "$ERR_FILE" | tr '\n' ' ')"
fi
SCRATCH_CREATED=1
if ! pg_restore --no-password --exit-on-error --no-owner --no-privileges --jobs="$RESTORE_JOBS" \
  --dbname="$SCRATCH" "$DUMP" 2>"$ERR_FILE"; then
  fail "pg_restore failed: $(tail -n 5 "$ERR_FILE" | tr '\n' ' ')"
fi

# ---------------------------------------------------------------- sanity queries
TABLE_TOTAL="$(psql_q "$SCRATCH" -c "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE'")"
[[ "$TABLE_TOTAL" -gt 0 ]] || fail "restored database has no tables"

table_exists() {
  [[ "$(psql_q "$SCRATCH" -c "SELECT to_regclass('public.$1') IS NOT NULL")" == "t" ]]
}

counts=""
missing=""
seen=" "
for t in $REQUIRED $TABLES; do
  case "$seen" in *" $t "*) continue ;; esac
  seen="$seen$t "
  if table_exists "$t"; then
    n="$(psql_q "$SCRATCH" -c "SELECT count(*) FROM public.\"$t\"")"
    counts="${counts:+$counts,}$(json_str "$t"):$n"
    log "  $t: $n rows"
  else
    missing="${missing:+$missing,}$(json_str "$t")"
  fi
done
TABLES_JSON="{$counts}"
MISSING_JSON="[$missing]"

for t in $REQUIRED; do
  table_exists "$t" || fail "required table $t is missing from the restored database"
  n="$(psql_q "$SCRATCH" -c "SELECT count(*) FROM public.\"$t\"")"
  [[ "$n" -gt 0 ]] || fail "required table $t is empty in the restored database"
done

STATUS="ok"
write_result
FINALIZED=1
log "restore test passed: $TABLE_TOTAL tables restored from $DUMP"
if [[ $KEEP -eq 1 ]]; then log "scratch database kept: $SCRATCH"; fi
