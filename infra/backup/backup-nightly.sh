#!/usr/bin/env bash
# Nightly backup (FEATURES 14.1): a verified pg_dump custom-format archive with day-based
# retention, an optional media archive, and optional pgBackRest full/diff backups.
#
# Runs inside the backup sidecar (infra/docker-compose.yml) or on any host with PostgreSQL 16
# client tools. Logs go to stderr; on success the dump path is the only line on stdout, so
# callers can do:  dump="$(backup-nightly.sh --label pre-update-v1.4.0)"
#
# Usage: backup-nightly.sh [--label NAME] [--no-pgbackrest] [--no-prune]
#
# Exit: 0 ok; 1 failed (no new dump); 3 partial (dump ok, a pgBackRest backup failed).
#
# Environment (defaults in brackets):
#   PGHOST PGPORT PGUSER PGPASSWORD   libpq connection
#   DB_NAME [hospital]                database to dump
#   BACKUP_DIR [/backups]             dumps/, media/, status/ live here
#   BACKUP_RETENTION_DAYS [14]        delete dumps older than this many days...
#   BACKUP_KEEP_MIN [3]               ...but always keep at least this many newest dumps
#   BACKUP_COMPRESSION [6]            pg_dump -Z value (gzip level; "zstd:3" also works on PG16)
#   BACKUP_MIN_FREE_FACTOR [1]        require free space >= factor x database size before dumping
#   MEDIA_DIR []                      if set and present, also archive uploaded files
#   PGBACKREST_ENABLED [false]        also run pgBackRest (needs PG_ARCHIVE_MODE=on, see runbook)
#   PGBACKREST_STANZA [hospital]
#   PGBACKREST_FULL_DAY [7]           ISO weekday (1=Mon..7=Sun) for full backups; diff otherwise
#   PGBACKREST_REPO2_S3_BUCKET []     when set, also back up to repo2 (cloud, one-way)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=infra/backup/lib.sh
source "$SCRIPT_DIR/lib.sh"
LOG_TAG="backup"

LABEL=""
RUN_PGBACKREST=1
PRUNE=1
while [[ $# -gt 0 ]]; do
  case "$1" in
    --label)
      LABEL="${2:-}"
      shift 2
      ;;
    --no-pgbackrest)
      RUN_PGBACKREST=0
      shift
      ;;
    --no-prune)
      PRUNE=0
      shift
      ;;
    -h | --help)
      sed -n '2,32p' "$0"
      exit 0
      ;;
    *) die "unknown argument: $1" ;;
  esac
done

DB_NAME="${DB_NAME:-hospital}"
BACKUP_DIR="${BACKUP_DIR:-/backups}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
BACKUP_KEEP_MIN="${BACKUP_KEEP_MIN:-3}"
BACKUP_COMPRESSION="${BACKUP_COMPRESSION:-6}"
BACKUP_MIN_FREE_FACTOR="${BACKUP_MIN_FREE_FACTOR:-1}"
MEDIA_DIR="${MEDIA_DIR:-}"
PGBACKREST_STANZA="${PGBACKREST_STANZA:-hospital}"
PGBACKREST_FULL_DAY="${PGBACKREST_FULL_DAY:-7}"

valid_identifier "$DB_NAME" || die "DB_NAME must be a plain lowercase identifier (got '$DB_NAME')"
require_uint BACKUP_RETENTION_DAYS "$BACKUP_RETENTION_DAYS"
require_uint BACKUP_KEEP_MIN "$BACKUP_KEEP_MIN"
require_uint BACKUP_MIN_FREE_FACTOR "$BACKUP_MIN_FREE_FACTOR"
[[ "$BACKUP_KEEP_MIN" -ge 1 ]] || die "BACKUP_KEEP_MIN must be at least 1"
if [[ -n "$LABEL" && ! "$LABEL" =~ ^[A-Za-z0-9._-]{1,64}$ ]]; then
  die "--label may contain only letters, digits, '.', '_' and '-' (max 64)"
fi
require_cmd pg_dump pg_restore psql

DUMP_DIR="$BACKUP_DIR/dumps"
MEDIA_OUT_DIR="$BACKUP_DIR/media"
STATUS_FILE="$BACKUP_DIR/status/backup-runs.jsonl"
LOCK_DIR="$BACKUP_DIR/.backup.lock"

