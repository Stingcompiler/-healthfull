# 0024: Refunds are cash only, from a credit note; the schema says so

Date: 2026-10-26. Status: accepted (owner decision on inspection finding F08).

## Context
ARCHITECTURE 4.6 and the service (`payments.services.request_refund`,
`open_refund_for_credit_note`) pay a refund only in cash, from the paying user's open shift,
out of patient credit that an approved credit note created. The schema was wider: `Refund.method`
accepted `bank_transfer` (with a bank) and `payments_refund_has_source` accepted a refund whose
only source was a service line. No code path writes either shape, but the database would accept
them, so the schema did not state the rule the money depends on (the inspection of October 2026,
`docs/inspection/REPORT-2026-10.md`, F08).

The alternative, building a bank-transfer refund path (bank, reference, verification, ledger
posting to BANK), was not asked for by the center and is not built.

## Decision
- `RefundMethod` has one value, `cash`. Constraint `payments_refund_cash_only`: method `cash`,
  no bank, empty reference. The `method`, `bank` and `reference` columns stay (history rows and
  `RefundEvent` keep their shape); they can only hold the cash values.
- `payments_refund_has_source` (credit note OR service line) is replaced by
  `payments_refund_from_credit_note` (credit note required). `service_line` stays optional
  context: the cancelled line the credit note covers.
- `payments_refund_transfer_has_bank` is dropped (no transfer refunds exist).
- Migration `payments 0005` first lists every existing refund that would break the new
  constraints and stops with their numbers and what is wrong ("no credit note", "method
  bank_transfer", "bank set", "reference set"). It never rewrites a row: a paid or rejected
  refund is frozen (invariant 4) and only the operator can decide what such a row means.

## If the migration stops
It runs inside `infra/update.sh`, which rolls the update back. No production row is expected to
fail (no code path ever wrote one). If one does, keep the update on the old release and:
1. Read the listed refunds in the audit trail (`/administration/audit`) and the shift reports
   they were paid in.
2. A refund with no credit note: find the credit note whose credit it paid; a database owner
   sets `credit_note_id` on that row in a reviewed, recorded change (the refund's request
   fields are read-only by the `refund_request_readonly` trigger, so only the owner role, with
   that trigger disabled for the one statement, can do it; keep the written reason with the
   update record).
3. A non-cash refund: none can have been paid by the app (it only pays cash); treat it as a data
   error to investigate before any change.
Then rerun the update.

## Consequences
- The database states the refund rule the service already followed; a future bank refund path
  needs a new ADR, a migration and its ledger posting.
- Tests: `payments/tests/test_models.py::test_refund_needs_a_credit_note_and_a_reason`,
  `test_refund_is_paid_in_cash_only_raw_sql_too` (raw INSERTs as an app-shaped role),
  `payments/tests/test_refund_narrowing_migration.py` (the check finds and names old rows and
  changes nothing).
