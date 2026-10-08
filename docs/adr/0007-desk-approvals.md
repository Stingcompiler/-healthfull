# 0007: Supervisor approvals at the cashier's desk

Date: 2026-10-08. Status: accepted.

## Context
Two cashier actions need a second person on the spot: a discount above the cashier's role
limit (FEATURES 5.9) and a transfer reference already used for the bank (FEATURES 6.2). The
money of both still belongs to the cashier's own open shift (ARCHITECTURE 4.6), so the
supervisor cannot simply take the action from their own session: a payment taken there would
land in the supervisor's shift, or fail with `SHIFT_NOT_OPEN`. Invariant 4 needs the approver,
the reason and the time recorded on the row.

## Decision
- The cashier's dialog has optional approver fields (username and password). The request
  carries them as `approver: {username, password}` (`DiscountIn.approver`,
  `PaymentIn.override.approver`). `apps.payments.approvals.resolve_approver` checks them
  through the one credential door of ADR 0005 (`authenticate_credentials`): lockout, the
  per-address throttle and the auth audit apply exactly as at login.
- A wrong or unknown username, an inactive account or a pending password change answers
  `APPROVER_INVALID` (409), never 401, which would end the cashier's own session. A locked
  account keeps `ACCOUNT_LOCKED` (423) and the throttle `RATE_LIMITED` (429).
- The approver's own permissions decide: `payments.override_duplicate` for a duplicate
  reference (`OVERRIDE_NOT_PERMITTED` otherwise), the approver's role discount limit for a
  discount (`DISCOUNT_LIMIT_EXCEEDED` otherwise). The engine services record the approver on
  the row (`Payment.override_by`, `InvoiceLine.discount_approved_by`) with the reason.
- The actor's own credentials, or no credentials, mean no separate approver: the actor's own
  permissions and limits apply (a supervisor working the desk approves their own discount).
- No session is created for the approver, and the password is never stored or logged.

- Approving a credit note that releases patient money opens the refund request in the
  approver's own name, not the note's creator's: the approver is the person who decided the
  money goes back, so invariant 4 records them. `payments.approve_refund` refuses
  `SELF_APPROVAL_NOT_ALLOWED` to the requester, so a second person (another supervisor or an
  accountant) approves the refund, and one person never decides both the credit and the cash
  leaving the drawer.

## Consequences
- A supervisor approves without the cashier signing out, and the money stays in the right
  drawer.
- Failed approver attempts count toward the approver's lockout like failed logins, so the
  dialog cannot be used to guess a supervisor's password.
- Refund approval, transfer confirmation and credit note approval are not desk approvals:
  they are done later by the supervisor in their own session (queues at `/cashier/transfers`
  and `/cashier/refunds`), because they move no cash at the desk.

## Code
`apps/payments/approvals.py`, `apps/billing/desk.py` (`discount_line`, `discount_invoice`),
`apps/payments/desk.py` (`take_payment`), tests in `apps/payments/tests/test_approvals.py`,
`apps/billing/tests/test_api.py`, `apps/payments/tests/test_api.py`.
