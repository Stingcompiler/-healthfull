#!/usr/bin/env bash
# Restore-from-scratch drill (FEATURES 14.1, 14.6): rebuild the database from a dump the way a
# replacement server does, then prove the result is usable and consistent.
#
#   1. a brand new, empty database <target>, and the two roles set up on it as the db
#      container's first start does (infra/db/roles.sh: owner owns it, app gets DML only)
#   2. restore-dump.sh restores the dump into it and hands every object to the owner role
#      (the empty database it replaced is dropped)
#   3. with --manage: `manage.py migrate --check` as the OWNER role (code and schema agree,
#      nothing pending) and `manage.py integrity_check --json` as the APP role (trial balance
#      zero, document positions = ledger, stock never negative, no orphan allocations; and the
#      app role can read everything it needs)
#   4. row counts of the key tables
#   5. one JSON line in the restore-test log (type restore_test, label drill), which the
#      status page shows next to the monthly restore tests; the target is dropped unless --keep
#
# Usage: restore-drill.sh [--dump FILE] [--target NAME] [--keep] [--manage "COMMAND"]
#   --dump FILE      the dump to restore [newest in $BACKUP_DIR/dumps]
#   --target NAME    database to build [restore_drill_<UTC stamp>]; must not exist
#   --keep           keep the database (e.g. to point a test app at it)
#   --manage CMD     how to run Django's manage.py here, e.g. "python manage.py" in the app
#                    image or "uv run --directory backend python manage.py" in a checkout
#                    [MANAGE_CMD]. Empty: steps 3 is skipped and recorded as skipped; run the
#                    two commands in the app containers instead (docs/runbooks/backup-restore.md)
#
# Environment (defaults in brackets):
#   PGHOST PGPORT PGUSER PGPASSWORD   libpq connection as a superuser (creates the database)
#   BACKUP_DIR [/backups]
#   RESTORE_DRILL_LOG [$BACKUP_DIR/status/restore-tests.jsonl]
#   DB_OWNER_USER [hospital_owner]  DB_APP_USER [hospital_app]
#   DB_OWNER_PASSWORD DB_APP_PASSWORD  when both are set the roles are created (or their
#                                      passwords reset) as on a new machine; otherwise the roles
#                                      must exist already. Also used to log in for step 3.
#   RESTORE_TEST_TABLES [key tables]   tables whose row counts are recorded
#
# Exit: 0 passed, 1 failed, 2 usage error.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=infra/backup/lib.sh
source "$SCRIPT_DIR/lib.sh"
LOG_TAG="restore-drill"

DUMP=""
TARGET=""
KEEP=0
MANAGE="${MANAGE_CMD:-}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dump)
      DUMP="${2:-}"
      shift 2
      ;;
    --target)
      TARGET="${2:-}"
      shift 2
      ;;
    --keep)
      KEEP=1
      shift
      ;;
    --manage)
      MANAGE="${2:-}"
      shift 2
      ;;
    -h | --help)
      sed -n '2,37p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "restore-drill: unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

BACKUP_DIR="${BACKUP_DIR:-/backups}"
LOG_FILE="${RESTORE_DRILL_LOG:-$BACKUP_DIR/status/restore-tests.jsonl}"
MAINT_DB="${RESTORE_MAINTENANCE_DB:-postgres}"
OWNER="${DB_OWNER_USER:-hospital_owner}"
APP="${DB_APP_USER:-hospital_app}"
TABLES="${RESTORE_TEST_TABLES:-django_migrations core_user patients_patient visits_visit billing_invoice billing_invoiceline payments_payment payments_allocation payments_shift ledger_journalentry ledger_journalline pharmacy_stockmove pharmacy_stockbalance lab_resultversion claims_claim ops_updaterun}"
TABLES="${TABLES//,/ }"
require_cmd pg_restore psql
for t in $TABLES; do
  valid_identifier "$t" || { echo "restore-drill: invalid table name '$t'" >&2; exit 2; }
