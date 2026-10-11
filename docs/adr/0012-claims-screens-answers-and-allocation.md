# 0012: Claim answers, rejection approvals and payer payment allocation on the claim screens

Date: 2026-10-09. Status: accepted; rebill and write-off approval amended by ADR 0018.

## Context
Phase 1 built the claims engine (`apps/claims/services.py`, `domain/claims.py`, ADR 0006 (b),
(c), (d)). The claim screens (FEATURES 11.2-11.7) need a few rules the engine left to its
callers: how the accountant enters a payer's answer per line, how a remittance advice that
pays per claim batch becomes claim-line allocations, who approves a rebill or a write-off,
and what "the payer's format" of an exported claim is.

## Decision
- **Answers per line.** The screen answers a line `accepted`, `rejected` or `partial`.
  `domain.claims.response_amount` turns that into the accepted amount the engine records:
  all of the claimed amount, nothing, or the part entered, which must be strictly between
  zero and the claimed amount (`CLAIM_PARTIAL_INVALID`). A rejected part needs the payer's
  reason (`REASON_REQUIRED`, unchanged). An amount sent with a whole answer is ignored.
- **Allocation per claim.** A payer payment is allocated by claim line (`lines`), by claim
  (`claims`: amount per claim batch, as remittance advices list them), or, with neither, to
  the oldest accepted amounts first. `domain.claims.allocate_to_claims` spreads each claim's
  amount over that claim's own accepted, unpaid lines in line order, never beyond a line's
  due and never onto another claim; a claim with nothing payable is refused
  (`CLAIM_NOTHING_UNPAID`), more than it owes too (`CLAIM_PAYMENT_EXCEEDS_ACCEPTED`). The
  spread runs inside `record_payer_payment` under the payer and line locks, and the usual
  balance check still applies (`PAYER_PAYMENT_UNBALANCED`). Lines and claims together are
  refused (`PAYER_ALLOCATION_CONFLICT`).
- **Rebill and write-off approval.** The approver of a rebill, a write-off of a rejection or
  of a short-paid accepted amount is the user who records it, who must hold
  `claims.resolve_rejection` (accountant, manager, admin). The reason code (`writeoff` list)
  is mandatory, a note when the reason asks for one; approver, reason and time are stored on
  the claim line (invariant 4). No second person is required, unlike refunds (ADR 0006 (e)):
  no money leaves the center, the receivable moves to the patient or to `WRITE_OFF`.
  **Amended by ADR 0018:** a second person now approves by default
  (`Policy.claims_second_approver`); this paragraph describes the switch turned off.
- **Payer cash.** Cash from a payer goes into the recorder's own open shift (ADR 0006 (d)).
  The screen offers cash only when the viewer has an open shift (`/api/claims/options`
  returns it); an accountant without a till records transfers and cheques.
- **The payer's format.** One layout for every payer: the center header, the payer (name,
  contract, address), the claim number and period, one row per claimed service (patient,
  file and card number, invoice and date, service code and name, quantity, gross,
  pre-approval reference, claimed amount; after the answer, accepted, rejected and the
  payer's reason) and the totals. Excel in Arabic (right-to-left sheet) or English, and an
  A4 print view. Per-payer templates are not built.
- **Access.** Every `/api/claims` operation requires a `claims.*` code. Cashiers, cashier
  supervisors, doctors, nurses, pharmacists, lab staff and receptionists hold none
  (`apps/claims/tests/test_permission_sweep.py`); managers read claims and may resolve
  rejections, as the permission defaults already said.

## Consequences
- The engine services are unchanged except `record_payer_payment(claim_amounts=...)`.
- A payer that wants its own column order or codes needs a per-payer export template later.
- Code: `domain/claims.py` (`response_amount`, `allocate_to_claims`), `apps/claims/desk.py`,
  `apps/claims/queries.py`, `apps/claims/export.py`, `apps/claims/api.py`.
