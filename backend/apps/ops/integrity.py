"""Read-only integrity check of the books and the stock (``manage.py integrity_check``).

Used by the restore drill (``infra/backup/restore-drill.sh``), after an update or a restore,
and whenever an operator doubts the data (docs/runbooks/operations.md). Every check reads two
views of the same thing and reports where they differ (``domain.integrity``):

* ``ledger_balanced``: the trial balance totals zero and every journal entry has two lines or
  more with equal debits and credits (ARCHITECTURE 4.7).
* ``invoice_positions``: per approved invoice, the AR_PATIENT balance equals the patient
  position derived from its documents (frozen lines, approved credit notes, rebills and
  every allocation row); no AR_PATIENT balance sits on an invoice that is not approved.
* ``payer_receivables``: per payer, the AR_PAYER balance equals the receivable derived from
  accrued lines, claims, answers and payer payments (invariant 7).
* ``shift_cash``: an open shift's CASH equals its expected cash; a closed shift's CASH is zero.
* ``stock``: no stock balance below zero, and every balance equals the sum of its stock moves
  (invariant 5).
* ``allocations``: no orphan allocations. Each allocation row has exactly one ALLOCATION
  journal entry and each such entry an allocation; allocations are on approved invoices; a
  payment never has more allocated than its amount, nor less than zero; a reversal row names
  an allocation of the same payment and invoice.

All checks run in one REPEATABLE READ, READ ONLY transaction: one consistent snapshot while
the application keeps working, and nothing can be written. The app role (DML only) may run it.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from django.db import connection, transaction
from django.db.models import Count, F, Q, Sum

from apps.billing import services as billing
from apps.billing.models import DocumentStatus, Invoice
from apps.claims import services as claims
from apps.ledger import services as ledger
from apps.ledger.models import JournalEntry, JournalLine, SourceType
from apps.payments import services as payments
from apps.payments.models import Allocation, AllocationKind, Payment, Shift, ShiftStatus
from apps.pharmacy.models import StockBalance, StockMove
from domain.integrity import CheckResult, all_ok, compare_amounts
from domain.money import ZERO

__all__ = ["CHECKS", "IntegrityReport", "run"]

#: Invoices read per batch for their positions (4 queries per batch).
_INVOICE_BATCH = 500


def _debit_minus_credit(code: str, by: str) -> dict[Any, Decimal]:
    rows = (
        JournalLine.objects.filter(account__code=code)
        .values(by)
        .annotate(d=Sum("debit"), c=Sum("credit"))
        .values_list(by, "d", "c")
    )
    return {key: (d or ZERO) - (c or ZERO) for key, d, c in rows}


def check_ledger_balanced() -> CheckResult:
    result = CheckResult("ledger_balanced")
    tb = ledger.trial_balance()
    result.checked = len(tb.rows)
    if not tb.balanced:
        result.add(
            f"trial balance: debits {tb.total_debit} and credits {tb.total_credit}"
            f" differ by {tb.total}"
        )
    bad = (
        JournalEntry.objects.annotate(
            n=Count("lines"), d=Sum("lines__debit"), c=Sum("lines__credit")
        )
        .filter(Q(n__lt=2) | ~Q(d=F("c")))
        .order_by("id")
        .values_list("id", "n", "d", "c")
    )
    for entry_id, n, d, c in bad:
        result.add(f"journal entry {entry_id}: {n} line(s), debits {d}, credits {c}")
    return result


def check_invoice_positions() -> CheckResult:
    result = CheckResult("invoice_positions")
    ledger_ar = _debit_minus_credit("AR_PATIENT", "invoice_id")
    expected: dict[Any, Decimal] = {}
    invoices = Invoice.objects.filter(status=DocumentStatus.APPROVED).order_by("id")
    ids = list(invoices.values_list("id", flat=True))
    for start in range(0, len(ids), _INVOICE_BATCH):
        batch = list(Invoice.objects.filter(id__in=ids[start : start + _INVOICE_BATCH]))
        for invoice_id, pos in billing.invoice_positions(batch).items():
            expected[invoice_id] = pos.patient_due - pos.allocated
    result.checked = len(ids)
    for m in compare_amounts(expected, ledger_ar):
        what = "no invoice" if m.key is None else f"invoice {m.key}"
        result.add(
            f"{what}: documents say the patient owes {m.expected}, AR_PATIENT has {m.actual}"
        )
    return result


def check_payer_receivables() -> CheckResult:
    result = CheckResult("payer_receivables")
    found = claims.payer_receivables()
    expected = {pid: r.receivable for pid, r in found.items()}
    actual = _debit_minus_credit("AR_PAYER", "payer_id")
    result.checked = len(set(expected) | set(actual))
    for m in compare_amounts(expected, actual):
        result.add(
            f"payer {m.key}: claims documents say {m.expected} is receivable, AR_PAYER has"
            f" {m.actual}"
        )
    return result


def check_shift_cash() -> CheckResult:
    result = CheckResult("shift_cash")
    actual = _debit_minus_credit("CASH", "shift_id")
    expected: dict[Any, Decimal] = {}
    shifts = list(Shift.objects.order_by("id"))
    for shift in shifts:
        expected[shift.pk] = (
            payments.expected_cash(shift) if shift.status == ShiftStatus.OPEN else ZERO
        )
    result.checked = len(shifts)
    for m in compare_amounts(expected, actual):
        what = "no shift" if m.key is None else f"shift {m.key}"
        result.add(f"{what}: expected cash {m.expected}, CASH has {m.actual}")
    return result


def check_stock() -> CheckResult:
    result = CheckResult("stock")
    for row in StockBalance.objects.filter(qty_base__lt=0).values_list(
        "item_id", "batch_id", "store_id", "qty_base"
    ):
        result.add(f"item {row[0]} batch {row[1]} store {row[2]}: negative stock {row[3]}")
    moves = {
        (batch, store): Decimal(total or 0)
        for batch, store, total in StockMove.objects.values("batch_id", "store_id")
        .annotate(t=Sum("qty_base"))
        .values_list("batch_id", "store_id", "t")
    }
    balances = {
        (batch, store): Decimal(qty)
        for batch, store, qty in StockBalance.objects.values_list(
            "batch_id", "store_id", "qty_base"
        )
    }
    result.checked = len(set(moves) | set(balances))
    for m in compare_amounts(moves, balances):
        batch, store = m.key
        result.add(
            f"batch {batch} store {store}: stock moves add up to {m.expected},"
            f" the balance says {m.actual}"
        )
    return result


def check_allocations() -> CheckResult:
    result = CheckResult("allocations")
    result.checked = Allocation.objects.count()
    entries: dict[int, int] = defaultdict(int)
    for source_id, n in (
        JournalEntry.objects.filter(source_type=SourceType.ALLOCATION)
        .values("source_id")
        .annotate(n=Count("id"))
        .values_list("source_id", "n")
    ):
        entries[source_id] = n
    allocation_ids = set(Allocation.objects.values_list("id", flat=True))
    for pk in sorted(allocation_ids):
        if entries.get(pk, 0) != 1:
            result.add(f"allocation {pk}: {entries.get(pk, 0)} ledger entries (want 1)")
    for source_id in sorted(set(entries) - allocation_ids):
        result.add(f"ledger allocation entry for allocation {source_id}, which does not exist")
    for pk, invoice_id, status in (
        Allocation.objects.exclude(invoice__status=DocumentStatus.APPROVED)
        .order_by("id")
        .values_list("id", "invoice_id", "invoice__status")
    ):
        result.add(f"allocation {pk}: invoice {invoice_id} is {status}, not approved")
    over = (
        Payment.objects.annotate(allocated=Sum("allocations__amount"))
        .filter(Q(allocated__gt=F("amount"), amount__gt=0) | Q(allocated__lt=0))
        .order_by("id")
        .values_list("id", "amount", "allocated")
    )
    for pk, amount, allocated in over:
        result.add(f"payment {pk}: amount {amount}, allocated {allocated}")
    reversals = (
        Allocation.objects.filter(kind=AllocationKind.REVERSAL)
        .exclude(
            reversal_of__payment_id=F("payment_id"),
            reversal_of__invoice_id=F("invoice_id"),
            reversal_of__kind=AllocationKind.ALLOCATE,
        )
        .order_by("id")
        .values_list("id", "reversal_of_id")
    )
    for pk, original in reversals:
        result.add(f"allocation {pk}: reverses {original}, not an allocation of its payment")
    return result


CHECKS: dict[str, Callable[[], CheckResult]] = {
    "ledger_balanced": check_ledger_balanced,
    "invoice_positions": check_invoice_positions,
    "payer_receivables": check_payer_receivables,
    "shift_cash": check_shift_cash,
    "stock": check_stock,
    "allocations": check_allocations,
}


@dataclass(frozen=True, slots=True)
class IntegrityReport:
    database: str
    results: tuple[CheckResult, ...]

    @property
    def ok(self) -> bool:
        return all_ok(self.results)

    def to_json(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "database": self.database,
            "checks": {
                r.name: {
                    "ok": r.ok,
                    "checked": r.checked,
                    "problems": r.count,
                    "examples": r.problems,
                }
                for r in self.results
            },
        }


def run(only: list[str] | None = None) -> IntegrityReport:
    """Run the named checks (all by default) on one read-only snapshot."""
    names = only or list(CHECKS)
    unknown = sorted(set(names) - set(CHECKS))
    if unknown:
        raise ValueError(f"unknown checks: {', '.join(unknown)}")
    outermost = not connection.in_atomic_block
    with transaction.atomic():
        if outermost:  # inside a caller's transaction (tests) the snapshot is the caller's
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        results = tuple(CHECKS[name]() for name in names)
    return IntegrityReport(database=str(connection.settings_dict["NAME"]), results=results)
