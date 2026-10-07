#!/usr/bin/env bash
# Shared helpers for the backup scripts. Sourced, never executed.
# Portable: bash 3.2+ (macOS) and bash 5.x (Ubuntu, Debian containers); GNU or BSD userland.

# bash >= 5.2 treats '&' in ${var//pat/rep} replacements specially; we want literal text.
shopt -u patsub_replacement 2>/dev/null || true

log() {
  # All diagnostics go to stderr so stdout can carry a machine-readable result.
  printf '%s [%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${LOG_TAG:-backup}" "$*" >&2
}

die() {
  log "ERROR: $*"
  exit 1
}

is_true() {
  case "$(printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]')" in
    1 | true | yes | on | y) return 0 ;;
    *) return 1 ;;
  esac
}

require_cmd() {
  local c
  for c in "$@"; do
    command -v "$c" >/dev/null 2>&1 || die "required command not found: $c"
  done
}

require_uint() {
  # require_uint NAME VALUE
  case "$2" in
    '' | *[!0-9]*) die "$1 must be a non-negative integer (got '$2')" ;;
  esac
}

valid_identifier() {
  [[ "$1" =~ ^[a-z_][a-z0-9_]{0,62}$ ]]
}

utc_stamp() {
  date -u +%Y%m%dT%H%M%SZ
}

iso_now() {
  date -u +%Y-%m-%dT%H:%M:%SZ
}

iso_to_epoch() {
  # iso_to_epoch 2026-10-07T00:30:00Z -> seconds since the epoch (GNU date, then BSD date).
  date -u -d "$1" +%s 2>/dev/null || date -j -u -f '%Y-%m-%dT%H:%M:%SZ' "$1" +%s 2>/dev/null
}

last_success() {
  # last_success FILE TYPE STATUS_REGEX -> finished_at (ISO UTC) of the newest matching
  # status line, or nothing. The status files are ours: one compact JSON object per line.
  local file="$1" type="$2" statuses="$3" line
  [[ -f "$file" ]] || return 0
  line="$(grep -E "\"type\":\"$type\"" "$file" | grep -E "\"status\":\"($statuses)\"" | tail -n 1 || true)"
  printf '%s' "$line" | sed -nE 's/.*"finished_at":"([0-9TZ:-]+)".*/\1/p'
}

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

file_size() {
  # Bytes; GNU stat, then BSD stat.
  stat -c %s "$1" 2>/dev/null || stat -f %z "$1"
}

free_kb() {
  # Free space in KiB on the filesystem holding $1.
  df -Pk "$1" | awk 'NR == 2 {print $4}'
}

json_str() {
  # Encode $1 as a JSON string literal.
  local s="$1"
  s="${s//\\/\\\\}"
  s="${s//\"/\\\"}"
  s="${s//$'\n'/\\n}"
  s="${s//$'\r'/\\r}"
  s="${s//$'\t'/\\t}"
  s="$(printf '%s' "$s" | LC_ALL=C tr -d '\000-\010\013\014\016-\037')"
  printf '"%s"' "$s"
}

json_str_or_null() {
  if [[ -n "${1:-}" ]]; then json_str "$1"; else printf 'null'; fi
}

append_json_line() {
  # append_json_line FILE JSON: one complete line per write so readers never see partial records.
  local file="$1" line="$2" dir
  dir="$(dirname "$file")"
  mkdir -p "$dir"
  chmod 0755 "$dir" 2>/dev/null || true
  printf '%s\n' "$line" >>"$file"
  chmod 0644 "$file" 2>/dev/null || true
}

# Exclusive, non-blocking lock held until this shell exits: flock(2) on file descriptor 9.
# The kernel drops the lock when the holder dies (crash, OOM, SIGKILL, power cut), so there
# is no stale-lock guessing; it also works across containers that share the bind mount,
# where PIDs from different PID namespaces would collide. Uses flock(1) (util-linux, in every
# Debian image) or, on hosts without it (macOS), perl locking the same inherited descriptor.
# Returns 1 when another process holds the lock.
acquire_lock() {
  local file="$1"
  exec 9>>"$file" || return 1
  if command -v flock >/dev/null 2>&1; then
    flock -n 9 || return 1
  else
    perl -MFcntl=:flock -e 'open(my $fh, ">&=", 9) or exit 2; flock($fh, LOCK_EX | LOCK_NB) or exit 1' ||
      return 1
  fi
  # Diagnostics only (who holds it); the lock itself is the flock, not this text.
  printf 'pid=%s host=%s since=%s\n' "$$" "$(hostname)" "$(iso_now)" >"$file" 2>/dev/null || true
}

lock_holder() {
  cat "$1" 2>/dev/null | head -n 1 || true
}

release_lock() {
  exec 9>&- 2>/dev/null || true
}

# psql wrapper: no .psqlrc, never prompt for a password, stop on error, unaligned tuples only.
psql_q() {
  local db="$1"
  shift
  psql -X -w -v ON_ERROR_STOP=1 -q -t -A -d "$db" "$@"
}
