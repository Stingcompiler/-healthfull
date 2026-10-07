#!/usr/bin/env bash
# Create or repair the database roles of a running install. Idempotent: safe to re-run.
#
#   1. .env      generate DB_OWNER_PASSWORD and DB_APP_PASSWORD when missing (atomic write)
#   2. apply     in the running db container, as the superuser (infra/db/roles.sql): create or
#                repair DB_OWNER_USER and DB_APP_USER, set their passwords from .env, hand the
#                database and every object to the owner, grant the app role DML only
#   3. verify    infra/db/roles-verify.sql; any difference is printed and fails the run
#
# When to run it:
#   - once, to move an install made before the roles existed; then `infra/compose.sh up -d` so
#     app and maintenance reconnect as the app role (docs/runbooks/update-rollback.md)
#   - after changing DB_OWNER_PASSWORD or DB_APP_PASSWORD in .env (then `up -d` as well)
#   - to repair ownership or grants; infra/update.sh runs it (--no-generate) before migrating
#
# Usage: infra/db-roles.sh [--no-generate]
#   --no-generate  fail instead of writing missing passwords to .env
# Settings: ENV_FILE [<repo>/.env]; DB_OWNER_USER, DB_APP_USER and the passwords come from the
# shell environment first, then the env file (the same precedence as docker compose).
#
# Exit: 0 roles ok; 1 apply failed or verification found problems; 2 usage, .env or docker.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
ENV_FILE="${ENV_FILE:-$ROOT/.env}"
COMPOSE_FILE="$ROOT/infra/docker-compose.yml"
ROLES="$ROOT/infra/db/roles.sh"

GENERATE=1
while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-generate) GENERATE=0; shift ;;
    -h | --help) sed -n '2,21p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "db-roles: unknown argument $1" >&2; exit 2 ;;
  esac
done

log() { printf '%s [db-roles] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >&2; }

[[ -f "$ENV_FILE" ]] || { log "$ENV_FILE not found. Copy .env.example to .env and fill it in."; exit 2; }
ENV_FILE="$(cd "$(dirname "$ENV_FILE")" && pwd -P)/$(basename "$ENV_FILE")"
export ENV_FILE
# shellcheck source=infra/env-lib.sh
source "$ROOT/infra/env-lib.sh"

command -v docker >/dev/null 2>&1 || { log "docker not found"; exit 2; }

compose() {
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

new_password() {
  # 48 hex characters (192 bits): within the allowed character set, nothing to quote.
  od -An -N24 -tx1 /dev/urandom | tr -d ' \n'
}

# ------------------------------------------------------------------------------------ 1. .env
for key in DB_OWNER_PASSWORD DB_APP_PASSWORD; do
  if [[ -z "${!key:-}" && -z "$(env_get "$key")" ]]; then
    if [[ $GENERATE -ne 1 ]]; then
      log "$key is not set in $ENV_FILE. Run infra/db-roles.sh once (it generates the role"
      log "passwords) or see docs/runbooks/update-rollback.md, \"Separate database roles\"."
      exit 2
    fi
    env_set "$key" "$(new_password)"
    log "generated $key in $ENV_FILE (keep the printed copy of .env up to date)"
  fi
done

DB_OWNER_USER="${DB_OWNER_USER:-$(env_get DB_OWNER_USER)}"
DB_APP_USER="${DB_APP_USER:-$(env_get DB_APP_USER)}"
DB_OWNER_PASSWORD="${DB_OWNER_PASSWORD:-$(env_get DB_OWNER_PASSWORD)}"
DB_APP_PASSWORD="${DB_APP_PASSWORD:-$(env_get DB_APP_PASSWORD)}"
POSTGRES_USER="${POSTGRES_USER:-$(env_get POSTGRES_USER)}"
export DB_OWNER_USER="${DB_OWNER_USER:-hospital_owner}" DB_APP_USER="${DB_APP_USER:-hospital_app}" \
  DB_OWNER_PASSWORD DB_APP_PASSWORD POSTGRES_USER="${POSTGRES_USER:-hospital}"

# psql inside the db container: local socket, as the image's superuser, on the database the
# container was created with (both from the container's own environment).
db_psql() {
  # shellcheck disable=SC2016 # expanded by the container's shell
  compose exec -T db sh -c 'exec psql -X -w -q -t -A -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
}

# ------------------------------------------------------------------------------------ 2. apply
# Built first (it validates names and passwords), then sent on stdin: never on a command line.
apply_sql="$("$ROLES" --print-sql)" || exit 2
if ! printf '%s\n' "$apply_sql" | db_psql >/dev/null; then
  log "could not apply the roles. Is the database up? (infra/compose.sh ps; infra/compose.sh up -d db)"
  exit 1
fi
log "applied: owner $DB_OWNER_USER owns the database and its objects; app $DB_APP_USER has DML only"

# ------------------------------------------------------------------------------------ 3. verify
verify_sql="$("$ROLES" --verify --print-sql)" || exit 2
if ! problems="$(printf '%s\n' "$verify_sql" | db_psql)"; then
  log "verification query failed"
  exit 1
fi
if [[ -n "$problems" ]]; then
  printf '%s\n' "$problems" >&2
  log "verification found $(printf '%s\n' "$problems" | wc -l | tr -d ' ') problem(s)"
  exit 1
fi
log "verified. If app or maintenance still connect as $POSTGRES_USER, recreate them: infra/compose.sh up -d"
