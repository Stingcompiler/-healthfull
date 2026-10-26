# 0025: The accountant gives no discounts

Date: 2026-10-26. Status: accepted (owner decision on inspection finding F11).

## Context
The default roles gave the accountant `billing.apply_discount` but neither
`billing.create_invoice` nor `billing.override_discount_limit`. A discount is given on a draft
invoice at the cashier's desk, before approval (ARCHITECTURE 4.5); the accountant drafts no
invoice, approves none and cannot approve a desk discount above the limit. The code therefore
only let the accountant change drafts that cashiers had prepared, which is no task of the role
(the role table at the end of FEATURES.md: confirm transfers, approve refunds and credit
notes, review shifts, run claims; "discounts above limit" there is the cashier supervisor's,
the accountant never held `billing.override_discount_limit`). Found in the phase 8 docs review (PROGRESS follow-ups) and the
October 2026 inspection (`docs/inspection/REPORT-2026-10.md`, F11).

## Decision
- `billing.apply_discount` defaults to cashier, cashier supervisor, manager and admin. The
  accountant keeps `billing.view`, `billing.create_credit_note` and
  `billing.approve_credit_note`: corrections after approval stay with them.
- No permission is granted to anyone in exchange. A center that wants its accountant to give
  discounts grants the code in the roles matrix (`/administration/roles`), which records the
  change in the audit trail.
- `Policy.discount_limits` keeps its `accountant` entry: it only matters if a center grants the
  code back.

## Consequences
- Existing installs: defaults live in code, so the accountant loses the code at the update
  unless a `RolePermission` override row grants it.
- The cashier screen hides the discount actions for an accountant (`usePermission`), and the
  API answers 403 `PERMISSION_DENIED` (`billing/tests/test_api.py::test_accountant_gives_no_discounts`).
- The accountant guide says so (`docs/guides/accountant.md`).
