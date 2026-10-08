# 0006: Phase 1 money and stock rules

Date: 2026-10-07. Status: accepted.

## Context
Phase 1 built `backend/domain/` (pure, Hypothesis-tested), the full schema with its database
guards, and the services of the money and stock engine (`apps/{orders,billing,payments,claims,
pharmacy,lab,ledger}/services.py`). FLOW and FEATURES left several edges open. The Phase 1
adversarial review (54 reported issues, 49 confirmed and fixed with regression tests) settled
them. This ADR records each decision as the code on `feat/1-domain-core` implements it, so
later phases build on the same rules. Each item was checked against the code; the differences
found are listed at the end.

## Decisions

### (a) A full credit of an open line cancels it; corrections re-bill through a new line
- Decision: a credit note credits whole units of one invoice line. When approved credits cover
  every unit, the service line becomes `credited`; a line still `pending` or `in_progress` is
  also `cancelled`, documented with the approver, the time and a line-cancel reason (default
  `OTHER` citing the note). A `performed` line stays performed: the credit is financial only.
  A partial credit changes no status, except that an open line whose remaining units are now
  all given is performed with the given units. A correction is approved with `rebill=True`:
  `domain.service_line.replacement()` gives a fresh `requested` line for a cancelled original,
  or an unbilled line already `performed` under a new perform-first authorization for a
  performed original. The new line is invoiced like any other.
- Why: a credited line left open would stay in a work list with no money behind it
  (invariant 1). Re-billing through a new line keeps the approved invoice and its line
  untouched (invariant 2) and prices the correction on its own approval date (invariant 6).
- Consequences: there is no "edit an invoice line" path. `LineStatus` refuses `credited`
  with an open fulfilment. A replacement line carries `order_note = "replaces line N"`.
- Code: `domain/service_line.py` (`credit`, `replacement`), `apps/billing/services.py`
  (`approve_credit_note`), `apps/orders/services.py` (`apply_credit`, `create_replacement`).

### (b) Credit notes against a claimed payer share
- Decision: before the payer share is claimed, a credit reduces the accrued amount (`voided`
  at zero). Once it is on a claim line, a credit that takes back payer share withdraws the
  claim line in two cases only: the line is unanswered (`claimed`, stored `pending`), for any
  amount; or it is answered (accepted, partially accepted or rejected) with nothing paid,
  resolved or written off, and the credit covers its whole claimed amount. Anything else
  raises `CLAIM_LINE_LOCKED`: the payer side is corrected through the claim (rejection, rebill,
  write-off). What is left of the payer share after a withdrawal is claimable again in a
  later batch.
- Why: until the payer answers, withdrawing a line corrects what was sent. After an answer
  the claim carries the payer's decision and possibly money; changing it silently would break
  the receivable and the payer's statement. The answered-but-untouched case covers a service
  that was never given.
- Consequences: building a claim and crediting a line lock the same `InvoiceLine` rows, so
  they serialize. A credit with no payer share never touches the claim.
- Code: `domain/claims.py` (`withdraw_for_credit`, `reduce_for_credit`),
  `apps/claims/services.py` (`claim_line_for_credit`, `withdraw_for_credit`), DB
  `claim_line_guard`.

### (c) A rebill adds to the patient due on the original invoice line
- Decision: rebilling a rejected payer share posts Dr AR_PATIENT / Cr AR_PAYER against the
  original invoice. `domain.invoice.invoice_position` adds the rebilled amount to that line's
  patient due (at most the payer share left after credits, `REBILL_EXCEEDS_PAYER_SHARE`) and
  settlement is refreshed.
- Why: the patient owes it for the same service at the price frozen on that invoice. A new
  invoice would bill the service a second time and price it on another day (invariant 6).
- Consequences: the approved invoice never changes, yet its outstanding grows. A settled line
  can go back to `invoiced`; an open line then leaves the work lists until the rebilled part
  is paid (invariant 1).
- Code: `domain/invoice.py` (`Rebill`, `invoice_position`), `apps/claims/services.py`
  (`resolve_rejection`), `apps/billing/services.py` (`invoice_position`, `refresh_settlement`).

