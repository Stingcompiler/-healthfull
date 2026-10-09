#!/usr/bin/env bash
# End-to-end run (make e2e): reset this worktree's e2e database, migrate, seed, then run
# Playwright, which starts the Django backend and the Vite frontend on free per-worktree ports
# and stops them at the end (e2e/playwright.config.ts).
#
#   make e2e                                  everything
#   make e2e E2E_GREP=@auth                   only tests whose title matches (Playwright --grep)
#   scripts/e2e.sh tests/auth.spec.ts --headed  extra arguments go to `playwright test`
#
# Environment:
#   E2E_GREP            passed to Playwright as --grep
#   E2E_SHARD           passed to Playwright as --shard (e.g. 2/4); CI runs four shards
#   E2E_DB_NAME         e2e database (default e2e_hospital_<hash>). It is DROPPED and recreated,
#                       so it must be e2e_hospital_<this worktree's hash>, unless
#   E2E_ALLOW_FOREIGN_DB=1  allows another e2e_hospital_* name (e.g. a CI-specific one)
#   E2E_BACKEND_PORT    force ports (must be free); otherwise scripts/ports.sh decides
#   E2E_FRONTEND_PORT   (BACKEND_PORT/FRONTEND_PORT are honored) and busy ports are skipped
#   PGHOST PGPORT PGUSER PGPASSWORD   PostgreSQL connection (libpq defaults: local socket)
#
# The inherited DB_NAME is deliberately ignored: a shell that exported DB_NAME=hospital_dev for
# `make dev` must never get its development database dropped by an e2e run.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
SCRIPTS="$ROOT/scripts"
E2E="$ROOT/e2e"
BACKEND="$ROOT/backend"

log() { printf 'e2e: %s\n' "$*"; }
die() {
  printf 'e2e: %s\n' "$*" >&2
  exit 1
}

# ------------------------------------------------------------------ preflight
command -v uv >/dev/null 2>&1 || die "uv not found (needed for the backend)"
command -v pnpm >/dev/null 2>&1 || die "pnpm not found (needed for the frontend and Playwright)"
command -v psql >/dev/null 2>&1 || die "psql not found; install the PostgreSQL 16 client tools"
[[ -d "$E2E/node_modules/@playwright/test" ]] || die "e2e dependencies missing; run 'make setup' (or: cd e2e && pnpm install)"
[[ -d "$ROOT/frontend/node_modules" ]] || die "frontend dependencies missing; run 'make setup'"
[[ -d "$BACKEND/.venv" ]] || die "backend environment missing; run 'make setup'"
pg_isready -q -d postgres 2>/dev/null || die "PostgreSQL is not reachable (PGHOST=${PGHOST:-<socket>} PGPORT=${PGPORT:-5432})"

# ------------------------------------------------------------------ identity: hash, DB, ports
HASH="$("$SCRIPTS/repo-hash.sh")"
DB="${E2E_DB_NAME:-e2e_hospital_${HASH}}"
# This database is dropped WITH (FORCE): never let it name anything but an e2e database, and by
# default only this worktree's own (another worktree's run would be killed mid-test).
[[ "$DB" =~ ^e2e_hospital_[a-z0-9_]{1,50}$ ]] || die "E2E_DB_NAME must match ^e2e_hospital_[a-z0-9_]+\$ (got '$DB')"
if [[ "$DB" != "e2e_hospital_${HASH}" && "${E2E_ALLOW_FOREIGN_DB:-0}" != "1" ]]; then
  die "E2E_DB_NAME=$DB is not this worktree's e2e database (e2e_hospital_${HASH}); set E2E_ALLOW_FOREIGN_DB=1 to use it anyway"
fi

