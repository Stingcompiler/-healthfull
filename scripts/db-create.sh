#!/usr/bin/env bash
# Create the local development database if it does not exist (make setup / make db).
# Connection comes from libpq env vars (PGHOST, PGPORT, PGUSER, PGPASSWORD); with none set,
# psql uses the local Homebrew Postgres socket and the current OS user.
# Database name: DB_NAME (default hospital_dev). Never hardcode names (ARCHITECTURE.md section 3).
set -euo pipefail

DB_NAME="${DB_NAME:-hospital_dev}"

if [[ ! "$DB_NAME" =~ ^[a-z_][a-z0-9_]{0,62}$ ]]; then
  echo "db-create: DB_NAME must match ^[a-z_][a-z0-9_]*\$ (got '$DB_NAME')" >&2
  exit 2
fi

if ! command -v psql >/dev/null 2>&1; then
  echo "db-create: psql not found; install PostgreSQL 16 client tools" >&2
  exit 1
fi

if ! pg_isready -q -d postgres 2>/dev/null; then
  echo "db-create: PostgreSQL is not reachable (PGHOST=${PGHOST:-<socket>} PGPORT=${PGPORT:-5432})" >&2
  exit 1
fi

exists="$(psql -X -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '${DB_NAME}'")"
if [[ "$exists" == "1" ]]; then
  echo "db-create: database ${DB_NAME} already exists"
else
  createdb "$DB_NAME"
  echo "db-create: created database ${DB_NAME}"
fi
