"""Minimal object builders for model and trigger tests across apps.

Each builder writes rows directly (bypassing services on purpose: these tests prove what the
database itself accepts and refuses). Helpers ``db_rejects`` / ``sql_rejects`` assert that a
statement fails inside its own savepoint, so the test transaction stays usable.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from django.db import DatabaseError, connection, transaction
from django.utils import timezone

_seq = itertools.count(1)


def n() -> int:
    return next(_seq)


# --- Assertions ----------------------------------------------------------------------------


def db_rejects(action: Callable[[], Any], match: str | None = None) -> None:
    """``action`` (ORM) must raise a database error matching ``match``."""
    with pytest.raises(DatabaseError, match=match), transaction.atomic():
        action()


def sql_rejects(
    sql: str, params: list[Any] | tuple[Any, ...] = (), match: str | None = None
) -> None:
    """Raw SQL must raise a database error matching ``match``."""
    with (
        pytest.raises(DatabaseError, match=match),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(sql, params)


def sql(sql_text: str, params: list[Any] | tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    with connection.cursor() as cursor:
        cursor.execute(sql_text, params)
        return cursor.fetchall() if cursor.description else []


def _constraints(mode: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(f"SET CONSTRAINTS ALL {mode}")


@contextmanager
def deferred_checks_fire(match: str | None = None, *, rejects: bool = True) -> Iterator[None]:
    """Run the block, then fire deferred (commit-time) constraint triggers immediately.

    Tests run inside a transaction that never commits, so commit-time checks would never run;
    ``SET CONSTRAINTS ALL IMMEDIATE`` makes PostgreSQL run them as if committing.
    """
    try:
        if rejects:
            with pytest.raises(DatabaseError, match=match), transaction.atomic():  # noqa: PT012
                yield
                _constraints("IMMEDIATE")
        else:
            with transaction.atomic():
                yield
                _constraints("IMMEDIATE")
    finally:
        _constraints("DEFERRED")


class _Rollback(Exception):
    pass


@contextmanager
def rolled_back() -> Iterator[None]:
    """Run the block in a savepoint that is always rolled back.

    Django's test teardown runs ``SET CONSTRAINTS ALL IMMEDIATE`` (``check_constraints``),
    which fires the commit-time triggers; scenarios that build deliberately incomplete
    documents (an entry without lines...) must not leave them pending.
    """
    try:
        with transaction.atomic():
            yield
            raise _Rollback
    except _Rollback:
        pass


# --- Core ----------------------------------------------------------------------------------


def user(username: str | None = None, **extra: Any) -> Any:
    from apps.core.models import User

    u = User(username=username or f"u{n()}", must_change_password=False, **extra)
    u.set_unusable_password()
    u.save()
    return u


def department(code: str | None = None) -> Any:
    from apps.core.models import Department

    code = code or f"D{n()}"
    return Department.objects.create(code=code, name_ar=f"قسم {code}", name_en=f"Dept {code}")


def reason(category: str) -> Any:
    from apps.core.models import ReasonCode

    found = ReasonCode.objects.filter(category=category).first()
    if found is not None:
        return found
    return ReasonCode.objects.create(
        category=category, code=f"R{n()}", label_ar="سبب", label_en="Reason"
    )


def doctor(dept: Any | None = None) -> Any:
    from apps.core.models import DoctorProfile

    return DoctorProfile.objects.create(user=user(), department=dept or department())


# --- Catalog -------------------------------------------------------------------------------


def service(kind: str = "lab", **extra: Any) -> Any:
    from apps.catalog.models import Service

    i = n()
    return Service.objects.create(
        code=extra.pop("code", f"S{i}"),
        name_ar=f"خدمة {i}",
        name_en=f"Service {i}",
        kind=kind,
        **extra,
    )


def price_version(price_list: Any | None = None, effective_from: date | None = None) -> Any:
    from apps.catalog.models import PriceList, PriceListVersion

    if price_list is None:
        price_list = PriceList.objects.filter(is_default=True).first()
    if price_list is None:  # seeded by catalog.0002, but transactional tests truncate it
        price_list = PriceList.objects.create(
            code="CASH", name_ar="نقد", name_en="Cash", kind="cash", is_default=True
        )
    return PriceListVersion.objects.create(
        price_list=price_list, effective_from=effective_from or date(2026, 1, n() % 28 + 1)
    )


def payer(**extra: Any) -> Any:
    from apps.catalog.models import Payer

    i = n()
    return Payer.objects.create(code=f"P{i}", name_ar=f"جهة {i}", name_en=f"Payer {i}", **extra)


# --- Patients and visits -------------------------------------------------------------------


def patient(**extra: Any) -> Any:
    from apps.patients.models import Patient

    extra.setdefault("full_name_ar", "أحمد محمد")
    extra.setdefault("sex", "male")
    return Patient.objects.create(file_no=f"PT-2026-{n():06d}", **extra)


def visit(pat: Any | None = None, **extra: Any) -> Any:
    from apps.visits.models import Visit

    return Visit.objects.create(
        number=f"VIS-2026-{n():06d}",
        patient=pat or patient(),
        created_by=extra.pop("created_by", None) or user(),
        **extra,
    )


def service_line(v: Any | None = None, svc: Any | None = None, **extra: Any) -> Any:
    from apps.orders.models import ServiceLine

    svc = svc or service()
    return ServiceLine.objects.create(
        visit=v or visit(),
        service=svc,
        kind=svc.kind,
        ordered_by=extra.pop("ordered_by", None) or user(),
        **extra,
    )


# --- Billing -------------------------------------------------------------------------------


def draft_invoice(v: Any | None = None) -> Any:
    from apps.billing.models import Invoice

    v = v or visit()
    return Invoice.objects.create(visit=v, patient=v.patient, created_by=user())


def invoice_line(
    inv: Any,
    *,
    line: Any | None = None,
    unit_price: str = "100.00",
    quantity: str = "1",
    payer_share: str = "0.00",
    payer_obj: Any | None = None,
    line_no: int | None = None,
) -> Any:
    from apps.billing.models import InvoiceLine

    line = line or service_line(inv.visit)
    gross = (Decimal(quantity) * Decimal(unit_price)).quantize(Decimal("0.01"))
    return InvoiceLine.objects.create(
        invoice=inv,
        line_no=line_no or inv.lines.count() + 1,
        service_line=line,
        service=line.service,
        kind=line.kind,
        description_ar=line.service.name_ar,
        description_en=line.service.name_en,
        quantity=Decimal(quantity),
        unit_price=Decimal(unit_price),
        gross=gross,
        payer=payer_obj,
        payer_share=Decimal(payer_share),
        patient_share=gross - Decimal(payer_share),
    )


def approve_invoice(inv: Any) -> Any:
    """Freeze every line, set totals from the lines, approve. Consistent by construction."""
    from django.db.models import Sum

    from apps.billing.models import Invoice, InvoiceLine

    version = price_version()
    InvoiceLine.objects.filter(invoice=inv).update(frozen=True, price_list_version=version)
    sums = InvoiceLine.objects.filter(invoice=inv).aggregate(
        g=Sum("gross"), d=Sum("discount"), p=Sum("payer_share"), s=Sum("patient_share")
    )
    Invoice.objects.filter(pk=inv.pk).update(
        status="approved",
        number=f"INV-2026-{n():06d}",
        approved_by=user(),
        approved_at=timezone.now(),
        priced_on=timezone.localdate(),
        gross_total=sums["g"],
        discount_total=sums["d"],
        payer_total=sums["p"],
        patient_total=sums["s"],
    )
    inv.refresh_from_db()
    return inv


def approved_invoice(lines: int = 1, unit_price: str = "100.00") -> Any:
    inv = draft_invoice()
    for _ in range(lines):
        invoice_line(inv, unit_price=unit_price)
    return approve_invoice(inv)


# --- Payments ------------------------------------------------------------------------------


def shift(cashier: Any | None = None, **extra: Any) -> Any:
    from apps.payments.models import Shift

    return Shift.objects.create(
        number=f"SH-2026-{n():06d}",
        cashier=cashier or user(),
        opened_at=timezone.now() - timedelta(hours=1),
        opening_float=Decimal("1000.00"),
        **extra,
    )


def close_shift(sh: Any) -> Any:
    from apps.payments.models import Shift

    Shift.objects.filter(pk=sh.pk).update(
        status="closed",
        closed_at=timezone.now(),
        closed_by=sh.cashier,
        expected_cash=Decimal("1000.00"),
        counted_cash=Decimal("1000.00"),
        variance=Decimal("0.00"),
    )
    sh.refresh_from_db()
    return sh


def bank(code: str = "BOK") -> Any:
    from apps.payments.models import Bank

    return Bank.objects.get_or_create(code=code, defaults={"name_ar": code, "name_en": code})[0]


def payment(sh: Any | None = None, pat: Any | None = None, **extra: Any) -> Any:
    from apps.payments.models import Payment

    method = extra.pop("method", "cash")
    if method in ("bank_transfer", "qr", "card"):
        extra.setdefault("bank", bank())
        extra.setdefault("reference", f"REF{n()}")
        extra.setdefault("verification", "pending")
    else:
        extra.setdefault("verification", "confirmed")
    return Payment.objects.create(
        number=f"RCP-2026-{n():06d}",
        shift=sh or shift(),
        patient=pat or patient(),
        method=method,
        amount=extra.pop("amount", Decimal("100.00")),
        created_by=user(),
        **extra,
    )


# --- Pharmacy ------------------------------------------------------------------------------


def item(**extra: Any) -> Any:
    from apps.pharmacy.models import Item

    return Item.objects.create(
        service=service(kind="drug"),
        generic_name=extra.pop("generic_name", f"Paracetamol {n()}"),
        base_unit_code="tablet",
        base_unit_name_ar="حبة",
        base_unit_name_en="tablet",
        **extra,
    )


def store(code: str | None = None) -> Any:
    from apps.pharmacy.models import Store

    code = code or f"ST{n()}"
    return Store.objects.create(code=code, name_ar=code, name_en=code)


def batch(it: Any | None = None, expiry: date | None = None) -> Any:
    from apps.pharmacy.models import Batch

    return Batch.objects.create(
        item=it or item(),
        batch_no=f"B{n()}",
        expiry_date=expiry or date(2028, 1, 1),
        unit_cost=Decimal("2.5000"),
    )


def stock_move(b: Any, st: Any, qty: str, kind: str = "receipt") -> Any:
    from apps.pharmacy.models import StockMove

    return StockMove.objects.create(
        item=b.item,
        batch=b,
        store=st,
        qty_base=Decimal(qty),
        kind=kind,
        source_type="test",
        unit_cost=b.unit_cost,
        created_by=user(),
    )
