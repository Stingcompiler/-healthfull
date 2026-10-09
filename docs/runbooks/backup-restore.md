# Backup and restore — النسخ الاحتياطي والاستعادة

FEATURES 14.1, 14.5, 14.6, 13.8. Scripts in `infra/backup/`, run by the `backup` container.
All paths below are on the host; inside containers `/srv/hospital/backups` is `/backups`.

## What is protected — ما الذي يُحفظ

| Layer | When | Where | Recovers |
|---|---|---|---|
| `pg_dump` (custom format, verified, SHA-256) | nightly `BACKUP_TIME` | `/srv/hospital/backups/dumps/` | whole database to last night |
| Media archive (uploaded files, logos) | with the dump | `/srv/hospital/backups/media/` | uploaded files |
| Pre-update dump | every `infra/update.sh` | `dumps/*-pre-update-<tag>.dump` | state just before an update |
| pgBackRest repo1 (optional) | WAL continuously, full weekly, diff nightly | `/srv/hospital/pgbackrest` | any point in time |
| pgBackRest repo2 (optional) | same, when online | S3-compatible bucket, encrypted | site loss |
| Off-site USB (manual) | weekly | USB disk kept outside the clinic | site loss without internet |

Retention: dumps older than `BACKUP_RETENTION_DAYS` are deleted, but the newest `BACKUP_KEEP_MIN`
are always kept. pgBackRest keeps `PGBACKREST_REPO1_RETENTION_FULL` full backups.

## Daily check — الفحص اليومي

The status page shows the last backup and restore test. From the server:

```bash
tail -n 1 /srv/hospital/backups/status/backup-runs.jsonl     # "status":"ok"
ls -lt /srv/hospital/backups/dumps | head -n 4
df -h /srv/hospital
infra/compose.sh logs --since 24h backup
```

`status` is `ok`, `partial` (the dump is fine and kept, but the media archive or a pgBackRest repo
failed, usually the cloud while offline: read `error`) or `failed` (no new dump: act today).

### Missed backups and power cuts — النسخ الفائتة وانقطاع الكهرباء

- **Catch-up:** if the server was off at `BACKUP_TIME`, the backup container takes the missed
  backup as soon as it starts (and after every wake-up) when the last `ok`/`partial` backup is older
  than `BACKUP_CATCHUP_HOURS` (24). A monthly restore test missed on `RESTORE_TEST_DAY` runs the
  same way, once per month. `BACKUP_CATCHUP_HOURS=0` turns catch-up off.
- **Locks:** backup and restore test each take a kernel lock (`flock`) on a file in
  `/srv/hospital/backups` (`.backup.flock`, `.restore-test.flock`). It is released automatically
  when the process ends for any reason, so a power cut can never leave a stale lock. A second run
  while one is active is refused and recorded as `failed` ("another backup run holds ...").
- **Leftovers:** a run killed mid-write leaves `.*.partial` files and possibly a
  `restore_test_<stamp>_<pid>` scratch database; the next run removes both.
- **Stopping:** `docker stop` passes the signal to a running backup, which cleans up; the backup
  service has a 300 s stop grace period for that.

### Status file format (read by the ops module)

One JSON object per line, append-only, `version: 1`.

- `status/backup-runs.jsonl`: `type:"backup"`, `status`, `started_at`, `finished_at`,
  `duration_s`, `host`, `database`, `label`, `dump:{file,size_bytes,sha256}`, `media:{file}`,
  `pgbackrest:[{repo,type,status}]`, `pruned:[files]`, `error`.
- `status/restore-tests.jsonl`: `type:"restore_test"`, `status`, `started_at`, `finished_at`,
  `duration_s`, `dump`, `dump_size_bytes`, `dump_sha256`, `scratch_db`, `table_count`,
  `tables:{name:rows}`, `missing_tables`, `error`.
