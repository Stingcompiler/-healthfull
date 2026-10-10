# Update and rollback — التحديث والتراجع

FEATURES 13.10. One image tag per release for `app` and `web`. Never change `APP_IMAGE_TAG` by hand
and never run `migrate` yourself: `infra/update.sh` does both with a safety net.

Installed before the separate database roles existed (no `DB_OWNER_PASSWORD` in `.env`)? Do
[Separate database roles](#separate-database-roles--فصل-أدوار-قاعدة-البيانات) once first;
`update.sh` refuses to run until then and says so.

## What update.sh does — ماذا يفعل سكربت التحديث

1. Gets `app:<tag>` and `web:<tag>` (registry pull, or `--image-archive` from USB).
2. Runs Django system checks and `migrate --plan` (dry run, as the owner role, which proves its
   login) in throwaway containers of the new image.
3. If migrations are pending, stops the app (maintenance), then takes a verified dump labelled
   `pre-update-<tag>`. Without migrations the app keeps serving during the backup.
4. Checks and repairs the database roles (`infra/db-roles.sh`: the owner owns everything, the app
   role has row rights only), then applies migrations in the one-off `migrate` container of the new
   image, which connects as the owner role. The app role cannot change the schema.
5. Recreates `app` and `web` on the new tag.
6. Polls `/api/ops/health` inside the app until `status=ok` and `version=<tag>`.
7. Writes `APP_IMAGE_TAG=<tag>` to `.env` and records the run.

On failure it restarts the previous tag. The database is restored from the step-3 dump only if
migrations were applied **and** you passed `--restore-db-on-failure`. Logs: `infra/logs/`.

**The update history.** Every run (success, failure, rollback) is recorded twice:

- one line in `status/update-runs.jsonl` (format in [backup-restore.md](backup-restore.md#status-file-format-read-by-the-ops-module));
- one `ops.UpdateRun` row, shown on **Administration > System status** with the version history:
  from and to tag, result (`succeeded`, `failed`, `rolled_back`), start and end, the
  `migrate --plan` output, whether migrations were applied and the database restored, the
  pre-update dump, the reason and step of a failure, the last 200 log lines and the release
  notes given with `--release-notes FILE`. The script writes it with
  `manage.py record_update` in a one-off container of the version serving at the end (the new
  one after a success, the previous one after a rollback), never with SQL.

Recording never changes the outcome: if it fails (database down, or a rollback to a version
older than the command) the script warns and the JSON line remains. A run cut short by a power
cut is recorded as `failed` ("interrupted during ...") by the next run.

| Exit | Meaning |
|---|---|
| 0 | updated |
| 1 | failed; previous version running again (or nothing changed) |
| 2 | wrong arguments, missing `.env` or docker |
| 3 | failed **and** the rollback is unhealthy: follow "Emergency" below now |

## Before — قبل التحديث

- Read the release notes. Note whether the release has migrations.
- Last nightly backup is `ok`: `tail -n 1 /srv/hospital/backups/status/backup-runs.jsonl`.
- Disk: `df -h / /srv/hospital` (images about 1 GB, plus one dump).
- Pick a quiet time; with migrations the app is down for the backup and migration (minutes).
- Close open cashier shifts or warn the cashiers.

## Get the images — الحصول على الصور

Online: nothing to do, `update.sh` pulls. Offline (USB), prepared on a connected machine:

```bash
docker pull <registry>/app:v1.4.0 && docker pull <registry>/web:v1.4.0 && docker pull <registry>/db:16
# The db/backup image is included so a fresh offline server (disaster recovery) never needs
# to pull or build it.
docker save <registry>/app:v1.4.0 <registry>/web:v1.4.0 <registry>/db:16 | gzip > hospital-sys-v1.4.0.tar.gz
```

## Run — التنفيذ

```bash
cd /opt/hospital-sys
git fetch --tags && git checkout v1.4.0        # infra scripts of the release (if installed from git)
infra/update.sh --tag v1.4.0 --dry-run         # shows the migration plan; changes nothing
infra/update.sh --tag v1.4.0 --restore-db-on-failure --release-notes /media/usb/RELEASE-v1.4.0.md
# offline:
infra/update.sh --tag v1.4.0 --image-archive /media/usb/hospital-sys-v1.4.0.tar.gz --restore-db-on-failure
```

`--restore-db-on-failure` is the recommended default: the app is stopped from the backup until the
end, so a restore loses nothing. Leave it out only if you would rather inspect a failed migration
first.

**Power cut during an update.** `.env` is replaced atomically, so it is never half-written, and the
update lock is a kernel lock that dies with the process (nothing to delete by hand). The script
keeps `infra/.update.state` (target tag, step, whether migrations ran or containers were swapped,
the run key). Simply run the same `infra/update.sh --tag ...` again: it prints what the
interrupted run left behind, records it as failed in the update history, and finishes the job
(or rolls back) from the last committed tag in `.env`.

A pre-update backup with status `partial` (database dump verified, media archive failed) does not
stop the update; it is logged as a warning. Fix the media problem afterwards (backup-restore.md).
After the swap the script checks the app and the web container (SPA served, proxy reaches the app).

## After — بعد التحديث

- Log in as a cashier and a doctor; open a patient, an invoice, the shift screen.
- Status page shows the new version and the run in the update history;
  `tail -n 1 /srv/hospital/backups/status/update-runs.jsonl`.
- After a release with migrations: `infra/compose.sh run --rm --no-deps -T app manage integrity_check`
  must end with "all checks passed" ([operations.md](operations.md#integrity-check--فحص-سلامة-البيانات)).
- Keep the previous images for a week (rollback), then `docker image prune -a --filter "until=168h"`.

## Separate database roles — فصل أدوار قاعدة البيانات

Once per install made before this change. Until then the app connects as the PostgreSQL superuser,
which could `TRUNCATE` the ledger or switch off the protection triggers (ADR 0006). After it, the
app and maintenance connect as `hospital_app` (rows only), migrations as `hospital_owner` (owns the
schema), and only the db and backup containers use the superuser. About 10 minutes; the app is down
for under a minute while the containers are recreated. Do it in a quiet hour.

```bash
cd /opt/hospital-sys
tail -n 1 /srv/hospital/backups/status/backup-runs.jsonl     # last backup "ok"
git fetch --tags && git checkout <release>                    # infra scripts with the roles
# The db/backup image must contain the role scripts (first-start roles, re-grant after a restore):
infra/compose.sh build db backup                              # online, or offline:
docker load -i /media/usb/hospital-sys-<release>.tar.gz       #   the release archive includes db:16
infra/db-roles.sh                     # writes DB_OWNER_PASSWORD and DB_APP_PASSWORD into .env if
                                      # missing, creates both roles, hands the database and every
                                      # table to hospital_owner, grants hospital_app, verifies
infra/compose.sh up -d                # recreates db, migrate, app, maintenance, backup with the roles
infra/compose.sh ps -a                # migrate "Exited (0)", the rest healthy / up
infra/compose.sh exec -T app python -c "import os, psycopg; print(psycopg.connect(dbname=os.environ['DB_NAME']).execute('select current_user').fetchone()[0])"
                                      # prints hospital_app
curl -s http://127.0.0.1/api/ops/health
```

Then print `.env` again for the clinic safe: it now holds two more passwords, and a restore on a
new server needs them. `infra/db-roles.sh` is idempotent: run it again any time, after changing
`DB_OWNER_PASSWORD` or `DB_APP_PASSWORD` in `.env` (then `infra/compose.sh up -d`), or when it
reports a problem.

**Undo.** The roles do no harm on their own. To go back to the superuser connection, check out the
previous release's infra (`git checkout <previous>`) and run `infra/compose.sh up -d`; the old
compose file connects the app as `POSTGRES_USER` again.

## Manual rollback — التراجع اليدوي

App only (no migrations in the bad release, or schema still compatible):

```bash
APP_IMAGE_TAG=v1.3.2 infra/compose.sh up -d --no-deps app web
sed -i 's/^APP_IMAGE_TAG=.*/APP_IMAGE_TAG=v1.3.2/' .env
curl -s http://127.0.0.1/api/ops/health
```

App and database (the bad release migrated the schema; data since the dump is lost):

```bash
infra/compose.sh stop app
infra/compose.sh run --rm --no-deps -T backup \
  /opt/backup/restore-dump.sh --dump /backups/dumps/<db>-<stamp>-pre-update-v1.4.0.dump --yes
APP_IMAGE_TAG=v1.3.2 infra/compose.sh up -d --no-deps app web
sed -i 's/^APP_IMAGE_TAG=.*/APP_IMAGE_TAG=v1.3.2/' .env
```

`restore-dump.sh` hands the restored database to the owner role and re-grants the app role before
it swaps it in, so the old tag can read it at once. If a migration ever has to be applied by hand
(support asked for it), it runs as the owner role, never through `app`:
`APP_IMAGE_TAG=<tag> infra/compose.sh run --rm --no-deps -T migrate migrate`.

## Emergency (exit 3) — حالة طارئة

1. `infra/compose.sh ps` and `infra/compose.sh logs --tail=200 app db`: is the database healthy?
   `permission denied for table ...` in the app log means ownership or grants are off (a database
   restored by hand, a role changed): run `infra/db-roles.sh`, then `infra/compose.sh up -d app`.
2. Database down: `infra/compose.sh up -d db`, wait for healthy, then start the previous tag as above.
3. Database up but the old app fails on the new schema: restore the pre-update dump (above),
   then `infra/compose.sh run --rm --no-deps -T app manage integrity_check`.
4. Still down after 30 minutes: switch the clinic to the paper fallback forms and call support with
   the log file from `infra/logs/`.
