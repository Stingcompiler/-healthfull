#!/usr/bin/env bash
# Run every infra shell test (make infra-test). Backup and role tests need PostgreSQL 16;
# set REQUIRE_PG=1 to make its absence a failure (CI does). The restore drill also needs the
# backend environment (uv, backend/.venv); REQUIRE_DJANGO=1 makes its absence a failure.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
status=0
for t in test_pgbackrest_conf.sh test_update.sh test_app_entrypoint.sh test_db_roles.sh test_backup_restore.sh \
  test_restore_drill.sh; do
  echo "=== $t"
  if ! bash "$HERE/$t"; then
    echo "=== $t FAILED" >&2
    status=1
  fi
done
exit $status
