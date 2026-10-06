#!/usr/bin/env bash
# Render pgbackrest.conf from pgbackrest.conf.template and the environment.
#
# - Only whitelisted ${VAR} placeholders are substituted (no eval, no envsubst).
# - The "repo1-cipher" block is kept only when PGBACKREST_REPO1_CIPHER_PASS is set.
# - The "repo2" block (cloud) is kept only when PGBACKREST_REPO2_S3_BUCKET is set, and then every
#   repo2 variable, including the encryption passphrase, is mandatory.
# - The output holds secrets: written atomically with mode 0640.
#
# Usage: render-pgbackrest-conf.sh OUTPUT [TEMPLATE]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=infra/backup/lib.sh
source "$SCRIPT_DIR/lib.sh"
LOG_TAG="pgbackrest-conf"

OUT="${1:?usage: render-pgbackrest-conf.sh OUTPUT [TEMPLATE]}"
TEMPLATE="${2:-$SCRIPT_DIR/pgbackrest.conf.template}"
[[ -f "$TEMPLATE" ]] || die "template not found: $TEMPLATE"

# Defaults for optional settings.
: "${PGBACKREST_STANZA:=hospital}"
: "${PGBACKREST_REPO1_PATH:=/var/lib/pgbackrest}"
: "${PGBACKREST_REPO1_RETENTION_FULL:=2}"
: "${PGBACKREST_PROCESS_MAX:=2}"
: "${PGBACKREST_ARCHIVE_QUEUE_MAX:=4GiB}"
: "${PGDATA:=/var/lib/postgresql/data}"
: "${PG_SOCKET_DIR:=/var/run/postgresql}"
: "${POSTGRES_USER:=postgres}"
: "${PGBACKREST_REPO2_PATH:=/hospital}"
: "${PGBACKREST_REPO2_S3_URI_STYLE:=host}"
: "${PGBACKREST_REPO2_S3_VERIFY_TLS:=y}"
: "${PGBACKREST_REPO2_RETENTION_FULL:=4}"

ALLOWED=" PGBACKREST_STANZA PGBACKREST_REPO1_PATH PGBACKREST_REPO1_RETENTION_FULL
 PGBACKREST_REPO1_CIPHER_PASS PGBACKREST_PROCESS_MAX PGBACKREST_ARCHIVE_QUEUE_MAX PGDATA PG_SOCKET_DIR
 POSTGRES_USER PGBACKREST_REPO2_PATH PGBACKREST_REPO2_S3_BUCKET PGBACKREST_REPO2_S3_ENDPOINT
 PGBACKREST_REPO2_S3_REGION PGBACKREST_REPO2_S3_KEY PGBACKREST_REPO2_S3_KEY_SECRET
 PGBACKREST_REPO2_S3_URI_STYLE PGBACKREST_REPO2_S3_VERIFY_TLS PGBACKREST_REPO2_RETENTION_FULL
 PGBACKREST_REPO2_CIPHER_PASS "
ALLOWED="$(printf '%s' "$ALLOWED" | tr '\n' ' ')"

valid_identifier "$PGBACKREST_STANZA" || die "PGBACKREST_STANZA must be a plain identifier"
require_uint PGBACKREST_REPO1_RETENTION_FULL "$PGBACKREST_REPO1_RETENTION_FULL"
require_uint PGBACKREST_PROCESS_MAX "$PGBACKREST_PROCESS_MAX"

enabled_block() {
  case "$1" in
    repo1-cipher) [[ -n "${PGBACKREST_REPO1_CIPHER_PASS:-}" ]] ;;
    repo2) [[ -n "${PGBACKREST_REPO2_S3_BUCKET:-}" ]] ;;
    *) die "unknown template block '$1'" ;;
  esac
}

if [[ -n "${PGBACKREST_REPO2_S3_BUCKET:-}" ]]; then
  for v in PGBACKREST_REPO2_S3_ENDPOINT PGBACKREST_REPO2_S3_REGION PGBACKREST_REPO2_S3_KEY \
    PGBACKREST_REPO2_S3_KEY_SECRET PGBACKREST_REPO2_CIPHER_PASS; do
    [[ -n "${!v:-}" ]] || die "$v is required when PGBACKREST_REPO2_S3_BUCKET is set"
  done
  [[ ${#PGBACKREST_REPO2_CIPHER_PASS} -ge 20 ]] || die "PGBACKREST_REPO2_CIPHER_PASS must be at least 20 characters"
  case "$PGBACKREST_REPO2_S3_URI_STYLE" in host | path) ;; *) die "PGBACKREST_REPO2_S3_URI_STYLE must be host or path" ;; esac
  case "$PGBACKREST_REPO2_S3_VERIFY_TLS" in y | n) ;; *) die "PGBACKREST_REPO2_S3_VERIFY_TLS must be y or n" ;; esac
  require_uint PGBACKREST_REPO2_RETENTION_FULL "$PGBACKREST_REPO2_RETENTION_FULL"
fi

substitute() {
  # Replace each ${NAME} in $1 by the value of NAME; NAME must be whitelisted and non-empty.
  local line="$1" out="" rest name value
  while [[ "$line" == *'${'*'}'* ]]; do
    out="$out${line%%\$\{*}"
    rest="${line#*\$\{}"
    name="${rest%%\}*}"
    line="${rest#*\}}"
    [[ "$name" =~ ^[A-Z][A-Z0-9_]*$ ]] || die "malformed placeholder \${$name} in template"
    case "$ALLOWED" in *" $name "*) ;; *) die "placeholder \${$name} is not allowed" ;; esac
    value="${!name:-}"
    [[ -n "$value" ]] || die "$name is empty but used by the template"
    [[ "$value" != *$'\n'* ]] || die "$name must not contain a newline"
    out="$out$value"
  done
  printf '%s\n' "$out$line"
}

tmp="$(mktemp "$(dirname "$OUT")/.pgbackrest.conf.XXXXXX")"
trap 'rm -f "$tmp"' EXIT
skip=""
while IFS= read -r line || [[ -n "$line" ]]; do
  case "$line" in
    '#BEGIN '*)
      block="${line#\#BEGIN }"
      if [[ -z "$skip" ]] && ! enabled_block "$block"; then skip="$block"; fi
      continue
      ;;
    '#END '*)
      [[ "${line#\#END }" == "$skip" ]] && skip=""
      continue
      ;;
  esac
  [[ -n "$skip" ]] && continue
  if [[ "$line" == '#'* ]]; then
    printf '%s\n' "$line" >>"$tmp" # comments pass through verbatim
  else
    substitute "$line" >>"$tmp"
  fi
done <"$TEMPLATE"

chmod 0640 "$tmp"
mv "$tmp" "$OUT"
trap - EXIT
repo2="off"
[[ -n "${PGBACKREST_REPO2_S3_BUCKET:-}" ]] && repo2="s3://${PGBACKREST_REPO2_S3_BUCKET} (encrypted)"
log "wrote $OUT (stanza=$PGBACKREST_STANZA, repo1=$PGBACKREST_REPO1_PATH, repo2=$repo2)"
