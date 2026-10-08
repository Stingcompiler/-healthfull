"""Builders for the financial engine's service tests (orders, billing, payments, ledger).

Unlike ``apps.core.tests.builders`` (raw rows for trigger tests), these go through the
services wherever a service exists, so tests exercise the real write path. Reference data
(prices, payers, coverage rules) is written directly: its own services belong to the
catalog app.

Transactional tests truncate migration seeds, so every test module calls :func:`seed` from
an autouse fixture.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any

from django.db.models import Sum

from apps.billing import services as billing
from apps.billing.models import Invoice
from apps.catalog.models import (
    CoverageRule,
    Exclusion,
    Payer,
    PriceItem,
    PriceList,
    PriceListVersion,
)
from apps.core.models import Department, Role, User, UserRole
from apps.core.reason_codes import ensure_reason_codes
from apps.core.tests import builders as b
from apps.ledger import services as ledger
from apps.ledger.chart import ensure_chart_of_accounts
from apps.ledger.models import JournalLine
from apps.orders import services as orders
from apps.orders.models import ServiceLine
from apps.patients.models import Patient, PatientCoverage
from apps.payments.models import Bank
from apps.visits.models import Visit

D = Decimal
_n = itertools.count(1)

#: Effective date of the reference price list versions (well before any test date).
SINCE = date(2020, 1, 1)


def seed() -> None:
    """Reference rows the services need, re-created after a transactional flush."""
    ensure_reason_codes()
    ensure_chart_of_accounts()
    for order, (code, name) in enumerate((("BOK", "Bankak"), ("FAISAL", "Faisal"))):
        Bank.objects.get_or_create(
            code=code, defaults={"name_ar": name, "name_en": name, "sort_order": order}
        )
    cash_list()


def staff(*roles: str, superuser: bool = False, **extra: Any) -> User:
    """A user holding ``roles``."""
    from conftest import ensure_reference_seed

    ensure_reference_seed()
    user = User(
        username=extra.pop("username", f"staff{next(_n)}"),
        must_change_password=False,
        is_superuser=superuser,
        **extra,
    )
    user.set_unusable_password()
    user.save()
    for code in roles:
        UserRole.objects.create(user=user, role=Role.objects.get(code=code))
    return user


def cash_list() -> PriceList:
    found = PriceList.objects.filter(is_default=True).first()
    if found is not None:
        return found
    return PriceList.objects.create(
        code="CASH", name_ar="نقدي", name_en="Cash", kind="cash", is_default=True
    )


def version(price_list: PriceList | None = None, on: date = SINCE) -> PriceListVersion:
    plist = price_list or cash_list()
    return PriceListVersion.objects.get_or_create(price_list=plist, effective_from=on)[0]


def set_price(
    service: Any, price: str | Decimal, *, price_list: PriceList | None = None, on: date = SINCE
) -> None:
    PriceItem.objects.update_or_create(
        version=version(price_list, on), service=service, defaults={"unit_price": D(price)}
    )


def priced(
    kind: str = "lab",
    price: str | Decimal = "100.00",
    *,
    price_list: PriceList | None = None,
    department: Department | None = None,
    **extra: Any,
) -> Any:
    """A service with a price in the cash list (or ``price_list``)."""
    svc = b.service(kind=kind, department=department, **extra)
    set_price(svc, price, price_list=price_list)
    return svc


def payer(
    *,
    percent: str | None = None,
    copay: str | None = None,
    ceiling: str | None = None,
    payer_percent: str | None = None,
    price_list: PriceList | None = None,
    preapproval: bool = False,
    service: Any | None = None,
    service_kind: str = "",
) -> Payer:
    """A payer with one coverage rule (default scope unless ``service``/``service_kind``)."""
    p = b.payer(price_list=price_list)
    if percent is not None:
        kind, fields = "percentage", {"payer_percent": D(percent)}
    elif copay is not None:
        kind, fields = "copay", {"copay_amount": D(copay)}
    elif ceiling is not None:
        kind = "ceiling"
        fields = {"ceiling_amount": D(ceiling)}
        if payer_percent is not None:
            fields["payer_percent"] = D(payer_percent)
    else:
        return p
    CoverageRule.objects.create(
        payer=p,
        service=service,
        service_kind=service_kind,
        rule_kind=kind,
        requires_pre_approval=preapproval,
        **fields,
    )
    return p


def exclude(p: Payer, service: Any) -> None:
    Exclusion.objects.create(payer=p, service=service)


def patient(**extra: Any) -> Patient:
    return b.patient(**extra)


def visit(
    pat: Patient | None = None,
    *,
    payer_obj: Payer | None = None,
    coverage: PatientCoverage | None = None,
    department: Department | None = None,
    **extra: Any,
) -> Visit:
    return b.visit(
        pat or b.patient(),
        payer=payer_obj or (coverage.payer if coverage else None),
        coverage=coverage,
        department=department,
        **extra,
    )


def order(v: Visit, actor: User, *items: Any, quantity: int = 1, **kw: Any) -> list[ServiceLine]:
    """Order services (or ``(service, quantity)`` pairs) on ``v`` through the service."""
    inputs = []
    for item in items:
        svc, qty = item if isinstance(item, tuple) else (item, quantity)
        inputs.append({"service": svc, "quantity": qty, **kw})
    return orders.create_service_lines(v, inputs, actor)


def invoice(v: Visit, actor: User, lines: Sequence[ServiceLine] | None = None) -> Invoice:
    """Create and approve an invoice of ``lines`` (default: every unbilled line)."""
    draft = billing.create_draft_invoice(
        v, actor, line_ids=[ln.pk for ln in lines] if lines is not None else None
    )
    return billing.approve_invoice(draft, actor=actor)


def some[T](value: T | None) -> T:
    """``value``, which the test knows is set (narrows ``Optional`` for the type checker)."""
    assert value is not None
    return value


def code(reason: Any) -> str:
    """The code of a stored reason (``ReasonCode | None`` on the model)."""
    return str(some(reason).code)


def refreshed(obj: Any) -> Any:
    obj.refresh_from_db()
    return obj


def assert_books_balance() -> None:
    """Every journal entry balances and the trial balance is zero."""
    tb = ledger.trial_balance()
    assert tb.balanced, tb
    sums = JournalLine.objects.values("entry_id").annotate(d=Sum("debit"), c=Sum("credit"))
    for row in sums:
        assert row["d"] == row["c"], row


def ar_patient(pat: Patient, inv: Invoice | None = None) -> Decimal:
    dims: dict[str, Any] = {"patient": pat}
    if inv is not None:
        dims["invoice"] = inv
    return ledger.account_balance("AR_PATIENT", **dims)


def assert_positions_match_ledger(pat: Patient) -> None:
    """Patient receivable per invoice in the ledger equals the documents' outstanding."""
    for inv in Invoice.objects.filter(patient=pat, status="approved"):
        assert ar_patient(pat, inv) == billing.invoice_position(inv).outstanding, inv.number
