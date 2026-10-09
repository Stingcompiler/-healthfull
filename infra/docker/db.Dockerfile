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

# The backup sidecar archives uploaded files from the app's media volume (owner 10001, mode
# 0750): the postgres user reads them as a member of the app's group, never as root.
RUN groupadd --system --gid 10001 hospital \
 && usermod -aG hospital postgres

COPY --chmod=0755 infra/backup/lib.sh infra/backup/backup-nightly.sh infra/backup/restore-test.sh \
     infra/backup/restore-dump.sh infra/backup/scheduler.sh infra/backup/render-pgbackrest-conf.sh \
     infra/backup/backup-requests.sh \
     /opt/backup/
COPY --chmod=0644 infra/backup/pgbackrest.conf.template /opt/backup/
# Database roles (infra/db): the owner runs migrations, the app connects with DML rights only.
# initdb-roles runs once, on the first start with an empty data directory; restore-dump.sh
# re-applies ownership and grants to every restored database.
COPY --chmod=0755 infra/db/roles.sh /opt/db/
COPY --chmod=0644 infra/db/roles.sql infra/db/roles-verify.sql /opt/db/
COPY --chmod=0755 infra/db/initdb-roles.sh /docker-entrypoint-initdb.d/10-roles.sh
COPY --chmod=0755 infra/docker/db-entrypoint.sh /usr/local/bin/db-entrypoint

ENV TZ=Africa/Khartoum \
    BACKUP_DIR=/backups

ENTRYPOINT ["db-entrypoint"]
CMD ["postgres"]