port_busy() {
  # Something accepts connections on 127.0.0.1:$1 (bash /dev/tcp; works on macOS bash 3.2).
  (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null
}

if [[ -n "${E2E_BACKEND_PORT:-}" || -n "${E2E_FRONTEND_PORT:-}" ]]; then
  BACKEND_PORT="${E2E_BACKEND_PORT:-}"
  FRONTEND_PORT="${E2E_FRONTEND_PORT:-}"
  [[ -n "$BACKEND_PORT" ]] || unset BACKEND_PORT
  [[ -n "$FRONTEND_PORT" ]] || unset FRONTEND_PORT
  # shellcheck source=scripts/ports.sh
  source "$SCRIPTS/ports.sh"
  for p in "$BACKEND_PORT" "$FRONTEND_PORT"; do
    port_busy "$p" && die "port $p is in use (set by E2E_BACKEND_PORT/E2E_FRONTEND_PORT)"
  done
else
  # shellcheck source=scripts/ports.sh
  source "$SCRIPTS/ports.sh"
  # Derived ports are shared with `make dev` in this worktree: step past busy ones.
  tries=0
  while port_busy "$BACKEND_PORT" || port_busy "$FRONTEND_PORT"; do
    tries=$((tries + 1))
    [[ $tries -le 50 ]] || die "no free port pair found near $BACKEND_PORT"
    BACKEND_PORT=$((BACKEND_PORT + 2))
    FRONTEND_PORT=$((FRONTEND_PORT + 2))
    [[ $BACKEND_PORT -le 65535 && $FRONTEND_PORT -le 65535 ]] || die "ran out of ports above 20000"
  done
fi
export BACKEND_PORT FRONTEND_PORT
export DB_NAME="$DB"
# e2e/env.ts reads E2E_DB_NAME (never DB_NAME, which a dev shell may point at hospital_dev).
export E2E_DB_NAME="$DB"
# seed_e2e refuses to run without DEBUG; this database is throwaway by construction.
export DJANGO_DEBUG=1

log "worktree $HASH  db=$DB_NAME  backend=127.0.0.1:$BACKEND_PORT  frontend=127.0.0.1:$FRONTEND_PORT"

# ------------------------------------------------------------------ database: drop, create, migrate, seed
log "resetting database $DB_NAME"
psql -X -q -v ON_ERROR_STOP=1 -d postgres \
  -c "DROP DATABASE IF EXISTS \"$DB_NAME\" WITH (FORCE)" \
  -c "CREATE DATABASE \"$DB_NAME\"" >/dev/null

log "migrating"
(cd "$BACKEND" && uv run python manage.py migrate --no-input -v 0)
log "seeding (seed_e2e)"
(cd "$BACKEND" && uv run python manage.py seed_e2e)

# ------------------------------------------------------------------ artifacts
mkdir -p "$ROOT/artifacts/screens" "$E2E/.logs"
# A full run replaces every screenshot, so stale ones (renamed or removed routes) go first. A filtered
# run (E2E_GREP or extra arguments) only overwrites the files it produces and keeps the rest.
if [[ -z "${E2E_GREP:-}" && -z "${E2E_SHARD:-}" && $# -eq 0 ]]; then
  find "$ROOT/artifacts/screens" -maxdepth 1 -type f -name '*.png' -delete
fi
: >"$E2E/.logs/backend.log"
: >"$E2E/.logs/frontend.log"

# ------------------------------------------------------------------ Playwright
args=()
if [[ -n "${E2E_SHARD:-}" ]]; then
  args+=(--shard "$E2E_SHARD")
  log "shard: $E2E_SHARD"
fi
if [[ -n "${E2E_GREP:-}" ]]; then
  args+=(--grep "$E2E_GREP")
  log "filter: --grep '$E2E_GREP'"
fi

status=0
(cd "$E2E" && pnpm exec playwright test ${args[@]+"${args[@]}"} "$@") || status=$?

shots="$(find "$ROOT/artifacts/screens" -maxdepth 1 -type f -name '*.png' | wc -l | tr -d ' ')"
log "screenshots: $shots in artifacts/screens/"
log "report: e2e/playwright-report/index.html (cd e2e && pnpm report)"
if [[ $status -ne 0 ]]; then
  log "FAILED (exit $status). Server logs: e2e/.logs/backend.log, e2e/.logs/frontend.log"
  for f in backend frontend; do
    if [[ -s "$E2E/.logs/$f.log" ]]; then
      echo "----- last lines of e2e/.logs/$f.log" >&2
      tail -n 25 "$E2E/.logs/$f.log" >&2
    fi
  done
fi
exit $status