- `status/update-runs.jsonl`: `type:"update"`, `status` (`ok`, `failed`, `rolled_back`),
  `from_tag`, `to_tag`, `migrations_applied`, `db_restored`, `backup`, `detail`, `log`.

The app container mounts `status/` read-only at `BACKUP_STATUS_DIR`.

## Manual backup and restore test — نسخة يدوية واختبار استعادة

```bash
infra/compose.sh run --rm --no-deps -T backup /opt/backup/backup-nightly.sh --label manual
infra/compose.sh run --rm --no-deps -T backup /opt/backup/restore-test.sh
infra/compose.sh run --rm --no-deps -T backup /opt/backup/restore-test.sh --dump /backups/dumps/<file>.dump
```

The restore test restores into a scratch database, checks `RESTORE_TEST_REQUIRED` tables are
non-empty, counts rows in `RESTORE_TEST_TABLES`, logs the result and drops the scratch database.

### From the status page — من صفحة حالة النظام

Administration > System status > "Back up now" (permission `ops.trigger_backup`, admins) does
not run anything on the app server: it records a request (`ops_backuprequest`, status
`pending`; one open request at a time). The backup service picks it up (ADR 0014):

- With the sidecar (`BACKUP_SCHEDULER=sidecar`, the default) the scheduler runs
  `/opt/backup/backup-requests.sh` every `BACKUP_REQUEST_POLL_SECONDS` (60) between its
  nightly jobs, and once at start. Jobs never overlap: a nightly backup or restore test that
  is running finishes first.
- With host timers (`BACKUP_SCHEDULER=off`) install `hospital-backup-requests.{service,timer}`
  or the per-minute crontab line from `infra/backup/examples/`.

`backup-requests.sh` claims the oldest pending request (`FOR UPDATE SKIP LOCKED`), marks it
`running`, runs `backup-nightly.sh --label manual-<id>` and writes `succeeded`, `partial` or
`failed` back with the dump file and, on a problem, the last lines of the backup log. A request
still `running` after `BACKUP_REQUEST_STALE_HOURS` (6; the service was stopped) is marked
failed. The status page shows the request and, as for any backup, the run from
`status/backup-runs.jsonl` with label `manual-<id>`. To check by hand:

```bash
infra/compose.sh run --rm --no-deps -T backup /opt/backup/backup-requests.sh   # one pending request
infra/compose.sh logs --since 1h backup | grep requests
```

## Off-site copy — نسخة خارج المركز

Weekly, with two USB disks in rotation (one always outside the clinic):

```bash
sudo mount /dev/sdc1 /mnt/usb
sudo rsync -a /srv/hospital/backups/ /mnt/usb/hospital-backups/
sudo cp /opt/hospital-sys/.env /mnt/usb/hospital-backups/env.backup     # secrets: keep the disk safe
sync && sudo umount /mnt/usb
```

## Restore the database on the same server — استعادة قاعدة البيانات

Use when data is damaged or a bad change must be undone. Everything since the dump is lost.

```bash
infra/compose.sh stop app                            # nobody writes during the restore
ls -lt /srv/hospital/backups/dumps | head            # choose the dump
infra/compose.sh run --rm --no-deps -T backup \
  /opt/backup/restore-dump.sh --dump /backups/dumps/<file>.dump --yes
infra/compose.sh up -d app
curl -s http://127.0.0.1/api/ops/health
```

`restore-dump.sh` verifies the checksum, restores into a new database beside the live one, hands
that copy and every object in it to the owner role (`DB_OWNER_USER`), grants the app role
(`DB_APP_USER`) its row rights again, verifies both, and only then swaps names. If the roles cannot
be applied it stops and the live database is untouched. The previous database stays as
`<db>_before_<stamp>`. After users confirm the data (`-U` is `POSTGRES_USER`, the superuser):

```bash
infra/compose.sh exec db psql -U hospital -d postgres -c 'DROP DATABASE "hospital_before_<stamp>"'
```

