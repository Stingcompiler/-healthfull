#!/usr/bin/env bash
# make demo: create the demo database, migrate it and load the demo dataset (seed_demo).
#
#   make demo                          demo_hospital: created if missing, migrated, seeded
#   make demo DEMO_RESET=1             drop it first (a fresh month ending today)
#   make demo DEMO_DB_NAME=demo_x DEMO_ARGS="--days 7 --seed 7"
#
# Environment:
#   DEMO_DB_NAME   database (default demo_hospital); must start with demo_ (seed_demo refuses
#                  anything else, and this script only ever drops a demo_* database)
#   DEMO_RESET     1 drops and recreates the database first
#   DEMO_ARGS      extra seed_demo options (--seed, --days, --patients, --visits-per-day)
#   PGHOST PGPORT PGUSER PGPASSWORD   PostgreSQL connection (libpq defaults: local socket)
#
# The inherited DB_NAME is ignored on purpose: a shell set up for `make dev` must never get
# demo data written into its development database.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
BACKEND="$ROOT/backend"

DB="${DEMO_DB_NAME:-demo_hospital}"
if [[ ! "$DB" =~ ^demo_[a-z0-9_]{1,50}$ ]]; then
  echo "demo: DEMO_DB_NAME must match ^demo_[a-z0-9_]+\$ (got '$DB')" >&2
  exit 2
fi
command -v psql >/dev/null 2>&1 || {
  echo "demo: psql not found; install the PostgreSQL 16 client tools" >&2
  exit 1
}
pg_isready -q -d postgres 2>/dev/null || {
  echo "demo: PostgreSQL is not reachable (PGHOST=${PGHOST:-<socket>} PGPORT=${PGPORT:-5432})" >&2
  exit 1
}

if [[ "${DEMO_RESET:-0}" == "1" ]]; then
  echo "demo: dropping $DB"
  psql -X -q -v ON_ERROR_STOP=1 -d postgres -c "DROP DATABASE IF EXISTS \"$DB\" WITH (FORCE)" >/dev/null
fi
exists="$(psql -X -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '$DB'")"
if [[ "$exists" != "1" ]]; then
  createdb "$DB"
  echo "demo: created database $DB"
fi

export DB_NAME="$DB"
echo "demo: migrating $DB"
(cd "$BACKEND" && uv run python manage.py migrate --no-input -v 0)
echo "demo: seeding $DB (seed_demo ${DEMO_ARGS:-})"
# shellcheck disable=SC2086 # DEMO_ARGS is a list of options
(cd "$BACKEND" && uv run python manage.py seed_demo ${DEMO_ARGS:-})
echo "demo: ready. Run the app on it with: DB_NAME=$DB make dev"
