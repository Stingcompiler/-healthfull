# Update and rollback — التحديث والتراجع

FEATURES 13.10. One image tag per release for `app` and `web`. Never change `APP_IMAGE_TAG` by hand
and never run `migrate` yourself: `infra/update.sh` does both with a safety net.

## What update.sh does — ماذا يفعل سكربت التحديث

1. Gets `app:<tag>` and `web:<tag>` (registry pull, or `--image-archive` from USB).
2. Runs Django system checks and `migrate --plan` (dry run) in a throwaway container of the new image.
3. If migrations are pending, stops the app (maintenance), then takes a verified dump labelled
   `pre-update-<tag>`. Without migrations the app keeps serving during the backup.
4. Applies migrations with the new image.
5. Recreates `app` and `web` on the new tag.
6. Polls `/api/ops/health` inside the app until `status=ok` and `version=<tag>`.
7. Writes `APP_IMAGE_TAG=<tag>` to `.env` and records the run in `status/update-runs.jsonl`.

On failure it restarts the previous tag. The database is restored from the step-3 dump only if
migrations were applied **and** you passed `--restore-db-on-failure`. Logs: `infra/logs/`.

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
docker pull <registry>/app:v1.4.0 && docker pull <registry>/web:v1.4.0
docker save <registry>/app:v1.4.0 <registry>/web:v1.4.0 | gzip > hospital-sys-v1.4.0.tar.gz
```

## Run — التنفيذ

```bash
cd /opt/hospital-sys
git fetch --tags && git checkout v1.4.0        # infra scripts of the release (if installed from git)
infra/update.sh --tag v1.4.0 --dry-run         # shows the migration plan; changes nothing
infra/update.sh --tag v1.4.0 --restore-db-on-failure
# offline:
infra/update.sh --tag v1.4.0 --image-archive /media/usb/hospital-sys-v1.4.0.tar.gz --restore-db-on-failure
```

`--restore-db-on-failure` is the recommended default: the app is stopped from the backup until the
end, so a restore loses nothing. Leave it out only if you would rather inspect a failed migration
first.

## After — بعد التحديث

- Log in as a cashier and a doctor; open a patient, an invoice, the shift screen.
- Status page shows the new version; `tail -n 1 /srv/hospital/backups/status/update-runs.jsonl`.
- Keep the previous images for a week (rollback), then `docker image prune -a --filter "until=168h"`.

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

## Emergency (exit 3) — حالة طارئة

1. `infra/compose.sh ps` and `infra/compose.sh logs --tail=200 app db`: is the database healthy?
2. Database down: `infra/compose.sh up -d db`, wait for healthy, then start the previous tag as above.
3. Database up but the old app fails on the new schema: restore the pre-update dump (above).
4. Still down after 30 minutes: switch the clinic to the paper fallback forms and call support with
   the log file from `infra/logs/`.
