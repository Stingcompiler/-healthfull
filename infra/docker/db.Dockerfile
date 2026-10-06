# syntax=docker/dockerfile:1.7
# hospital-sys database image: the official postgres:16 plus pgBackRest and the backup scripts.
# The same image runs the `db` service (PostgreSQL) and the `backup` sidecar, so pg_dump,
# pg_restore and pgBackRest always match the server's major version.
#
# Build from the repository root:
#   docker build -f infra/docker/db.Dockerfile -t hospital-sys-db:16 .

ARG PG_MAJOR=16
FROM postgres:${PG_MAJOR}

# pgBackRest comes from the PGDG apt repository that the official image already configures.
RUN apt-get update \
 && apt-get install -y --no-install-recommends pgbackrest ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && pgbackrest version

COPY --chmod=0755 infra/backup/lib.sh infra/backup/backup-nightly.sh infra/backup/restore-test.sh \
     infra/backup/restore-dump.sh infra/backup/scheduler.sh infra/backup/render-pgbackrest-conf.sh \
     /opt/backup/
COPY --chmod=0644 infra/backup/pgbackrest.conf.template /opt/backup/
COPY --chmod=0755 infra/docker/db-entrypoint.sh /usr/local/bin/db-entrypoint

ENV TZ=Africa/Khartoum \
    BACKUP_DIR=/backups

ENTRYPOINT ["db-entrypoint"]
CMD ["postgres"]
