# hospital-sys: rules for coding agents

Medical center management system for Sudan: local-LAN web app, Django 5.2 + django-ninja backend, React + TypeScript frontend, PostgreSQL 16.

Read before any work, in order:
1. `docs/ARCHITECTURE.md`: layout, layering, money, ledger, states, API and UI conventions. Binding.
2. `docs/FLOW.md`: the business cycle and the seven invariants.
3. `docs/FEATURES.md`: what to build, by phase tag.
4. `PROGRESS.md`: what is done, what is next.

## The seven invariants (never break, never weaken a test that guards them)
1. No service is performed without an invoiced-and-settled line or a documented perform-first authorization.
2. An approved invoice never changes. Corrections are credit notes linked to the original.
3. A closed shift never changes. Later effects post to the current shift, linked to the original.
4. Every cancellation, discount, refund, transfer confirmation, and override records reason, approver, and time.
5. Stock decrements at dispense, never at invoicing. Stock never goes negative.
6. A line's price is frozen at invoice approval from the price list effective that day.
7. Payer share is a receivable, never cash, until a payer payment is recorded.

## Working rules
- Money: `Decimal` via `domain.money`, never float. Splits derive one side by subtraction.
- Logic lives in `backend/domain` (pure, Hypothesis-tested) and `apps/*/services.py`. Routers and React components hold no business rules.
- Test first for anything touching invoices, payments, shifts, stock, claims, or the ledger.
- UI: semantic color tokens only, logical direction utilities only (`ms-/me-/ps-/pe-/start-/end-`), every string through i18next with ar and en keys in parity.
- Every screen must pass the responsive e2e check at 375, 768, and 1280 widths with no horizontal scroll.
- No runtime internet dependency of any kind.
- Never hardcode DB names or ports; see ARCHITECTURE section 3.
- Run `make check` before declaring work done. Report real results; never claim a test passed without running it.
- Ship with the `ship-feature` skill: build, test, review, fix, push, PR, merge.
