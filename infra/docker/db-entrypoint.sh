#!/usr/bin/env bash
# Entrypoint of the db image (used by both the `db` and `backup` services).
#  - As root: prepare pgBackRest directories and render /etc/pgbackrest/pgbackrest.conf from env.
#  - `postgres ...` (or flags): hand over to the official postgres entrypoint.
#  - `backup-scheduler`: run the backup loop as the postgres user.
#  - anything else: run it as the postgres user (e.g. /opt/backup/backup-nightly.sh).
set -euo pipefail

if [[ "$(id -u)" == "0" ]]; then
  install -d -o postgres -g postgres -m 0750 \
    /var/lib/pgbackrest /var/spool/pgbackrest /var/log/pgbackrest /etc/pgbackrest
  if [[ -d /backups ]]; then
    # Only the top-level directories: never walk (and re-own) existing backup files.
    chown postgres:postgres /backups
    install -d -o postgres -g postgres -m 0750 /backups/dumps /backups/media
    install -d -o postgres -g postgres -m 0755 /backups/status
  fi
  # A backup misconfiguration must never keep the database from starting: warn loudly instead.
  # (With pgBackRest enabled, the backup job then fails and records it on the status page.)
  if /opt/backup/render-pgbackrest-conf.sh /etc/pgbackrest/pgbackrest.conf; then
    chown root:postgres /etc/pgbackrest/pgbackrest.conf
  else
    echo "db-entrypoint: WARNING: pgBackRest config not rendered; fix the PGBACKREST_* settings" >&2
  fi
fi

case "${1:-postgres}" in
  postgres | -*)
    exec docker-entrypoint.sh "$@"
    ;;
  backup-scheduler)
    shift
    set -- /opt/backup/scheduler.sh "$@"
    ;;
esac

if [[ "$(id -u)" == "0" ]]; then
  exec gosu postgres "$@"
fi
exec "$@"
