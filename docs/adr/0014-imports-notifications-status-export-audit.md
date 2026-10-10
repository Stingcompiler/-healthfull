# 0014: Imports, notifications, system status, data export and the audit viewer

Date: 2026-10-10. Status: accepted.

## Context
FEATURES 1.8 (completion), 8.13, 0.13, 13.8, 13.9, 13.10 and the audit trail viewer need rules
the earlier phases left open: how a spreadsheet may create stock and prices without bypassing
the pharmacy and catalog rules, what the app may do when an administrator asks for a backup,
how time-based alerts are raised without flooding inboxes, and how a full export stays safe
to open and accountable.

## Decision
- **One import flow, three kinds.** Patients, stock items with opening stock, and prices share
  upload, preview (`ImportJob` + `ImportRow`, nothing written), confirm and cancel
  (`/api/imports/jobs`, `/api/imports/templates/{kind}`); the reception's patient endpoints
  stay as they were and run the same service. Rows with errors never import; possible
  duplicates only when the user asks; informational hints (`warning`: an existing item, an
  unchanged price) import like valid rows. Each kind also needs its module's permission
  (`pharmacy.manage_items`, plus `pharmacy.receive_goods` for opening stock and
  `catalog.manage` for new catalog codes; `catalog.manage_prices`).
- **Files are read defensively.** Only `.xlsx` (zip signature checked, unpacked size at most
  60 MB, so a decompression bomb is refused before parsing) and `.csv` (no NUL bytes); 5 MB
  and 2,000 rows. Workbooks are opened without cached values: a formula cell, or text starting
  with `=`, is the row error `FORMULA_NOT_ALLOWED`. Formulas are never evaluated or stored.
- **Opening stock is a goods receipt.** Items and pack units are created through
  `catalog.create_service`, `pharmacy.create_item` and `pharmacy.add_unit` (one savepoint per
  service code: a refusal skips that code's rows only). Opening quantities become one posted
  goods receipt per store from the `OPENING` supplier, supplier invoice `IMPORT-<job>-<store>`
  (posting one job twice is impossible): batches are created by `post_receipt` and the moves
  are ordinary `receipt` moves (invariant 5, append-only stock ledger untouched). A row for an
  item that already has stock, or for a batch that already exists, is a possible duplicate
  (it would count opening stock twice).
- **Prices only into a future version.** A price import names a list and a start date after
  today; confirm edits the planned version of that date (`set_prices`) or derives a new one
  from the version effective then (`derive_version`), all rows or none. Effective versions
  never change (invariant 6).
- **Notifications.** Event alerts stay where things happen. Time-based ones
  (`transfers_pending_overdue`, `shift_review_pending`, `stock_low_summary`, `backup_stale`)
  come from `manage.py notify_scan`, recipients by permission (`roles_holding`), each with a
  per-day dedupe key (`Notification.key`, unique per user when set). The maintenance loop runs
  it with `maintenance` and `charge_bed_nights --as $BED_CHARGE_USER` every hour; all three
  are idempotent. The bell polls the unread count every minute (no push channel on the LAN).
  Notification endpoints are open to every signed-in user and scoped to `request.user`.
- **A backup request is a row.** "Back up now" (`ops.trigger_backup`) inserts a
  `BackupRequest` (one open at a time, advisory lock plus a partial unique index). The app
  never runs a command: the backup sidecar's scheduler (or a host timer) runs
  `infra/backup/backup-requests.sh`, which claims the oldest pending row with
  `FOR UPDATE SKIP LOCKED`, runs `backup-nightly.sh --label manual-<id>` and writes the outcome
  back; rows left `running` by a dead run are failed after `BACKUP_REQUEST_STALE_HOURS`.
- **Status from the scripts' logs.** The status page reads the backup and restore-test JSON
  lines in `BACKUP_STATUS_DIR` (read-only mount) and the `BackupRun`/`RestoreTest` rows,
  newest wins; warning codes (`BACKUP_STALE` after 36 hours, `RESTORE_TEST_STALE` after 35
  days, `DISK_LOW` under 10%, `MIGRATIONS_PENDING`, ...) are computed by the server. Update
  history shows `UpdateRun` rows (release notes) and the update script's own log.
- **Full export.** `POST /api/ops/export` (`ops.export_data`, admin and manager) streams a zip
  of one UTF-8 CSV per table (every concrete column) with a README. A `DataExport` row (who,
  when, tables; then row counts and size) is written before the first byte, so cut-off
  exports are audited too. Text cells starting with `= + - @`, tab or carriage return get a
  leading apostrophe (CSV injection); numbers and dates are written as they are. POST, so a
  cross-site page cannot start one.
- **Audit viewer.** `core.view_audit` reads the pghistory event tables (names from the model
  registry, values parameterized): filter by model, user, day range, object id and action,
  newest first, with the fields of an insert or delete and the changed fields of an update.
  Fields whose name looks secret (password, token, code hash) show `***`.

## Consequences
- An import is as strict as the screens it replaces; a center migrating from another system
  fixes its sheet instead of the data later.
- Opening stock appears in the receipts list and stock card as receipts from "Opening stock
  (import)".
- A manual backup waits up to `BACKUP_REQUEST_POLL_SECONDS` (60) plus the duration of a
  running nightly job; without a backup service (development, e2e) it stays pending.
- Exports and audit queries over very large installations read every table; both are rare,
  administrative actions.
