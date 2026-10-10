# Runbooks — أدلة التشغيل

For whoever installs and looks after the clinic server. User guides per role are in
[../guides/](../guides/README.md).

| Runbook | Use it for |
|---|---|
| [install.md](install.md) | a new mini PC: hardware and UPS, Ubuntu, LAN and firewall, Docker, disks, `.env`, database roles, first start, first admin, backup proof and the first drill, UPS shutdown, internal TLS, workstations |
| [operations.md](operations.md) | daily, weekly, monthly checks; adding users, password reset, account unlock, the break-glass account; internet down, power cut, dead server; the integrity check; troubleshooting table |
| [backup-restore.md](backup-restore.md) | what is backed up, status files, manual backup and restore test, the restore-from-scratch drill, off-site copy, restore on the same server, new server after a disaster, pgBackRest and point-in-time restore |
| [update-rollback.md](update-rollback.md) | updating with `infra/update.sh`, the update history (`ops.UpdateRun`), offline images, separate database roles for old installs, manual rollback, emergency |

Scripts these runbooks call: `infra/compose.sh`, `infra/update.sh`, `infra/db-roles.sh`,
`infra/backup/{backup-nightly,restore-test,restore-drill,restore-dump,backup-requests}.sh`
(inside the `backup` container as `/opt/backup/...`), and the management commands
`integrity_check`, `record_update`, `maintenance`, `notify_scan`, `charge_bed_nights`,
`createsuperuser`, `changepassword` (inside the app containers as `manage <command>`).
Every script prints its usage with `--help`; `make infra-test` exercises them.