### (d) Payer payments are fully allocated; where payer money lands
- Decision: a payer payment equals the sum of its allocations to accepted, unpaid claim-line
  amounts (`PAYER_PAYMENT_UNBALANCED` otherwise); without explicit allocations it pays the
  oldest claims first. There is no payer advance account, so an overpayment is refused. A
  payer transfer posts Dr BANK. A cheque posts Dr BANK_PENDING until `clear_payer_cheque`
  (Dr BANK / Cr BANK_PENDING). Payer cash posts Dr CASH in the recording user's open shift
  (`SHIFT_NOT_OPEN` otherwise) and counts in that drawer's expected cash. A bounced transfer
  or cheque is reversed from where the money sits now, with negative allocation rows. Payer
  cash is never reversed. An accepted amount the payer short-pays is written off with an
  approval (Dr WRITE_OFF / Cr AR_PAYER).
- Why: invariant 7 keeps the payer share a receivable until real money arrives. Every
  payer payment must close named receivables, and cash in a drawer must be in that drawer's
  count.
- Consequences: unlike patient transfers, a payer transfer has no pending step: the
  accountant records it from the bank statement. A claim that is closed cannot have its
  payment reversed (`CLAIM_FINAL`).
- Code: `domain/claims.py` (`validate_payer_payment`, `allocate_oldest_first`),
  `domain/ledger.py` (`post_payer_payment`, `post_payer_cheque_cleared`,
  `post_payer_payment_reversed`), `apps/claims/services.py`, `apps/payments/services.py`
  (`cash_movements`).

### (e) Refunds
- Decision: a refund is paid in cash from the paying user's own open shift (Dr
  PATIENT_CREDIT / Cr CASH) and needs enough expected cash in that drawer. Its source is an
  approved credit note of the person (any merged file). It is at most the credit that note's
  de-allocation created less earlier refunds of it that were not rejected, and at most the
  patient's spendable credit (checked at approval and again at payment). One person requests,
  another approves (`SELF_APPROVAL_NOT_ALLOWED`, DB check). A cancellation opens the request
  itself, requested by the cancelling user.
- Why: FLOW 8: a refund opens from a cancelled paid line, never from nothing, and money
  leaves the center only with a second person's approval (invariant 4).
- Consequences: unallocated money (an overpayment) is not refundable in V1. It stays as
  patient credit to spend. Pending transfer money is never refundable.
- Code: `domain/allocation.py` (`refund_source_available`, `validate_refund`),
  `apps/payments/services.py` (`open_refund_for_credit_note`, `approve_refund`, `pay_refund`).

### (f) Transfer confirmation needs an approval with a reason
- Decision: confirming a pending transfer needs `payments.confirm_transfer` and a note saying
  what was checked. The rule takes an `Approval`, so an empty note raises `REASON_REQUIRED`.
  The approver and time are stored on the payment. Rejection (pending or confirmed) needs
  `payments.reject_transfer` and a reason code.
- Why: invariant 4 lists transfer confirmation among the actions that record reason,
  approver and time.
- Consequences: Dr BANK / Cr BANK_PENDING is booked in the original shift while it is open,
  else in the confirmer's open shift (shown there as a late confirmation), else in no shift.
- Code: `domain/payments.py` (`confirm`, `reject`), `apps/payments/services.py`
  (`confirm_transfer`, `reject_transfer`).

### (g) Batches are usable through their expiry date
- Decision: a batch is usable while `expiry >= today + min_days_left`, so it may be dispensed
  on its expiry date. FEFO picks usable batches with stock, earliest expiry first. Another
  batch choice needs `pharmacy.override_batch` and a reason; an expired batch is never
  dispensed, even by override. Goods already expired are refused at receipt.
- Why: the expiry date is the last day of use. A safety margin is a center policy, not a
  rule.
- Consequences: `min_days_left` exists in `domain.stock` but no setting feeds it yet:
  dispensing uses 0. It applies only to the FEFO suggestion, not to an override.
- Code: `domain/stock.py` (`is_usable`, `fefo_order`, `select_batches`),
  `apps/pharmacy/services.py` (`dispense`, `add_receipt_line`).