STARTED_AT="$(iso_now)"
START_EPOCH="$(date +%s)"
STAMP="$(utc_stamp)"
STATUS="failed"
ERROR=""
DUMP_PATH=""
DUMP_SIZE=""
DUMP_SHA=""
MEDIA_PATH=""
PGBR_JSON="null"
PRUNED_JSON="[]"
PARTIAL=""
ERR_FILE=""
FINALIZED=0

mkdir -p "$DUMP_DIR" "$BACKUP_DIR/status"
chmod 0750 "$DUMP_DIR" 2>/dev/null || true

write_status() {
  local finished duration
  finished="$(iso_now)"
  duration=$(($(date +%s) - START_EPOCH))
  local dump_json="null" media_json="null"
  if [[ -n "$DUMP_PATH" ]]; then
    dump_json="{\"file\":$(json_str "$DUMP_PATH"),\"size_bytes\":${DUMP_SIZE:-0},\"sha256\":$(json_str "$DUMP_SHA")}"
  fi
  [[ -n "$MEDIA_PATH" ]] && media_json="{\"file\":$(json_str "$MEDIA_PATH")}"
  append_json_line "$STATUS_FILE" "{\"version\":1,\"type\":\"backup\",\"status\":$(json_str "$STATUS"),\"started_at\":$(json_str "$STARTED_AT"),\"finished_at\":$(json_str "$finished"),\"duration_s\":$duration,\"host\":$(json_str "$(hostname)"),\"database\":$(json_str "$DB_NAME"),\"label\":$(json_str_or_null "$LABEL"),\"dump\":$dump_json,\"media\":$media_json,\"pgbackrest\":$PGBR_JSON,\"pruned\":$PRUNED_JSON,\"error\":$(json_str_or_null "$ERROR")}"
}

on_exit() {
  local code=$?
  [[ -n "$PARTIAL" && -f "$PARTIAL" ]] && rm -f "$PARTIAL"
  if [[ $code -ne 0 && $FINALIZED -eq 0 ]]; then
    [[ -z "$ERROR" ]] && ERROR="backup failed (exit $code)"
    STATUS="failed"
    write_status || true
    log "FAILED: $ERROR"
  fi
  [[ -n "$ERR_FILE" ]] && rm -f "$ERR_FILE"
  release_lock "$LOCK_DIR"
  exit "$code"
}

fail() {
  ERROR="$*"
  die "$*"
}

acquire_lock "$LOCK_DIR"
trap on_exit EXIT
trap 'exit 130' INT TERM
ERR_FILE="$(mktemp "${TMPDIR:-/tmp}/backup-err.XXXXXX")"

# ---------------------------------------------------------------- preflight
log "starting backup of database $DB_NAME into $DUMP_DIR${LABEL:+ (label $LABEL)}"
if ! DB_SIZE="$(psql_q "$DB_NAME" -c "SELECT pg_database_size(current_database())" 2>"$ERR_FILE")"; then
  fail "cannot connect to database $DB_NAME: $(tail -n 3 "$ERR_FILE" | tr '\n' ' ')"
fi
need_kb=$(((DB_SIZE / 1024) * BACKUP_MIN_FREE_FACTOR))
have_kb="$(free_kb "$DUMP_DIR")"
if [[ "$have_kb" -lt "$need_kb" ]]; then
  fail "not enough free space in $DUMP_DIR: ${have_kb} KiB free, need ${need_kb} KiB"
fi

# ---------------------------------------------------------------- pg_dump
name="${DB_NAME}-${STAMP}${LABEL:+-$LABEL}.dump"
DUMP_PATH="$DUMP_DIR/$name"
PARTIAL="$DUMP_DIR/.${name}.partial"
if ! pg_dump --no-password --format=custom --compress="$BACKUP_COMPRESSION" --lock-wait-timeout=120000 \
  --file="$PARTIAL" --dbname="$DB_NAME" 2>"$ERR_FILE"; then
  DUMP_PATH=""
  fail "pg_dump failed: $(tail -n 5 "$ERR_FILE" | tr '\n' ' ')"
fi
# A dump whose table of contents cannot be read is not a backup.
if ! entries="$(pg_restore --list "$PARTIAL" 2>"$ERR_FILE" | grep -cv '^;')"; then
  DUMP_PATH=""
  fail "dump verification failed: $(tail -n 5 "$ERR_FILE" | tr '\n' ' ')"
