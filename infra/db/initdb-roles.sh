#!/usr/bin/env bash
# First start of the db container only (/docker-entrypoint-initdb.d, empty data directory):
# create the owner and app roles, hand the new database to the owner, grant the app role DML.
# The official entrypoint has just created POSTGRES_DB as POSTGRES_USER and runs this against
# its temporary server, which listens on the local socket only.
set -euo pipefail

echo "initdb-roles: creating ${DB_OWNER_USER:-hospital_owner} (owner) and ${DB_APP_USER:-hospital_app} (app) in ${POSTGRES_DB}"
# The local socket as the superuser, whatever PG* connection settings the env file carries.
local_psql_env=(env -u PGHOST -u PGHOSTADDR -u PGPORT PGUSER="$POSTGRES_USER")
"${local_psql_env[@]}" /opt/db/roles.sh --db "$POSTGRES_DB"
"${local_psql_env[@]}" /opt/db/roles.sh --db "$POSTGRES_DB" --verify