done
[[ -z "$TARGET" ]] && TARGET="restore_drill_$(date -u +%Y%m%d%H%M%S)"
valid_identifier "$TARGET" || { echo "restore-drill: invalid target name '$TARGET'" >&2; exit 2; }
[[ ${#TARGET} -le 40 ]] || { echo "restore-drill: target name longer than 40 characters" >&2; exit 2; }

STARTED_AT="$(iso_now)"
START_EPOCH="$(date +%s)"
STATUS="failed"
ERROR=""
CREATED=0
FINALIZED=0
STEP=""
DUMP_SHA=""
ROLES="not run"
MIGRATIONS="not run"
INTEGRITY="not run"
INTEGRITY_JSON="null"
TABLES_JSON="{}"
ERR_FILE="$(mktemp "${TMPDIR:-/tmp}/restore-drill-err.XXXXXX")"

write_result() {
  local duration=$(($(date +%s) - START_EPOCH))
  append_json_line "$LOG_FILE" "{\"version\":1,\"type\":\"restore_test\",\"label\":\"drill\",\"status\":$(json_str "$STATUS"),\"started_at\":$(json_str "$STARTED_AT"),\"finished_at\":$(json_str "$(iso_now)"),\"duration_s\":$duration,\"host\":$(json_str "$(hostname)"),\"dump\":$(json_str_or_null "$DUMP"),\"dump_sha256\":$(json_str_or_null "$DUMP_SHA"),\"target_db\":$(json_str "$TARGET"),\"kept\":$([[ $KEEP -eq 1 ]] && echo true || echo false),\"roles\":$(json_str "$ROLES"),\"migrations_check\":$(json_str "$MIGRATIONS"),\"integrity_check\":$(json_str "$INTEGRITY"),\"integrity\":$INTEGRITY_JSON,\"tables\":$TABLES_JSON,\"error\":$(json_str_or_null "$ERROR")}"
}

drop_target() {
  [[ $CREATED -eq 1 && $KEEP -eq 0 ]] || return 0
  psql_q "$MAINT_DB" -c "DROP DATABASE IF EXISTS \"$TARGET\" WITH (FORCE)" >/dev/null 2>&1 ||
    log "WARNING: could not drop $TARGET; drop it by hand (it is a full copy of the data)"
}

on_exit() {
  local code=$?
  drop_target
  if [[ $FINALIZED -eq 0 ]]; then
    [[ -z "$ERROR" ]] && ERROR="drill aborted during ${STEP:-start} (exit $code)"
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

acquire_lock "$BACKUP_DIR/.restore-test.flock" ||
  fail "a restore test or drill holds $BACKUP_DIR/.restore-test.flock ($(lock_holder "$BACKUP_DIR/.restore-test.flock"))"

# ---------------------------------------------------------------- 0. the dump
STEP="choose dump"
if [[ -z "$DUMP" ]]; then
  while IFS= read -r f; do
    case "$f" in *.dump) DUMP="$BACKUP_DIR/dumps/$f" && break ;; esac
  done < <(ls -1t "$BACKUP_DIR/dumps" 2>/dev/null)
  [[ -n "$DUMP" ]] || fail "no dumps found in $BACKUP_DIR/dumps"
fi
[[ -f "$DUMP" ]] || fail "dump not found: $DUMP"
DUMP_SHA="$(sha256_of "$DUMP")"
log "drill: $DUMP into new database $TARGET (owner $OWNER, app $APP)"

# ---------------------------------------------------------------- 1. new database and roles
STEP="create database and roles"
exists="$(psql_q "$MAINT_DB" -c "SELECT 1 FROM pg_database WHERE datname = '$TARGET'")"
[[ -z "$exists" ]] || fail "database $TARGET already exists; the drill builds a new one"
psql_q "$MAINT_DB" -c "CREATE DATABASE \"$TARGET\" TEMPLATE template0" >/dev/null 2>"$ERR_FILE" ||
  fail "cannot create $TARGET: $(tail -n 3 "$ERR_FILE" | tr '\n' ' ')"
CREATED=1
roles_args=(--db "$TARGET")
if [[ -z "${DB_OWNER_PASSWORD:-}" || -z "${DB_APP_PASSWORD:-}" ]]; then
  roles_args+=(--no-passwords)
fi
DB_OWNER_USER="$OWNER" DB_APP_USER="$APP" "$SCRIPT_DIR/../db/roles.sh" "${roles_args[@]}" 2>"$ERR_FILE" ||
  fail "roles could not be set up: $(tail -n 3 "$ERR_FILE" | tr '\n' ' ')"

# ---------------------------------------------------------------- 2. restore
STEP="restore"
DB_OWNER_USER="$OWNER" DB_APP_USER="$APP" \
  "$SCRIPT_DIR/restore-dump.sh" --dump "$DUMP" --target "$TARGET" --yes >/dev/null 2>"$ERR_FILE" ||
  fail "restore-dump failed: $(tail -n 5 "$ERR_FILE" | tr '\n' ' ')"
# restore-dump kept the empty database it replaced as <target>_before_<stamp>: ours, drop it.
for before in $(psql_q "$MAINT_DB" -c "SELECT datname FROM pg_database WHERE datname ~ '^${TARGET}_before_[0-9]{14}\$'"); do
  psql_q "$MAINT_DB" -c "DROP DATABASE IF EXISTS \"$before\" WITH (FORCE)" >/dev/null
done
DB_OWNER_USER="$OWNER" DB_APP_USER="$APP" "$SCRIPT_DIR/../db/roles.sh" --db "$TARGET" --verify >/dev/null 2>"$ERR_FILE" ||
  fail "roles verification failed on the restored database: $(tail -n 3 "$ERR_FILE" | tr '\n' ' ')"
ROLES="ok"
log "restored and handed to $OWNER; $APP has DML only"

# ---------------------------------------------------------------- 3. Django checks
run_manage() {
  # run_manage ROLE PASSWORD ARGS...: manage.py against the drill database as ROLE.
  local role="$1" password="$2"
  shift 2
  # shellcheck disable=SC2086 # MANAGE is a command line ("python manage.py"), split on purpose
  env DB_NAME="$TARGET" PGUSER="$role" PGPASSWORD="$password" $MANAGE "$@"
}

if [[ -n "$MANAGE" ]]; then
  STEP="migrations check"
  if run_manage "$OWNER" "${DB_OWNER_PASSWORD:-}" migrate --check >/dev/null 2>"$ERR_FILE"; then
    MIGRATIONS="ok"
  else
    MIGRATIONS="failed"
    fail "migrate --check: the restored schema does not match this version: $(tail -n 3 "$ERR_FILE" | tr '\n' ' ')"
  fi
  STEP="integrity check"
  set +e
  out="$(run_manage "$APP" "${DB_APP_PASSWORD:-}" integrity_check --json 2>"$ERR_FILE")"
  rc=$?
  set -e
  out="$(printf '%s\n' "$out" | tail -n 1)"
  if [[ "$out" =~ ^\{.*\}$ ]]; then
    INTEGRITY_JSON="$out"
  else
    INTEGRITY_JSON="$(json_str_or_null "$out")"
  fi
  if [[ $rc -eq 0 && "$out" == *'"ok": true}' ]]; then
    INTEGRITY="ok"
  else
    INTEGRITY="failed"
    fail "integrity_check failed (exit $rc): $(tail -n 3 "$ERR_FILE" | tr '\n' ' ')"
  fi
  log "migrate --check ok (as $OWNER); integrity_check ok (as $APP)"
else
  MIGRATIONS="skipped"
  INTEGRITY="skipped"
  log "no --manage: run migrate --check and integrity_check against $TARGET in the app containers"
fi

# ---------------------------------------------------------------- 4. row counts
STEP="row counts"
counts=""
for t in $TABLES; do
  if [[ "$(psql_q "$TARGET" -c "SELECT to_regclass('public.$t') IS NOT NULL")" == "t" ]]; then
    n="$(psql_q "$TARGET" -c "SELECT count(*) FROM public.\"$t\"")"
    counts="${counts:+$counts,}$(json_str "$t"):$n"
    log "  $t: $n rows"
  fi
done
TABLES_JSON="{$counts}"
[[ "$counts" == *'"django_migrations":'* && "$counts" != *'"django_migrations":0'* ]] ||
  fail "django_migrations is missing or empty in the restored database"

STATUS="ok"
write_result
FINALIZED=1
log "drill passed: $TARGET rebuilt from $DUMP"
[[ $KEEP -eq 1 ]] && log "database kept: $TARGET (drop it when done)"
exit 0