fi
[[ "$entries" -gt 0 ]] || {
  DUMP_PATH=""
  fail "dump has no entries"
}
mv "$PARTIAL" "$DUMP_PATH"
PARTIAL=""
chmod 0640 "$DUMP_PATH" 2>/dev/null || true
DUMP_SHA="$(sha256_of "$DUMP_PATH")"
DUMP_SIZE="$(file_size "$DUMP_PATH")"
printf '%s  %s\n' "$DUMP_SHA" "$name" >"$DUMP_PATH.sha256"
log "dump ok: $DUMP_PATH ($DUMP_SIZE bytes, $entries TOC entries)"

# ---------------------------------------------------------------- media (uploaded files)
if [[ -n "$MEDIA_DIR" && -d "$MEDIA_DIR" ]]; then
  mkdir -p "$MEDIA_OUT_DIR"
  chmod 0750 "$MEDIA_OUT_DIR" 2>/dev/null || true
  media_name="media-${STAMP}${LABEL:+-$LABEL}.tar.gz"
  if tar -C "$MEDIA_DIR" -czf "$MEDIA_OUT_DIR/.$media_name.partial" . 2>"$ERR_FILE"; then
    mv "$MEDIA_OUT_DIR/.$media_name.partial" "$MEDIA_OUT_DIR/$media_name"
    printf '%s  %s\n' "$(sha256_of "$MEDIA_OUT_DIR/$media_name")" "$media_name" >"$MEDIA_OUT_DIR/$media_name.sha256"
    MEDIA_PATH="$MEDIA_OUT_DIR/$media_name"
    log "media ok: $MEDIA_PATH"
  else
    rm -f "$MEDIA_OUT_DIR/.$media_name.partial"
    fail "media archive failed: $(tail -n 3 "$ERR_FILE" | tr '\n' ' ')"
  fi
fi

# ---------------------------------------------------------------- pgBackRest (optional)
pgbackrest_failed=0
if [[ $RUN_PGBACKREST -eq 1 ]] && is_true "${PGBACKREST_ENABLED:-false}"; then
  require_cmd pgbackrest
  if [[ "$(date +%u)" == "$PGBACKREST_FULL_DAY" ]]; then btype="full"; else btype="diff"; fi
  repos="1"
  [[ -n "${PGBACKREST_REPO2_S3_BUCKET:-}" ]] && repos="1 2"
  # Idempotent: succeeds when the stanza already exists and matches this cluster.
  pgbackrest --stanza="$PGBACKREST_STANZA" stanza-create >&2 || true
  items=""
  for repo in $repos; do
    log "pgbackrest $btype backup to repo$repo"
    if pgbackrest --stanza="$PGBACKREST_STANZA" --repo="$repo" --type="$btype" backup >&2; then
      result="ok"
    else
      result="failed"
      pgbackrest_failed=1
      # repo2 (cloud) failing while offline is expected; repo1 failing is not.
      log "WARNING: pgbackrest backup to repo$repo failed"
    fi
    items="${items:+$items,}{\"repo\":$repo,\"type\":\"$btype\",\"status\":\"$result\"}"
  done
  PGBR_JSON="[$items]"
fi

# ---------------------------------------------------------------- retention
prune() {
  # prune DIR SUFFIX: newest-first by mtime; keep BACKUP_KEEP_MIN, delete the rest when old.
  local dir="$1" suffix="$2" f i=0 out=""
  [[ -d "$dir" ]] || return 0
  local minutes=$((BACKUP_RETENTION_DAYS * 1440))
  while IFS= read -r f; do
    [[ "$f" == *"$suffix" ]] || continue
    i=$((i + 1))
    [[ $i -le $BACKUP_KEEP_MIN ]] && continue
    if [[ -n "$(find "$dir/$f" -prune -mmin +"$minutes" 2>/dev/null)" ]]; then
      rm -f "$dir/$f" "$dir/$f.sha256"
      out="${out:+$out,}$(json_str "$dir/$f")"
      log "pruned $dir/$f"
    fi
  done < <(ls -1t "$dir" 2>/dev/null)
  printf '%s' "$out"
}

if [[ $PRUNE -eq 1 ]]; then
  pruned_dumps="$(prune "$DUMP_DIR" ".dump")"
  pruned_media="$(prune "$MEDIA_OUT_DIR" ".tar.gz")"
  joined="$pruned_dumps"
  [[ -n "$pruned_media" ]] && joined="${joined:+$joined,}$pruned_media"
  PRUNED_JSON="[$joined]"
fi

if [[ $pgbackrest_failed -eq 1 ]]; then STATUS="partial"; else STATUS="ok"; fi
write_status
FINALIZED=1
log "backup finished: status=$STATUS"
printf '%s\n' "$DUMP_PATH"
[[ "$STATUS" == "ok" ]] || exit 3
