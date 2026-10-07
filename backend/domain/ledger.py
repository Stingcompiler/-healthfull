"""Append-only double-entry ledger: fixed chart and posting rules (ARCHITECTURE 4.7).

Every money event produces one :class:`JournalDraft` (``source_type``, ``source_id``,
lines). Each line is one-sided (debit xor credit, positive) and carries exactly the
dimensions its account requires. Builders return balanced drafts; a builder may return an
*empty* draft when the event moves nothing (a zero variance, spending patient credit),
and services store only non-empty drafts.

Postings:

* Invoice approved: Dr AR_PATIENT (patient share), Dr AR_PAYER (payer share, per payer),
  Dr DISCOUNT / Cr REVENUE (gross, per department and service kind).
* Payment received: Dr CASH (cash, by shift) or BANK_PENDING (transfer, QR, card) /
  Cr PATIENT_CREDIT. Spending patient credit posts nothing here.
* Allocation (signed): Dr PATIENT_CREDIT / Cr AR_PATIENT; a negative row (reversal or
  de-allocation of an over-allocated invoice) posts the opposite.
* Transfer confirmed: Dr BANK / Cr BANK_PENDING. Rejected: the payment's allocations are
  reversed as negative allocation rows, then Dr PATIENT_CREDIT / Cr BANK_PENDING (or BANK
  if it had been confirmed).
* Credit note: Dr REVENUE / Cr AR_PATIENT, Cr AR_PAYER, Cr DISCOUNT (mirror of the credited
  shares). An over-allocated invoice is then de-allocated with negative allocation rows.
* Refund: Dr PATIENT_CREDIT / Cr CASH. Shift variance: CASH vs CASH_OVER_SHORT.
* Payer rejection rebilled: Dr AR_PATIENT / Cr AR_PAYER. Written off: Dr WRITE_OFF /
  Cr AR_PAYER. Payer payment: Dr BANK / Cr AR_PAYER.

Invariant 7 follows from the chart: payer share enters CASH/BANK only through a payer
payment.

Error codes: ``JOURNAL_LINE_INVALID``, ``JOURNAL_DIMENSIONS_INVALID``,
``JOURNAL_UNBALANCED``, ``INVALID_AMOUNT``.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType

from domain.errors import DomainError
from domain.money import ZERO, require_money, require_non_negative, require_positive
from domain.payments import PaymentMethod

__all__ = [
    "CHART",
    "MONEY_ACCOUNTS",
    "Account",
    "AccountKind",
    "AccountSpec",
    "Dim",
    "DimValue",
    "JournalDraft",
    "JournalLine",
    "RevenueLine",
    "Side",
    "SourceType",
    "account_balance",
    "assert_balanced",
    "post_allocation",
    "post_credit_note",
    "post_invoice_approved",
    "post_payer_payment",
    "post_payer_rebill",
    "post_payer_write_off",
    "post_payment_received",
    "post_refund",
    "post_shift_variance",
    "post_transfer_confirmed",
    "post_transfer_rejected",
    "trial_balance",
]

type DimValue = int | str


class Account(StrEnum):
    CASH = "CASH"
    BANK_PENDING = "BANK_PENDING"
    BANK = "BANK"
    AR_PATIENT = "AR_PATIENT"
    AR_PAYER = "AR_PAYER"
    PATIENT_CREDIT = "PATIENT_CREDIT"
    REVENUE = "REVENUE"
    DISCOUNT = "DISCOUNT"
    WRITE_OFF = "WRITE_OFF"
    CASH_OVER_SHORT = "CASH_OVER_SHORT"


class AccountKind(StrEnum):
    ASSET = "asset"
    LIABILITY = "liability"
    REVENUE = "revenue"
    CONTRA_REVENUE = "contra_revenue"
    EXPENSE = "expense"


class Side(StrEnum):
    DEBIT = "debit"
    CREDIT = "credit"


class Dim(StrEnum):
    SHIFT = "shift"
    PATIENT = "patient"
    INVOICE = "invoice"
    PAYER = "payer"
    DEPARTMENT = "department"
    SERVICE_KIND = "service_kind"


class SourceType(StrEnum):
    INVOICE = "invoice"
    CREDIT_NOTE = "credit_note"
    PAYMENT = "payment"
    ALLOCATION = "allocation"
    TRANSFER_CONFIRMATION = "transfer_confirmation"
    TRANSFER_REJECTION = "transfer_rejection"
    REFUND = "refund"
    SHIFT_VARIANCE = "shift_variance"
    PAYER_REBILL = "payer_rebill"
    PAYER_WRITE_OFF = "payer_write_off"
    PAYER_PAYMENT = "payer_payment"


@dataclass(frozen=True, slots=True)
class AccountSpec:
    code: Account
    name_en: str
    name_ar: str
    kind: AccountKind
    normal: Side
    dimensions: frozenset[Dim]


def _spec(
    code: Account, en: str, ar: str, kind: AccountKind, normal: Side, *dims: Dim
) -> AccountSpec:
    return AccountSpec(code, en, ar, kind, normal, frozenset(dims))


#: The fixed chart of accounts; seeded into ``ledger.Account`` rows.
CHART: Mapping[Account, AccountSpec] = MappingProxyType(
    {
        s.code: s
        for s in (
            _spec(
                Account.CASH,
                "Cash in drawer",
                "نقد في الصندوق",
                AccountKind.ASSET,
                Side.DEBIT,
                Dim.SHIFT,
            ),
            _spec(
                Account.BANK_PENDING,
                "Transfers awaiting verification",
                "تحويلات بانتظار التحقق",
                AccountKind.ASSET,
                Side.DEBIT,
            ),
            _spec(
                Account.BANK,
                "Verified bank money",
                "أموال بنكية مؤكدة",
                AccountKind.ASSET,
                Side.DEBIT,
            ),
            _spec(
                Account.AR_PATIENT,
                "Patient receivable",
                "مستحقات على المرضى",
                AccountKind.ASSET,
                Side.DEBIT,
                Dim.PATIENT,
                Dim.INVOICE,
            ),
            _spec(
                Account.AR_PAYER,
                "Payer receivable",
                "مستحقات على جهات التغطية",
                AccountKind.ASSET,
                Side.DEBIT,
                Dim.PAYER,
                Dim.INVOICE,
            ),
            _spec(
                Account.PATIENT_CREDIT,
                "Patient credit",
                "أرصدة المرضى",
                AccountKind.LIABILITY,
                Side.CREDIT,
                Dim.PATIENT,
            ),
            _spec(
                Account.REVENUE,
                "Service revenue",
                "إيراد الخدمات",
                AccountKind.REVENUE,
                Side.CREDIT,
                Dim.DEPARTMENT,
                Dim.SERVICE_KIND,
            ),
            _spec(
                Account.DISCOUNT,
                "Discounts given",
                "خصومات ممنوحة",
                AccountKind.CONTRA_REVENUE,
                Side.DEBIT,
            ),
            _spec(
                Account.WRITE_OFF,
                "Payer rejections written off",
                "مرفوضات مشطوبة",
                AccountKind.EXPENSE,
                Side.DEBIT,
                Dim.PAYER,
            ),
            _spec(
                Account.CASH_OVER_SHORT,
                "Shift variances",
                "فروق الورديات",
                AccountKind.EXPENSE,
                Side.DEBIT,
                Dim.SHIFT,
            ),
        )
    }
)

#: Accounts that hold real money. Payer share reaches them only via a payer payment.
MONEY_ACCOUNTS = frozenset({Account.CASH, Account.BANK_PENDING, Account.BANK})


@dataclass(frozen=True, slots=True)
class JournalLine:
    account: Account
    debit: Decimal = ZERO
    credit: Decimal = ZERO
    dimensions: Mapping[Dim, DimValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        debit = require_non_negative(self.debit, "debit")
        credit = require_non_negative(self.credit, "credit")
        if (debit > 0) == (credit > 0):
            raise DomainError(
                "JOURNAL_LINE_INVALID",
                "A journal line is either a debit or a credit, and not zero",
                account=str(self.account),
            )
        dims = {Dim(k): v for k, v in self.dimensions.items()}
        if set(dims) != CHART[self.account].dimensions:
            raise DomainError(
                "JOURNAL_DIMENSIONS_INVALID",
                "Journal line dimensions do not match the account",
                account=str(self.account),
                given=sorted(dims),
                required=sorted(CHART[self.account].dimensions),
            )
        object.__setattr__(self, "dimensions", MappingProxyType(dims))

    @property
    def amount(self) -> Decimal:
        return self.debit if self.debit > 0 else self.credit

    @property
    def signed(self) -> Decimal:
        """``debit - credit``."""
        return self.debit - self.credit


@dataclass(frozen=True, slots=True)
class JournalDraft:
    source_type: SourceType
    source_id: int
    lines: tuple[JournalLine, ...] = ()
    memo: str = ""

    @property
    def total_debit(self) -> Decimal:
        return sum((ln.debit for ln in self.lines), ZERO)

    @property
    def total_credit(self) -> Decimal:
        return sum((ln.credit for ln in self.lines), ZERO)

    @property
    def is_empty(self) -> bool:
        return not self.lines


def assert_balanced(draft: JournalDraft) -> None:
    """Raise ``JOURNAL_UNBALANCED`` unless total debit equals total credit."""
    if draft.total_debit != draft.total_credit:
        raise DomainError(
            "JOURNAL_UNBALANCED",
            "Journal entry does not balance",
            source_type=str(draft.source_type),
            source_id=draft.source_id,
            debit=str(draft.total_debit),
            credit=str(draft.total_credit),
        )


type _Key = tuple[Account, tuple[tuple[Dim, DimValue], ...]]


class _Builder:
    """Accumulates signed amounts per (account, dimensions) and emits netted lines."""

    def __init__(self) -> None:
        self._amounts: dict[_Key, Decimal] = defaultdict(lambda: ZERO)

    def add(self, account: Account, signed: Decimal, **dims: DimValue) -> None:
        key = (account, tuple(sorted((Dim(k), v) for k, v in dims.items())))
        self._amounts[key] += signed

    def debit(self, account: Account, amount: Decimal, **dims: DimValue) -> None:
        self.add(account, amount, **dims)

    def credit(self, account: Account, amount: Decimal, **dims: DimValue) -> None:
        self.add(account, -amount, **dims)

    def build(self, source_type: SourceType, source_id: int, memo: str = "") -> JournalDraft:
        lines = []
        for (account, dims), net in self._amounts.items():
            if net > 0:
                lines.append(JournalLine(account, debit=net, dimensions=dict(dims)))
            elif net < 0:
                lines.append(JournalLine(account, credit=-net, dimensions=dict(dims)))
        draft = JournalDraft(source_type, source_id, tuple(lines), memo)
        assert_balanced(draft)
        return draft


@dataclass(frozen=True, slots=True)
class RevenueLine:
    """The amounts of one invoice (or credit note) line, with its ledger dimensions."""

    gross: Decimal
    discount: Decimal
    payer_share: Decimal
    patient_share: Decimal
    payer_id: int | None
    department_id: int
    service_kind: str

    def __post_init__(self) -> None:
        for name in ("gross", "discount", "payer_share", "patient_share"):
            require_non_negative(getattr(self, name), name)
        if self.gross != self.discount + self.payer_share + self.patient_share or (
            self.payer_id is None and self.payer_share != 0
        ):
            raise DomainError("JOURNAL_LINE_INVALID", "Revenue line amounts are inconsistent")


def _revenue(
    b: _Builder, invoice_id: int, patient_id: int, lines: Iterable[RevenueLine], sign: int
) -> None:
    for ln in lines:
        b.add(Account.AR_PATIENT, sign * ln.patient_share, patient=patient_id, invoice=invoice_id)
        if ln.payer_id is not None:
            b.add(Account.AR_PAYER, sign * ln.payer_share, payer=ln.payer_id, invoice=invoice_id)
        b.add(Account.DISCOUNT, sign * ln.discount)
        b.add(
            Account.REVENUE,
            -sign * ln.gross,
            department=ln.department_id,
            service_kind=ln.service_kind,
        )


def post_invoice_approved(
    invoice_id: int, patient_id: int, lines: Iterable[RevenueLine]
) -> JournalDraft:
    b = _Builder()
    _revenue(b, invoice_id, patient_id, lines, 1)
    return b.build(SourceType.INVOICE, invoice_id)


def post_credit_note(
    credit_note_id: int, invoice_id: int, patient_id: int, lines: Iterable[RevenueLine]
) -> JournalDraft:
    """Mirror of the credited lines' shares, against the original invoice's receivables."""
    b = _Builder()
    _revenue(b, invoice_id, patient_id, lines, -1)
    return b.build(SourceType.CREDIT_NOTE, credit_note_id)


def post_payment_received(
    payment_id: int, patient_id: int, method: PaymentMethod, amount: Decimal, shift_id: int
) -> JournalDraft:
    value = require_positive(amount, "amount")
    b = _Builder()
    if method is PaymentMethod.PATIENT_CREDIT:
        return b.build(SourceType.PAYMENT, payment_id, "credit spend: allocations only")
    if method is PaymentMethod.CASH:
        b.debit(Account.CASH, value, shift=shift_id)
    else:
        b.debit(Account.BANK_PENDING, value)
    b.credit(Account.PATIENT_CREDIT, value, patient=patient_id)
    return b.build(SourceType.PAYMENT, payment_id)


def post_allocation(
    allocation_id: int, patient_id: int, invoice_id: int, amount: Decimal
) -> JournalDraft:
    """Signed: positive applies credit to the invoice, negative takes it back."""
    value = require_money(amount, "amount")
    if value == 0:
        raise DomainError("INVALID_AMOUNT", "An allocation cannot be zero", field="amount")
    b = _Builder()
    b.debit(Account.PATIENT_CREDIT, value, patient=patient_id)
    b.credit(Account.AR_PATIENT, value, patient=patient_id, invoice=invoice_id)
    return b.build(SourceType.ALLOCATION, allocation_id)


def post_transfer_confirmed(payment_id: int, amount: Decimal) -> JournalDraft:
    value = require_positive(amount, "amount")
    b = _Builder()
    b.debit(Account.BANK, value)
    b.credit(Account.BANK_PENDING, value)
    return b.build(SourceType.TRANSFER_CONFIRMATION, payment_id)


def post_transfer_rejected(
    payment_id: int, patient_id: int, amount: Decimal, *, was_confirmed: bool
) -> JournalDraft:
    """The money leaves patient credit. Post the allocation reversals separately first."""
    value = require_positive(amount, "amount")
    b = _Builder()
    b.debit(Account.PATIENT_CREDIT, value, patient=patient_id)
    b.credit(Account.BANK if was_confirmed else Account.BANK_PENDING, value)
    return b.build(SourceType.TRANSFER_REJECTION, payment_id)


def post_refund(refund_id: int, patient_id: int, amount: Decimal, shift_id: int) -> JournalDraft:
    value = require_positive(amount, "amount")
    b = _Builder()
    b.debit(Account.PATIENT_CREDIT, value, patient=patient_id)
    b.credit(Account.CASH, value, shift=shift_id)
    return b.build(SourceType.REFUND, refund_id)


def post_shift_variance(shift_id: int, variance: Decimal) -> JournalDraft:
    """Over (positive): Dr CASH / Cr CASH_OVER_SHORT. Short: the opposite. Zero: empty."""
    value = require_money(variance, "variance")
    b = _Builder()
    b.add(Account.CASH, value, shift=shift_id)
    b.add(Account.CASH_OVER_SHORT, -value, shift=shift_id)
    return b.build(SourceType.SHIFT_VARIANCE, shift_id)


def post_payer_rebill(
    source_id: int, patient_id: int, payer_id: int, invoice_id: int, amount: Decimal
) -> JournalDraft:
    value = require_positive(amount, "amount")
    b = _Builder()
    b.debit(Account.AR_PATIENT, value, patient=patient_id, invoice=invoice_id)
    b.credit(Account.AR_PAYER, value, payer=payer_id, invoice=invoice_id)
    return b.build(SourceType.PAYER_REBILL, source_id)


def post_payer_write_off(
    source_id: int, payer_id: int, invoice_id: int, amount: Decimal
) -> JournalDraft:
    value = require_positive(amount, "amount")
    b = _Builder()
    b.debit(Account.WRITE_OFF, value, payer=payer_id)
    b.credit(Account.AR_PAYER, value, payer=payer_id, invoice=invoice_id)
    return b.build(SourceType.PAYER_WRITE_OFF, source_id)


def post_payer_payment(
    payer_payment_id: int, payer_id: int, allocations: Iterable[tuple[int, Decimal]]
) -> JournalDraft:
    """Dr BANK (total) / Cr AR_PAYER per invoice. A payer payment is fully allocated."""
    b = _Builder()
    total = ZERO
    for invoice_id, amount in allocations:
        value = require_positive(amount, "amount")
        b.credit(Account.AR_PAYER, value, payer=payer_id, invoice=invoice_id)
        total += value
    if total == 0:
        raise DomainError("INVALID_AMOUNT", "A payer payment needs allocations", field="amount")
    b.debit(Account.BANK, total)
    return b.build(SourceType.PAYER_PAYMENT, payer_payment_id)


def _matches(line: JournalLine, filters: Mapping[str, DimValue]) -> bool:
    return all(line.dimensions.get(Dim(k)) == v for k, v in filters.items())


def account_balance(entries: Iterable[JournalDraft], account: Account, **dims: DimValue) -> Decimal:
    """Balance on the account's normal side, optionally filtered by dimensions."""
    signed = ZERO
    for entry in entries:
        for line in entry.lines:
            if line.account is account and _matches(line, dims):
                signed += line.signed
    return signed if CHART[account].normal is Side.DEBIT else -signed


def trial_balance(entries: Iterable[JournalDraft]) -> dict[Account, Decimal]:
    """Signed ``debit - credit`` per account touched by ``entries``."""
    out: dict[Account, Decimal] = defaultdict(lambda: ZERO)
    for entry in entries:
        for line in entry.lines:
            out[line.account] += line.signed
    return dict(out)
