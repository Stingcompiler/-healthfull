"""Ledger services: store balanced journal drafts and read balances (ARCHITECTURE 4.7).

The posting rules live in ``domain.ledger`` (one builder per money event). Services build a
:class:`~domain.ledger.JournalDraft` with those builders and hand it to :func:`post`, which
is the only writer of ``JournalEntry`` / ``JournalLine``. The database refuses unbalanced
entries at commit and any UPDATE/DELETE, so a posting is never edited: a correction is a new
entry.

Dimension mapping: ``shift``, ``patient``, ``invoice``, ``payer`` and ``department`` become the
foreign keys of ``JournalLine``; ``service_kind`` is stored as text. Department ``0`` is the
domain's stand-in for "no department" (a service without one) and is stored as NULL.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from apps.core.models import User
from apps.ledger.models import Account, JournalEntry, JournalLine
from apps.ledger.models import SourceType as DbSourceType
from domain import ledger as dl
from domain.errors import DomainError
from domain.money import ZERO

#: Domain source types to the stored ``JournalEntry.source_type`` values.
SOURCE_TYPES: dict[dl.SourceType, str] = {
    dl.SourceType.INVOICE: DbSourceType.INVOICE,
    dl.SourceType.CREDIT_NOTE: DbSourceType.CREDIT_NOTE,
    dl.SourceType.PAYMENT: DbSourceType.PAYMENT,
    dl.SourceType.ALLOCATION: DbSourceType.ALLOCATION,
    dl.SourceType.TRANSFER_CONFIRMATION: DbSourceType.TRANSFER_CONFIRM,
    dl.SourceType.TRANSFER_REJECTION: DbSourceType.TRANSFER_REJECT,
    dl.SourceType.REFUND: DbSourceType.REFUND,
    dl.SourceType.SHIFT_VARIANCE: DbSourceType.SHIFT_CLOSE,
    dl.SourceType.PAYER_REBILL: DbSourceType.CLAIM_REBILL,
    dl.SourceType.PAYER_WRITE_OFF: DbSourceType.CLAIM_WRITEOFF,
    dl.SourceType.PAYER_SHORT_WRITE_OFF: DbSourceType.CLAIM_SHORT_WRITEOFF,
    dl.SourceType.PAYER_PAYMENT: DbSourceType.PAYER_PAYMENT,
    dl.SourceType.PAYER_CHEQUE_CLEARED: DbSourceType.PAYER_CHEQUE_CLEAR,
    dl.SourceType.PAYER_PAYMENT_REVERSED: DbSourceType.PAYER_PAYMENT_REVERSE,
    dl.SourceType.SHIFT_OPENING: DbSourceType.SHIFT_OPEN,
    dl.SourceType.SHIFT_SWEEP: DbSourceType.SHIFT_SWEEP,
    dl.SourceType.CASH_HANDOVER: DbSourceType.HANDOVER,
    dl.SourceType.HANDOVER_RECEIPT: DbSourceType.HANDOVER_RECEIPT,
    dl.SourceType.HANDOVER_CANCELLED: DbSourceType.HANDOVER_CANCEL,
}

#: Sentinel the services pass as ``department_id`` for revenue without a department.
NO_DEPARTMENT = 0

_FK_DIMS = {
    dl.Dim.SHIFT: "shift_id",
    dl.Dim.PATIENT: "patient_id",
    dl.Dim.INVOICE: "invoice_id",
    dl.Dim.PAYER: "payer_id",
    dl.Dim.DEPARTMENT: "department_id",
}
_FILTERS = {"shift", "patient", "invoice", "payer", "department", "service_kind"}


def _accounts() -> dict[str, Account]:
    return {a.code: a for a in Account.objects.all()}


def _line_kwargs(line: dl.JournalLine) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"debit": line.debit, "credit": line.credit}
    for dim, value in line.dimensions.items():
        if dim is dl.Dim.SERVICE_KIND:
            kwargs["service_kind"] = str(value)
        elif dim is dl.Dim.DEPARTMENT and value == NO_DEPARTMENT:
            kwargs["department_id"] = None
        else:
            kwargs[_FK_DIMS[dim]] = value
    return kwargs


def post(
    draft: dl.JournalDraft,
    *,
    actor: User | None = None,
    shift_id: int | None = None,
    entry_date: date | None = None,
    reversal_of: JournalEntry | None = None,
) -> JournalEntry | None:
    """Store one balanced draft as a ``JournalEntry`` with its lines.

    Empty drafts (the event moved nothing, e.g. a zero variance or spending patient credit)
    store nothing and return None.

    Args:
        draft: Built by a ``domain.ledger.post_*`` builder.
        actor: The user who caused the posting.
        shift_id: The shift the effect belongs to (the acting user's current shift for a
            late effect of a closed shift).
        entry_date: Accounting date (default today).
        reversal_of: The entry this one fully reverses, if any.

    Raises:
        DomainError: ``JOURNAL_UNBALANCED`` (also enforced at commit by the database);
            ``LEDGER_ACCOUNT_MISSING`` when the chart of accounts is not seeded.
    """
    if draft.is_empty:
        return None
    dl.assert_balanced(draft)
    accounts = _accounts()
    missing = sorted({str(ln.account) for ln in draft.lines} - set(accounts))
    if missing:
        raise DomainError(
            "LEDGER_ACCOUNT_MISSING", "The chart of accounts is incomplete", accounts=missing
        )
    with transaction.atomic():
        entry = JournalEntry.objects.create(
            source_type=SOURCE_TYPES[draft.source_type],
            source_id=draft.source_id,
            entry_date=entry_date or timezone.localdate(),
            shift_id=shift_id,
            reversal_of=reversal_of,
            memo=draft.memo[:300],
            posted_by=actor,
        )
        JournalLine.objects.bulk_create(
            [
                JournalLine(entry=entry, account=accounts[str(ln.account)], **_line_kwargs(ln))
                for ln in draft.lines
            ]
        )
    return entry


def _filters(dims: dict[str, Any]) -> Q:
    unknown = set(dims) - _FILTERS
    if unknown:
        raise ValueError(f"Unknown ledger dimensions: {sorted(unknown)}")
    q = Q()
    for name, value in dims.items():
        if name == "service_kind":
            q &= Q(service_kind=str(value))
        else:
            q &= Q(**{f"{name}_id": getattr(value, "pk", value)})
    return q


def account_balance(code: str, **dimensions: Any) -> Decimal:
    """Balance of account ``code`` on its normal side, filtered by dimensions.

    ``dimensions`` take model instances or ids: ``shift``, ``patient``, ``invoice``,
    ``payer``, ``department``, ``service_kind``. A debit-normal account (CASH, AR_PATIENT)
    is positive when debits exceed credits; a credit-normal one (PATIENT_CREDIT, REVENUE)
    when credits exceed debits.
    """
    account = dl.Account(code)
    sums = JournalLine.objects.filter(Q(account__code=code) & _filters(dimensions)).aggregate(
        d=Sum("debit"), c=Sum("credit")
    )
    signed = (sums["d"] or ZERO) - (sums["c"] or ZERO)
    return signed if dl.CHART[account].normal is dl.Side.DEBIT else -signed


@dataclass(frozen=True, slots=True)
class TrialBalance:
    """Signed ``debit - credit`` per account code; ``total`` is zero when the books balance."""

    rows: dict[str, Decimal]
    total_debit: Decimal
    total_credit: Decimal

    @property
    def total(self) -> Decimal:
        return self.total_debit - self.total_credit

    @property
    def balanced(self) -> bool:
        return self.total == 0


def trial_balance(*, until: date | None = None) -> TrialBalance:
    """Totals of every account over all entries (optionally up to ``until`` inclusive)."""
    qs = JournalLine.objects.all()
    if until is not None:
        qs = qs.filter(entry__entry_date__lte=until)
    rows: dict[str, Decimal] = defaultdict(lambda: ZERO)
    debit = credit = ZERO
    grouped = qs.values("account__code").annotate(d=Sum("debit"), c=Sum("credit"))
    for code, d, c in grouped.values_list("account__code", "d", "c"):
        rows[code] += d - c
        debit += d
        credit += c
    return TrialBalance(rows=dict(rows), total_debit=debit, total_credit=credit)


def entries_for(source_type: dl.SourceType, source_id: int) -> list[JournalEntry]:
    """Entries posted for one business document, oldest first."""
    return list(
        JournalEntry.objects.filter(
            source_type=SOURCE_TYPES[source_type], source_id=source_id
        ).order_by("id")
    )
