"""Read-only report queries (FEATURES 4.5, 12.1-12.10; FLOW "reports").

Each report function takes :class:`~apps.reports.kit.Filters` and returns a
:class:`~apps.reports.kit.Report`. Reports never write. Totals come from database
aggregates grouped once per section (no query per row), and names are fetched in bulk.
Where a module already owns a report query it is reused: the exception reports from
``apps.orders.services``, payer receivables and aging from ``apps.claims.queries``, lab
turnaround from ``apps.lab.queries`` and expiring batches from ``apps.pharmacy.queries``.

Money rules (CLAUDE.md invariants 6 and 7, FEATURES 6.4):

* Revenue is what approved invoices froze (their lines' gross, discount and shares on the
  approval day) less what approved credit notes took back on theirs; the same amounts the
  ledger books to REVENUE and DISCOUNT (``test_reconciliation``).
* Collections are patient payments by the day they were taken: cash and confirmed transfers
  are collected; pending transfers are reported apart and never as collected; the payer share
  stays a receivable until a payer payment is recorded.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from django.db.models import Count, DecimalField, ExpressionWrapper, F, Min, Q, Sum
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone

from apps.billing.models import CreditNoteLine, DocumentStatus, InvoiceLine
from apps.claims import queries as claims_queries
from apps.claims.models import PayerPayment, PayerPaymentMethod
from apps.core.models import Department, DoctorProfile, ReasonCode, User
from apps.lab import queries as lab_queries
from apps.lab.models import LabTest
from apps.orders import services as orders
from apps.orders.models import BillingStatus, FulfilmentStatus, ServiceLine
from apps.payments.models import BANK_METHODS, Payment, Refund, RefundStatus, Shift, ShiftStatus
from apps.payments.models import Verification as PaymentVerification
from apps.pharmacy import queries as pharmacy_queries
from apps.pharmacy.models import (
    CountStatus,
    Item,
    MoveKind,
    StockBalance,
    StockCountLine,
    StockMove,
    Store,
)
from apps.reports import labels
from apps.reports.kit import (
    MAX_ROWS,
    Cell,
    Column,
    Filters,
    Metric,
    Name,
    Option,
    Report,
    Section,
    age_days,
    as_int,
    as_money,
    capped,
    m,
    name,
    patient_name,
    person,
    sum_column,
    totals,
    window,
)
from apps.visits.models import QueueEntry, QueueStatus, Visit, VisitStatus, VisitType
from domain import reports as dr
from domain.money import ZERO, money

# --- shared lookups ----------------------------------------------------------------------------


def _department_options() -> list[Option]:
    return [
        Option(d.pk, name(d)) for d in Department.objects.filter(active=True).order_by("sort_order")
    ]


def _user_options(ids: Iterable[int] | None = None) -> list[Option]:
    qs = User.objects.filter(is_active=True)
    if ids is not None:
        qs = qs.filter(pk__in=set(ids))
    else:
        qs = qs.filter(user_roles__isnull=False).distinct()
    return [Option(u.pk, person(u)) for u in qs.order_by("username")]


def _departments(ids: Iterable[int | None]) -> dict[int, Department]:
    return Department.objects.in_bulk([i for i in set(ids) if i is not None])


def _users(ids: Iterable[int | None]) -> dict[int, User]:
    return User.objects.in_bulk([i for i in set(ids) if i is not None])


def _reasons(ids: Iterable[int | None]) -> dict[int, ReasonCode]:
    return ReasonCode.objects.in_bulk([i for i in set(ids) if i is not None])


def _reason(reasons: Mapping[int, ReasonCode], pk: int | None) -> Name:
    found = reasons.get(pk) if pk is not None else None
    if found is None:
        return labels.name("none.reason")
    return name(found, ar="label_ar", en="label_en")


def _dept_name(depts: Mapping[int, Department], pk: int | None) -> Name:
    found = depts.get(pk) if pk is not None else None
    return name(found) if found is not None else labels.name("none.department")


def _user_name(users: Mapping[int, User], pk: int | None, empty: str = "none.user") -> Name:
    found = users.get(pk) if pk is not None else None
    return person(found) if found is not None else labels.name(empty)


def _sorted_by_name(rows: list[dict[str, Cell]], column: str) -> list[dict[str, Cell]]:
    def key(row: dict[str, Cell]) -> str:
        value = row.get(column)
        return value.get("en", "") if isinstance(value, dict) else str(value)

    return sorted(rows, key=key)


def _item_name(item: Item) -> str:
    text = f"{item.generic_name} {item.strength}".strip()
    return f"{text} ({item.brand_name})" if item.brand_name else text


# --- 12.1 daily revenue ------------------------------------------------------------------------

_REVENUE_COLUMNS = [
    Column("gross", "money"),
    Column("discount", "money"),
    Column("credited", "money"),
    Column("net", "money"),
    Column("payer_share", "money"),
    Column("patient_share", "money"),
]


@dataclass
class _Money:
    gross: Decimal = ZERO
    discount: Decimal = ZERO
    payer: Decimal = ZERO
    patient: Decimal = ZERO
    credited: Decimal = ZERO
    credited_discount: Decimal = ZERO
    credited_payer: Decimal = ZERO
    credited_patient: Decimal = ZERO

    def totals(self) -> dr.RevenueTotals:
        return dr.RevenueTotals(self.gross, self.discount, self.credited, self.credited_discount)

    def row(self) -> dict[str, Cell]:
        return {
            "gross": money(self.gross),
            "discount": money(self.discount),
            "credited": money(self.credited),
            "net": money(self.totals().net),
            "payer_share": money(self.payer - self.credited_payer),
            "patient_share": money(self.patient - self.credited_patient),
        }


def _invoice_lines(filters: Filters) -> Any:
    start, end = window(filters)
    qs = InvoiceLine.objects.filter(
        frozen=True,
        invoice__status=DocumentStatus.APPROVED,
        invoice__approved_at__gte=start,
        invoice__approved_at__lt=end,
    )
    if filters.department_id is not None:
        qs = qs.filter(department_id=filters.department_id)
    return qs


def _credit_lines(filters: Filters) -> Any:
    start, end = window(filters)
    qs = CreditNoteLine.objects.filter(
        credit_note__status=DocumentStatus.APPROVED,
        credit_note__approved_at__gte=start,
        credit_note__approved_at__lt=end,
    )
    if filters.department_id is not None:
        qs = qs.filter(invoice_line__department_id=filters.department_id)
    return qs


_LINE_SUMS = {
    "g": Sum("gross"),
    "d": Sum("discount"),
    "p": Sum("payer_share"),
    "s": Sum("patient_share"),
}


def _revenue_by(filters: Filters, invoice_key: Any, credit_key: Any) -> dict[Any, _Money]:
    """Billed money grouped by a key of the invoice line and the matching credit-note key."""
    out: dict[Any, _Money] = defaultdict(_Money)
    for row in _invoice_lines(filters).annotate(k=invoice_key).values("k").annotate(**_LINE_SUMS):
        acc = out[row["k"]]
        acc.gross += m(row["g"])
        acc.discount += m(row["d"])
        acc.payer += m(row["p"])
        acc.patient += m(row["s"])
    for row in _credit_lines(filters).annotate(k=credit_key).values("k").annotate(**_LINE_SUMS):
        acc = out[row["k"]]
        acc.credited += m(row["g"])
        acc.credited_discount += m(row["d"])
        acc.credited_payer += m(row["p"])
        acc.credited_patient += m(row["s"])
    return out


def _patient_payments(filters: Filters) -> Any:
    start, end = window(filters)
    return Payment.objects.filter(
        reversal_of__isnull=True, created_at__gte=start, created_at__lt=end
    )


def revenue(filters: Filters) -> Report:
    """Daily revenue (FEATURES 12.1) with collections by method, pending kept apart.

    A department filter narrows the billed revenue; payments are not per department, so the
    collection metrics and the payment-method section are left out then.
    """
    report = Report("revenue", filters, departments=_department_options())
    by_dept = _revenue_by(filters, F("department_id"), F("invoice_line__department_id"))
    by_doctor = _revenue_by(
        filters, F("invoice__visit__doctor_id"), F("invoice_line__invoice__visit__doctor_id")
    )
    by_day = _revenue_by(
        filters, TruncDate("invoice__approved_at"), TruncDate("credit_note__approved_at")
    )
    total = _Money()
    for acc in by_dept.values():
        for attr in vars(total):
            setattr(total, attr, getattr(total, attr) + getattr(acc, attr))
    t_row = total.row()

    collect_all = filters.department_id is None
    pay_rows: list[tuple[str, str, Decimal]] = []
    per_day_pay: dict[date, list[tuple[str, str, Decimal]]] = defaultdict(list)
    method_rows: dict[str, dict[str, Any]] = {}
    if collect_all:
        grouped = (
            _patient_payments(filters)
            .annotate(day=TruncDate("created_at"))
            .values("day", "method", "verification")
            .annotate(n=Count("id"), s=Sum("amount"))
        )
        for g in grouped:
            item = (g["method"], g["verification"], m(g["s"]))
            pay_rows.append(item)
            per_day_pay[g["day"]].append(item)
            entry = method_rows.setdefault(g["method"], {"n": 0, "rows": []})
            entry["n"] += g["n"]
            entry["rows"].append(item)
    c = dr.collections(pay_rows)

    report.metrics = [
        Metric("gross", t_row["gross"]),
        Metric("discount", t_row["discount"]),
        Metric("credited", t_row["credited"]),
        Metric("net_revenue", t_row["net"], tone="primary"),
        Metric("payer_share", t_row["payer_share"], tone="info"),
        Metric("patient_share", t_row["patient_share"]),
    ]
    if collect_all:
        report.metrics += [
            Metric("collected", money(c.confirmed), tone="success"),
            Metric("cash", money(c.cash)),
            Metric("bank_confirmed", money(c.bank_confirmed)),
            Metric("pending_transfers", money(c.pending), tone="warning"),
            Metric("rejected_transfers", money(c.rejected), tone="danger"),
            Metric("credit_used", money(c.credit_used)),
        ]

    day_columns = [Column("date", "date"), *_REVENUE_COLUMNS]
    if collect_all:
        day_columns += [Column("collected", "money"), Column("pending", "money")]
    days = sorted(set(by_day) | set(per_day_pay))
    day_rows: list[dict[str, Cell]] = []
    for d in days:
        row: dict[str, Cell] = {"date": d, **by_day.get(d, _Money()).row()}
        if collect_all:
            dc = dr.collections(per_day_pay.get(d, []))
            row["collected"] = money(dc.confirmed)
            row["pending"] = money(dc.pending)
        day_rows.append(row)
    report.sections.append(
        Section("by_day", day_columns, day_rows, totals(day_rows, day_columns, "date"))
    )

    depts = _departments(by_dept)
    dept_columns = [Column("department", "name"), *_REVENUE_COLUMNS]
    dept_rows = _sorted_by_name(
        [{"department": _dept_name(depts, k), **acc.row()} for k, acc in by_dept.items()],
        "department",
    )
    report.sections.append(
        Section(
            "by_department", dept_columns, dept_rows, totals(dept_rows, dept_columns, "department")
        )
    )

    doctors = DoctorProfile.objects.select_related("user").in_bulk(
        [k for k in by_doctor if k is not None]
    )
    doc_columns = [Column("doctor", "name"), *_REVENUE_COLUMNS]
    doc_rows = _sorted_by_name(
        [
            {
                "doctor": person(doctors[k].user) if k in doctors else labels.name("none.doctor"),
                **acc.row(),
            }
            for k, acc in by_doctor.items()
        ],
        "doctor",
    )
    report.sections.append(
        Section("by_doctor", doc_columns, doc_rows, totals(doc_rows, doc_columns, "doctor"))
    )

    if collect_all:
        method_columns = [
            Column("method", "name"),
            Column("count", "int"),
            Column("confirmed", "money"),
            Column("pending", "money"),
            Column("rejected", "money"),
        ]
        method_list: list[dict[str, Cell]] = []
        for method, entry in sorted(method_rows.items()):
            mc = dr.collections(entry["rows"])
            confirmed = mc.confirmed if method != "patient_credit" else mc.credit_used
            method_list.append(
                {
                    "method": labels.name(f"method.{method}"),
                    "count": entry["n"],
                    "confirmed": money(confirmed),
                    "pending": money(mc.pending),
                    "rejected": money(mc.rejected),
                }
            )
        collected_rows = [
            r for r in method_list if r["method"] != labels.name("method.patient_credit")
        ]
        method_totals = totals(collected_rows, method_columns, "method")
        report.sections.append(Section("by_method", method_columns, method_list, method_totals))
        report.sections.append(_payer_collections(filters))
    return report


def _payer_collections(filters: Filters) -> Section:
    """Payer payments received in the period: the only money that settles payer shares."""
    columns = [
        Column("method", "name"),
        Column("count", "int"),
        Column("collected", "money"),
        Column("pending", "money"),
    ]
    qs = PayerPayment.objects.filter(
        received_on__gte=filters.date_from,
        received_on__lte=filters.date_to,
        reversed_at__isnull=True,
    )
    rows: list[dict[str, Cell]] = []
    for method in PayerPaymentMethod.values:
        part = qs.filter(method=method)
        n = part.count()
        if not n:
            continue
        uncleared = Q(method=PayerPaymentMethod.CHEQUE, cleared_at__isnull=True)
        pending = m(part.filter(uncleared).aggregate(s=Sum("amount"))["s"])
        collected = m(part.exclude(uncleared).aggregate(s=Sum("amount"))["s"])
        rows.append(
            {
                "method": labels.name(f"payer_method.{method}"),
                "count": n,
                "collected": collected,
                "pending": pending,
            }
        )
    return Section("payer_payments", columns, rows, totals(rows, columns, "method"))


# --- 12.3 shift variances ----------------------------------------------------------------------


def shift_variances(filters: Filters) -> Report:
    """Closed shifts of the period with their variances, by cashier and date (FEATURES 12.3).

    Figures are the frozen close values (invariant 3); later effects show in later shifts.
    """
    start, end = window(filters)
    qs = Shift.objects.filter(
        status=ShiftStatus.CLOSED, closed_at__gte=start, closed_at__lt=end
    ).select_related("cashier", "till", "variance_reason", "review")
    if filters.user_id is not None:
        qs = qs.filter(cashier_id=filters.user_id)
    shifts, truncated = capped(list(qs.order_by("-closed_at", "-id")[: MAX_ROWS + 1]))
    cashier_ids = Shift.objects.values_list("cashier_id", flat=True).distinct()
    report = Report("shift_variances", filters, users=_user_options(cashier_ids))

    columns = [
        Column("shift", "code"),
        Column("cashier", "name"),
        Column("till", "name"),
        Column("closed_at", "datetime"),
        Column("expected", "money"),
        Column("counted", "money"),
        Column("variance", "money"),
        Column("reason", "name"),
        Column("note", "text"),
        Column("review", "name"),
    ]
    rows: list[dict[str, Cell]] = []
    for s in shifts:
        review = getattr(s, "review", None) if hasattr(s, "review") else None
        rows.append(
            {
                "shift": s.number,
                "cashier": person(s.cashier),
                "till": name(s.till) if s.till is not None else labels.name("none.till"),
                "closed_at": s.closed_at,
                "expected": m(s.expected_cash),
                "counted": m(s.counted_cash),
                "variance": m(s.variance),
                "reason": name(s.variance_reason, ar="label_ar", en="label_en")
                if s.variance_reason is not None
                else labels.name("none.reason"),
                "note": s.variance_note,
                "review": labels.name(f"review.{review.outcome}" if review else "review.none"),
            }
        )
    # Totals over every shift of the period (not only the rows shown).
    all_values = [m(v) for v in qs.values_list("variance", flat=True)]
    v = dr.variances(all_values)
    agg = qs.aggregate(e=Sum("expected_cash"), c=Sum("counted_cash"), n=Count("id"))
    section = Section(
        "shifts",
        columns,
        rows,
        {"expected": m(agg["e"]), "counted": m(agg["c"]), "variance": money(v.net)},
        truncated,
    )

    by_cashier: dict[int, list[Decimal]] = defaultdict(list)
    for cashier_id, value in qs.values_list("cashier_id", "variance"):
        by_cashier[cashier_id].append(m(value))
    users = _users(by_cashier)
    cashier_columns = [
        Column("cashier", "name"),
        Column("shifts", "int"),
        Column("short", "money"),
        Column("over", "money"),
        Column("net", "money"),
    ]
    cashier_rows: list[dict[str, Cell]] = []
    for cashier_id, values in by_cashier.items():
        cv = dr.variances(values)
        cashier_rows.append(
            {
                "cashier": _user_name(users, cashier_id),
                "shifts": len(values),
                "short": money(cv.short),
                "over": money(cv.over),
                "net": money(cv.net),
            }
        )
    cashier_rows = _sorted_by_name(cashier_rows, "cashier")
    unreviewed = qs.filter(review__isnull=True).exclude(variance=0).count()
    report.metrics = [
        Metric("shifts", agg["n"], "int"),
        Metric("short", money(v.short), tone="danger"),
        Metric("over", money(v.over), tone="warning"),
        Metric("net_variance", money(v.net), tone="primary"),
        Metric("unreviewed", unreviewed, "int", tone="warning" if unreviewed else "neutral"),
    ]
    report.sections = [
        Section(
            "by_cashier",
            cashier_columns,
            cashier_rows,
            totals(cashier_rows, cashier_columns, "cashier"),
        ),
        section,
    ]
    return report


# --- 12.4 pending transfers --------------------------------------------------------------------


def pending_transfers(filters: Filters, *, today: date | None = None) -> Report:
    """Transfers awaiting verification now, by age in days (FEATURES 6.4, 12.4).

    Pending money settles lines but is never collected; with the uncleared payer cheques it
    is what the ledger holds in BANK_PENDING.
    """
    day = today or timezone.localdate()
    qs = Payment.objects.filter(
        verification=PaymentVerification.PENDING,
        method__in=BANK_METHODS,
        reversal_of__isnull=True,
    ).select_related("patient", "bank", "created_by", "shift")
    if filters.user_id is not None:
        qs = qs.filter(created_by_id=filters.user_id)
    taker_ids = Payment.objects.filter(verification=PaymentVerification.PENDING).values_list(
        "created_by_id", flat=True
    )
    report = Report("pending_transfers", filters, users=_user_options(taker_ids))
    payments, truncated = capped(list(qs.order_by("created_at", "id")[: MAX_ROWS + 1]))
    columns = [
        Column("received_on", "date"),
        Column("age", "days"),
        Column("payment", "code"),
        Column("file_no", "code"),
        Column("patient", "name"),
        Column("method", "name"),
        Column("bank", "name"),
        Column("reference", "code"),
        Column("amount", "money"),
        Column("cashier", "name"),
        Column("shift", "code"),
    ]
    rows: list[dict[str, Cell]] = [
        {
            "received_on": timezone.localdate(p.created_at),
            "age": age_days(p.created_at, day),
            "payment": p.number,
            "file_no": p.patient.file_no,
            "patient": patient_name(p.patient),
            "method": labels.name(f"method.{p.method}"),
            "bank": name(p.bank) if p.bank is not None else labels.name("none.bank"),
            "reference": p.reference,
            "amount": m(p.amount),
            "cashier": person(p.created_by),
            "shift": p.shift.number,
        }
        for p in payments
    ]
    buckets: dict[str, list[Decimal]] = {key: [] for key in dr.AGE_BUCKET_KEYS}
    oldest = 0
    for created, amount in qs.values_list("created_at", "amount"):
        age = age_days(created, day)
        oldest = max(oldest, age)
        buckets[dr.age_bucket(age)].append(m(amount))
    total = money(sum((sum(v, ZERO) for v in buckets.values()), ZERO))
    count = sum(len(v) for v in buckets.values())
    age_columns = [Column("age_bucket", "name"), Column("count", "int"), Column("amount", "money")]
    age_rows: list[dict[str, Cell]] = [
        {"age_bucket": labels.name(f"bucket.{key}"), "count": len(v), "amount": money(sum(v, ZERO))}
        for key, v in buckets.items()
    ]

    cheques = PayerPayment.objects.filter(
        method=PayerPaymentMethod.CHEQUE, cleared_at__isnull=True, reversed_at__isnull=True
    ).select_related("payer", "bank")
    cheque_columns = [
        Column("received_on", "date"),
        Column("age", "days"),
        Column("payment", "code"),
        Column("payer", "name"),
        Column("bank", "name"),
        Column("reference", "code"),
        Column("amount", "money"),
    ]
    cheque_rows: list[dict[str, Cell]] = [
        {
            "received_on": c.received_on,
            "age": age_days(c.received_on, day),
            "payment": c.number,
            "payer": name(c.payer),
            "bank": name(c.bank) if c.bank is not None else labels.name("none.bank"),
            "reference": c.reference,
            "amount": m(c.amount),
        }
        for c in cheques.order_by("received_on", "id")[:MAX_ROWS]
    ]
    cheque_total = m(cheques.aggregate(s=Sum("amount"))["s"])
    report.metrics = [
        Metric("pending_total", total, tone="warning"),
        Metric("pending_count", count, "int"),
        Metric("oldest_age", oldest, "days", tone="danger" if oldest > 3 else "neutral"),
        Metric("cheques_pending", cheque_total, tone="info"),
    ]
    report.sections = [
        Section("by_age", age_columns, age_rows, {"count": count, "amount": total}),
        Section("transfers", columns, rows, {"amount": total}, truncated),
        Section("payer_cheques", cheque_columns, cheque_rows, {"amount": cheque_total}),
    ]
    return report


# --- 12.5 discounts, cancellations, refunds ---------------------------------------------------


def adjustments(filters: Filters) -> Report:
    """Discounts, credit notes, cancellations and refunds by user and reason (12.5).

    The user is who approved: the discount approver, the credit-note approver, the refund
    approver; for lines cancelled before billing, who cancelled them.
    """
    start, end = window(filters)
    report = Report(
        "adjustments", filters, departments=_department_options(), users=_user_options()
    )
    uid = filters.user_id

    discounts = _invoice_lines(filters).filter(discount__gt=0)
    if uid is not None:
        discounts = discounts.filter(discount_approved_by_id=uid)
    disc_groups = list(
        discounts.values("discount_approved_by_id", "discount_reason_id").annotate(
            n=Count("id"), s=Sum("discount")
        )
    )
    credits = _credit_lines(filters)
    if uid is not None:
        credits = credits.filter(credit_note__approved_by_id=uid)
    cn_groups = list(
        credits.values("credit_note__approved_by_id", "credit_note__reason_code_id").annotate(
            n=Count("credit_note_id", distinct=True),
            g=Sum("gross"),
            p=Sum("patient_share"),
            y=Sum("payer_share"),
        )
    )
    cancels = ServiceLine.objects.filter(
        fulfilment_status=FulfilmentStatus.CANCELLED,
        billing_status=BillingStatus.UNBILLED,
        cancelled_at__gte=start,
        cancelled_at__lt=end,
    )
    if filters.department_id is not None:
        cancels = cancels.filter(department_id=filters.department_id)
    if uid is not None:
        cancels = cancels.filter(cancelled_by_id=uid)
    cancel_groups = list(
        cancels.values("cancelled_by_id", "cancel_reason_id").annotate(n=Count("id"))
    )
    refunds = Refund.objects.filter(status=RefundStatus.PAID, paid_at__gte=start, paid_at__lt=end)
    if filters.department_id is not None:
        refunds = refunds.filter(service_line__department_id=filters.department_id)
    if uid is not None:
        refunds = refunds.filter(decided_by_id=uid)
    refund_groups = list(
        refunds.values("decided_by_id", "reason_code_id").annotate(n=Count("id"), s=Sum("amount"))
    )

    users = _users(
        [g["discount_approved_by_id"] for g in disc_groups]
        + [g["credit_note__approved_by_id"] for g in cn_groups]
        + [g["cancelled_by_id"] for g in cancel_groups]
        + [g["decided_by_id"] for g in refund_groups]
    )
    reasons = _reasons(
        [g["discount_reason_id"] for g in disc_groups]
        + [g["credit_note__reason_code_id"] for g in cn_groups]
        + [g["cancel_reason_id"] for g in cancel_groups]
        + [g["reason_code_id"] for g in refund_groups]
    )

    disc_columns = [
        Column("user", "name"),
        Column("reason", "name"),
        Column("count", "int"),
        Column("amount", "money"),
    ]
    disc_rows = _sorted_by_name(
        [
            {
                "user": _user_name(users, g["discount_approved_by_id"]),
                "reason": _reason(reasons, g["discount_reason_id"]),
                "count": g["n"],
                "amount": m(g["s"]),
            }
            for g in disc_groups
        ],
        "user",
    )
    cn_columns = [
        Column("user", "name"),
        Column("reason", "name"),
        Column("count", "int"),
        Column("gross", "money"),
        Column("patient_share", "money"),
        Column("payer_share", "money"),
    ]
    cn_rows = _sorted_by_name(
        [
            {
                "user": _user_name(users, g["credit_note__approved_by_id"]),
                "reason": _reason(reasons, g["credit_note__reason_code_id"]),
                "count": g["n"],
                "gross": m(g["g"]),
                "patient_share": m(g["p"]),
                "payer_share": m(g["y"]),
            }
            for g in cn_groups
        ],
        "user",
    )
    cancel_columns = [Column("user", "name"), Column("reason", "name"), Column("count", "int")]
    cancel_rows = _sorted_by_name(
        [
            {
                "user": _user_name(users, g["cancelled_by_id"]),
                "reason": _reason(reasons, g["cancel_reason_id"]),
                "count": g["n"],
            }
            for g in cancel_groups
        ],
        "user",
    )
    refund_rows = _sorted_by_name(
        [
            {
                "user": _user_name(users, g["decided_by_id"]),
                "reason": _reason(reasons, g["reason_code_id"]),
                "count": g["n"],
                "amount": m(g["s"]),
            }
            for g in refund_groups
        ],
        "user",
    )

    detail = _adjustment_detail(discounts, credits, cancels, refunds)
    report.metrics = [
        Metric("discounts", sum_column(disc_rows, "amount"), tone="warning"),
        Metric("credit_notes", sum_column(cn_rows, "gross"), tone="danger"),
        Metric("refunds", sum_column(refund_rows, "amount"), tone="info"),
        Metric("cancellations", sum(as_int(r["count"]) for r in cancel_rows), "int"),
    ]
    report.sections = [
        Section("discounts", disc_columns, disc_rows, totals(disc_rows, disc_columns, "user")),
        Section("credit_notes", cn_columns, cn_rows, totals(cn_rows, cn_columns, "user")),
        Section(
            "line_cancellations",
            cancel_columns,
            cancel_rows,
            totals(cancel_rows, cancel_columns, "user"),
        ),
        Section("refunds", disc_columns, refund_rows, totals(refund_rows, disc_columns, "user")),
        detail,
    ]
    return report


def _adjustment_detail(discounts: Any, credits: Any, cancels: Any, refunds: Any) -> Section:
    """Every adjustment of the period, newest first: who, why, on which document."""
    columns = [
        Column("at", "datetime"),
        Column("kind", "name"),
        Column("document", "code"),
        Column("file_no", "code"),
        Column("user", "name"),
        Column("reason", "name"),
        Column("amount", "money"),
        Column("note", "text"),
    ]
    events: list[tuple[datetime, dict[str, Any]]] = []
    for il in discounts.select_related(
        "invoice__patient", "discount_approved_by", "discount_reason"
    ).order_by("-invoice__approved_at")[: MAX_ROWS + 1]:
        events.append(
            (
                il.invoice.approved_at,
                {
                    "kind": "discount",
                    "document": il.invoice.number,
                    "file_no": il.invoice.patient.file_no,
                    "user": il.discount_approved_by,
                    "reason": il.discount_reason,
                    "amount": m(il.discount),
                    "note": il.discount_note,
                },
            )
        )
    notes: dict[int, dict[str, Any]] = {}
    for cl in credits.select_related(
        "credit_note__patient", "credit_note__approved_by", "credit_note__reason_code"
    ).order_by("-credit_note__approved_at")[: MAX_ROWS + 1]:
        cn = cl.credit_note
        entry = notes.setdefault(
            cn.pk,
            {
                "at": cn.approved_at,
                "kind": "credit_note",
                "document": cn.number,
                "file_no": cn.patient.file_no,
                "user": cn.approved_by,
                "reason": cn.reason_code,
                "amount": ZERO,
                "note": cn.reason_note,
            },
        )
        entry["amount"] = money(entry["amount"] + cl.gross)
    for entry in notes.values():
        events.append((entry.pop("at"), entry))
    for ln in cancels.select_related("visit__patient", "cancelled_by", "cancel_reason").order_by(
        "-cancelled_at"
    )[: MAX_ROWS + 1]:
        events.append(
            (
                ln.cancelled_at,
                {
                    "kind": "line_cancellation",
                    "document": ln.visit.number,
                    "file_no": ln.visit.patient.file_no,
                    "user": ln.cancelled_by,
                    "reason": ln.cancel_reason,
                    "amount": None,
                    "note": ln.cancel_note,
                },
            )
        )
    for rf in refunds.select_related("patient", "decided_by", "reason_code").order_by("-paid_at")[
        : MAX_ROWS + 1
    ]:
        events.append(
            (
                rf.paid_at,
                {
                    "kind": "refund",
                    "document": rf.number,
                    "file_no": rf.patient.file_no,
                    "user": rf.decided_by,
                    "reason": rf.reason_code,
                    "amount": m(rf.amount),
                    "note": rf.reason_note,
                },
            )
        )
    events.sort(key=lambda e: e[0], reverse=True)
    shown, truncated = capped(events)
    rows: list[dict[str, Cell]] = []
    for at, e in shown:
        reason = e["reason"]
        rows.append(
            {
                "at": at,
                "kind": labels.name(f"adjustment.{e['kind']}"),
                "document": e["document"],
                "file_no": e["file_no"],
                "user": person(e["user"]) if e["user"] is not None else labels.name("none.user"),
                "reason": name(reason, ar="label_ar", en="label_en")
                if reason is not None
                else labels.name("none.reason"),
                "amount": e["amount"],
                "note": e["note"],
            }
        )
    return Section("detail", columns, rows, None, truncated)


# --- 12.7 payer receivables --------------------------------------------------------------------

_STAGES = (
    "accrued",
    "claimed",
    "accepted_unpaid",
    "rejected_unresolved",
    "receivable",
    "collected",
    "rebilled",
    "written_off",
)
_AGING = ("days_0_30", "days_31_60", "days_61_90", "days_over_90", "total")


def payer_receivables(filters: Filters) -> Report:
    """Payer shares by claim stage and age on ``date_to`` (FEATURES 11.2, 11.7, 12.7).

    The receivable is never cash (invariant 7); only recorded payer payments are collected.
    Built from ``apps.claims.queries`` so the claims screens and this report agree.
    """
    as_of = filters.date_to
    data = claims_queries.receivables(as_of)
    aging = claims_queries.aging(as_of)
    report = Report("payer_receivables", filters)
    stage_columns = [Column("payer", "name"), *(Column(s, "money") for s in _STAGES)]
    stage_rows: list[dict[str, Cell]] = []
    for item in data["items"]:
        stages = item["stages"]
        if all(Decimal(stages[s]) == 0 for s in _STAGES):
            continue
        stage_rows.append(
            {
                "payer": {"ar": item["payer"]["name_ar"], "en": item["payer"]["name_en"]},
                **{s: money(Decimal(stages[s])) for s in _STAGES},
            }
        )
    aging_columns = [Column("payer", "name"), *(Column(a, "money") for a in _AGING)]
    aging_rows: list[dict[str, Cell]] = [
        {
            "payer": {"ar": item["payer"]["name_ar"], "en": item["payer"]["name_en"]},
            **{a: money(Decimal(item["aging"][a])) for a in _AGING},
        }
        for item in aging["items"]
        if Decimal(item["aging"]["total"]) != 0
    ]
    t = {s: money(Decimal(data["totals"][s])) for s in _STAGES}
    report.metrics = [
        Metric("receivable", t["receivable"], tone="primary"),
        Metric("claimed", t["claimed"], tone="info"),
        Metric("collected", t["collected"], tone="success"),
        Metric("written_off", t["written_off"], tone="danger"),
    ]
    report.sections = [
        Section("by_stage", stage_columns, stage_rows, totals(stage_rows, stage_columns, "payer")),
        Section(
            "aging",
            aging_columns,
            aging_rows,
            {a: money(Decimal(aging["totals"][a])) for a in _AGING},
        ),
    ]
    return report


# --- 4.5 / 12.2 exception reports --------------------------------------------------------------

_LINE_COLUMNS = [
    Column("age", "days"),
    Column("file_no", "code"),
    Column("patient", "name"),
    Column("visit", "code"),
    Column("service", "name"),
    Column("department", "name"),
    Column("quantity", "int"),
]


def _line_row(line: ServiceLine, age: int) -> dict[str, Cell]:
    return {
        "age": age,
        "file_no": line.visit.patient.file_no,
        "patient": patient_name(line.visit.patient),
        "visit": line.visit.number,
        "service": name(line.service),
        "department": name(line.department)
        if line.department is not None
        else labels.name("none.department"),
        "quantity": int(line.quantity),
    }


def _by_department(rows: list[dict[str, Cell]], amount: str | None = None) -> Section:
    columns = [Column("department", "name"), Column("count", "int")]
    if amount:
        columns.append(Column(amount, "money"))
    acc: dict[str, dict[str, Cell]] = {}
    for row in rows:
        dept = row["department"]
        key = dept["en"] if isinstance(dept, dict) else str(dept)
        entry = acc.setdefault(
            key, {"department": dept, "count": 0, **({amount: ZERO} if amount else {})}
        )
        entry["count"] = as_int(entry["count"]) + 1
        if amount:
            entry[amount] = money(as_money(entry[amount]) + as_money(row[amount]))
    out = _sorted_by_name(list(acc.values()), "department")
    return Section("by_department", columns, out, totals(out, columns, "department"))


def _by_age(rows: list[dict[str, Cell]]) -> Section:
    columns = [Column("age_bucket", "name"), Column("count", "int")]
    counts = dict.fromkeys(dr.AGE_BUCKET_KEYS, 0)
    for row in rows:
        counts[dr.age_bucket(as_int(row["age"]))] += 1
    out: list[dict[str, Cell]] = [
        {"age_bucket": labels.name(f"bucket.{k}"), "count": n} for k, n in counts.items()
    ]
    return Section("by_age", columns, out, {"count": sum(counts.values())})


def requested_not_invoiced(filters: Filters) -> Report:
    """Open lines never invoiced, oldest first, with their age in days (FEATURES 4.5)."""
    found = orders.report_requested_not_invoiced(
        department=filters.department_id, limit=MAX_ROWS + 1
    )
    shown, truncated = capped(found)
    report = Report("requested_not_invoiced", filters, departments=_department_options())
    columns = [Column("ordered_at", "datetime"), *_LINE_COLUMNS, Column("ordered_by", "name")]
    rows: list[dict[str, Cell]] = [
        {
            "ordered_at": a.line.ordered_at,
            **_line_row(a.line, a.age_days),
            "ordered_by": person(a.line.ordered_by),
        }
        for a in shown
    ]
    oldest = max((as_int(r["age"]) for r in rows), default=0)
    report.metrics = [
        Metric("lines", len(rows), "int", tone="warning" if rows else "neutral"),
        Metric("oldest_age", oldest, "days", tone="danger" if oldest > 1 else "neutral"),
    ]
    report.sections = [
        _by_age(rows),
        _by_department(rows),
        Section(
            "lines",
            columns,
            rows,
            {"quantity": sum(as_int(r["quantity"]) for r in rows)},
            truncated,
        ),
    ]
    return report


def _billed_value(line_ids: list[int]) -> dict[int, Decimal]:
    """Net billed value (gross less discount, less credits) per service line."""
    out: dict[int, Decimal] = defaultdict(lambda: ZERO)
    for sl, g, d in (
        InvoiceLine.objects.filter(
            service_line_id__in=line_ids, frozen=True, invoice__status=DocumentStatus.APPROVED
        )
        .values("service_line_id")
        .annotate(g=Sum("gross"), d=Sum("discount"))
        .values_list("service_line_id", "g", "d")
    ):
        out[sl] += m(g) - m(d)
    for sl, g, d in (
        CreditNoteLine.objects.filter(
            invoice_line__service_line_id__in=line_ids,
            credit_note__status=DocumentStatus.APPROVED,
        )
        .values("invoice_line__service_line_id")
        .annotate(g=Sum("gross"), d=Sum("discount"))
        .values_list("invoice_line__service_line_id", "g", "d")
    ):
        out[sl] -= m(g) - m(d)
    return {k: money(v) for k, v in out.items()}


def paid_not_performed(filters: Filters) -> Report:
    """Settled lines not yet performed, oldest settlement first (FEATURES 4.5): the first
    leak of pay-first. ``amount`` is what was billed for the line (net of discount)."""
    found = orders.report_paid_not_performed(department=filters.department_id, limit=MAX_ROWS + 1)
    shown, truncated = capped(found)
    values = _billed_value([a.line.pk for a in shown])
    report = Report("paid_not_performed", filters, departments=_department_options())
    columns = [Column("settled_at", "datetime"), *_LINE_COLUMNS, Column("amount", "money")]
    rows: list[dict[str, Cell]] = [
        {
            "settled_at": a.line.settled_at,
            **_line_row(a.line, a.age_days),
            "amount": values.get(a.line.pk, ZERO),
        }
        for a in shown
    ]
    total = sum_column(rows, "amount")
    oldest = max((as_int(r["age"]) for r in rows), default=0)
    report.metrics = [
        Metric("lines", len(rows), "int", tone="warning" if rows else "neutral"),
        Metric("amount", total, tone="warning"),
        Metric("oldest_age", oldest, "days", tone="danger" if oldest > 1 else "neutral"),
    ]
    report.sections = [
        _by_age(rows),
        _by_department(rows, "amount"),
        Section("lines", columns, rows, {"amount": total}, truncated),
    ]
    return report


def performed_by_authorization(filters: Filters) -> Report:
    """Lines performed before payment under a perform-first authorization, newest first,
    with who allowed them and why (FEATURES 4.4, 4.5)."""
    found = orders.report_performed_by_authorization(
        department=filters.department_id,
        date_from=filters.date_from,
        date_to=filters.date_to,
        limit=MAX_ROWS + 1,
    )
    shown, truncated = capped(found)
    report = Report("performed_by_authorization", filters, departments=_department_options())
    performers = _users(a.line.performed_by_id for a in shown)
    columns = [
        Column("performed_at", "datetime"),
        *_LINE_COLUMNS[1:],
        Column("authorization", "name"),
        Column("reason", "name"),
        Column("authorized_by", "name"),
        Column("performed_by", "name"),
        Column("billing", "name"),
    ]
    rows: list[dict[str, Cell]] = []
    by_authorizer: dict[str, dict[str, Cell]] = {}
    for a in shown:
        auth = a.line.authorization
        if auth is None:  # pragma: no cover - the query filters on the authorization
            continue
        authorizer = person(auth.authorized_by)
        base = _line_row(a.line, a.age_days)
        base.pop("age")
        rows.append(
            {
                "performed_at": a.line.performed_at,
                **base,
                "authorization": labels.name(f"authorization.{auth.kind}"),
                "reason": name(auth.reason_code, ar="label_ar", en="label_en"),
                "authorized_by": authorizer,
                "performed_by": _user_name(performers, a.line.performed_by_id),
                "billing": labels.name(f"billing.{a.line.billing_status}"),
            }
        )
        entry = by_authorizer.setdefault(
            authorizer["en"], {"authorized_by": authorizer, "count": 0, "unbilled": 0}
        )
        entry["count"] = as_int(entry["count"]) + 1
        if a.line.billing_status == BillingStatus.UNBILLED:
            entry["unbilled"] = as_int(entry["unbilled"]) + 1
    who_columns = [
        Column("authorized_by", "name"),
        Column("count", "int"),
        Column("unbilled", "int"),
    ]
    who_rows = _sorted_by_name(list(by_authorizer.values()), "authorized_by")
    unbilled = sum(1 for a in shown if a.line.billing_status == BillingStatus.UNBILLED)
    report.metrics = [
        Metric("lines", len(rows), "int", tone="info"),
        Metric("unbilled", unbilled, "int", tone="warning" if unbilled else "neutral"),
    ]
    report.sections = [
        Section(
            "by_authorizer", who_columns, who_rows, totals(who_rows, who_columns, "authorized_by")
        ),
        Section(
            "lines",
            columns,
            rows,
            {"quantity": sum(as_int(r["quantity"]) for r in rows)},
            truncated,
        ),
    ]
    return report


# --- 12.6 stock --------------------------------------------------------------------------------

_VALUE = ExpressionWrapper(
    F("qty_base") * F("batch__unit_cost"),
    output_field=DecimalField(max_digits=20, decimal_places=4),
)
_MOVE_VALUE = ExpressionWrapper(
    F("qty_base") * F("unit_cost"), output_field=DecimalField(max_digits=20, decimal_places=4)
)


def stock_valuation(filters: Filters, *, today: date | None = None) -> Report:
    """On-hand stock at batch cost, per item and store, as of now (FEATURES 12.6)."""
    day = today or timezone.localdate()
    report = Report("stock_valuation", filters)
    balances = StockBalance.objects.filter(qty_base__gt=0)
    grouped = list(
        balances.values("item_id", "store_id").annotate(
            qty=Sum("qty_base"),
            value=Sum(_VALUE),
            batches=Count("batch_id"),
            nearest=Min("batch__expiry_date"),
        )
    )
    items = Item.objects.in_bulk({g["item_id"] for g in grouped})
    stores = Store.objects.in_bulk({g["store_id"] for g in grouped})
    columns = [
        Column("item", "text"),
        Column("store", "name"),
        Column("unit", "name"),
        Column("on_hand", "int"),
        Column("batches", "int"),
        Column("nearest_expiry", "date"),
        Column("value", "money"),
    ]
    rows: list[dict[str, Cell]] = sorted(
        (
            {
                "item": _item_name(items[g["item_id"]]),
                "store": name(stores[g["store_id"]]),
                "unit": name(items[g["item_id"]], ar="base_unit_name_ar", en="base_unit_name_en"),
                "on_hand": int(g["qty"]),
                "batches": g["batches"],
                "nearest_expiry": g["nearest"],
                "value": m(g["value"]),
            }
            for g in grouped
        ),
        key=lambda r: (str(r["item"]), str(r["store"])),
    )
    shown, truncated = capped(rows)
    store_columns = [
        Column("store", "name"),
        Column("items", "int"),
        Column("batches", "int"),
        Column("value", "money"),
    ]
    by_store = list(
        balances.values("store_id").annotate(
            items=Count("item_id", distinct=True), batches=Count("batch_id"), value=Sum(_VALUE)
        )
    )
    store_rows = _sorted_by_name(
        [
            {
                "store": name(stores.get(s["store_id"]) or Store.objects.get(pk=s["store_id"])),
                "items": s["items"],
                "batches": s["batches"],
                "value": m(s["value"]),
            }
            for s in by_store
        ],
        "store",
    )
    expired = m(balances.filter(batch__expiry_date__lt=day).aggregate(v=Sum(_VALUE))["v"])
    total = sum_column(store_rows, "value")
    report.metrics = [
        Metric("stock_value", total, tone="primary"),
        Metric("items", len({g["item_id"] for g in grouped}), "int"),
        Metric("batches", sum(int(s["batches"]) for s in by_store), "int"),
        Metric("expired_value", expired, tone="danger" if expired else "neutral"),
    ]
    report.sections = [
        Section("by_store", store_columns, store_rows, totals(store_rows, store_columns, "store")),
        Section("items", columns, shown, {"value": total}, truncated),
    ]
    return report


_MOVE_COLUMNS = {
    MoveKind.RECEIPT: "receipts",
    MoveKind.DISPENSE: "dispensed",
    MoveKind.RETURN: "returns",
    MoveKind.ADJUSTMENT: "adjustments",
    MoveKind.COUNT_CORRECTION: "count_corrections",
    MoveKind.TRANSFER_IN: "transfers",
    MoveKind.TRANSFER_OUT: "transfers",
}


def stock_movement(filters: Filters) -> Report:
    """Per item: opening on-hand, the period's moves by kind, closing on-hand (12.6).

    Quantities are base units; dispensed units show as a positive number going out.
    """
    start, end = window(filters)
    report = Report("stock_movement", filters)
    opening = dict(
        StockMove.objects.filter(moved_at__lt=start)
        .values("item_id")
        .annotate(q=Sum("qty_base"))
        .values_list("item_id", "q")
    )
    moves = list(
        StockMove.objects.filter(moved_at__gte=start, moved_at__lt=end)
        .values("item_id", "kind")
        .annotate(q=Sum("qty_base"), v=Sum(_MOVE_VALUE))
    )
    per_item: dict[int, dict[str, Any]] = defaultdict(
        lambda: (
            dict.fromkeys(set(_MOVE_COLUMNS.values()), 0) | {"in_value": ZERO, "out_value": ZERO}
        )
    )
    for mv in moves:
        acc = per_item[mv["item_id"]]
        column = _MOVE_COLUMNS[MoveKind(mv["kind"])]
        qty = int(mv["q"])
        acc[column] += -qty if column == "dispensed" else qty
        value = m(mv["v"])
        if mv["kind"] == MoveKind.RECEIPT:
            acc["in_value"] += value
        elif mv["kind"] == MoveKind.DISPENSE:
            acc["out_value"] += -value
    ids = set(per_item) | {k for k, v in opening.items() if v}
    items = Item.objects.in_bulk(ids)
    columns = [
        Column("item", "text"),
        Column("unit", "name"),
        Column("opening", "int"),
        Column("receipts", "int"),
        Column("dispensed", "int"),
        Column("returns", "int"),
        Column("adjustments", "int"),
        Column("count_corrections", "int"),
        Column("transfers", "int"),
        Column("closing", "int"),
        Column("received_value", "money"),
        Column("dispensed_value", "money"),
    ]
    rows: list[dict[str, Cell]] = []
    for item_id in ids:
        acc = per_item[item_id]
        start_qty = int(opening.get(item_id) or 0)
        net = (
            acc["receipts"]
            - acc["dispensed"]
            + acc["returns"]
            + acc["adjustments"]
            + acc["count_corrections"]
            + acc["transfers"]
        )
        it = items[item_id]
        rows.append(
            {
                "item": _item_name(it),
                "unit": name(it, ar="base_unit_name_ar", en="base_unit_name_en"),
                "opening": start_qty,
                "receipts": acc["receipts"],
                "dispensed": acc["dispensed"],
                "returns": acc["returns"],
                "adjustments": acc["adjustments"],
                "count_corrections": acc["count_corrections"],
                "transfers": acc["transfers"],
                "closing": start_qty + net,
                "received_value": money(acc["in_value"]),
                "dispensed_value": money(acc["out_value"]),
            }
        )
    rows.sort(key=lambda r: str(r["item"]))
    shown, truncated = capped(rows)
    t = totals(rows, columns, "item")
    for key in ("opening", "closing"):
        t.pop(key, None)  # different units: only money and move counts add up meaningfully
    report.metrics = [
        Metric("received_value", sum_column(rows, "received_value"), tone="success"),
        Metric("dispensed_value", sum_column(rows, "dispensed_value"), tone="primary"),
        Metric("items_moved", len(per_item), "int"),
    ]
    report.sections = [Section("items", columns, shown, t, truncated)]
    return report


def stock_variance(filters: Filters) -> Report:
    """Book versus counted stock of the counts posted in the period (FEATURES 8.7, 12.6)."""
    start, end = window(filters)
    report = Report("stock_variance", filters)
    lines = (
        StockCountLine.objects.filter(
            count__status=CountStatus.POSTED,
            count__posted_at__gte=start,
            count__posted_at__lt=end,
            counted_qty__isnull=False,
        )
        .exclude(counted_qty=F("book_qty"))
        .select_related("count__store", "item", "batch", "counted_by")
        .order_by("-count__posted_at", "item__generic_name", "id")
    )
    shown, truncated = capped(list(lines[: MAX_ROWS + 1]))
    columns = [
        Column("count", "code"),
        Column("posted_at", "datetime"),
        Column("store", "name"),
        Column("item", "text"),
        Column("batch", "code"),
        Column("book", "int"),
        Column("counted", "int"),
        Column("difference", "int"),
        Column("value", "money"),
        Column("counted_by", "name"),
    ]
    rows: list[dict[str, Cell]] = []
    for ln in shown:
        diff = int(ln.counted_qty or 0) - int(ln.book_qty)
        rows.append(
            {
                "count": ln.count.number,
                "posted_at": ln.count.posted_at,
                "store": name(ln.count.store),
                "item": _item_name(ln.item),
                "batch": ln.batch.batch_no,
                "book": int(ln.book_qty),
                "counted": int(ln.counted_qty or 0),
                "difference": diff,
                "value": money(Decimal(diff) * ln.batch.unit_cost),
                "counted_by": person(ln.counted_by)
                if ln.counted_by is not None
                else labels.name("none.user"),
            }
        )
    diff_value = ExpressionWrapper(
        (F("counted_qty") - F("book_qty")) * F("batch__unit_cost"),
        output_field=DecimalField(max_digits=20, decimal_places=4),
    )
    agg = lines.aggregate(
        short=Coalesce(Sum(diff_value, filter=Q(counted_qty__lt=F("book_qty"))), Decimal(0)),
        over=Coalesce(Sum(diff_value, filter=Q(counted_qty__gt=F("book_qty"))), Decimal(0)),
        n=Count("id"),
    )
    short, over = m(agg["short"]), m(agg["over"])
    report.metrics = [
        Metric("lines", agg["n"], "int"),
        Metric("shortage_value", short, tone="danger"),
        Metric("surplus_value", over, tone="warning"),
        Metric("net_value", money(short + over), tone="primary"),
    ]
    report.sections = [Section("lines", columns, rows, {"value": money(short + over)}, truncated)]
    return report


def stock_expiry(filters: Filters, *, today: date | None = None) -> Report:
    """Batches with stock expiring within ``days`` (expired included), soonest first (8.8).

    Reuses ``apps.pharmacy.queries.expiry``.
    """
    days = filters.days if filters.days is not None else 90
    report = Report("stock_expiry", filters)
    hits = pharmacy_queries.expiry(days=days, store_id=None, today=today)
    columns = [
        Column("expiry_date", "date"),
        Column("days_left", "days"),
        Column("item", "text"),
        Column("batch", "code"),
        Column("store", "name"),
        Column("unit", "name"),
        Column("on_hand", "int"),
        Column("value", "money"),
    ]
    rows: list[dict[str, Cell]] = [
        {
            "expiry_date": h["expiry_date"],
            "days_left": h["days_left"],
            "item": h["item_name"],
            "batch": h["batch_no"],
            "store": {"ar": h["store"]["name_ar"], "en": h["store"]["name_en"]},
            "unit": {"ar": h["base_unit_name_ar"], "en": h["base_unit_name_en"]},
            "on_hand": h["on_hand"],
            "value": money(Decimal(h["value"])),
        }
        for h in hits
    ]
    shown, truncated = capped(rows)
    expired = [r for r in rows if as_int(r["days_left"]) < 0]
    report.metrics = [
        Metric("batches", len(rows), "int", tone="warning" if rows else "neutral"),
        Metric("expired_value", sum_column(expired, "value"), tone="danger"),
        Metric("expiring_value", sum_column(rows, "value"), tone="warning"),
    ]
    report.sections = [
        Section("batches", columns, shown, {"value": sum_column(rows, "value")}, truncated)
    ]
    return report


# --- 12.8 visits -------------------------------------------------------------------------------

_VISIT_TYPES = {
    VisitType.NEW: "new",
    VisitType.FOLLOW_UP: "follow_up",
    VisitType.EMERGENCY: "emergency",
    VisitType.INPATIENT: "other",
}
_VISIT_COLUMNS = [
    Column("total", "int"),
    Column("new", "int"),
    Column("follow_up", "int"),
    Column("emergency", "int"),
    Column("other", "int"),
    Column("cancelled", "int"),
]


def _visit_counts(groups: Iterable[Mapping[str, Any]], key: str) -> dict[Any, dict[str, int]]:
    out: dict[Any, dict[str, int]] = defaultdict(lambda: {c.key: 0 for c in _VISIT_COLUMNS})
    for g in groups:
        acc = out[g[key]]
        if g["status"] == VisitStatus.CANCELLED:
            acc["cancelled"] += g["n"]
            continue
        acc["total"] += g["n"]
        acc[_VISIT_TYPES.get(g["visit_type"], "other")] += g["n"]
    return out


def visits(filters: Filters) -> Report:
    """Patient visits by department, doctor and day, new versus follow-up (FEATURES 12.8).

    Walk-in pharmacy sales are not visits; cancelled visits are counted apart.
    """
    start, end = window(filters)
    qs = Visit.objects.filter(created_at__gte=start, created_at__lt=end).exclude(
        visit_type=VisitType.PHARMACY_SALE
    )
    if filters.department_id is not None:
        qs = qs.filter(department_id=filters.department_id)
    if filters.user_id is not None:
        qs = qs.filter(doctor__user_id=filters.user_id)
    doctor_users = DoctorProfile.objects.values_list("user_id", flat=True)
    report = Report(
        "visits", filters, departments=_department_options(), users=_user_options(doctor_users)
    )
    base = ("visit_type", "status")
    by_day = _visit_counts(
        qs.annotate(day=TruncDate("created_at")).values("day", *base).annotate(n=Count("id")),
        "day",
    )
    by_dept = _visit_counts(
        qs.values("department_id", *base).annotate(n=Count("id")), "department_id"
    )
    by_doc = _visit_counts(qs.values("doctor_id", *base).annotate(n=Count("id")), "doctor_id")

    day_columns = [Column("date", "date"), *_VISIT_COLUMNS]
    day_rows: list[dict[str, Cell]] = [{"date": d, **by_day[d]} for d in sorted(by_day)]
    depts = _departments(by_dept)
    dept_columns = [Column("department", "name"), *_VISIT_COLUMNS]
    dept_rows = _sorted_by_name(
        [{"department": _dept_name(depts, k), **v} for k, v in by_dept.items()], "department"
    )
    doctors = DoctorProfile.objects.select_related("user").in_bulk([k for k in by_doc if k])
    doc_columns = [Column("doctor", "name"), *_VISIT_COLUMNS]
    doc_rows = _sorted_by_name(
        [
            {
                "doctor": person(doctors[k].user) if k in doctors else labels.name("none.doctor"),
                **v,
            }
            for k, v in by_doc.items()
        ],
        "doctor",
    )
    t = totals(day_rows, day_columns, "date")
    patients = qs.exclude(status=VisitStatus.CANCELLED).values("patient_id").distinct().count()
    report.metrics = [
        Metric("visits", t.get("total", 0), "int", tone="primary"),
        Metric("new", t.get("new", 0), "int", tone="info"),
        Metric("follow_up", t.get("follow_up", 0), "int"),
        Metric("emergency", t.get("emergency", 0), "int", tone="danger"),
        Metric("patients", patients, "int"),
    ]
    report.sections = [
        Section("by_day", day_columns, day_rows, t),
        Section(
            "by_department", dept_columns, dept_rows, totals(dept_rows, dept_columns, "department")
        ),
        Section("by_doctor", doc_columns, doc_rows, totals(doc_rows, doc_columns, "doctor")),
    ]
    return report


# --- 12.9 lab turnaround and volume ------------------------------------------------------------


def lab_turnaround(filters: Filters) -> Report:
    """Turnaround (sample received to first approval) and volume per test (FEATURES 9.8, 12.9).

    Turnaround reuses ``apps.lab.queries.turnaround``; volume counts lab lines ordered,
    performed and cancelled in the period.
    """
    start, end = window(filters)
    tat = lab_queries.turnaround(filters.date_from, filters.date_to)
    report = Report("lab_turnaround", filters)
    lab_lines = ServiceLine.objects.filter(kind="lab")
    ordered = dict(
        lab_lines.filter(ordered_at__gte=start, ordered_at__lt=end)
        .values("service_id")
        .annotate(n=Count("id"))
        .values_list("service_id", "n")
    )
    performed = dict(
        lab_lines.filter(
            fulfilment_status=FulfilmentStatus.PERFORMED,
            performed_at__gte=start,
            performed_at__lt=end,
        )
        .values("service_id")
        .annotate(n=Count("id"))
        .values_list("service_id", "n")
    )
    cancelled = dict(
        lab_lines.filter(
            fulfilment_status=FulfilmentStatus.CANCELLED,
            cancelled_at__gte=start,
            cancelled_at__lt=end,
        )
        .values("service_id")
        .annotate(n=Count("id"))
        .values_list("service_id", "n")
    )
    services = dict(LabTest.objects.values_list("id", "service_id"))
    columns = [
        Column("test", "code"),
        Column("name", "name"),
        Column("target", "minutes"),
        Column("ordered", "int"),
        Column("performed", "int"),
        Column("cancelled", "int"),
        Column("completed", "int"),
        Column("median", "minutes"),
        Column("p90", "minutes"),
        Column("maximum", "minutes"),
        Column("within_target", "percent"),
        Column("open_overdue", "int"),
    ]
    rows: list[dict[str, Cell]] = []
    for r in tat["rows"]:
        test, stats = r["test"], r["stats"]
        service_id = services.get(test["id"], 0)
        volume = (
            ordered.get(service_id, 0),
            performed.get(service_id, 0),
            cancelled.get(service_id, 0),
        )
        if not any(volume) and not stats["count"] and not r["open_overdue"]:
            continue
        rows.append(
            {
                "test": test["code"],
                "name": {"ar": test["name_ar"], "en": test["name_en"]},
                "target": test["turnaround_minutes"],
                "ordered": volume[0],
                "performed": volume[1],
                "cancelled": volume[2],
                "completed": stats["count"],
                "median": stats["median"],
                "p90": stats["p90"],
                "maximum": stats["maximum"],
                "within_target": dr.share_percent(stats["within_target"], stats["count"]),
                "open_overdue": r["open_overdue"],
            }
        )
    total = tat["total"]
    t = totals(rows, columns, "test")
    t.update(
        {
            "median": total["median"],
            "p90": total["p90"],
            "maximum": total["maximum"],
            "within_target": dr.share_percent(total["within_target"], total["count"]),
        }
    )
    report.metrics = [
        Metric("completed", total["count"], "int", tone="primary"),
        Metric("median", total["median"], "minutes", tone="info"),
        Metric(
            "within_target",
            dr.share_percent(total["within_target"], total["count"]),
            "percent",
            tone="success",
        ),
        Metric("open_overdue", as_int(t.get("open_overdue")), "int", tone="danger"),
    ]
    report.sections = [Section("tests", columns, rows, t)]
    return report


# --- 12.10 manager dashboard -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Alert:
    key: str
    tone: str
    count: int
    amount: Decimal | None = None
    report: str | None = None


@dataclass(slots=True)
class Dashboard:
    day: date
    metrics: list[Metric] = field(default_factory=list)
    alerts: list[Alert] = field(default_factory=list)
    trend: list[dict[str, Any]] = field(default_factory=list)
    departments: list[dict[str, Any]] = field(default_factory=list)
    generated_at: datetime = field(default_factory=timezone.now)


#: Days of history in the dashboard's collection chart.
TREND_DAYS = 14


def dashboard(*, today: date | None = None) -> Dashboard:
    """Today at a glance for the manager (FEATURES 12.10): confirmed collection, pending
    transfers, the queue and what needs attention. Phone first; a handful of queries."""
    day = today or timezone.localdate()
    filters = Filters(day, day)
    start, end = window(filters)
    out = Dashboard(day)

    today_pay = _patient_payments(filters).values_list("method", "verification", "amount")
    c = dr.collections((mt, v, m(a)) for mt, v, a in today_pay)
    pending = Payment.objects.filter(
        verification=PaymentVerification.PENDING, method__in=BANK_METHODS, reversal_of__isnull=True
    ).aggregate(n=Count("id"), s=Sum("amount"), oldest=Min("created_at"))
    pending_total = m(pending["s"])
    oldest = age_days(pending["oldest"], day) if pending["oldest"] else 0
    revenue_today = _revenue_by(filters, F("department_id"), F("invoice_line__department_id"))
    net_today = dr.add_revenue(acc.totals() for acc in revenue_today.values()).net
    queue = QueueEntry.objects.filter(
        queue_date=day, status__in=[QueueStatus.WAITING, QueueStatus.CALLED]
    ).count()
    with_doctor = QueueEntry.objects.filter(queue_date=day, status=QueueStatus.IN_PROGRESS).count()
    visits_today = (
        Visit.objects.filter(created_at__gte=start, created_at__lt=end)
        .exclude(visit_type=VisitType.PHARMACY_SALE)
        .exclude(status=VisitStatus.CANCELLED)
        .count()
    )
    open_shifts = Shift.objects.filter(status=ShiftStatus.OPEN).count()

    out.metrics = [
        Metric("collected_today", money(c.confirmed), tone="success"),
        Metric("cash_today", money(c.cash)),
        Metric("bank_today", money(c.bank_confirmed)),
        Metric("pending_transfers", pending_total, tone="warning"),
        Metric("pending_count", pending["n"], "int"),
        Metric("net_revenue_today", money(net_today), tone="primary"),
        Metric("queue_waiting", queue, "int", tone="info"),
        Metric("with_doctor", with_doctor, "int"),
        Metric("visits_today", visits_today, "int"),
        Metric("open_shifts", open_shifts, "int"),
    ]

    alerts: list[Alert] = []
    stale = Payment.objects.filter(
        verification=PaymentVerification.PENDING,
        method__in=BANK_METHODS,
        reversal_of__isnull=True,
        created_at__lt=start - timedelta(days=2),
    ).aggregate(n=Count("id"), s=Sum("amount"))
    if stale["n"]:
        alerts.append(
            Alert("stale_transfers", "warning", stale["n"], m(stale["s"]), "pending_transfers")
        )
    unreviewed = (
        Shift.objects.filter(status=ShiftStatus.CLOSED, review__isnull=True)
        .exclude(variance=0)
        .aggregate(n=Count("id"), s=Sum("variance"))
    )
    if unreviewed["n"]:
        alerts.append(
            Alert(
                "unreviewed_variances",
                "danger",
                unreviewed["n"],
                m(unreviewed["s"]),
                "shift_variances",
            )
        )
    paid_open = ServiceLine.objects.filter(
        billing_status=BillingStatus.SETTLED,
        fulfilment_status__in=[FulfilmentStatus.PENDING, FulfilmentStatus.IN_PROGRESS],
        settled_at__lt=start,
    ).count()
    if paid_open:
        alerts.append(Alert("paid_not_performed", "warning", paid_open, None, "paid_not_performed"))
    unbilled_old = ServiceLine.objects.filter(
        billing_status=BillingStatus.UNBILLED,
        fulfilment_status=FulfilmentStatus.PENDING,
        authorization__isnull=True,
        ordered_at__lt=start,
    ).count()
    if unbilled_old:
        alerts.append(
            Alert("requested_not_invoiced", "info", unbilled_old, None, "requested_not_invoiced")
        )
    authorized_today = ServiceLine.objects.filter(
        authorization__isnull=False,
        fulfilment_status=FulfilmentStatus.PERFORMED,
        performed_at__gte=start,
        performed_at__lt=end,
    ).count()
    if authorized_today:
        alerts.append(
            Alert(
                "performed_by_authorization",
                "info",
                authorized_today,
                None,
                "performed_by_authorization",
            )
        )
    expiring = pharmacy_queries.expiry(days=30, store_id=None, today=day)
    if expiring:
        alerts.append(
            Alert(
                "expiring_stock",
                "warning",
                len(expiring),
                money(sum((Decimal(h["value"]) for h in expiring), ZERO)),
                "stock_expiry",
            )
        )
    low = pharmacy_queries.low_stock(store_id=None)
    if low:
        alerts.append(Alert("low_stock", "warning", len(low), None, None))
    if oldest > 3:
        out.metrics.append(Metric("oldest_pending_age", oldest, "days", tone="danger"))
    out.alerts = alerts

    first = day - timedelta(days=TREND_DAYS - 1)
    trend_filters = Filters(first, day)
    t_start, t_end = window(trend_filters)
    per_day: dict[date, list[tuple[str, str, Decimal]]] = defaultdict(list)
    for d, mt, v, s in (
        _patient_payments(trend_filters)
        .annotate(day=TruncDate("created_at"))
        .values("day", "method", "verification")
        .annotate(s=Sum("amount"))
        .values_list("day", "method", "verification", "s")
    ):
        per_day[d].append((mt, v, m(s)))
    visit_days = dict(
        Visit.objects.filter(created_at__gte=t_start, created_at__lt=t_end)
        .exclude(visit_type=VisitType.PHARMACY_SALE)
        .exclude(status=VisitStatus.CANCELLED)
        .annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(n=Count("id"))
        .values_list("day", "n")
    )
    for i in range(TREND_DAYS):
        d = first + timedelta(days=i)
        dc = dr.collections(per_day.get(d, []))
        out.trend.append(
            {
                "date": d,
                "collected": money(dc.confirmed),
                "pending": money(dc.pending),
                "visits": visit_days.get(d, 0),
            }
        )
    depts = _departments(revenue_today)
    out.departments = sorted(
        (
            {"department": _dept_name(depts, k), "net": money(acc.totals().net)}
            for k, acc in revenue_today.items()
        ),
        key=lambda r: r["net"],
        reverse=True,
    )
    return out


__all__ = [
    "Alert",
    "Dashboard",
    "adjustments",
    "dashboard",
    "lab_turnaround",
    "paid_not_performed",
    "payer_receivables",
    "pending_transfers",
    "performed_by_authorization",
    "requested_not_invoiced",
    "revenue",
    "shift_variances",
    "stock_expiry",
    "stock_movement",
    "stock_valuation",
    "stock_variance",
    "visits",
]