### (h) Critical lab limits are inclusive
- Decision: `critical_low` when `value <= critical_low`, `critical_high` when
  `value >= critical_high`. `low` and `high` bound an inclusive normal range. Critical limits
  must lie strictly outside the normal range (`INVALID_REFERENCE_RANGE`). An approved version
  with a critical value notifies the ordering and visit doctors as `lab_result_critical`.
- Why: a value exactly at a critical limit is treated as critical. A missed call costs more
  than an extra one.
- Code: `domain/lab.py` (`flag`, `ReferenceRange`), `apps/lab/services.py` (`_notify_result`).

### (i) Cash outside the drawers: the CASH_SAFE account
- Decision: an eleventh account, `CASH_SAFE` (asset, no dimension), holds cash in the safe, with
  a supervisor, or in transit between shifts. Postings:
  - Shift opening: Dr CASH (shift) / Cr CASH_SAFE for the opening float.
  - Handover to the safe, a supervisor or the next shift: Dr CASH_SAFE / Cr CASH (shift).
    A bank deposit: Dr BANK / Cr CASH.
  - Receipt by the next shift: Dr CASH (receiving shift) / Cr CASH_SAFE. A handover to the safe
    or a supervisor has no receipt posting.
  - Cancellation of an unreceived handover (sending shift still open, with a reason): the
    opposite of the handover.
  - Close: the variance (CASH vs CASH_OVER_SHORT), then the counted cash swept Dr CASH_SAFE /
    Cr CASH.
- Why: without it the drawer's ledger CASH could not equal its expected cash, and a closed
  shift would keep a balance forever.
- Consequences: an open shift's CASH equals its expected cash, and a closed shift's CASH is
  zero. A shift cannot close while cash handed to it waits to be received
  (`HANDOVER_PENDING`). CASH_SAFE pools safe, supervisor and in-transit cash, and no service
  records the safe's starting cash, so its balance is relative (negative after floats are
  issued) until a safe count exists.
- Code: `domain/ledger.py` (`post_shift_opening`, `post_cash_handover`,
  `post_handover_received`, `post_handover_cancelled`, `post_shift_sweep`),
  `apps/payments/services.py`, migration `ledger.0005_seed_cash_safe`.

### (j) The shift report is frozen at close
- Decision: `close_shift` stores the report as it stands in `Shift.close_report` (DB check:
  closed means a report is present). `shift_summary` serves a closed shift from that snapshot
  and never recomputes it.
- Why: invariant 3. A transfer confirmed or rejected after the close would otherwise change
  a report the manager already reviewed.
- Consequences: later effects show in the shift where they are booked (`late_confirmations`,
  `late_reversals`). A rejection after close books a negative payment row linked to the
  original in the acting shift.
- Code: `apps/payments/services.py` (`close_shift`, `ShiftSummary`, `shift_summary`).

### (k) Credited units are never given; partly dispensed lines
- Decision: units that may still be performed or dispensed are
  `open_quantity = ordered - credited - given`. A credit of an open line may take back only
  ungiven units (`CREDIT_EXCEEDS_UNGIVEN`). A performed quantity is at most ordered less
  credited, and defaults to that when units were credited. Dispensing is refused beyond the
  open units (`DISPENSE_EXCEEDS_LINE`, also in the DB). A line with dispensed units is never
  cancelled outright: its given units are performed and only the rest is closed
  (`cancel_line_remainder`, which credits `remainder_to_credit` units of a billed line, never
  units an earlier note took back). An unbilled, perform-first line is then invoiced for the
  performed quantity only. `Policy.partial_dispense_remainder` chooses whether an incomplete
  dispense defers the rest (default) or closes it with a refund.
- Why: invariants 1 and 5. A refunded unit given anyway is a free unit. A dispensed unit
  cancelled away is stock with no record.
- Code: `domain/service_line.py` (`open_quantity`, `remainder_to_credit`),
  `apps/orders/services.py`, `apps/pharmacy/services.py` (`dispense`), DB `line_guard`
  (`LINE_PARTLY_DISPENSED`) and `dispense_line_eligible`.

