#!/usr/bin/env bash
# Restore a pg_dump archive as the live database, without destroying anything:
#   1. restore into a new database <target>_incoming_<stamp> (the live DB keeps serving meanwhile)
#   2. stop accepting connections to the live DB, terminate its sessions
#   3. rename live -> <target>_before_<stamp>, then incoming -> <target>
# The previous database is kept under its new name until an operator drops it.
# With DB_OWNER_USER / DB_APP_USER set (the compose backup service sets both), step 1 also hands
# the restored database and every object to the owner role and re-grants the app role
# (infra/db/roles.sh): pg_restore --no-owner makes the restoring superuser the owner of all.
# Stop the app first (docker compose stop app) so it does not reconnect during step 3.
#
# Usage: restore-dump.sh --dump FILE [--target DB_NAME] --yes
#
# Environment: PGHOST PGPORT PGUSER PGPASSWORD (superuser or owner with CREATEDB),
#              DB_NAME [hospital] default target, RESTORE_JOBS [2], RESTORE_MAINTENANCE_DB [postgres],
#              DB_OWNER_USER DB_APP_USER [unset: ownership and grants left as restored]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=infra/backup/lib.sh
source "$SCRIPT_DIR/lib.sh"
LOG_TAG="restore"

DUMP=""
TARGET="${DB_NAME:-hospital}"
YES=0
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
    --yes)
      YES=1
      shift
      ;;
    -h | --help)
      sed -n '2,18p' "$0"
      exit 0
      ;;
    *) die "unknown argument: $1" ;;
  esac
done

RESTORE_JOBS="${RESTORE_JOBS:-2}"
MAINT_DB="${RESTORE_MAINTENANCE_DB:-postgres}"
require_uint RESTORE_JOBS "$RESTORE_JOBS"
require_cmd pg_restore psql
[[ -n "$DUMP" && -f "$DUMP" ]] || die "--dump FILE is required and must exist"
valid_identifier "$TARGET" || die "invalid target database name '$TARGET'"
# Leave room for the _incoming_/_before_ suffixes within the 63-char identifier limit.
[[ ${#TARGET} -le 40 ]] || die "target database name too long for safe renaming"

if [[ -f "$DUMP.sha256" ]]; then
  expected="$(awk '{print $1; exit}' "$DUMP.sha256")"
  actual="$(sha256_of "$DUMP")"
  [[ "$expected" == "$actual" ]] || die "checksum mismatch for $DUMP; refusing to restore"
  log "checksum ok"
else
  log "WARNING: no checksum file next to $DUMP"
fi
pg_restore --list "$DUMP" >/dev/null || die "cannot read dump table of contents"

if [[ $YES -ne 1 ]]; then
  if [[ -t 0 ]]; then
    printf 'Replace database %s with %s? The current one is kept as %s_before_<stamp>. [y/N] ' \
      "$TARGET" "$DUMP" "$TARGET" >&2
    read -r answer
    [[ "$answer" == "y" || "$answer" == "Y" ]] || die "aborted by operator"
  else
    die "refusing to restore without --yes (non-interactive)"
  fi
fi

STAMP="$(date -u +%Y%m%d%H%M%S)"
INCOMING="${TARGET}_incoming_${STAMP}"
BEFORE="${TARGET}_before_${STAMP}"

cleanup_incoming() {
  psql_q "$MAINT_DB" -c "DROP DATABASE IF EXISTS \"$INCOMING\" WITH (FORCE)" >/dev/null 2>&1 || true
}

log "restoring into $INCOMING"
psql_q "$MAINT_DB" -c "CREATE DATABASE \"$INCOMING\" TEMPLATE template0" >/dev/null
if ! pg_restore --no-password --exit-on-error --no-owner --no-privileges --jobs="$RESTORE_JOBS" \
  --dbname="$INCOMING" "$DUMP"; then
  cleanup_incoming
  die "pg_restore failed; live database $TARGET untouched"
fi
tables="$(psql_q "$INCOMING" -c "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'")"
if [[ "$tables" -eq 0 ]]; then
  cleanup_incoming
  die "restored database has no tables; live database $TARGET untouched"
fi
log "restored $tables tables into $INCOMING"

if [[ -n "${DB_OWNER_USER:-}" || -n "${DB_APP_USER:-}" ]]; then
  # Before the swap: a database the app role cannot use never becomes the live one.
  roles="$SCRIPT_DIR/../db/roles.sh"
  if ! "$roles" --db "$INCOMING" --no-passwords || ! "$roles" --db "$INCOMING" --verify; then
    cleanup_incoming
    die "could not hand $INCOMING to the owner and app roles; live database $TARGET untouched"
  fi
  log "ownership: ${DB_OWNER_USER:-hospital_owner}; app role ${DB_APP_USER:-hospital_app} granted DML"
else
  log "DB_OWNER_USER/DB_APP_USER not set: objects stay owned by ${PGUSER:-the restoring role}"
fi

exists="$(psql_q "$MAINT_DB" -c "SELECT 1 FROM pg_database WHERE datname = '$TARGET'")"
if [[ "$exists" == "1" ]]; then
  log "swapping: $TARGET -> $BEFORE, $INCOMING -> $TARGET"
  # 1. Block new connections and end existing ones (a rename needs the database idle).
  if ! psql_q "$MAINT_DB" <<SQL >/dev/null; then
ALTER DATABASE "$TARGET" WITH ALLOW_CONNECTIONS false;
SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$TARGET' AND pid <> pg_backend_pid();
SELECT pg_sleep(1);
SQL
    psql_q "$MAINT_DB" -c "ALTER DATABASE \"$TARGET\" WITH ALLOW_CONNECTIONS true" >/dev/null 2>&1 || true
    die "could not take $TARGET offline for the swap; it is unchanged and open again"
  fi
  # 2. Both renames in ONE transaction: all or nothing. If anything fails, PostgreSQL rolls
  #    back, so $TARGET still exists under its own name, and step 3 re-opens it.
  if ! psql_q "$MAINT_DB" <<SQL >/dev/null; then
BEGIN;
ALTER DATABASE "$TARGET" RENAME TO "$BEFORE";
ALTER DATABASE "$BEFORE" WITH ALLOW_CONNECTIONS true;
ALTER DATABASE "$INCOMING" RENAME TO "$TARGET";
COMMIT;
SQL
    # 3. Rolled back: the live database is still $TARGET (with connections blocked).
    psql_q "$MAINT_DB" -c "ALTER DATABASE \"$TARGET\" WITH ALLOW_CONNECTIONS true" >/dev/null 2>&1 || true
    die "swap failed and was rolled back; $TARGET is unchanged (restored copy left in $INCOMING)"
  fi
  log "done. Previous database kept as $BEFORE (drop it once the restore is confirmed)."
else
  psql_q "$MAINT_DB" -c "ALTER DATABASE \"$INCOMING\" RENAME TO \"$TARGET\"" >/dev/null
  log "done. $TARGET did not exist; restored as new."
fi
printf '%s\n' "$TARGET"
