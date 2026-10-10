# 0015: A transfer rejection never uses pending money

Date: 2026-10-10. Status: accepted. Amends ADR 0006 (p).

## Context
ADR 0006 (p) says that rejecting a transfer takes its amount out of the pooled patient credit
and, if that credit was already spent, takes credit-funded allocations back newest first.
`domain.allocation.plan_rejection` measured "already spent" against the raw pool
(`PATIENT_CREDIT`), which also holds the unallocated part of transfers still pending. The
stateful machine (`domain/tests/test_visit_machine.py`) found two consequences:

1. A confirmed transfer of 1205.00 was spent in full by a credit payment while a 0.01
   transfer was pending. Rejecting the 1205.00 took back only 1204.99 of the spend: the
   pending 0.01 covered the rest. That is pending money spent, which ADR 0006 (e) and
   ARCHITECTURE 4.6 forbid.
2. Rejecting that pending 0.01 next found the pool short and took back another 0.01 of
   credit-funded allocation. Another saved run had a pending rejection report 10.14 as
   `uncovered`. The same mechanism: after a bounce that was refunded in cash, pending money
   hid part of the loss, and the later pending rejection reported the whole pool deficit
   again (a 5000.00 loss with 200.00 pending was reported as 4800.00, then 5000.00).

The services (`apps/payments/services.py` `reject_transfer`) call the same planner, so real
data hits both cases. A pytest-django regression test reproduces case 1 and 2 through the
services.

## Decision
- `plan_rejection` takes `pending` and `spendable` (spendable credit before the rejection,
  from `spendable_credit`: the pool less every pending transfer's unallocated remainder,
  never below zero) instead of the raw credit balance.
- Rejecting a pending transfer reverses its own allocations and nothing else: its remainder
  was never spendable, so nothing can have been spent or refunded from it. No recovery,
  nothing `uncovered`.
- Rejecting a confirmed transfer takes its unallocated remainder out of confirmed credit only.
  The shortfall is `remainder - spendable`. It is recovered from credit-funded allocations
  newest first; what is left is `uncovered` and notified as before.
- A loss already reported by an earlier rejection is not counted again by a later one.

## Why
Spendable credit is the one measure of money the patient may use (ADR 0006 (e), (p)).
Covering a bounce with pending money spends it; if the pending transfer is then rejected the
clinic has lost the money and the books show a smaller loss than the real one.

## Consequences
- The pool never falls below the patient's pending money except by losses reported as
  `uncovered`. The stateful machine checks this after every step
  (`patient_credit_equals_documents`).
- A bounce may now take back more credit-funded allocations than before, never less: the
  lines they settled return to `invoiced` until the patient pays with confirmed money.
- Code: `domain/allocation.py` (`plan_rejection`), `apps/payments/services.py`
  (`reject_transfer`), tests in `domain/tests/test_allocation.py`,
  `domain/tests/test_visit_machine.py`, `apps/payments/tests/test_services.py`.