### (l) Merged patient files aggregate money; balances do not move
- Decision: a merge posts nothing. The patient balance, spendable credit and open invoices of
  a person sum every file merged into the survivor. Allocating one file's payment to another
  file's invoice debits PATIENT_CREDIT on the paying file and credits AR_PATIENT on the
  invoice's file. New money is taken only on the surviving file (`PATIENT_MERGED`). A merged
  file may only spend the credit it holds. Refund requests are opened per file the money came
  from.
- Why: ledger lines carry the file they were posted to, and the ledger is append-only.
  Moving balances would need artificial entries and would lose which file paid.
- Consequences: every money read for a person goes through `patients.person_file_ids`.
- Code: `apps/payments/services.py` (`patient_balance`, `record_payment`,
  `open_refunds_for_credit_note`), `apps/billing/services.py` (`open_invoices`),
  `domain/ledger.py` (`post_allocation`).

### (m) Database guards and their residual risk
- Decision: the database repeats the rules that protect money and stock, so that a bug or a
  raw SQL statement cannot break them:
  - `line_guard` (service line): no delete; inserted unbilled; terminal fulfilment fixed;
    billing moves only along the allowed edges and leaves `unbilled` only from a frozen line
    of an approved invoice; a billed order is read-only; a billed line is cancelled only by
    its credit note; a line with dispensed units is never cancelled; entering `in_progress`
    or `performed` needs `settled` or an unrevoked authorization of the same visit.
  - `dispense_line_eligible`: the line is open and settled or authorized, on the dispense's
    visit, and the cumulative dispensed units never exceed ordered less credited.
  - `claim_line_guard`: no delete; new lines join a draft claim and never claim more than
    the payer share less approved credits; claimed amounts and payer answers are read-only;
    status moves only along the allowed edges, including the two withdrawals of (b).
  - `truncate_guard` on 22 tables (invoices, credit notes and their lines, service lines,
    authorizations, shifts, payments, allocations, refunds, handovers, journal entries and
    lines, claim lines, payer payments and their allocations, stock moves and balances,
    dispense lines and returns, result versions and values): `TRUNCATE` is refused unless the
    session role is a member of the table owner.
  - Also: append-only ledger, allocation, stock move, dispense and payer allocation tables;
    a deferred trigger that refuses unbalanced journal entries; `shift_must_be_open` on every
    money row that names a shift; frozen invoices, credit notes, closed shifts, approved
    result versions and price list versions already used; `StockBalance` maintained only by
    the stock move trigger with `CHECK (qty_base >= 0)`. `pgtrigger`'s ignore switch is
    replaced after each migrate by a function that never ignores a trigger.
- Why: invariants 1 to 7 must hold even when application code is wrong.
- Residual risk: a role that owns the tables, or a superuser, can still `TRUNCATE`, run
  `ALTER TABLE ... DISABLE TRIGGER`, or (superuser) set `session_replication_role = replica`
  and bypass every trigger. Mitigation: production runs the application (and the maintenance
  job) as a non-owner role with DML grants only; only migrations run as the owner, and only
  the db container and backup sidecar use the superuser. That set-up lives in `infra/db/`
  (see Differences below). Backups and the audit history remain the last line.
- Code: `apps/core/db.py`, `apps/orders/models.py`, `apps/pharmacy/models.py`,
  `apps/claims/models.py`, `apps/ledger/models.py`, `apps/payments/models.py`.

### (n) Pay-first is always on in V1
- Decision: `Policy.default_pay_first` stays `True` (DB check `core_policy_pay_first_always`).
  It documents the rule; it is not a switch. Perform-first exists only as a documented
  `PerformAuthorization` with a reason and an authorizing role from
  `Policy.perform_first_roles`.
- Why: invariant 1. A center-wide perform-first switch would make every line eligible
  without a record of who allowed it.
- Consequences: an authorization can be revoked only while no unpaid work under it is in
  progress (`AUTHORIZATION_IN_USE`). Work performed before a revocation stays covered.
- Code: `apps/core/models.py` (`Policy`), `apps/orders/services.py`
  (`authorize_perform_first`, `revoke_authorization`).

