# 0007: Who may read and write a visit's clinical record

Date: 2026-10-08. Status: accepted.

## Context
The clinic module (FEATURES 2.3, 3.1-3.9) lets a doctor work a queue and a visit workspace.
The wave a review asked two questions the documents left open: which roles may read a visit's
orders (they carry prescriptions, approved results and allergy override reasons), and whether
writes to a visit (notes, diagnoses, vitals, orders, referrals) are limited to the visit's own
doctor, as queue actions are.

## Decisions

### (a) A visit's orders are part of the clinical record
- Decision: `GET /api/orders/visits/{id}/lines` needs `clinical.view` (doctor, nurse, admin by
  default), like the workspace, summary, history and results. `orders.view` no longer opens it.
- Why: the doctor's line view inlines approved result values, full prescriptions and the
  reasons (with the prescriber) for overriding an allergy. Reception, cashiers, pharmacists
  and lab staff see the lines they work on through their own modules (work lists, invoices,
  dispensing), each with a schema shaped for that role.
- Consequences: a module that needs order status for a non-clinical role builds its own
  status-only schema; it never reuses `DoctorLineOut`.

### (b) The queue is per doctor; the visit record is shared by the clinical team
- Decision: queue actions (call, start, complete, no-show, requeue) stay limited to the entry's
  doctor, or to a doctor of the entry's department while it is unassigned. Calling or starting
  an unassigned entry claims it (and its visit, when the visit has no doctor) under the entry's
  row lock, so a second doctor gets `QUEUE_OTHER_DOCTOR`. Writing to an open visit's clinical
  record (notes, diagnoses, vitals, allergies, conditions, orders, referrals) is allowed to any
  holder of the matching permission, whichever department they belong to.
- Why: in a small center the same patient is often seen by a covering doctor, a consultant
  asked for an opinion, or a nurse taking vitals; refusing them would push work onto paper.
  Every write records its author and time (pghistory context plus the author columns), notes
  are edited only by their author and frozen when signed, and diagnoses are removed only by
  whoever recorded them. Queue ownership, by contrast, decides who performs and is credited
  with the consultation fee, so it must be exclusive.
- Consequences: limiting writes to the visit's doctor, department or referral targets would be
  a new rule enforced in `apps/clinical/services.py` (`place_orders`, `save_note`,
  `add_diagnosis`, `record_vitals`) with its own tests, and recorded in a later ADR.

## Addendum (second clinic review, 2026-10-08)
- Withdrawing an order (`POST /api/orders/lines/{id}/withdraw`) answers with `DoctorLineOut`, so
  it needs `clinical.view` besides `orders.cancel_line` (checked in
  `orders.services.withdraw_order`). Cashiers, pharmacists and lab staff cancel lines through
  their own modules. The doctor withdraws only what `can_withdraw` shows: unbilled, not started
  and nothing given (409 `LINE_IN_PROGRESS` otherwise).
- Completing a consultation from the clinic queue needs `visits.finish_consultation`, as
  finishing from the visits board does.
- A referral is cancelled only by the doctor who wrote it, on an open visit, with a reason;
  reason, canceller and time are stored on the row (invariant 4). This follows the rule that
  diagnoses are removed only by whoever recorded them.
- Removing a diagnosis and marking an allergy or chronic condition entered in error need a
  stated reason, kept with the actor and time in the audit history context.
