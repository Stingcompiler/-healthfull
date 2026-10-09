# 0010: The nursing desk and minimal inpatient

Date: 2026-10-09. Status: accepted.

## Context
FEATURES 10.1-10.3 and 10.5 (with 3.4 for nurses) give nurses a procedure work list with a
one-tap "done", vitals and nursing notes, and a minimal inpatient flow: admit, beds, daily bed
charge, discharge. FLOW step 7 calls the done mark the hardest record of the cycle because it
gives the nurse nothing back, so it must take seconds. The Phase 1 services already held the
rules (`orders.worklist`, `perform_line`, `visits.admit/transfer_bed/charge_bed_days/
discharge`, `clinical.record_vitals/add_nursing_note`); this ADR records the choices the
screens added on top.

## Decisions
- **One tap, undone in the browser.** A performed line is terminal (ARCHITECTURE 4.4 rule 6),
  so "undo" cannot be a server action. The desk waits five seconds after the tap before it
  sends `POST /api/orders/procedures/{id}/done`; "Undo" in that window sends nothing, "Save
  now" sends at once. Leaving the screen sends what is still waiting (the tap was meant);
  closing the tab inside the window asks the browser to confirm. Two nurses tapping one line
  perform it once: the line is locked, the second gets `LINE_ALREADY_PERFORMED`, which the
  desk shows as information, not as a failure.
- **Only procedures here.** `perform_procedure` refuses other kinds (`LINE_NOT_PROCEDURE`):
  lab results and dispensing perform their lines in their own modules with their own steps.
  Eligibility stays invariant 1's (settled, or an unrevoked perform-first authorization).
- **Nurses may admit by default** (`visits.admit` gains `nurse`). In a small center the ward
  nurse records the admission on the doctor's decision; the admitting doctor is a required
  field. Admission from the board opens a new `inpatient` visit (no consultation fee, no
  queue token) in the ward's department, or uses an open visit of the patient (the
  consultation that decided it). The patient is locked first, so a refused admission leaves
  no visit behind; two admissions or two transfers into one bed serialize on the bed row
  and the loser gets `BED_NOT_AVAILABLE`.
- **Bed nights are posted by a run, not by reading.** `charge_due_bed_nights` charges every
  open admission's passed nights (idempotent, one transaction per admission). It runs from
  the bed board ("Post due nights", `visits.manage_beds`, the count of nights due is on the
  button) and from `manage.py charge_bed_nights --as <user>` for a scheduler. Discharge
  charges the rest (at least one day). The board never writes on GET.
- **Free beds only change status.** `set_bed_status` moves a bed between available and out of
  service; an occupied bed refuses (`BED_OCCUPIED`). No reason is recorded (it is not a
  cancellation, discount, refund or override).
- **Nursing notes on closed visits.** A note may be written after discharge closed the visit;
  a cancelled visit refuses it (`VISIT_CANCELLED`). Vitals keep needing an open visit.
- **No prices on the nursing screens.** The procedure list, chart and board carry no money;
  nights are counts.

## Consequences
- The undo window is client timing only: a lost connection inside it loses the tap, as any
  unsent form would; the card then still shows "Done".
- Until a scheduler runs `charge_bed_nights`, nights reach the cashier when a nurse posts them
  or at discharge. Wiring the command into the compose `maintenance` loop needs a configured
  acting user (follow-up).
- An admission made in error has no cancel action yet (`AdmissionStatus.CANCELLED` exists
  but needs reason fields): discharge it and credit the night at the cashier (follow-up).

## Code
`apps/orders/services.py` (`procedure_worklist`, `procedures_done`, `perform_procedure`),
`apps/orders/procedures.py`, `procedures_api.py`; `apps/clinical/nursing.py`,
`nursing_api.py`; `apps/visits/services.py` (`admit_patient`, `bed_board`, `set_bed_status`,
`charge_due_bed_nights`), `inpatient_api.py`, `inpatient_schemas.py`,
`management/commands/charge_bed_nights.py`; `frontend/src/features/nursing/`.
