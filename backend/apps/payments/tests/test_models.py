"""Shift, payment, allocation, refund and handover schema (invariants 3, 4, 7; ARCH 4.6)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.tests import builders as b
from apps.payments.models import (
    Allocation,
    CashHandover,
    Payment,
    Refund,
    Shift,
    ShiftReview,
)

pytestmark = pytest.mark.django_db


# --- Shifts ------------------------------------------------------------------------------------


def test_one_open_shift_per_cashier() -> None:
    cashier = b.user()
    first = b.shift(cashier)
    with (
        pytest.raises(IntegrityError, match="payments_shift_one_open_per_cashier"),
        transaction.atomic(),
    ):
        b.shift(cashier)
    b.close_shift(first)
    b.shift(cashier)  # a new shift once the previous one is closed


def test_closed_shift_rejects_orm_update_and_delete() -> None:
    sh = b.close_shift(b.shift())
    b.db_rejects(lambda: Shift.objects.filter(pk=sh.pk).update(note="x"), "SHIFT_CLOSED")
    b.db_rejects(lambda: Shift.objects.filter(pk=sh.pk).delete(), "SHIFT_CLOSED")
    sh.counted_cash = Decimal("0")
    b.db_rejects(sh.save, "SHIFT_CLOSED")


def test_closed_shift_rejects_raw_sql_update_and_delete() -> None:
    sh = b.close_shift(b.shift())
    b.sql_rejects(
        "UPDATE payments_shift SET status = 'open' WHERE id = %s", [sh.pk], "SHIFT_CLOSED"
    )
    b.sql_rejects(
        "UPDATE payments_shift SET counted_cash = 5, variance = -995 WHERE id = %s",
        [sh.pk],
        "SHIFT_CLOSED",
    )
    b.sql_rejects("DELETE FROM payments_shift WHERE id = %s", [sh.pk], "SHIFT_CLOSED")


def test_open_shift_is_editable() -> None:
    sh = b.shift()
    Shift.objects.filter(pk=sh.pk).update(note="busy day")


def test_close_must_be_documented_and_variance_explained() -> None:
    sh = b.shift()
    b.db_rejects(
        lambda: Shift.objects.filter(pk=sh.pk).update(status="closed"),
        "payments_shift_close_documented",
    )
    common = {
        "status": "closed",
        "closed_at": timezone.now(),
        "closed_by": sh.cashier,
        "expected_cash": Decimal("1000.00"),
    }
    b.db_rejects(
        lambda: Shift.objects.filter(pk=sh.pk).update(
            **common, counted_cash=Decimal("990.00"), variance=Decimal("-10.00")
        ),
        "payments_shift_variance_explained",
    )
    b.db_rejects(
        lambda: Shift.objects.filter(pk=sh.pk).update(
            **common, counted_cash=Decimal("990.00"), variance=Decimal("0.00")
        ),
        "payments_shift_variance_is_counted_minus_expected",
    )
    Shift.objects.filter(pk=sh.pk).update(
        **common,
        counted_cash=Decimal("990.00"),
        variance=Decimal("-10.00"),
        variance_reason=b.reason("variance"),
    )


def test_shift_review_is_append_only() -> None:
    sh = b.close_shift(b.shift())
    review = ShiftReview.objects.create(shift=sh, outcome="approved", reviewed_by=b.user())
    b.db_rejects(
        lambda: ShiftReview.objects.filter(pk=review.pk).update(outcome="flagged"), "APPEND_ONLY"
    )
    b.sql_rejects("DELETE FROM payments_shiftreview WHERE id = %s", [review.pk], "APPEND_ONLY")
    with (
        pytest.raises(IntegrityError, match="payments_shiftreview_flag_explained"),
        transaction.atomic(),
    ):
        ShiftReview.objects.create(
            shift=b.close_shift(b.shift()), outcome="flagged", reviewed_by=b.user()
        )


# --- Nothing new on a closed shift (invariant 3) --------------------------------------------


def test_payment_on_closed_shift_rejected_orm_and_raw_sql() -> None:
    sh = b.close_shift(b.shift())
    b.db_rejects(lambda: b.payment(sh), "SHIFT_NOT_OPEN")
    pat = b.patient()
    user = b.user()
    b.sql_rejects(
        "INSERT INTO payments_payment (number, shift_id, patient_id, method, amount, reference, "
        "sender_name, verification, rejection_note, duplicate_override, override_note, note, "
        "created_by_id, created_at) VALUES ('RCP-X', %s, %s, 'cash', 10, '', '', 'confirmed', "
        "'', false, '', '', %s, now())",
        [sh.pk, pat.pk, user.pk],
        "SHIFT_NOT_OPEN",
    )


def test_refund_cannot_be_paid_from_a_closed_shift() -> None:
    inv = b.approved_invoice()
    line = inv.lines.get().service_line
    refund = Refund.objects.create(
        number="RF-1",
        patient=inv.patient,
        amount=Decimal("50.00"),
        service_line=line,
        reason_code=b.reason("refund"),
        requested_by=b.user(),
    )
    closed = b.close_shift(b.shift())
    b.db_rejects(
        lambda: Refund.objects.filter(pk=refund.pk).update(
            status="paid",
            decided_by=b.user(),
            decided_at=timezone.now(),
            shift=closed,
            paid_by=closed.cashier,
            paid_at=timezone.now(),
        ),
        "SHIFT_NOT_OPEN",
    )
    open_shift = b.shift()
    Refund.objects.filter(pk=refund.pk).update(
        status="paid",
        decided_by=b.user(),
        decided_at=timezone.now(),
        shift=open_shift,
        paid_by=open_shift.cashier,
        paid_at=timezone.now(),
    )
    # Paid refunds are final.
    b.sql_rejects(
        "UPDATE payments_refund SET amount = 1 WHERE id = %s", [refund.pk], "REFUND_FINAL"
    )
    b.db_rejects(lambda: Refund.objects.filter(pk=refund.pk).delete(), "REFUND_FINAL")


def test_handover_from_or_to_closed_shift_rejected() -> None:
    open_shift = b.shift()
    closed = b.close_shift(b.shift())

    def handover(**kw: object) -> CashHandover:
        return CashHandover.objects.create(
            number=f"HO-{b.n()}",
            amount=Decimal("100.00"),
            handed_by=b.user(),
            handed_at=timezone.now(),
            **kw,
        )

    b.db_rejects(lambda: handover(shift=closed, destination="safe"), "SHIFT_NOT_OPEN")
    b.db_rejects(
        lambda: handover(shift=open_shift, destination="next_shift", to_shift=closed),
        "SHIFT_NOT_OPEN",
    )
    handover(shift=open_shift, destination="safe")


def test_refund_needs_a_source_and_a_reason() -> None:
    pat = b.patient()
    with pytest.raises(IntegrityError, match="payments_refund_has_source"), transaction.atomic():
        Refund.objects.create(
            number="RF-2",
            patient=pat,
            amount=Decimal("5"),
            reason_code=b.reason("refund"),
            requested_by=b.user(),
        )


# --- Payments ------------------------------------------------------------------------------


def test_payment_money_fields_are_read_only_orm_and_raw_sql() -> None:
    pay = b.payment(amount=Decimal("200.00"))
    b.db_rejects(
        lambda: Payment.objects.filter(pk=pay.pk).update(amount=Decimal("1.00")), "Cannot update"
    )
    b.sql_rejects("UPDATE payments_payment SET amount = 1 WHERE id = %s", [pay.pk], "Cannot update")
    b.sql_rejects(
        "UPDATE payments_payment SET shift_id = %s WHERE id = %s",
        [b.shift().pk, pay.pk],
        "Cannot update",
    )


def test_payments_are_never_deleted() -> None:
    pay = b.payment()
    b.db_rejects(lambda: Payment.objects.filter(pk=pay.pk).delete(), "PAYMENT_PERMANENT")
    b.sql_rejects("DELETE FROM payments_payment WHERE id = %s", [pay.pk], "PAYMENT_PERMANENT")


def test_transfer_can_be_confirmed_after_its_shift_closed() -> None:
    sh = b.shift()
    pay = b.payment(sh, method="bank_transfer")
    b.close_shift(sh)
    Payment.objects.filter(pk=pay.pk).update(
        verification="confirmed", verified_by=b.user(), verified_at=timezone.now()
    )
    pay.refresh_from_db()
    assert pay.verification == "confirmed"


def test_rejected_transfer_is_final_and_documented() -> None:
    pay = b.payment(method="bank_transfer")
    b.db_rejects(
        lambda: Payment.objects.filter(pk=pay.pk).update(
            verification="rejected", verified_by=b.user(), verified_at=timezone.now()
        ),
        "payments_payment_rejection_has_reason",
    )
    Payment.objects.filter(pk=pay.pk).update(
        verification="rejected",
        verified_by=b.user(),
        verified_at=timezone.now(),
        rejection_reason=b.reason("transfer_reject"),
    )
    b.db_rejects(
        lambda: Payment.objects.filter(pk=pay.pk).update(verification="confirmed"),
        "PAYMENT_REJECTED",
    )


def test_confirmation_records_actor_and_time() -> None:
    pay = b.payment(method="qr")
    b.db_rejects(
        lambda: Payment.objects.filter(pk=pay.pk).update(verification="confirmed"),
        "payments_payment_verification_documented",
    )


def test_cash_is_confirmed_and_bank_methods_need_bank_and_reference() -> None:
    with (
        pytest.raises(IntegrityError, match="payments_payment_cash_is_confirmed_without_bank"),
        transaction.atomic(),
    ):
        b.payment(method="cash", verification="pending")
    with (
        pytest.raises(IntegrityError, match="payments_payment_bank_needs_reference"),
        transaction.atomic(),
    ):
        b.payment(method="bank_transfer", reference="")
    with pytest.raises(IntegrityError, match="payments_payment_amount_sign"), transaction.atomic():
        b.payment(amount=Decimal("-5.00"))


def test_bank_reference_unique_per_bank_after_normalization() -> None:
    b.payment(method="bank_transfer", reference="ft-123 abc")
    with (
        pytest.raises(IntegrityError, match="payments_payment_bank_reference_unique"),
        transaction.atomic(),
    ):
        b.payment(method="bank_transfer", reference="FT123ABC")
    # Arabic-Indic digits are the same reference too.
    b.payment(method="qr", reference="٧٧٧")
    with (
        pytest.raises(IntegrityError, match="payments_payment_bank_reference_unique"),
        transaction.atomic(),
    ):
        b.payment(method="qr", reference="777")
    # Same reference at another bank is a different transfer.
    b.payment(method="bank_transfer", reference="FT123ABC", bank=b.bank("FIB"))


def test_duplicate_reference_override_is_documented() -> None:
    original = b.payment(method="bank_transfer", reference="DUP1")
    with (
        pytest.raises(IntegrityError, match="payments_payment_override_documented"),
        transaction.atomic(),
    ):
        b.payment(method="bank_transfer", reference="DUP1", duplicate_override=True)
    dup = b.payment(
        method="bank_transfer",
        reference="DUP1",
        duplicate_override=True,
        duplicate_of=original,
        override_by=b.user(),
        override_reason=b.reason("override"),
        override_at=timezone.now(),
    )
    dup.refresh_from_db()
    assert dup.reference_norm == "DUP1"
    assert dup.duplicate_of == original


def test_reversal_is_a_negative_row_on_the_current_shift() -> None:
    sh = b.shift()
    original = b.payment(sh, method="bank_transfer", reference="REV1")
    b.close_shift(sh)
    reversal = b.payment(
        b.shift(),
        original.patient,
        method="bank_transfer",
        bank=original.bank,
        reference=original.reference,
        amount=Decimal("-100.00"),
        reversal_of=original,
        verification="confirmed",
        verified_by=b.user(),
        verified_at=timezone.now(),
    )
    assert original.reversal == reversal
    with pytest.raises(IntegrityError), transaction.atomic():
        b.payment(
            b.shift(),
            original.patient,
            method="cash",
            amount=Decimal("-100.00"),
            reversal_of=original,
        )


# --- Allocations (append-only) -------------------------------------------------------------


def _allocation(**kw: object) -> Allocation:
    defaults: dict[str, object] = {"amount": Decimal("100.00"), "created_by": b.user()}
    defaults.update(kw)
    return Allocation.objects.create(**defaults)


def test_allocation_is_append_only_orm_and_raw_sql() -> None:
    inv = b.approved_invoice()
    alloc = _allocation(payment=b.payment(pat=inv.patient), invoice=inv)
    b.db_rejects(
        lambda: Allocation.objects.filter(pk=alloc.pk).update(amount=Decimal("1")), "APPEND_ONLY"
    )
    b.db_rejects(lambda: Allocation.objects.filter(pk=alloc.pk).delete(), "APPEND_ONLY")
    b.sql_rejects(
        "UPDATE payments_allocation SET amount = 1 WHERE id = %s", [alloc.pk], "APPEND_ONLY"
    )
    b.sql_rejects("DELETE FROM payments_allocation WHERE id = %s", [alloc.pk], "APPEND_ONLY")
    # The correction is a new negative row.
    reversal = _allocation(
        payment=alloc.payment,
        invoice=inv,
        kind="reversal",
        amount=Decimal("-100.00"),
        reversal_of=alloc,
    )
    assert alloc.reversal == reversal


@pytest.mark.parametrize(
    "kw",
    [
        {"amount": Decimal("-1.00")},
        {"kind": "reversal", "amount": Decimal("-1.00")},
        {"kind": "reversal", "amount": Decimal("1.00")},
        {"kind": "deallocation", "amount": Decimal("-1.00")},
        {"amount": Decimal("0.00")},
    ],
)
def test_allocation_shape(kw: dict[str, object]) -> None:
    inv = b.approved_invoice()
    with (
        pytest.raises(IntegrityError, match="payments_allocation_kind_shape"),
        transaction.atomic(),
    ):
        _allocation(payment=b.payment(pat=inv.patient), invoice=inv, **kw)
