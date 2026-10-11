# 0021: Notification recipients and links in one table; the daily integrity check

Date: 2026-10-11. Status: accepted.

## Context

- Notifications were created with role lists scattered over the modules (`MANAGER_ROLES`,
  `VERIFIER_ROLES`, `[PHARMACIST]`, `roles_holding(...)`), and the bell decided the link from
  the kind alone. Managers got `transfer_rejected` with a link to `/cashier/transfers`, whose
  endpoints need `payments.confirm_transfer`, which managers do not hold: the link opened a
  refused page (phase 8 docs follow-ups).
- ADR 0020 added `manage.py integrity_check` but left open running it on a schedule and telling
  anyone in the app when it finds something.

## Decision

1. **One table of kinds** (`apps/core/notification_kinds.py`): per kind, the recipients (by role,
   by permission, or chosen per event with the permission they are assumed to hold) and the
   screens that resolve it, in order of preference, each with the permission its endpoints
   require. `notify_kind(kind, ...)` sends a kind to the recipients the table names;
   `notify_users` refuses an unregistered kind (programming error). The ordering doctor's lab
   result alerts stay per event (`notify_users`).
2. **Every recipient may open a link.** `apps/core/tests/test_notification_kinds.py` checks, for
   every kind and every role receiving it by default, that one of its links needs a permission
   that role holds by default, and that every kind the code sends is in the table. The bell
   (`features/notifications/kinds.ts`) opens the first link the reader may open (and none when
   there is none, e.g. after a matrix change); its contract test reads the Python table and fails
   on any difference. `transfer_rejected` now links to the transfer queue for verifiers and to
   the patient file for managers.
3. **Daily integrity check.** The compose `maintenance` loop runs
   `manage.py integrity_check --daily` every cycle. It runs the six checks once a local day,
   stores the result in `ops.IntegrityRun` (ops migration 0005: start, end, ok, source
   `scheduled`/`manual`, per check what was looked at, how many problems and the first examples),
   and exits 0 even on findings: they are reported in the app, and the loop must not read them as
   a job to retry. A non-zero exit means the check could not run, and the loop logs it.
   `--record` stores a run made by hand.
4. **Alert and status page.** A run with findings sends `integrity_failed` (dedupe key per day) to
   the holders of `ops.view_status` (administrators and managers by default), linking to
   `/administration/system`. `GET /api/ops/status` carries `last_integrity_check` and the warning
   `INTEGRITY_FAILED`; the status page shows the newest run per check and says to back up and call
   support. Nothing is repaired.

## Consequences

- A new notification kind needs a row in the table, a text in `ops:notifications.kinds`, and the
  same links in `kinds.ts`; the tests point at each missing piece.
- The integrity check reads every approved invoice once a day; on a large installation the
  maintenance cycle takes longer that once (ADR 0020: batches of 500, no locks).
- The app role inserts `IntegrityRun` rows (ordinary DML; no new grant).

## Code
`backend/apps/core/notification_kinds.py`, `apps/core/services.py` (`notify_kind`),
`apps/ops/integrity_runs.py`, `apps/ops/management/commands/integrity_check.py`,
`apps/ops/models.py` (`IntegrityRun`), `apps/ops/services.py` (`system_status`),
`infra/docker/app-entrypoint.sh`; tests `apps/core/tests/test_notification_kinds.py`,
`apps/ops/tests/test_integrity_schedule.py`, `infra/tests/test_app_entrypoint.sh`; frontend
`features/notifications/kinds.ts` (+ test), `features/admin/pages/SystemPage.tsx`.