### (o) Price list versions start on a future date
- Decision: a new version starts tomorrow or later, on a date no other version of that list
  uses (`PRICE_VERSION_BACKDATED`, `PRICE_VERSION_DATE_TAKEN`). One exception: the first
  version of a list that has nothing effective yet may start today, because no invoice can
  have been priced from it. Such a same-day first version must come with prices, copied
  from a version of another list (`copy_from_id`), because it is read-only at once: an empty
  one would leave every payer on the list without prices until a later version starts
  (`PRICE_VERSION_EMPTY`). Prices of a version can be edited only before it starts
  (`PRICE_VERSION_LOCKED`).
- Why: invariant 6. Backdating, or a second version starting today, would change which price
  was "the list effective that day" after invoices of that day froze it.
- Consequences: a price correction takes effect tomorrow. The DB `version_guard` is a narrower
  backstop: it refuses a version that would reprice frozen invoices, and any change to a
  version already used by a frozen invoice line. It does not refuse a same-day version when
  no invoice was frozen that day. The service rule is the stricter one.
- Code: `domain/pricing.py` (`validate_new_version`), `apps/catalog/services.py`
  (`create_version`, `set_prices`), DB `version_guard`, `item_guard`.

### (p) Pooled patient credit can go negative
- Decision: patient credit is one pooled balance per file. Rejecting a transfer reverses its
  own allocations, then takes its whole amount out of credit. If that credit was already spent,
  credit-funded allocations are taken back newest first. What cannot be recovered (the money
  was refunded in cash after the transfer was confirmed) stays as a negative credit balance,
  returned as `uncovered`, and managers get a `patient_credit_negative` notification next to
  the usual `transfer_rejected` one.
- Why: the refund was real cash paid out. Hiding the loss would break the ledger, and
  reversing the refund is not possible.
- Consequences: the patient balance shows the person owing that amount (`net` > 0). Spendable
  credit is never below zero, so no further credit can be spent or refunded until it is
  covered.
- Code: `domain/allocation.py` (`plan_rejection`, `spendable_credit`),
  `apps/payments/services.py` (`reject_transfer`).

## Differences found while checking the code
1. (m) Resolved in configuration, pending its first Docker run. Compose used to connect the app
   as `POSTGRES_USER`, a superuser that owns the tables, so the guards stopped application bugs
   but not the application's own account. `infra/db/` now creates two roles: `hospital_owner`
   owns the database and every object and is used only by the one-off `migrate` service and
   `infra/update.sh`; `hospital_app` (DML only, not a member of the owner) is used by `app` and
   `maintenance`. The superuser is left to the db container and the backup sidecar. Proven on a
   local PostgreSQL 16 (the app role is refused `TRUNCATE`, `DISABLE TRIGGER`, `DROP` and the
   `pgtrigger` ignore switch; the backend suite and an HTTP smoke flow pass as that role). The
   compose stack itself is first exercised by the CI `docker` job.
2. (e) The schema is wider than the rule: `RefundMethod` still has `bank_transfer`, and the
   check `payments_refund_has_source` accepts a refund with only a service line. No service
   creates either. Tighten in a migration or drop the unused choice.
3. (g) `min_days_left` is a domain parameter only; no `Policy` field feeds it. Expired
   batches are refused by the domain and the receipt service, with no database backstop.
4. (o) The database backstop is narrower than the service rule (see above). The service is
   the only path that creates versions.
5. (i) CASH_SAFE has no opening balance and no dimension for safe, supervisor or transit.
6. (f) Segregation of duties is enforced for refunds and shift reviews only. A holder of
   `payments.confirm_transfer` may confirm a transfer they recorded, and a holder of
   `billing.approve_credit_note` may approve a credit note they created.
7. (n) The Django admin shows `default_pay_first` as an editable field; unticking it fails on
   the database check instead of being read-only.
8. (m) A few append-only or frozen tables have no `truncate_guard` (`PatientMerge`,
   `ShiftReview`, `AuthEvent`, `Claim`, the `Dispense` header, stock documents, price list
   versions). They are protected from a role without the `TRUNCATE` grant, and a
   `TRUNCATE ... CASCADE` that reaches a guarded table is refused.

## Consequences
- ARCHITECTURE 4.4 to 4.9 describe these rules and are binding.
- Changing any rule above is a change to its domain module, its property tests, the matching
  DB guard and this ADR together.
