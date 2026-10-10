# 0018: Second-person approvals: admissions made in error and paid dispense returns

Date: 2026-10-10. Status: accepted.

## Context
Three Phase 8 follow-ups need a decision taken by two people on the spot, with the reason,
both names and the time recorded (invariant 4):

- An admission made in error (wrong patient, never admitted, recorded twice) had no action:
  `AdmissionStatus.CANCELLED` existed without reason, approver or time columns (ADR 0011),
  so the nurse discharged and the cashier credited the night.
- Dispense returns (`pharmacy.return_dispense`) had no endpoint or screen, and returning
  units of a paid line needed only the pharmacist's word although their money is refunded.
- Claims rebills and write-offs (FEATURES 11.5 "with approval") were approved by the
  recording user alone (ADR 0012); see the claims section below.

ADR 0009 already lets a supervisor approve at someone else's desk by typing their own
username and password (`apps.payments.approvals`), checked through the one credential door
of ADR 0005. There, the actor's own credentials mean "no separate approver". These actions
need the opposite: someone other than the actor must decide.

## Decisions

**The second-person rule.** `domain.audit.second_approval(actor_id, approver_id, ...)` builds
the `Approval` of a second person and refuses a missing approver or the actor
(`SECOND_APPROVER_REQUIRED`, 409). `apps.payments.approvals.resolve_second_approver` resolves
the typed credentials exactly as ADR 0009 does (lockout, throttle, audit, `APPROVER_INVALID`
never 401) and then checks the approver's own permission (`APPROVER_NOT_PERMITTED`, 409 with
the permission code, never a 403 that would read as the actor's own lack of access). The
screens use one shared field set (`components/SecondApproverFields.tsx`).

**Admission made in error** (`visits.cancel_admission`: nurse, manager, admin; approver needs
`visits.approve_admission_cancel`: cashier supervisor, manager, admin).
- Only an open admission. A reason of the new `admission_cancel` category (`WRONG_PATIENT`,
  `NOT_ADMITTED`, `DUPLICATE_ADMISSION`, `OTHER` with a note; core migration 0012) and an
  optional note. `Admission` gains `cancelled_at`, `cancelled_by`, `cancel_approved_by`,
  `cancel_reason`, `cancel_note`; a check constraint requires all of them on a cancelled
  admission and an approver other than the canceller.
- The bed is freed and the stay ends. Bed nights still unbilled are voided (they leave draft
  invoices); a night on an approved invoice and not credited blocks the cancellation
  (`ADMISSION_NIGHTS_INVOICED`, with the count): the invoice is frozen (invariant 2), so the
  nurse is sent to the cashier, who credits the night, and the cancellation is done after.
  Credited nights stay as they are. The board shows the invoiced count (no prices).
- The stay's perform-first authorization is revoked. An inpatient visit opened for the
  admission is cancelled (`REGISTRATION_ERROR`) when nothing else on it is still standing,
  else closed; an outpatient visit the admission was made on is left as it was.
- **The one exception to "performed is terminal"** (ARCHITECTURE 4.4 rule 6). Bed nights are
  recorded performed under the stay's authorization when they are charged (invariant 1's
  documented exception). A night of an admission made in error was never given, so
  `domain.service_line.void_in_error` takes an unbilled, authorized, performed line to
  cancelled with a reason and the second person's approval; every other status is refused
  (`CREDIT_NOTE_REQUIRED` for billed lines, `LINE_NOT_VOIDABLE`, `LINE_ALREADY_CANCELLED`).
  The `line_guard` trigger allows exactly this edge and only for a `bed_charge` line whose
  admission is already cancelled; every other change of a performed line still raises
  `LINE_TERMINAL` (tested). Nothing billed changes: no invoice, credit note, shift or ledger
  row is touched (invariants 2, 3, 6, 7).

**Dispense returns** (`pharmacy.dispense` for the pharmacist; approver needs
`pharmacy.approve_return`: cashier supervisor, manager, admin).
- `GET /api/pharmacy/returns` lists recent dispenses (30 days, or any by dispense or visit
  number, file number or name) with what was given, returned and still returnable per line;
  `POST /api/pharmacy/dispense-lines/{id}/returns` puts units back. The stock move goes
  through the stock engine into the batch and store the units left (`return` move, row
  locks, `domain.stock.return_move`, invariant 5); at most dispensed less returned.
- A reason is required (`stock_adjust`; core migration 0013 adds `PATIENT_RETURNED` and
  `DISPENSED_IN_ERROR`). Units of a billed line (invoiced, paid or credited) need a second
  person (`domain.stock.return_approval`), recorded in `DispenseReturn.approved_by` (a check
  constraint refuses the returner as approver); units given under a perform-first
  authorization and never billed come back on the pharmacist's reason.
- A return never moves money. The refund of paid units stays with the cashier's credit note
  and refund (ADR 0008, 0009); the return may name the approved credit note that credits the
  line, and the screen links to the cashier desk for the visit.

## Consequences
- A nurse on a night shift needs a cashier supervisor or manager on hand (or reachable) to
  cancel an admission made in error, as the lab bench does for a billed test (ADR 0010).
- An admission discharged before the error is noticed is corrected at the cashier only
  (credit the nights); the cancel action covers open admissions.
- The performed-terminal exception is narrow by construction (unbilled, bed charge, cancelled
  admission); widening it needs a new ADR.

## Code
`domain/audit.py` (`second_approval`), `domain/service_line.py` (`void_in_error`),
`domain/inpatient.py`, `domain/stock.py` (`return_approval`), `apps/payments/approvals.py`,
`apps/visits/services.py` (`cancel_admission`, `cancel_admission_at_desk`),
`apps/visits/inpatient_api.py`, `apps/orders/services.py` (`void_line_in_error`,
`end_stay_authorization`), `apps/orders/models.py` (`line_guard`), `apps/pharmacy/services.py`
(`return_dispense`), `apps/pharmacy/queries.py`, `apps/pharmacy/api.py`; frontend
`features/nursing/components/CancelAdmissionDialog.tsx`, `features/pharmacy/pages/ReturnsPage.tsx`.
