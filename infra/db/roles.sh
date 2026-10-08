#!/usr/bin/env bash
# Create or repair the two database roles of hospital-sys and their privileges. Idempotent.
#
#   owner  DB_OWNER_USER [hospital_owner]: owns the database and every object in it. Only
#          migrations connect as it (compose `migrate` service, infra/update.sh).
#   app    DB_APP_USER [hospital_app]: what the application connects as. LOGIN only;
#          SELECT/INSERT/UPDATE/DELETE on tables, USAGE/SELECT on sequences, EXECUTE on
#          functions. Not an owner, so it cannot TRUNCATE, ALTER, DROP or disable triggers.
# SQL: roles.sql (apply) and roles-verify.sql (check) next to this script.
#
# Usage: roles.sh [--db NAME] [--no-passwords] [--verify] [--print-sql]
#   --db NAME      target database [DB_NAME, else POSTGRES_DB, else hospital]
#   --no-passwords keep the roles' passwords (after a restore); the roles must already exist
#   --verify       check only: print one "PROBLEM: ..." line per difference, exit 1 if any
#   --print-sql    print the SQL (apply, or verify with --verify) instead of running it, for
#                  piping into psql elsewhere (infra/db-roles.sh: `compose exec db psql`)
#
# Runs as a superuser through libpq (PGHOST PGPORT PGUSER PGPASSWORD, or the local socket).
# Passwords: DB_OWNER_PASSWORD and DB_APP_PASSWORD, 16-128 characters from A-Z a-z 0-9 . _ - ~
# (they pass unchanged through .env, compose interpolation and libpq). They travel to psql on
# stdin, never on a command line.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"

die() {
  echo "db-roles: $*" >&2
  exit 2
}

DB="${DB_NAME:-${POSTGRES_DB:-hospital}}"
PASSWORDS=1
VERIFY=0
PRINT=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --db)
      DB="${2:-}"
      shift 2
      ;;
    --no-passwords)
      PASSWORDS=0
      shift
      ;;
    --verify)
      VERIFY=1
      shift
      ;;
    --print-sql)
      PRINT=1
      shift
      ;;
    -h | --help)
      sed -n '2,21p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) die "unknown argument: $1" ;;
  esac
done

OWNER="${DB_OWNER_USER:-hospital_owner}"
APP="${DB_APP_USER:-hospital_app}"

ident() { [[ "$1" =~ ^[a-z_][a-z0-9_]{0,62}$ ]]; }
ident "$DB" || die "database name must match ^[a-z_][a-z0-9_]*\$ (got '$DB')"
ident "$OWNER" || die "DB_OWNER_USER must match ^[a-z_][a-z0-9_]*\$ (got '$OWNER')"
ident "$APP" || die "DB_APP_USER must match ^[a-z_][a-z0-9_]*\$ (got '$APP')"
[[ "$OWNER" != "$APP" ]] || die "DB_OWNER_USER and DB_APP_USER must be different roles"
for r in "$OWNER" "$APP"; do
  if [[ -n "${POSTGRES_USER:-}" && "$r" == "$POSTGRES_USER" ]]; then
    die "$r is POSTGRES_USER (the superuser); DB_OWNER_USER and DB_APP_USER must be other roles"
  fi
done

check_password() {
  # check_password NAME VALUE
  [[ -n "$2" ]] || die "$1 is not set (generate one: infra/db-roles.sh, or see .env.example)"
  [[ "$2" =~ ^[A-Za-z0-9._~-]{16,128}$ ]] ||
    die "$1 must be 16-128 characters from A-Z a-z 0-9 . _ - ~"
}

sql() {
  # The whole psql script: variables first (single-quoted values need no escaping: names and
  # passwords are restricted to characters that are literal inside quotes), then the SQL file.
  printf '\\set owner_role %s\n' "'$OWNER'"
  printf '\\set app_role %s\n' "'$APP'"
  if [[ $VERIFY -eq 1 ]]; then
    cat "$SCRIPT_DIR/roles-verify.sql"
    return 0
  fi
  if [[ $PASSWORDS -eq 1 ]]; then
    printf '\\set set_passwords true\n'
    printf '\\set owner_pw %s\n' "'$DB_OWNER_PASSWORD'"
    printf '\\set app_pw %s\n' "'$DB_APP_PASSWORD'"
  else
    printf '\\set set_passwords false\n'
    printf '\\set owner_pw %s\n' "''"
    printf '\\set app_pw %s\n' "''"
  fi
  cat "$SCRIPT_DIR/roles.sql"
}

if [[ $VERIFY -eq 0 && $PASSWORDS -eq 1 ]]; then
  check_password DB_OWNER_PASSWORD "${DB_OWNER_PASSWORD:-}"
  check_password DB_APP_PASSWORD "${DB_APP_PASSWORD:-}"
  [[ "$DB_OWNER_PASSWORD" != "$DB_APP_PASSWORD" ]] ||
    die "DB_OWNER_PASSWORD and DB_APP_PASSWORD must be different"
fi

if [[ $PRINT -eq 1 ]]; then
  sql
  exit 0
fi

command -v psql >/dev/null 2>&1 || die "psql not found"
if [[ $VERIFY -eq 1 ]]; then
  out="$(sql | psql -X -w -q -t -A -v ON_ERROR_STOP=1 -d "$DB")" || die "verify query failed on $DB"
  if [[ -n "$out" ]]; then
    printf '%s\n' "$out"
    echo "db-roles: $DB: $(printf '%s\n' "$out" | wc -l | tr -d ' ') problem(s)" >&2
    exit 1
  fi
  echo "db-roles: $DB: owner $OWNER, app $APP: ok" >&2
  exit 0
fi
sql | psql -X -w -q -v ON_ERROR_STOP=1 -d "$DB" >/dev/null || die "could not apply roles to $DB"
echo "db-roles: $DB: owner $OWNER, app $APP: applied$([[ $PASSWORDS -eq 1 ]] && echo ' (passwords set)')" >&2
