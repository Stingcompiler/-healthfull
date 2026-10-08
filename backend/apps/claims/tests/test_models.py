"""Claims, responses and payer payments (FEATURES 11, invariant 7)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.claims.models import Claim, ClaimLine, PayerPayment, PayerPaymentAllocation
from apps.core.tests import builders as b

pytestmark = pytest.mark.django_db


def _claim_line(**kw: Any) -> ClaimLine:
    payer = b.payer()
    inv = b.draft_invoice()
    b.invoice_line(inv, payer_obj=payer, payer_share="80.00")
    b.approve_invoice(inv)
    claim = Claim.objects.create(
        number=f"CLM-{b.n()}",
        payer=payer,
        period_start=date(2026, 9, 1),
        period_end=date(2026, 9, 30),
        created_by=b.user(),
    )
    line = ClaimLine.objects.create(
        claim=claim, invoice_line=inv.lines.get(), amount_claimed=Decimal("80.00")
    )
    if kw:  # lines join a draft claim as pending; the answer comes afterwards
        ClaimLine.objects.filter(pk=line.pk).update(**kw)
        line.refresh_from_db()
    return line


def test_response_amounts_add_up() -> None:
    line = _claim_line()
    for kw, name in (
        ({"status": "accepted", "accepted_amount": Decimal("70")}, "claims_line_response_adds_up"),
        (
            {"status": "partial", "accepted_amount": Decimal("80")},
            "claims_line_partial_has_both",
        ),
        (
            {
                "status": "rejected",
                "accepted_amount": Decimal("10"),
                "rejected_amount": Decimal("70"),
            },
            "claims_line_rejected_has_no_acceptance",
        ),
    ):

        def respond(values: dict[str, Any] = kw) -> None:
            ClaimLine.objects.filter(pk=line.pk).update(**values)

        b.db_rejects(respond, name)
    ClaimLine.objects.filter(pk=line.pk).update(
        status="partial", accepted_amount=Decimal("50"), rejected_amount=Decimal("30")
    )


def test_rebill_or_write_off_is_documented() -> None:
    line = _claim_line(status="rejected", rejected_amount=Decimal("80.00"))
    b.db_rejects(
        lambda: ClaimLine.objects.filter(pk=line.pk).update(resolution="written_off"),
        "claims_line_resolution_documented",
    )
    ClaimLine.objects.filter(pk=line.pk).update(
        resolution="written_off",
        resolution_reason=b.reason("writeoff"),
        resolved_by=b.user(),
        resolved_at=timezone.now(),
    )


def test_invoice_line_is_claimed_once() -> None:
    line = _claim_line()
    with (
        pytest.raises(IntegrityError, match="claims_line_invoice_line_claimed_once"),
        transaction.atomic(),
    ):
        ClaimLine.objects.create(
            claim=line.claim, invoice_line=line.invoice_line, amount_claimed=Decimal("80")
        )
    b.db_rejects(
        lambda: ClaimLine.objects.filter(pk=line.pk).update(status="withdrawn"),
        "claims_line_withdrawal_documented",
    )
    ClaimLine.objects.filter(pk=line.pk).update(
        status="withdrawn", withdrawn_at=timezone.now(), withdrawn_by=b.user(), withdraw_note="x"
    )
    ClaimLine.objects.create(
        claim=line.claim, invoice_line=line.invoice_line, amount_claimed=Decimal("80")
    )


def test_closed_claim_is_final() -> None:
    line = _claim_line()
    Claim.objects.filter(pk=line.claim_id).update(
        status="closed", submitted_by=b.user(), submitted_at=timezone.now()
    )
    b.sql_rejects(
        "UPDATE claims_claim SET status = 'draft' WHERE id = %s", [line.claim_id], "CLAIM_FINAL"
    )


def _payer_payment(**kw: Any) -> PayerPayment:
    defaults: dict[str, Any] = {
        "number": f"PP-{b.n()}",
        "payer": b.payer(),
        "amount": Decimal("1000.00"),
        "bank": b.bank(),
        "reference": f"PP{b.n()}",
        "received_on": timezone.localdate(),
        "recorded_by": b.user(),
    }
    defaults.update(kw)
    return PayerPayment.objects.create(**defaults)


def test_payer_payment_money_is_read_only_and_permanent() -> None:
    pay = _payer_payment()
    b.db_rejects(
        lambda: PayerPayment.objects.filter(pk=pay.pk).update(amount=Decimal("1")), "Cannot update"
    )
    b.sql_rejects(
        "UPDATE claims_payerpayment SET amount = 1 WHERE id = %s", [pay.pk], "Cannot update"
    )
    b.sql_rejects("DELETE FROM claims_payerpayment WHERE id = %s", [pay.pk], "PAYMENT_PERMANENT")
    with (
        pytest.raises(IntegrityError, match="claims_payerpayment_reference_unique"),
        transaction.atomic(),
    ):
        _payer_payment(reference=pay.reference.lower())


def test_payer_allocation_is_append_only() -> None:
    line = _claim_line()
    alloc = PayerPaymentAllocation.objects.create(
        payer_payment=_payer_payment(payer=line.claim.payer),
        claim=line.claim,
        claim_line=line,
        amount=Decimal("80.00"),
        created_by=b.user(),
    )
    b.db_rejects(
        lambda: PayerPaymentAllocation.objects.filter(pk=alloc.pk).update(amount=Decimal("1")),
        "APPEND_ONLY",
    )
    b.sql_rejects(
        "DELETE FROM claims_payerpaymentallocation WHERE id = %s", [alloc.pk], "APPEND_ONLY"
    )
    with pytest.raises(IntegrityError, match="claims_payeralloc_amount_sign"), transaction.atomic():
        PayerPaymentAllocation.objects.create(
            payer_payment=alloc.payer_payment,
            claim=line.claim,
            amount=Decimal("-5"),
            created_by=b.user(),
        )
