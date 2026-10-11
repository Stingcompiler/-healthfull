# 0022: One approver field set for every desk approval; approval errors are 409

Date: 2026-10-11. Status: accepted.

## Context
Desk approvals (ADR 0009) and second-person approvals (ADR 0018) had four looks: the cashier's
`ApproverFields` (switch «يعتمد المشرف»), the pharmacy's `ApproverInputs` (switch «يعتمد المشرف
الآن», plain state), the lab cancel dialog's own fieldset («اعتماد مالي», «المعتمد» without its
kasra) and the shared `SecondApproverFields` (always shown). A pharmacist receiving a short
transfer without an approver got a bare `PERMISSION_DENIED`, which reads as their own lack of
access rather than "a manager must approve this".

## Decision
- `components/SecondApproverFields.tsx` is the only approver UI: `SecondApproverFields`
  (react-hook-form) and `ApproverFieldset` (plain state), same look and words
  (`common:approver.*`, «اعتماد شخص آخر», «اسم مستخدم المعتمِد»). Two shapes:
  - required (a second person must approve: admission in error, paid return, claims rebill and
    write-off): the fields always show;
  - optional (the actor's own permission may be enough: cashier discount above the limit,
    duplicate transfer reference, partial-dispense refund, short transfer receipt): a switch
    «يعتمد شخص آخر الآن» shows them; the lab cancel shows them always but required only when the
    actor may not approve the credit.
- The flows that use it: cashier discount and duplicate reference, lab cancel, pharmacy
  dispense remainder, returns and short transfer receipts, claims rebill/write-off/shortfall,
  admission cancel.
- Not desk approvals, unchanged (ADR 0009): refund approval, credit note approval, transfer
  confirmation and perform-first authorization are decided by the approver in their own session
  from the queues at `/cashier/refunds`, `/cashier/credit-notes`, `/cashier/transfers` and
  `/cashier/perform-first`. Stock adjustments are approved by the manager in their own session.
- A short transfer receipt without an approver, by an actor who may not approve adjustments,
  answers `SECOND_APPROVER_REQUIRED` (409, `permission`), and a typed approver without the
  permission `APPROVER_NOT_PERMITTED` (409), as ADR 0018 does; never a 403.

## Consequences
- One place to change the approver UI; e2e specs select the fields by the common labels.
- The two pharmacy tests that expected 403 now expect the 409 codes (the action is still
  refused; only the answer is specific).

## Code
`frontend/src/components/SecondApproverFields.tsx`, `frontend/src/lib/approver.ts`,
`backend/apps/pharmacy/services.py` (`receive_transfer`), tests
`apps/pharmacy/tests/test_api.py`, `apps/pharmacy/tests/test_review_fixes.py`.
