# Daily operations — التشغيل اليومي

For the person who looks after the server (system admin or IT support). Commands run on the
server in `/opt/hospital-sys`; `infra/compose.sh` is `docker compose` with the right env and
compose files. Related: [install.md](install.md), [backup-restore.md](backup-restore.md),
[update-rollback.md](update-rollback.md), user guides in [../guides/](../guides/README.md).

## Daily check (5 minutes) — الفحص اليومي

1. Open **Administration > System status** (`/administration/system`, «حالة النظام»). It must show
   no warning. The warnings and what to do:

   | Warning code | Meaning | Do |
   |---|---|---|
   | `BACKUP_STALE` | no `ok`/`partial` backup in 36 hours | [backup-restore.md](backup-restore.md#daily-check--الفحص-اليومي): run a manual backup now |
   | `BACKUP_FAILED` | the last backup failed | read its `error`; usually the backup disk (full or unmounted) |
   | `RESTORE_TEST_STALE` / `RESTORE_TEST_FAILED` | no passing restore test in 35 days | run `restore-test.sh` by hand (below) |
   | `DISK_LOW` | a disk below 10 % free | prune old images (`docker image prune -a --filter "until=168h"`), check backup retention |
   | `MIGRATIONS_PENDING` | code and schema differ | an update was interrupted: re-run `infra/update.sh --tag <tag>` |
   | `DB_UNAVAILABLE` | the app cannot reach PostgreSQL | `infra/compose.sh ps`, `infra/compose.sh logs --tail=100 db` |
   | `BACKUP_STATUS_UNAVAILABLE` | the backup status folder is not mounted | check `BACKUP_HOST_DIR` in `.env`, `mount | grep /srv/hospital` |

2. From the server (or when the status page itself does not open):

   ```bash
   infra/compose.sh ps                                           # db, app, web healthy; backup, maintenance up
   curl -s http://127.0.0.1/api/ops/health                       # {"status": "ok", ...}
   tail -n 1 /srv/hospital/backups/status/backup-runs.jsonl      # "status":"ok"
   df -h / /srv/hospital
   ```

3. Ask the cashier supervisor whether yesterday's shifts are closed and reviewed (the manager's
   dashboard and the bell list shifts awaiting review and transfers pending too long).

## Weekly — أسبوعياً

