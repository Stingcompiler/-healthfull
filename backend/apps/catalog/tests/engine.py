"""Build service lines that are settled through the real financial engine (test support).

A payer that covers 100% of a service settles the line at invoice approval (zero patient
share), so stock, lab and claims tests can reach ``settled`` through ``orders`` and
``billing`` services without taking a payment.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from apps.core.tests import builders as b


def price_version() -> Any:
    from apps.catalog.models import PriceList, PriceListVersion

    plist = PriceList.objects.filter(is_default=True).first()
    if plist is None:
        return b.price_version()
    version, _ = PriceListVersion.objects.get_or_create(
        price_list=plist, effective_from=b.REFERENCE_VERSION_DATE
    )
    return version


def covering_payer(percent: int = 100) -> Any:
    from apps.catalog.models import CoverageRule

    payer = b.payer(requires_card_number=False)
    CoverageRule.objects.create(payer=payer, rule_kind="percentage", payer_percent=Decimal(percent))
    return payer


def settled_line(service: Any, quantity: int, actor: Any, *, unit_price: str = "10.00") -> Any:
    """A line of ``service`` on a new covered visit, invoiced and approved: settled."""
    from apps.billing import services as billing
    from apps.catalog.models import PriceItem
    from apps.orders import services as orders

    PriceItem.objects.get_or_create(
        version=price_version(), service=service, defaults={"unit_price": Decimal(unit_price)}
    )
    visit = b.visit(payer=covering_payer(100))
    [line] = orders.create_service_lines(visit, [{"service": service, "quantity": quantity}], actor)
    billing.approve_invoice(billing.create_draft_invoice(visit, actor), actor=actor)
    line.refresh_from_db()
    assert line.billing_status == "settled"
    return line


def cash_paid_line(
    service: Any, quantity: int, cashier: Any, *, unit_price: str = "10.00", visit: Any = None
) -> Any:
    """A cash patient's line: invoiced, paid in cash in the cashier's shift, settled."""
    from apps.billing import services as billing
    from apps.catalog.models import PriceItem
    from apps.orders import services as orders
    from apps.payments import services as payments

    PriceItem.objects.get_or_create(
        version=price_version(), service=service, defaults={"unit_price": Decimal(unit_price)}
    )
    visit = visit or b.visit()
    [line] = orders.create_service_lines(
        visit, [{"service": service, "quantity": quantity}], cashier
    )
    invoice = billing.approve_invoice(billing.create_draft_invoice(visit, cashier), actor=cashier)
    shift = payments.current_shift(cashier) or payments.open_shift(cashier, Decimal("0.00"))
    payments.record_payment(
        shift,
        visit.patient,
        "cash",
        invoice.patient_total,
        actor=cashier,
        allocations=[(invoice, invoice.patient_total)],
    )
    line.refresh_from_db()
    assert line.billing_status == "settled"
    return line