**Restored by hand?** A database restored any other way (plain `pg_restore`, an old db image) is
owned by the superuser and the app role cannot read it: the app answers errors. Run
`infra/db-roles.sh` (hands everything to the owner, re-grants, verifies), then
`infra/compose.sh up -d app`.

## New server after a disaster — خادم جديد بعد كارثة

Target: clinic working again within 2 hours with last night's data.

1. Install a new server per [install.md](install.md) steps 1-5. Use the saved `.env`
   (same `POSTGRES_PASSWORD`, `DB_OWNER_PASSWORD`, `DB_APP_PASSWORD`, `DJANGO_SECRET_KEY`, cipher
   passphrases). The first `up -d db` creates the owner and app roles from it.
2. Copy the backups (USB or cloud) to `/srv/hospital/backups/`.
3. Load images (`docker load` from the release archive) with the same `APP_IMAGE_TAG`.
4. Start only the database, restore, then the rest:

Everything below uses only images that are already on the machine (no internet needed).

```bash
infra/compose.sh up -d db
infra/compose.sh run --rm --no-deps -T backup \
  /opt/backup/restore-dump.sh --dump /backups/dumps/<newest>.dump --yes
# Uploaded files back into the media volume, owned by the app user (uid 10001), using the db image:
docker run --rm -u 0 --entrypoint sh -v hospital_media:/m -v /srv/hospital/backups/media:/b:ro \
  <registry>/db:16 -c 'tar -xzf /b/<newest>.tar.gz -C /m && chown -R 10001:10001 /m && chmod 0750 /m'
infra/compose.sh up -d
infra/compose.sh run --rm --no-deps -T backup /opt/backup/restore-test.sh
infra/db-roles.sh                     # roles and grants verified on the restored database
```

5. Log in, open a recent patient and invoice, check the last shift. Record the restore in the log book.

## Enable pgBackRest — تفعيل الأرشفة المستمرة

Adds point-in-time recovery and an encrypted cloud copy. Do it in a quiet hour.

1. In `.env`: `PGBACKREST_ENABLED=true`. For the cloud also fill every `PGBACKREST_REPO2_*` value and
   a long `PGBACKREST_REPO2_CIPHER_PASS` (store it offline: without it the cloud copy is useless).
   Use a bucket with versioning or object lock, and a key that can only write to that bucket.
2. Render the config and create the stanza while archiving is still off:

```bash
infra/compose.sh up -d db backup
infra/compose.sh exec -u postgres db pgbackrest --stanza=hospital stanza-create
```

3. Turn archiving on (restarts PostgreSQL, a few seconds):

```bash
sed -i 's/^PG_ARCHIVE_MODE=.*/PG_ARCHIVE_MODE=on/' .env
infra/compose.sh up -d db
infra/compose.sh exec -u postgres db pgbackrest --stanza=hospital check
infra/compose.sh run --rm --no-deps -T backup /opt/backup/backup-nightly.sh    # first pgBackRest backup
infra/compose.sh exec -u postgres db pgbackrest info
```

While offline, WAL for the cloud queues up to `PGBACKREST_ARCHIVE_QUEUE_MAX`, then is dropped (the
local repo keeps everything); the next backup closes the gap.

## Point-in-time restore (pgBackRest) — استعادة إلى لحظة محددة

```bash
infra/compose.sh stop app web backup db
docker run --rm -v hospital_pgdata:/var/lib/postgresql/data \
  -v /srv/hospital/pgbackrest:/var/lib/pgbackrest --env-file .env \
  --entrypoint db-entrypoint hospital-sys/db:16 \
  pgbackrest --stanza=hospital --delta --type=time --target="2026-10-06 10:15:00+02" \
  --target-action=promote restore
infra/compose.sh up -d
```

Add `--repo=2` to restore from the cloud copy. Check the data, then take a fresh full backup.
A point-in-time restore brings back the whole cluster, roles and grants included; if the target
time is before the roles were introduced, run `infra/db-roles.sh` and `infra/compose.sh up -d`.