- Off-site copy to the rotated USB disk ([backup-restore.md](backup-restore.md#off-site-copy--نسخة-خارج-المركز)).
- Integrity check of the books and the stock (read-only, safe during work):

  ```bash
  infra/compose.sh run --rm --no-deps -T app manage integrity_check
  ```

  Ends with `integrity_check: <db>: all checks passed` (exit 0). See
  [Integrity check](#integrity-check--فحص-سلامة-البيانات) for what a failure means.
- Glance at **Administration > Audit** («سجل التدقيق») for unlocks, overrides and role changes
  you do not recognise.
- `sudo apt list --upgradable` (security updates install themselves with unattended-upgrades;
  reboot in a quiet hour when `/var/run/reboot-required` exists).

## Monthly and quarterly — شهرياً وكل ثلاثة أشهر

- **Monthly**: the backup sidecar runs `restore-test.sh` on `RESTORE_TEST_DAY`. Confirm it on
  the status page. To run it now:
  `infra/compose.sh run --rm --no-deps -T backup /opt/backup/restore-test.sh`.
- **Quarterly**: the restore-from-scratch drill ([backup-restore.md](backup-restore.md#restore-from-scratch-drill--تمرين-الاستعادة-من-الصفر)),
  which rebuilds the database with new roles and runs the integrity check on it. Write the
  time it took in the log book.
- Test the UPS: pull the mains plug with everyone warned; the server must shut down cleanly on
  low battery and come back by itself.

## Users and passwords — المستخدمون وكلمات المرور

Everyday account work is done on screen by a system admin: **Administration > Users**
(`/administration/users`, «المستخدمون»). Step by step with the exact labels:
[system-admin.md](../guides/system-admin.md).

| Task | Where | Notes |
|---|---|---|
| Add a user | «المستخدمون» > new user: username, names, roles, temporary password | the user must change the password at first sign-in; give each person their own account, never share |
| Reset a forgotten password | user row > «إعادة تعيين كلمة المرور» | check the person's identity face to face; their open sessions end; they must change it at next sign-in |
| Unlock a locked account | user row > «فك القفل», with a reason | 5 wrong passwords lock an account for 15 minutes; the lock also ends by itself. The reason, your name and the time go to the audit trail. If someone else may be guessing, reset the password instead |
| Someone leaves | user row > deactivate | never delete: their name stays on the documents they signed |
| Waiting-room screen | a dedicated account with the `display` role only | see [waiting-room-display.md](../guides/waiting-room-display.md) |

**Break-glass account** (the superuser created at install with `createsuperuser`). Only another
superuser can reset it on screen. If it is the only admin and its password is lost:

```bash
infra/compose.sh run --rm --no-deps app manage changepassword <username>   # asks twice, validates
```

A locked break-glass account unlocks itself after 15 minutes. Keep its password sealed in the
clinic safe with the printed `.env`, and use it only to repair access.

## When the internet is down — عند انقطاع الإنترنت

Nothing to do. The system runs entirely on the clinic LAN: no page, font, script or service
comes from the internet, and patients' phones reach the portal over the clinic Wi-Fi. Only
these wait for the connection and catch up by themselves:

- the optional cloud copy (pgBackRest repo2): WAL queues up to `PGBACKREST_ARCHIVE_QUEUE_MAX`; the
  local backups and repo1 are not affected (a backup may be `partial` for that reason only);
- `infra/update.sh` without `--image-archive` cannot pull images: use the USB release archive;
- the server clock cannot sync. Check `timedatectl` once a week while offline: prices take effect
  by date and shifts and reports use the clock. Correct it with
  `sudo timedatectl set-time "2026-10-10 08:00:00"` if it drifted, and never move it backwards
  during opening hours.

## When the power fails — عند انقطاع الكهرباء

1. The UPS keeps the server, switch and router up. On low battery NUT shuts the server down
   cleanly ([install.md](install.md#8-ups-shutdown-nut--الإيقاف-الآمن-عند-انقطاع-الكهرباء)).
2. Workstations without a UPS go dark: work continues on the tablets and phones that still have
   battery, or on paper (below). Nothing typed into a screen that was not saved is kept.
3. When power returns the BIOS powers the server on and the stack starts by itself. Check:

   ```bash
   infra/compose.sh ps
   curl -s http://127.0.0.1/api/ops/health
   ```

4. Nothing else is needed: a backup missed during the outage runs as soon as the backup
   container starts; locks die with their processes; open cashier shifts stay open and are
   closed as usual. If an update was running, re-run the same `infra/update.sh --tag <tag>`: it
   reports and records the interrupted run and finishes the job ([update-rollback.md](update-rollback.md)).

## When the server dies — عند تعطل الخادم

1. **Keep the clinic working on paper.** Reception, the cashier and the pharmacy keep the paper
   fallback forms (patient, service, receipt number, amount, cashier). Pay-first still applies.
2. **Decide within 30 minutes**: a fault you can fix (cable, disk full, a container that will not
   start, see the table below) or a dead machine.
3. **Dead machine**: a replacement server from the newest backup, target 2 hours
   ([backup-restore.md](backup-restore.md#new-server-after-a-disaster--خادم-جديد-بعد-كارثة)). You
   need the release archive (USB), the backup disk or off-site USB copy, and the printed `.env`.
4. After the restore run the integrity check, then enter the paper records through the normal
   screens (each receipt with today's date and a note naming the paper receipt). Work since the
   last backup is lost and must be re-entered from paper as well.

## Integrity check — فحص سلامة البيانات

`manage.py integrity_check` reads the database in one read-only snapshot (it can never change
anything, and the app role may run it during opening hours) and checks:

| Check | Passes when |
|---|---|
| `ledger_balanced` | the trial balance is zero and every journal entry has 2+ lines with debits = credits |
| `invoice_positions` | for every approved invoice, the patient receivable in the ledger (AR_PATIENT) equals what its lines, credit notes, rebills and payments say |
| `payer_receivables` | for every payer, AR_PAYER equals the claims documents (accrued, claimed, answered, paid) |
| `shift_cash` | each open shift's CASH equals its expected cash; a closed shift holds none |
| `stock` | no batch below zero, and every stock balance equals the sum of its moves |
| `allocations` | each payment allocation has exactly one ledger entry and every allocation entry an allocation; only approved invoices; never more allocated than paid; reversals match their original |

```bash
infra/compose.sh run --rm --no-deps -T app manage integrity_check            # text
infra/compose.sh run --rm --no-deps -T app manage integrity_check --json     # one JSON object
infra/compose.sh run --rm --no-deps -T app manage integrity_check --check stock
```

Exit 0: all checks passed. Exit 1: at least one failed; up to 20 examples per check are printed.
**A failure is never fixed by editing the database.** The guards (triggers, the app role) exist
so that nobody can; a mismatch means a bug or a hand-made change. Do this instead: take a manual
backup at once, save the output, note what happened just before (an update, a restore, a power
cut), and call support with the output and the backup. The clinic can keep working.

## Troubleshooting — حل المشكلات

| Symptom | Likely cause | Fix |
|---|---|---|
| Nobody can open `http://hospital.lan` | server off, network, or `web` down | ping the server's IP; `infra/compose.sh ps`; `infra/compose.sh up -d` |
| Opens by IP but not by name | router DNS entry lost | re-add `hospital.lan` in the router, or use the IP |
| Page opens, every screen shows an error | `app` down or the database unreachable | `infra/compose.sh logs --tail=100 app db`; `infra/compose.sh up -d` |
| App log: `permission denied for table ...` | database restored by hand, ownership or grants off | `infra/db-roles.sh`, then `infra/compose.sh up -d app` |
| `migrate` service "Exited (1)", app stays down | a migration failed at first start | `infra/compose.sh logs migrate`; after an update see [update-rollback.md](update-rollback.md#emergency-exit-3--حالة-طارئة) |
| A user: «أُوقف الحساب مؤقتاً…» | 5 wrong passwords | wait 15 minutes, or «فك القفل» with a reason (above) |
| Everyone on one PC is refused sign-in | too many failures from that address (throttle) | wait 15 minutes; check nobody is guessing passwords |
| Cashier: «لا توجد وردية مفتوحة» / `SHIFT_NOT_OPEN` | the cashier has no open shift | open a shift on «ورديتي»; late effects of a closed shift go into the current one |
| Status page: `BACKUP_STALE` | backup disk full or unmounted, backup container stopped | `df -h /srv/hospital`, `mount -a`, `infra/compose.sh up -d backup`, manual backup |
| "Back up now" stays pending | the backup service is not polling | `infra/compose.sh logs --since 1h backup`; `infra/compose.sh up -d backup` |
| Disk full | old images, dumps kept too long | `docker image prune -a --filter "until=168h"`; lower `BACKUP_RETENTION_DAYS` |
| Receipt printer prints nothing | device agent not running on that PC | start the agent ([agent/README.md](../../agent/README.md)); browser printing still works |
| Patient cannot sign in to the portal | wrong or expired code, or 5 wrong tries | cashier or reception issues a new code (the old one stops working) |
| Prices look wrong today | a new price list version started today, or the server clock is wrong | check the version dates (Administration > Price lists) and `timedatectl` |
| `integrity_check` fails | a bug or a hand-made database change | do not edit data; backup, save output, call support (above) |
| `update.sh` exit 3 | the rollback is unhealthy too | [update-rollback.md](update-rollback.md#emergency-exit-3--حالة-طارئة) |
