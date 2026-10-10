# 0010: Lab bench rules: approval revision, billing approver at the bench, rejected samples

Date: 2026-10-09. Status: accepted.

## Context
The laboratory screens (FEATURES 9.1-9.8) put the Phase 1 lab services in front of users.
Building them raised four questions the documents left open: what a supervisor approves when
a technician edits a draft at the same moment, who approves the credit note when a paid test
cannot be performed (lab supervisors hold no billing code), what happens to values entered
on a sample that is later rejected, and who reads turnaround figures.

## Decisions
- **Approval names the draft it approves.** `GET /api/lab/lines/{id}/result` returns each
  draft's `revision` (a fingerprint of its values and comment); `POST .../result/approve`
  must send it, and the service refuses `RESULT_CHANGED` (409) when the draft changed since.
  Approval also refuses a cancelled line (`LINE_CANCELLED`), a first result whose sample is
  not received (`SAMPLE_NOT_RECEIVED`), and a first result of a line that is no longer paid or
  authorized (`LINE_NOT_ELIGIBLE` from `orders.perform_line`, invariant 1). Line lock first,
  as every work path.
- **Billing approver at the bench.** `lab.cancel_test` (lab supervisor, admin) cancels a test
  that cannot be performed. A billed test is credited by `orders.cancel_line`, whose credit
  note needs a `billing.approve_credit_note` holder (ARCHITECTURE 4.4 rule 5). The lab dialog
  takes that person's credentials exactly like the cashier's desk approvals (ADR 0009,
  `apps.payments.approvals`); without them the service answers
  `CANCEL_NEEDS_BILLING_APPROVER` (409) instead of a bare 403. The refund itself still needs
  a second person at the cashier (ADR 0008).
- **Amendments stay with amenders.** The draft that amends an approved result is edited only
  by holders of `lab.amend_results` (lab supervisor, admin); technicians enter first results.
- **Rejecting a sample discards its draft.** Draft values measured on an unusable sample are
  deleted (audited by pghistory) when the sample is rejected, so they can never be approved
  for a new sample nobody measured. Approved results still refuse rejection.
- **Reports.** `lab.view_reports` (lab supervisor, manager, admin) reads the turnaround report;
  minutes run from sample receipt (or collection) to first approval, summarised with
  nearest-rank median and 90th percentile (`domain.lab.turnaround_stats`).
- A lab supervisor may approve a result they entered themselves: small centers often have one
  supervisor on a shift. Each version records who entered and who approved it.

## Consequences
- The approve button works only on the version the supervisor sees; a concurrent edit makes
  the supervisor reload and read again.
- A lab bench needs a cashier supervisor or accountant on hand to cancel a paid test, as the
  cashier's desk does for over-limit discounts.

## Code
`apps/lab/services.py` (`approve_results`, `result_revision`, `cannot_perform`,
`reject_sample`, `turnaround_report`), `apps/lab/bench.py`, `apps/lab/queries.py`,
`apps/lab/api.py`, `domain/lab.py` (`stage`, `turnaround_stats`), tests in
`apps/lab/tests/test_bench.py` and `test_api.py`.
