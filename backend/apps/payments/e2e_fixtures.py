"""e2e builders of the cashier module (``manage.py e2e_fixture``, test databases only).

``cashier_screens``: the cashier queues and shift screens with data in them, for the
responsive matrix (see its summary).

``cashier_payer``: a payer that pays 70% of the cash price of every line, so a 10,000 service
(``PRC-ECG``) splits exactly 7,000 payer / 3,000 patient, the split the cashier specs check.
The seeded payers price from discounted lists (``AMAN`` = cash x 0.90), so none of them gives
that split. Reference data (payer, price list, coverage rule) is written like the base seed
writes it; the price list version goes through the catalog service.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.utils import timezone

from apps.billing import services as billing
from apps.billing.models import CreditNote, DocumentStatus, Invoice
from apps.catalog import services as catalog_services
from apps.catalog.models import (
    ClaimPeriod,
    CoverageRule,
    CoverageRuleKind,
    Payer,
    PayerKind,
    PriceList,
    PriceListKind,
    PriceListVersion,
)
from apps.core.e2e.fixtures import Json, Params, fixture, run_nested
from apps.core.models import User
from apps.payments import services as payments
from apps.payments.models import (
    CashHandover,
    HandoverDestination,
    Payment,
    Refund,
    RefundStatus,
    Shift,
    ShiftStatus,
    Verification,
)
from domain.errors import DomainError
from domain.money import ZERO

CODE = "CSH70"
CASH_LIST = "CASH"


@fixture(
    "cashier_payer",
    summary=(
        f"Payer {CODE}: cash prices, payer pays 70% of every line (idempotent); returns its code."
    ),
    params=(),
)
def cashier_payer(p: Params) -> Json:
    actor = p.actor("admin")
    today = timezone.localdate()
    plist, _ = PriceList.objects.update_or_create(
        code=CODE,
        defaults={
            "name_ar": "أسعار تأمين اختبار الكاشير",
            "name_en": "Cashier test insurance prices",
            "kind": PriceListKind.PAYER,
            "is_default": False,
            "active": True,
        },
    )
    if not PriceListVersion.objects.filter(price_list=plist).exists():
        cash = catalog_services.effective_version(PriceList.objects.get(code=CASH_LIST), today)
        catalog_services.create_version(
            plist,
            effective_from=today,
            prices=catalog_services.version_prices(cash),
            actor=actor,
            note="Cash prices (cashier e2e)",
            today=today,
        )
    payer, _ = Payer.objects.update_or_create(
        code=CODE,
        defaults={
            "name_ar": "تأمين اختبار الكاشير",
            "name_en": "Cashier test insurance",
            "kind": PayerKind.INSURANCE,
            "price_list": plist,
            "contract_no": "CSH-70",
            "contract_start": date(today.year, 1, 1),
            "contract_end": None,
            "claim_period": ClaimPeriod.MONTHLY,
            "requires_card_number": False,
            "active": True,
        },
    )
    CoverageRule.objects.update_or_create(
        payer=payer,
        service=None,
        service_kind="",
        active=True,
        defaults={
            "rule_kind": CoverageRuleKind.PERCENTAGE,
            "payer_percent": 70,
            "note": "70% of every line (cashier e2e)",
        },
    )
    return {"payer": payer.code, "id": payer.pk}


SCREENS_ACTOR = "admin"
SCREENS_FLOAT = Decimal("20000.00")
SCREENS_HANDOVER = Decimal("5000.00")


def _paid_invoice(actor: str) -> Invoice:
    """A new patient's consultation, invoiced and paid in cash in ``actor``'s open shift."""
    made = run_nested("paid_visit", {"cashier_as": actor})
    return Invoice.objects.get(pk=made["invoice"]["id"])


def _first_line(invoice: Invoice) -> int:
    return int(invoice.lines.order_by("line_no").values_list("pk", flat=True)[0])


@fixture(
    "cashier_screens",
    summary=(
        "Populated cashier screens for the responsive matrix, built once (idempotent, as "
        "`admin`): a closed shift with a variance awaiting review, the open shift with a "
        "handover to the safe in transit and a pending transfer (sender and date), a draft "
        "credit note and a requested refund. Returns the shift ids and the transfer."
    ),
    params=(),
)
def cashier_screens(p: Params) -> Json:
    actor = p.actor(SCREENS_ACTOR)
    # Workers resolve their routes at the same time: one builds, the others read.
    list(User.objects.select_for_update().filter(pk=actor.pk).values_list("pk", flat=True))
    if not CreditNote.objects.filter(created_by=actor, status=DocumentStatus.DRAFT).exists():
        inv = _paid_invoice(actor.username)
        billing.create_credit_note(
            inv, [(_first_line(inv), 1)], actor=actor, reason="SERVICE_CANCELLED"
        )
    if not Refund.objects.filter(requested_by=actor, status=RefundStatus.REQUESTED).exists():
        inv = _paid_invoice(actor.username)
        cn = billing.create_credit_note(
            inv, [(_first_line(inv), 1)], actor=actor, reason="SERVICE_CANCELLED"
        )
        # A second person approves the note (ADR 0008); the refund stays in the actor's name.
        billing.approve_credit_note(
            cn,
            actor=p.user("approver", "accountant"),
            open_refund=True,
            refund_requested_by=actor,
        )
    closed = (
        Shift.objects.filter(cashier=actor, status=ShiftStatus.CLOSED, review__isnull=True)
        .exclude(variance=ZERO)
        .order_by("-id")
        .first()
    )
    if closed is None:
        current = payments.current_shift(actor)
        if current is None:
            _paid_invoice(actor.username)  # opens the shift and puts cash in it
            current = payments.current_shift(actor)
        if current is None:  # pragma: no cover - paid_visit always opens the shift
            raise DomainError("SHIFT_NOT_OPEN", "The screens fixture found no open shift")
        expected = payments.expected_cash(current)
        closed = payments.close_shift(
            current, expected - Decimal("100.00"), actor=actor, reason="COUNTING_ERROR"
        )
    shift = payments.current_shift(actor) or payments.open_shift(actor, SCREENS_FLOAT)
    transfer = Payment.objects.filter(
        shift=shift, verification=Verification.PENDING, reversal_of__isnull=True
    ).first()
    if transfer is None:
        made = run_nested("patient", {"as": "reception"})
        visit = run_nested("visit", {"patient": made["patient"]["id"], "as": "reception"})
        vid = visit["visit"]["id"]
        run_nested("approve_invoice", {"visit": vid, "as": actor.username})
        paid = run_nested(
            "pay",
            {
                "visit": vid,
                "method": "bank_transfer",
                "sender_name": "Osman Ali",
                "transfer_date": timezone.localdate().isoformat(),
                "as": actor.username,
            },
        )
        transfer = Payment.objects.get(pk=paid["payment"]["id"])
    if not CashHandover.objects.filter(
        shift=shift, received_at__isnull=True, cancelled_at__isnull=True
    ).exists():
        if payments.expected_cash(shift) < SCREENS_HANDOVER:
            _paid_invoice(actor.username)
        payments.cash_handover(shift, SCREENS_HANDOVER, HandoverDestination.SAFE, actor=actor)
    return {
        "open_shift": shift.pk,
        "closed_shift": closed.pk,
        "transfer": {"id": transfer.pk, "number": transfer.number},
    }
