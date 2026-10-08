#!/usr/bin/env bash
# Run every infra shell test (make infra-test). Backup and role tests need PostgreSQL 16;
# set REQUIRE_PG=1 to make its absence a failure (CI does).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
status=0
for t in test_pgbackrest_conf.sh test_update.sh test_db_roles.sh test_backup_restore.sh; do
  echo "=== $t"
  if ! bash "$HERE/$t"; then
    echo "=== $t FAILED" >&2
    status=1
  fi
done
exit $status
