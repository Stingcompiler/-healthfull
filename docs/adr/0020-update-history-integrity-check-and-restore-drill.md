# 0020: Update history in UpdateRun, the integrity check and the restore-from-scratch drill

Date: 2026-10-10. Status: accepted.

## Context

Phase 8 (handover) needs operations a clinic can trust without the developers present:

- `ops.UpdateRun` existed (FEATURES 13.10) but nothing wrote it; `infra/update.sh` kept only a
  JSON line per run in `update-runs.jsonl` (PROGRESS, ops follow-ups).
- Restore tests (`restore-test.sh`) proved a dump can be read and counted rows, but not that a
  restored database works with the application's roles, matches the code's migrations, or that
  its books balance (FEATURES 14.1, 14.6: a timed replace-the-server drill had never run).
- No command re-checked the money and stock invariants on a live or restored database. The
  database guards prevent damage; nothing verified their result after a restore, an update or a
  hand-made change.

## Decision

1. **`manage.py record_update`** writes one `UpdateRun` per update run through
   `apps.ops.services.record_update_run` (never raw SQL). `infra/update.sh` calls it once at the
   end of every run (success, failure, rollback) in a one-off `app` container of the version
   serving at that moment: the new tag after a success, the previous tag otherwise. Long texts
   (the `migrate --plan` output read in preflight, optional `--release-notes FILE`, the last 200
   log lines) travel on stdin in `@@plan` / `@@notes` / `@@log` sections; short facts as options.
   A `run_key` (`<UTC stamp>-<tag>`, unique, also in the state file and the JSON line) makes the
   write idempotent and lets the next run record a run a power cut interrupted, as `failed`.
2. **Recording is best effort.** It never changes the outcome or exit code of an update; a failed
   write warns and the JSON line remains the record. The first rollback from the release that
   introduces the command runs an image without it, which is expected.
3. **Rollback-compatible columns.** The columns added to `UpdateRun` (`run_key`,
   `migration_plan`, `migrations_applied`, `db_restored`, `backup_file`, `detail`) have database
   defaults (`db_default`), so an older image started by a rollback, whose models do not know
   them, can still insert rows. New columns on tables written during a rollback should follow
   the same rule.
4. **`manage.py integrity_check`** (`apps/ops/integrity.py`, pure comparison in
   `domain/integrity.py`) runs six read-only checks in one `REPEATABLE READ, READ ONLY`
   transaction: ledger balanced, AR_PATIENT per invoice = its document position, AR_PAYER per
   payer = claims documents, shift CASH = expected cash, stock non-negative and = its moves, no
   orphan allocations (one ledger entry per allocation and back, approved invoices only, never
   over-allocated, reversals match). It uses the existing services for the document side
   (`billing.invoice_positions`, `claims.payer_receivables`, `payments.expected_cash`), so a check
   and the screens never disagree on a rule. The app role can run it; it exits 1 on any finding.
   A finding is reported, never repaired: the runbook says to back up and call support.
5. **`infra/backup/restore-drill.sh`** rebuilds a dump the way a replacement server does: a new
   empty database, the owner and app roles set up on it (`infra/db/roles.sh`), `restore-dump.sh`
   into it, then `migrate --check` as the owner and `integrity_check` as the app role, row counts,
   and one `restore_test` line with `label: "drill"` in `restore-tests.jsonl` (the status page
   already reads it). Because the backup image has `pg_restore` but no Django and the app image
   the opposite, on a server the drill runs with `--keep` in the backup container and the two
   Django checks in the `migrate` and `app` containers (`-e DB_NAME=...`); where both exist (a
   checkout, CI) `--manage "<command>"` runs everything and records every result.
6. **The drill is tested end to end** by `infra/tests/test_restore_drill.sh` (`make infra-test`):
   a database migrated and seeded through the services, a nightly backup, the drill with new
   roles, row counts equal to the source, a damaged ledger failing it and a corrupt dump refused.
   The CI `infra` job installs the backend environment for it (`REQUIRE_DJANGO=1`).

## Consequences

- The status page's update history shows every scripted update with its plan and outcome; the
  JSON line stays for installs whose database was down at the end of a run.
- Operators have one command to answer "are the books right?" after a restore, an update with
  migrations, a power cut or a suspicion, and a quarterly drill whose result is recorded.
- `make infra-test` takes a few minutes longer (migrate and seed a database).
- `integrity_check` reads every approved invoice's documents; on a large installation it takes
  longer (batches of 500 invoices, four queries each) but holds no locks.
- Not done: exposing the new `UpdateRun` columns in `/api/ops/updates` and on the status page
  (the API schema is unchanged); a scheduled integrity check with an in-app alert.
