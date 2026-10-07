"""Pure business rules for hospital-sys.

Nothing in this package may import Django (enforced by ``domain/tests/test_purity.py``).
Functions take and return plain values (Decimal, datetime, dataclasses, enums) and
signal rule violations by raising :class:`domain.errors.DomainError`.

Modules (ARCHITECTURE section 4; FLOW invariants in brackets):

* ``money``: Decimal money, rounding, exact splits.
* ``audit``: :class:`~domain.audit.Approval` (approver, time, reason) [4].
* ``service_line``: billing/fulfilment statuses, derived state, work-list rule, every
  transition [1].
* ``pricing``: effective price-list version for a date, bulk percentage update [6].
* ``coverage``: payer/patient split per line, discounts and role limits, pre-approval [7].
* ``invoice``: frozen lines, totals, credit lines, the invoice position (what is due, paid,
  outstanding and settled per line) [2].
* ``allocation``: allocating payments, reversals, de-allocation, credit spending, refunds.
* ``payments``: methods, transfer verification, duplicate references.
* ``shift``: expected cash, variance, close, late effects [3].
* ``ledger``: fixed chart of accounts and balanced posting builders [7].
* ``stock``: units, FEFO, stock moves, counts, adjustments [5].
* ``claims``: payer claim lines, responses, payer payments, rebill and write-off [7].
* ``lab``: reference ranges, flags, result versions.
* ``lockout``, ``throttle``, ``numbering``, ``permissions``: Phase 0 platform rules.
"""
