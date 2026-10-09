#!/usr/bin/env bash
# Manual backups asked for on the status page (FEATURES 13.8, ADR 0014).
#
# The app never runs a backup: "Back up now" only inserts a row in ops_backuprequest
# (status "pending"). This script, run every minute by the backup sidecar's scheduler
# (BACKUP_REQUEST_POLL_SECONDS) or by a host timer (infra/backup/examples), picks it up:
#   1. requests left "running" by a run that died (container stopped, power cut) for more than
#      BACKUP_REQUEST_STALE_HOURS are marked failed;
#   2. the oldest pending request is claimed atomically (FOR UPDATE SKIP LOCKED, so two
#      schedulers never run the same request) and marked "running";
#   3. backup-nightly.sh --label manual-<id> runs (same checks, lock, retention and status
#      line as the nightly backup);
#   4. the outcome goes back on the row: succeeded, partial or failed, the dump file and, when
#      something went wrong, the last lines of the backup's log.
# One request per run. Logs go to stderr; nothing is printed on stdout.
#
# Exit: 0 nothing to do, or a request was processed (its outcome is on the row);
#       1 the database could not be read.
#
# Environment (defaults in brackets):
#   PGHOST PGPORT PGUSER PGPASSWORD   libpq connection (the sidecar's superuser)
#   DB_NAME [hospital]                the application database (ops_backuprequest lives there)
#   BACKUP_REQUEST_STALE_HOURS [6]    a "running" request older than this is marked failed
# plus everything backup-nightly.sh reads (BACKUP_DIR, MEDIA_DIR, ...).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=infra/backup/lib.sh
source "$SCRIPT_DIR/lib.sh"
LOG_TAG="requests"

DB_NAME="${DB_NAME:-hospital}"
BACKUP_REQUEST_STALE_HOURS="${BACKUP_REQUEST_STALE_HOURS:-6}"
valid_identifier "$DB_NAME" || die "DB_NAME must be a plain lowercase identifier (got '$DB_NAME')"
require_uint BACKUP_REQUEST_STALE_HOURS "$BACKUP_REQUEST_STALE_HOURS"
require_cmd psql

present="$(psql_q "$DB_NAME" -c "SELECT to_regclass('public.ops_backuprequest') IS NOT NULL")" ||
  die "cannot read database $DB_NAME"
if [[ "$present" != "t" ]]; then
  # A database migrated before manual backups existed: nothing can be waiting.
  exit 0
fi

psql_q "$DB_NAME" -v hours="$BACKUP_REQUEST_STALE_HOURS" >/dev/null <<'SQL'
UPDATE ops_backuprequest
   SET status = 'failed', finished_at = now(),
       message = 'Interrupted: the backup service stopped before the backup finished.'
 WHERE status = 'running'
   AND started_at < now() - make_interval(hours => :hours);
SQL

id="$(
  psql_q "$DB_NAME" <<'SQL'
UPDATE ops_backuprequest
   SET status = 'running', started_at = now()
 WHERE id = (SELECT id FROM ops_backuprequest
              WHERE status = 'pending'
              ORDER BY id
              LIMIT 1
              FOR UPDATE SKIP LOCKED)
RETURNING id;
SQL
)"
id="$(printf '%s' "$id" | head -n 1 | tr -cd '0-9')"
[[ -n "$id" ]] || exit 0

log "manual backup request $id claimed; running backup-nightly.sh --label manual-$id"
err_file="$(mktemp "${TMPDIR:-/tmp}/backup-request.XXXXXX")"
trap 'rm -f "$err_file"' EXIT
rc=0
dump="$("$SCRIPT_DIR/backup-nightly.sh" --label "manual-$id" 2>"$err_file")" || rc=$?
cat "$err_file" >&2
case "$rc" in
  0) status="succeeded" message="" ;;
  3) status="partial" message="$(grep -E 'WARNING|ERROR' "$err_file" | tail -n 3 || true)" ;;
  *) status="failed" message="$(tail -n 5 "$err_file")" ;;
esac
dump="$(printf '%s' "$dump" | head -n 1)"

psql_q "$DB_NAME" -v id="$id" -v status="$status" -v dump="$dump" -v message="$message" \
  >/dev/null <<'SQL'
UPDATE ops_backuprequest
   SET status = :'status', finished_at = now(), dump_file = left(:'dump', 500),
       message = left(:'message', 4000)
 WHERE id = :id;
SQL
log "manual backup request $id finished: $status"
