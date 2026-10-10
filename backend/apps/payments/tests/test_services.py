"""Shifts, payments, allocation, verification, refunds and handovers (ARCHITECTURE 4.6)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import DatabaseError, transaction
from django.utils import timezone

from api.errors import PermissionRequired
from apps.billing import services as billing
from apps.core.models import Notification, Policy
from apps.ledger import services as ledger
from apps.orders import services as orders
from apps.payments import services as pay
from apps.payments.models import Allocation, Bank, Payment, Refund, ShiftReview
from apps.payments.tests import fin
from domain.errors import DomainError

D = Decimal
pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _seed() -> None:
    fin.seed()


@pytest.fixture
def cashier():
    return fin.staff("cashier")


@pytest.fixture
def supervisor():
    return fin.staff("cashier_supervisor")


@pytest.fixture
def shift(cashier):
    return pay.open_shift(cashier, D("500.00"))


@pytest.fixture
def bok() -> Bank:
    return Bank.objects.get(code="BOK")


def _code(exc: pytest.ExceptionInfo[DomainError]) -> str:
    return exc.value.code


def _invoice(cashier, *prices: str, patient=None):
    """An approved invoice of lab lines at ``prices`` for ``patient`` (new one by default)."""
    doctor = fin.staff("doctor")
    visit = fin.visit(patient)
    lines = fin.order(visit, doctor, *(fin.priced("lab", p) for p in prices))
    return fin.invoice(visit, cashier), lines


def _transfer(shift, patient, amount, cashier, bok, ref="FT-1", **kw):
    return pay.record_payment(
        shift, patient, "bank_transfer", D(amount), actor=cashier, bank=bok, reference=ref, **kw
    )


# --- shifts ----------------------------------------------------------------------------------


def test_open_shift(cashier) -> None:
    sh = pay.open_shift(cashier, D("250.00"), note="morning")
    assert (sh.status, sh.cashier, sh.opening_float, sh.note) == (
        "open",
        cashier,
        D("250.00"),
        "morning",
    )
    assert sh.number.startswith("SH-")
    assert pay.current_shift(cashier) == sh
    with pytest.raises(DomainError) as exc:
        pay.open_shift(cashier, D("0.00"))
    assert _code(exc) == "SHIFT_ALREADY_OPEN"
    with pytest.raises(DomainError) as exc:
        pay.open_shift(fin.staff("cashier"), D("-1.00"))
    assert _code(exc) == "INVALID_AMOUNT"


def test_close_shift_without_variance(cashier, shift) -> None:
    patient = fin.patient()
    pay.record_payment(shift, patient, "cash", D("120.00"), actor=cashier)
    closed = pay.close_shift(shift, D("620.00"), actor=cashier)
    assert (closed.status, closed.expected_cash, closed.variance, closed.closed_by) == (
        "closed",
        D("620.00"),
        D("0.00"),
        cashier,
    )
    assert not ledger.entries_for(ledger.dl.SourceType.SHIFT_VARIANCE, shift.pk)
    assert not Notification.objects.filter(kind="shift_variance").exists()
    with pytest.raises(DomainError) as exc:
        pay.close_shift(shift, D("620.00"), actor=cashier)
    assert _code(exc) == "SHIFT_CLOSED"
    # A closed shift never takes money again (service and database).
    with pytest.raises(DomainError) as exc:
        pay.record_payment(shift, patient, "cash", D("1.00"), actor=cashier)
    assert _code(exc) == "SHIFT_CLOSED"
    with pytest.raises(DatabaseError, match="SHIFT_CLOSED"), transaction.atomic():
        type(shift).objects.filter(pk=shift.pk).update(note="edited")


def test_close_shift_variance_rules(cashier, shift, supervisor) -> None:
    manager = fin.staff("manager")
    with pytest.raises(DomainError) as exc:
        pay.close_shift(shift, D("480.00"), actor=cashier)
    assert _code(exc) == "VARIANCE_EXPLANATION_REQUIRED"
    with pytest.raises(DomainError) as exc:
        pay.close_shift(shift, D("480.00"), actor=cashier, reason="UNEXPLAINED")
    assert _code(exc) == "REASON_NOTE_REQUIRED"
    with pytest.raises(DomainError) as exc:
        pay.close_shift(shift, D("480.00"), actor=fin.staff("cashier"), reason="CHANGE_ERROR")
    assert _code(exc) == "SHIFT_NOT_YOURS"
    with pytest.raises(DomainError) as exc:
        pay.close_shift(shift, D("-1.00"), actor=cashier)
    assert _code(exc) == "INVALID_AMOUNT"
    # A supervisor (payments.view_all_shifts) may close another cashier's shift.
    closed = pay.close_shift(shift, D("480.00"), actor=supervisor, reason="CHANGE_ERROR")
    assert (closed.variance, fin.code(closed.variance_reason), closed.closed_by) == (
        D("-20.00"),
        "CHANGE_ERROR",
        supervisor,
    )
    assert ledger.account_balance("CASH_OVER_SHORT", shift=shift) == D("20.00")
    # The counted cash went to the safe (ADR 0006): the drawer is empty in the ledger and
    # the safe is 20 short of the 500 float it gave out.
    assert ledger.account_balance("CASH", shift=shift) == D("0.00")
    assert ledger.account_balance("CASH_SAFE") == D("-20.00")
    note = Notification.objects.get(user=manager, kind="shift_variance")
    assert note.payload["variance"] == "-20.00"
    fin.assert_books_balance()


def test_review_shift(cashier, shift, supervisor) -> None:
    manager = fin.staff("manager")
    with pytest.raises(DomainError) as exc:
        pay.review_shift(shift, actor=manager)
    assert _code(exc) == "SHIFT_NOT_CLOSED"
    pay.close_shift(shift, D("500.00"), actor=cashier)
    with pytest.raises(PermissionRequired):
        pay.review_shift(shift, actor=cashier)
    with pytest.raises(DomainError) as exc:
        pay.review_shift(shift, actor=manager, outcome="maybe")
    assert _code(exc) == "INVALID_REVIEW_OUTCOME"
    with pytest.raises(DomainError) as exc:
        pay.review_shift(shift, actor=manager, outcome="flagged")
    assert _code(exc) == "REASON_REQUIRED"
    own = pay.open_shift(supervisor, D("0.00"))
    pay.close_shift(own, D("0.00"), actor=supervisor)
    with pytest.raises(DomainError) as exc:
        pay.review_shift(own, actor=supervisor)
    assert _code(exc) == "SELF_REVIEW_NOT_ALLOWED"
    review = pay.review_shift(shift, actor=manager, outcome="flagged", note="check float")
    assert (review.outcome, review.reviewed_by) == ("flagged", manager)
    with pytest.raises(DomainError) as exc:
        pay.review_shift(shift, actor=supervisor)
    assert _code(exc) == "SHIFT_ALREADY_REVIEWED"
    assert ShiftReview.objects.count() == 1


# --- payments --------------------------------------------------------------------------------


def test_cash_payment_without_allocation_is_patient_credit(cashier, shift) -> None:
    patient = fin.patient()
    p = pay.record_payment(shift, patient, "cash", D("300.00"), actor=cashier, note="deposit")
    assert (p.verification, p.method, p.shift, p.created_by) == (
        "confirmed",
        "cash",
        shift,
        cashier,
    )
    assert p.number.startswith("RCP-")
    # The drawer in the ledger is the 500 float plus the payment (ADR 0006).
    assert ledger.account_balance("CASH", shift=shift) == D("800.00") == pay.expected_cash(shift)
    assert pay.credit_balance(patient) == D("300.00")
    balance = pay.patient_balance(patient)
    assert (balance.credit, balance.spendable, balance.pending, balance.net) == (
        D("300.00"),
        D("300.00"),
        D("0.00"),
        D("-300.00"),
    )


@pytest.mark.parametrize(
    ("method", "kwargs", "code"),
    [
        ("cheque", {}, "INVALID_PAYMENT_METHOD"),
        ("cash", {"amount": D("0.00")}, "INVALID_AMOUNT"),
        ("cash", {"amount": D("1.005")}, "INVALID_AMOUNT"),
        ("bank_transfer", {"reference": "X1"}, "BANK_REQUIRED"),
        ("bank_transfer", {"bank": "BOK", "reference": " - "}, "REFERENCE_REQUIRED"),
        ("qr", {"bank": "OFF", "reference": "Q1"}, "BANK_INACTIVE"),
    ],
)
def test_payment_validation(cashier, shift, method, kwargs, code) -> None:
    Bank.objects.create(code="OFF", name_ar="x", name_en="x", active=False)
    if "bank" in kwargs:
        kwargs["bank"] = Bank.objects.get(code=kwargs["bank"])
    amount = kwargs.pop("amount", D("10.00"))
    with pytest.raises(DomainError) as exc:
        pay.record_payment(shift, fin.patient(), method, amount, actor=cashier, **kwargs)
    assert _code(exc) == code


def test_payment_needs_the_cashiers_own_open_shift(cashier, shift) -> None:
    other = fin.staff("cashier")
    with pytest.raises(DomainError) as exc:
        pay.record_payment(shift, fin.patient(), "cash", D("1.00"), actor=other)
    assert _code(exc) == "SHIFT_NOT_YOURS"
    with pytest.raises(DomainError) as exc:
        pay.record_payment(None, fin.patient(), "cash", D("1.00"), actor=other)  # type: ignore[arg-type]
    assert _code(exc) == "SHIFT_NOT_OPEN"


def test_transfer_reference_is_unique_per_bank(cashier, shift, supervisor, bok) -> None:
    patient = fin.patient()
    first = _transfer(shift, patient, "100.00", cashier, bok, ref="ft-12 3")
    assert (first.verification, first.bank, first.transfer_date) == (
        "pending",
        bok,
        timezone.localdate(),
    )
    assert ledger.account_balance("BANK_PENDING") == D("100.00")
    with pytest.raises(DomainError) as exc:
        _transfer(shift, patient, "100.00", cashier, bok, ref="FT123")
    assert _code(exc) == "DUPLICATE_REFERENCE"
    # Another bank may use the same reference.
    _transfer(shift, patient, "100.00", cashier, Bank.objects.get(code="FAISAL"), ref="FT123")
    with pytest.raises(DomainError) as exc:
        _transfer(shift, patient, "100.00", cashier, bok, ref="FT123", override_reason="OTHER")
    assert _code(exc) == "REASON_NOTE_REQUIRED"
    with pytest.raises(DomainError) as exc:
        _transfer(
            shift,
            patient,
            "100.00",
            cashier,
            bok,
            ref="FT123",
            override_reason="DISCOUNT_ABOVE_LIMIT",
        )
    assert _code(exc) == "OVERRIDE_NOT_PERMITTED"
    sup_shift = pay.open_shift(supervisor, D("0.00"))
    dup = _transfer(
        sup_shift,
        patient,
        "100.00",
        supervisor,
        bok,
        ref="FT 123",
        override_reason="OTHER",
        override_note="two transfers, one reference (bank error)",
    )
    assert (dup.duplicate_override, dup.duplicate_of, dup.override_by) == (True, first, supervisor)
    assert dup.override_reason.code == "OTHER"
    assert dup.override_at is not None


def test_allocation_rules(cashier, shift) -> None:
    patient = fin.patient()
    inv_a, _ = _invoice(cashier, "100.00", patient=patient)
    inv_b, _ = _invoice(cashier, "50.00", patient=patient)
    stranger, _ = _invoice(cashier, "10.00")
    cases = [
        ([(inv_a, D("60.00"))], "PARTIAL_PAYMENT_NOT_ALLOWED"),
        ([(inv_a, D("120.00"))], "ALLOCATION_EXCEEDS_OUTSTANDING"),
        ([(stranger, D("10.00"))], "INVOICE_NOT_OPEN"),
        ([(inv_b, D("50.00")), (inv_b.pk, D("50.00"))], "DUPLICATE_ALLOCATION"),
        ([(inv_a, D("0.00"))], "INVALID_AMOUNT"),
        ([(inv_a, D("100.00")), (inv_b, D("50.00"))], "ALLOCATION_EXCEEDS_PAYMENT"),
    ]
    for allocations, code in cases:
        with pytest.raises(DomainError) as exc:
            pay.record_payment(
                shift, patient, "cash", D("120.00"), actor=cashier, allocations=allocations
            )
        assert _code(exc) == code, code
    assert not Payment.objects.exists()
    # One payment across two invoices; the remainder stays as credit.
    p = pay.record_payment(
        shift,
        patient,
        "cash",
        D("200.00"),
        actor=cashier,
        allocations=[(inv_a, D("100.00")), (inv_b, D("50.00"))],
    )
    assert sorted(Allocation.objects.filter(payment=p).values_list("amount", flat=True)) == [
        D("50.00"),
        D("100.00"),
    ]
    assert pay.credit_balance(patient) == D("50.00")
    assert billing.open_invoices(patient) == []
    with pytest.raises(DomainError) as exc:
        pay.allocate(p, [(inv_a, D("1.00"))], actor=cashier)
    assert _code(exc) == "INVOICE_NOT_OPEN"
    fin.assert_books_balance()
    fin.assert_positions_match_ledger(patient)


def test_partial_payment_policy_and_later_allocation(cashier, shift) -> None:
    Policy.objects.update(allow_partial_payment=True)
    patient = fin.patient()
    inv, (first, second) = _invoice(cashier, "60.00", "40.00", patient=patient)
    p = pay.record_payment(shift, patient, "cash", D("70.00"), actor=cashier)
    pay.allocate(p, [(inv, D("65.00"))], actor=cashier)
    first.refresh_from_db()
    second.refresh_from_db()
    assert (first.billing_status, second.billing_status) == ("settled", "invoiced")
    with pytest.raises(DomainError) as exc:
        pay.allocate(p, [(inv, D("10.00"))], actor=cashier)
    assert _code(exc) == "ALLOCATION_EXCEEDS_PAYMENT"
    pay.allocate(p, [(inv, D("5.00"))], actor=cashier)
    with pytest.raises(DomainError) as exc:
        pay.allocate(p, [(inv, D("1.00"))], actor=cashier)
    assert _code(exc) == "ALLOCATION_EXCEEDS_PAYMENT"
    second_payment = pay.record_payment(
        shift, patient, "cash", D("30.00"), actor=cashier, auto=True
    )
    second.refresh_from_db()
    assert second.billing_status == "settled"
    assert pay.auto_allocate(second_payment, actor=cashier) == []
    fin.assert_positions_match_ledger(patient)


def test_auto_allocation_pays_oldest_first(cashier, shift) -> None:
    patient = fin.patient()
    older, _ = _invoice(cashier, "30.00", patient=patient)
    newer, _ = _invoice(cashier, "20.00", patient=patient)
    p = pay.record_payment(shift, patient, "cash", D("25.00"), actor=cashier, auto=True)
    # Partial payment is off: the older invoice does not fit, the newer one is paid in full.
    assert list(Allocation.objects.filter(payment=p).values_list("invoice_id", "amount")) == [
        (newer.pk, D("20.00"))
    ]
    p2 = pay.record_payment(shift, patient, "cash", D("30.00"), actor=cashier)
    assert [a.invoice_id for a in pay.auto_allocate(p2, actor=cashier)] == [older.pk]
    assert pay.credit_balance(patient) == D("5.00")


def test_spending_patient_credit(cashier, shift, bok) -> None:
    patient = fin.patient()
    pay.record_payment(shift, patient, "cash", D("40.00"), actor=cashier)
    _transfer(shift, patient, "100.00", cashier, bok)  # pending: not spendable
    assert pay.spendable_credit(patient) == D("40.00")
    _invoice(cashier, "60.00", patient=patient)
    with pytest.raises(DomainError) as exc:
        pay.record_payment(shift, patient, "patient_credit", D("60.00"), actor=cashier)
    assert _code(exc) == "INSUFFICIENT_CREDIT"
    with pytest.raises(DomainError) as exc:  # credit spend must be allocated in full
        pay.record_payment(shift, patient, "patient_credit", D("30.00"), actor=cashier)
    assert _code(exc) == "ALLOCATION_INCOMPLETE"
    _small, (small_line,) = _invoice(cashier, "40.00", patient=patient)
    spend = pay.record_payment(shift, patient, "patient_credit", D("40.00"), actor=cashier)
    assert (spend.verification, spend.bank) == ("confirmed", None)
    small_line.refresh_from_db()
    assert small_line.billing_status == "settled"
    assert pay.spendable_credit(patient) == D("0.00")
    assert pay.credit_balance(patient) == D("100.00")  # the pending transfer
    assert not ledger.entries_for(ledger.dl.SourceType.PAYMENT, spend.pk)
    summary = pay.shift_summary(shift)
    assert (summary.collection.credit_used, summary.collection.confirmed_collection) == (
        D("40.00"),
        D("40.00"),
    )
    fin.assert_books_balance()


def test_credit_spend_with_nothing_to_pay_is_refused(cashier, shift) -> None:
    patient = fin.patient()
    pay.record_payment(shift, patient, "cash", D("40.00"), actor=cashier)
    with pytest.raises(DomainError) as exc:
        pay.record_payment(shift, patient, "patient_credit", D("10.00"), actor=cashier)
    assert _code(exc) == "ALLOCATION_INCOMPLETE"


# --- verification ----------------------------------------------------------------------------


def test_confirm_transfer(cashier, shift, supervisor, bok) -> None:
    patient = fin.patient()
    t = _transfer(shift, patient, "80.00", cashier, bok)
    with pytest.raises(PermissionRequired):
        pay.confirm_transfer(t, actor=cashier, note="seen")
    with pytest.raises(DomainError) as exc:
        pay.confirm_transfer(t, actor=supervisor, note=" ")
    assert _code(exc) == "REASON_REQUIRED"
    confirmed = pay.confirm_transfer(t, actor=supervisor, note="bank statement line 14")
    assert (confirmed.verification, confirmed.verified_by) == ("confirmed", supervisor)
    assert ledger.account_balance("BANK") == D("80.00")
    assert ledger.account_balance("BANK_PENDING") == D("0.00")
    with pytest.raises(DomainError) as exc:
        pay.confirm_transfer(t, actor=supervisor, note="again")
    assert _code(exc) == "PAYMENT_NOT_PENDING"
    cash = pay.record_payment(shift, patient, "cash", D("1.00"), actor=cashier)
    with pytest.raises(DomainError) as exc:
        pay.confirm_transfer(cash, actor=supervisor, note="cash")
    assert _code(exc) == "PAYMENT_NOT_PENDING"
    assert pay.shift_summary(shift).collection.bank_confirmed == D("80.00")


def test_reject_pending_transfer_in_open_shift(cashier, shift, supervisor, bok) -> None:
    manager = fin.staff("manager")
    patient = fin.patient()
    inv, (line,) = _invoice(cashier, "80.00", patient=patient)
    t = _transfer(shift, patient, "80.00", cashier, bok, allocations=[(inv, D("80.00"))])
    line.refresh_from_db()
    assert line.billing_status == "settled"  # pending money settles lines
    with pytest.raises(PermissionRequired):
        pay.reject_transfer(t, actor=cashier, reason="NOT_RECEIVED")
    with pytest.raises(DomainError) as exc:
        pay.reject_transfer(t, actor=supervisor, reason="OTHER")
    assert _code(exc) == "REASON_NOTE_REQUIRED"
    result = pay.reject_transfer(t, actor=supervisor, reason="NOT_RECEIVED", note="no credit")
    assert result.reversal is None  # its shift is open: the rejection belongs to it
    assert (result.payment.verification, fin.code(result.payment.rejection_reason)) == (
        "rejected",
        "NOT_RECEIVED",
    )
    (row,) = result.allocations
    assert (row.kind, row.amount, row.shift, fin.some(row.reversal_of).payment) == (
        "reversal",
        D("-80.00"),
        shift,
        t,
    )
    line.refresh_from_db()
    assert line.billing_status == "invoiced"
    assert billing.invoice_position(inv).outstanding == D("80.00")
    assert ledger.account_balance("BANK_PENDING") == D("0.00")
    assert pay.credit_balance(patient) == D("0.00")
    assert (
        Notification.objects.get(user=manager, kind="transfer_rejected").payload["after_close"]
        is False
    )
    with pytest.raises(DomainError) as exc:
        pay.reject_transfer(t, actor=supervisor, reason="NOT_RECEIVED")
    assert _code(exc) == "PAYMENT_NOT_REJECTABLE"
    with pytest.raises(DomainError) as exc:
        pay.allocate(t, [(inv, D("80.00"))], actor=cashier)
    assert _code(exc) == "PAYMENT_NOT_ALLOCATABLE"
    summary = pay.shift_summary(shift)
    assert (summary.collection.bank_rejected, summary.collection.bank_pending) == (
        D("80.00"),
        D("0.00"),
    )
    fin.assert_books_balance()
    fin.assert_positions_match_ledger(patient)


def test_reject_after_close_needs_an_open_shift(cashier, shift, supervisor, bok) -> None:
    patient = fin.patient()
    t = _transfer(shift, patient, "80.00", cashier, bok)
    pay.confirm_transfer(t, actor=supervisor, note="statement")
    pay.close_shift(shift, D("500.00"), actor=cashier)
    with pytest.raises(DomainError) as exc:
        pay.reject_transfer(t, actor=supervisor, reason="WRONG_AMOUNT")
    assert _code(exc) == "SHIFT_NOT_OPEN"
    own = pay.open_shift(supervisor, D("0.00"))
    result = pay.reject_transfer(t, actor=supervisor, reason="WRONG_AMOUNT")
    assert result.reversal is not None
    assert (result.reversal.shift, result.reversal.amount, result.reversal.reversal_of) == (
        own,
        D("-80.00"),
        t,
    )
    # A confirmed transfer leaves BANK, not BANK_PENDING.
    assert ledger.account_balance("BANK") == D("0.00")
    assert ledger.account_balance("BANK_PENDING") == D("0.00")
    assert pay.shift_summary(own).late_reversals == D("80.00")
    fin.assert_books_balance()


def test_rejection_recovers_spent_credit_newest_first(cashier, shift, supervisor, bok) -> None:
    """A confirmed transfer funded credit that was spent; its rejection takes the spend back."""
    manager = fin.staff("manager")
    patient = fin.patient()
    t = _transfer(shift, patient, "100.00", cashier, bok)
    pay.confirm_transfer(t, actor=supervisor, note="statement")
    inv1, (l1,) = _invoice(cashier, "30.00", patient=patient)
    inv2, (l2,) = _invoice(cashier, "50.00", patient=patient)
    pay.record_payment(shift, patient, "patient_credit", D("30.00"), actor=cashier)
    pay.record_payment(shift, patient, "patient_credit", D("50.00"), actor=cashier)
    pay.record_payment(shift, patient, "cash", D("10.00"), actor=cashier)
    # Pool 110 (100 transfer + 10 cash), 80 spent. Rejecting the 100 leaves -70: the newest
    # spend (50 on inv2) and 20 of the older one (inv1) are taken back.
    result = pay.reject_transfer(t, actor=supervisor, reason="DUPLICATE")
    assert sorted((r.invoice_id, r.amount) for r in result.allocations) == sorted(
        [(inv2.pk, D("-50.00")), (inv1.pk, D("-20.00"))]
    )
    assert result.uncovered == D("0.00")
    l1.refresh_from_db()
    l2.refresh_from_db()
    assert (l1.billing_status, l2.billing_status) == ("invoiced", "invoiced")
    assert pay.credit_balance(patient) == D("0.00")
    assert billing.invoice_position(inv1).outstanding == D("20.00")
    assert not Notification.objects.filter(user=manager, kind="patient_credit_negative").exists()
    fin.assert_books_balance()
    fin.assert_positions_match_ledger(patient)


def test_two_rejections_take_back_one_spend_in_parts(cashier, shift, supervisor, bok) -> None:
    """One credit-funded allocation row can be reversed in parts (schema: reversal_of is FK)."""
    patient = fin.patient()
    t1 = _transfer(shift, patient, "100.00", cashier, bok, ref="FT-A")
    t2 = _transfer(shift, patient, "50.00", cashier, bok, ref="FT-B")
    for t in (t1, t2):
        pay.confirm_transfer(t, actor=supervisor, note="statement")
    inv, _ = _invoice(cashier, "120.00", patient=patient)
    spend = pay.record_payment(shift, patient, "patient_credit", D("120.00"), actor=cashier)
    (spent,) = Allocation.objects.filter(payment=spend)
    first = pay.reject_transfer(t1, actor=supervisor, reason="DUPLICATE")
    second = pay.reject_transfer(t2, actor=supervisor, reason="DUPLICATE")
    assert [r.amount for r in first.allocations] == [D("-70.00")]
    assert [r.amount for r in second.allocations] == [D("-50.00")]
    assert sorted(spent.reversals.values_list("amount", flat=True)) == [D("-70.00"), D("-50.00")]
    assert billing.invoice_position(inv).outstanding == D("120.00")
    assert pay.credit_balance(patient) == D("0.00")
    fin.assert_books_balance()
    fin.assert_positions_match_ledger(patient)


def test_bounce_is_never_covered_by_pending_money(cashier, shift, supervisor, bok) -> None:
    """Regression: pending money must not absorb a confirmed bounce (ADR 0006 (p), 0015).

    The confirmed 100 was spent in full while a 10 transfer was still pending. Rejecting the
    100 must take the whole spend back; rejecting the pending 10 afterwards touches nothing
    but its own money.
    """
    manager = fin.staff("manager")
    patient = fin.patient()
    t = _transfer(shift, patient, "100.00", cashier, bok, ref="FT-A")
    pay.confirm_transfer(t, actor=supervisor, note="statement")
    inv, (line,) = _invoice(cashier, "100.00", patient=patient)
    pending = _transfer(shift, patient, "10.00", cashier, bok, ref="FT-B")
    assert pay.spendable_credit(patient) == D("100.00")
    spend = pay.record_payment(shift, patient, "patient_credit", D("100.00"), actor=cashier)
    first = pay.reject_transfer(t, actor=supervisor, reason="DUPLICATE")
    assert [(r.payment_id, r.amount) for r in first.allocations] == [(spend.pk, D("-100.00"))]
    assert first.uncovered == D("0.00")
    assert pay.credit_balance(patient) == D("10.00")  # still the pending transfer's money
    assert pay.spendable_credit(patient) == D("0.00")
    assert billing.invoice_position(inv).outstanding == D("100.00")
    line.refresh_from_db()
    assert line.billing_status == "invoiced"
    second = pay.reject_transfer(pending, actor=supervisor, reason="NOT_RECEIVED")
    assert (second.allocations, second.uncovered) == ((), D("0.00"))
    assert pay.credit_balance(patient) == D("0.00")
    assert not Notification.objects.filter(user=manager, kind="patient_credit_negative").exists()
    fin.assert_books_balance()
    fin.assert_positions_match_ledger(patient)


def test_rejection_after_refund_leaves_the_patient_owing(cashier, shift, supervisor, bok) -> None:
    manager = fin.staff("manager")
    accountant = fin.staff("accountant")  # approves refunds the supervisor requested
    doctor = fin.staff("doctor")
    patient = fin.patient()
    visit = fin.visit(patient)
    (line,) = fin.order(visit, doctor, fin.priced("lab", "60.00"))
    inv = fin.invoice(visit, cashier)
    t = _transfer(shift, patient, "60.00", cashier, bok, allocations=[(inv, D("60.00"))])
    pay.confirm_transfer(t, actor=supervisor, note="statement")
    orders.cancel_line(line, "EQUIPMENT_DOWN", supervisor)
    refund = Refund.objects.get()
    pay.approve_refund(refund, actor=accountant)
    pay.record_payment(shift, patient, "cash", D("100.00"), actor=cashier)  # a deposit
    pay.pay_refund(refund, actor=cashier)
    result = pay.reject_transfer(t, actor=supervisor, reason="NOT_RECEIVED")
    assert result.uncovered == D("0.00")
    assert pay.credit_balance(patient) == D("40.00")  # the deposit covers the bounce
    fin.assert_books_balance()
    # Without other money the pool goes negative and managers hear about it.
    other = fin.patient()
    visit2 = fin.visit(other)
    (line2,) = fin.order(visit2, doctor, fin.priced("lab", "30.00"))
    inv2 = fin.invoice(visit2, cashier)
    t2 = _transfer(
        shift, other, "30.00", cashier, bok, ref="FT-9", allocations=[(inv2, D("30.00"))]
    )
    pay.confirm_transfer(t2, actor=supervisor, note="statement")
    orders.cancel_line(line2, "EQUIPMENT_DOWN", supervisor)
    refund2 = Refund.objects.get(patient=other)
    pay.approve_refund(refund2, actor=accountant)
    pay.pay_refund(refund2, actor=cashier)
    result = pay.reject_transfer(t2, actor=supervisor, reason="NOT_RECEIVED")
    assert result.uncovered == D("30.00")
    assert pay.credit_balance(other) == D("-30.00")
    assert Notification.objects.filter(user=manager, kind="patient_credit_negative").exists()
    fin.assert_books_balance()


# --- refunds ---------------------------------------------------------------------------------


def _credit_from_cancel(cashier, supervisor, shift, price="70.00", method="cash", bok=None):
    doctor = fin.staff("doctor")
    patient = fin.patient()
    visit = fin.visit(patient)
    (line,) = fin.order(visit, doctor, fin.priced("lab", price))
    inv = fin.invoice(visit, cashier)
    if method == "cash":
        pay.record_payment(shift, patient, "cash", D(price), actor=cashier, auto=True)
    else:
        _transfer(shift, patient, price, cashier, bok, ref=f"R{price}", auto=True)
    orders.cancel_line(line, "SAMPLE_UNUSABLE", supervisor, open_refund=False)
    from apps.billing.models import CreditNote

    return patient, CreditNote.objects.get(invoice=inv), line


def test_refund_request_approve_pay(cashier, shift, supervisor) -> None:
    patient, cn, line = _credit_from_cancel(cashier, supervisor, shift)
    with pytest.raises(DomainError) as exc:
        pay.request_refund(
            patient, D("70.01"), credit_note=cn, actor=cashier, reason="SERVICE_CANCELLED"
        )
    assert _code(exc) == "REFUND_EXCEEDS_SOURCE"
    with pytest.raises(DomainError) as exc:
        pay.request_refund(
            fin.patient(), D("1.00"), credit_note=cn, actor=cashier, reason="SERVICE_CANCELLED"
        )
    assert _code(exc) == "REFUND_SOURCE_INVALID"
    with pytest.raises(DomainError) as exc:
        pay.request_refund(patient, D("1.00"), credit_note=cn, actor=cashier, reason="")
    assert _code(exc) == "REASON_REQUIRED"
    refund = pay.request_refund(
        patient,
        D("70.00"),
        credit_note=cn,
        actor=cashier,
        reason="SERVICE_CANCELLED",
        service_line=line,
    )
    assert (refund.status, refund.number[:4], refund.requested_by) == ("requested", "RFD-", cashier)
    with pytest.raises(DomainError) as exc:
        pay.pay_refund(refund, actor=cashier)
    assert _code(exc) == "REFUND_NOT_APPROVED"
    with pytest.raises(PermissionRequired):
        pay.approve_refund(refund, actor=cashier)
    approved = pay.approve_refund(refund, actor=supervisor, note="ok")
    assert (approved.status, approved.decided_by) == ("approved", supervisor)
    with pytest.raises(DomainError) as exc:
        pay.approve_refund(refund, actor=supervisor)
    assert _code(exc) == "REFUND_NOT_REQUESTED"
    with pytest.raises(DomainError) as exc:  # the source is used up by the open request
        pay.request_refund(
            patient, D("1.00"), credit_note=cn, actor=cashier, reason="SERVICE_CANCELLED"
        )
    assert _code(exc) == "REFUND_EXCEEDS_SOURCE"
    with pytest.raises(DomainError) as exc:
        pay.pay_refund(refund, actor=fin.staff("cashier"))
    assert _code(exc) == "SHIFT_NOT_OPEN"
    paid = pay.pay_refund(refund, actor=cashier)
    assert (paid.status, paid.shift, paid.paid_by) == ("paid", shift, cashier)
    assert pay.credit_balance(patient) == D("0.00")
    assert pay.expected_cash(shift) == D("500.00")  # 500 + 70 - 70
    assert ledger.account_balance("CASH", shift=shift) == D("500.00")  # the float
    with pytest.raises(DatabaseError, match="REFUND_FINAL"), transaction.atomic():
        Refund.objects.filter(pk=refund.pk).update(amount=D("1.00"))
    fin.assert_books_balance()


def test_refund_of_pending_money_waits_for_confirmation(cashier, shift, supervisor, bok) -> None:
    patient, cn, _ = _credit_from_cancel(cashier, supervisor, shift, method="transfer", bok=bok)
    refund = pay.request_refund(
        patient, D("70.00"), credit_note=cn, actor=cashier, reason="SERVICE_CANCELLED"
    )
    with pytest.raises(DomainError) as exc:
        pay.approve_refund(refund, actor=supervisor)
    assert _code(exc) == "REFUND_EXCEEDS_CREDIT"
    pay.confirm_transfer(Payment.objects.get(patient=patient), actor=supervisor, note="statement")
    pay.approve_refund(refund, actor=supervisor)


def test_refund_rejection_and_cash_limit(cashier, supervisor) -> None:
    shift = pay.open_shift(cashier, D("0.00"))
    patient, cn, _ = _credit_from_cancel(cashier, supervisor, shift)
    refund = pay.request_refund(
        patient, D("70.00"), credit_note=cn, actor=cashier, reason="SERVICE_CANCELLED"
    )
    pay.approve_refund(refund, actor=supervisor)
    pay.cash_handover(shift, D("50.00"), "safe", actor=cashier)
    with pytest.raises(DomainError) as exc:
        pay.pay_refund(refund, actor=cashier)
    assert _code(exc) == "CASH_INSUFFICIENT"
    with pytest.raises(DomainError) as exc:
        pay.reject_refund(refund, actor=supervisor, note="")
    assert _code(exc) == "REASON_REQUIRED"
    rejected = pay.reject_refund(refund, actor=supervisor, note="patient keeps credit")
    assert rejected.status == "rejected"
    assert pay.credit_balance(patient) == D("70.00")
    with pytest.raises(DomainError) as exc:
        pay.reject_refund(refund, actor=supervisor, note="again")
    assert _code(exc) == "REFUND_NOT_REQUESTED"


# --- handovers -------------------------------------------------------------------------------


def test_cash_handover_between_shifts(cashier, shift) -> None:
    patient = fin.patient()
    pay.record_payment(shift, patient, "cash", D("300.00"), actor=cashier)
    other = fin.staff("cashier")
    next_shift = pay.open_shift(other, D("0.00"))
    cases = [
        ({"amount": D("10.00"), "destination": "pocket"}, "INVALID_HANDOVER_DESTINATION"),
        ({"amount": D("10.00"), "destination": "next_shift"}, "HANDOVER_TARGET_REQUIRED"),
        (
            {"amount": D("10.00"), "destination": "next_shift", "to_shift": shift},
            "HANDOVER_TO_ITSELF",
        ),
        ({"amount": D("900.00"), "destination": "safe"}, "CASH_INSUFFICIENT"),
        ({"amount": D("0.00"), "destination": "safe"}, "INVALID_AMOUNT"),
    ]
    for kwargs, code in cases:
        with pytest.raises(DomainError) as exc:
            pay.cash_handover(
                shift, kwargs.pop("amount"), kwargs.pop("destination"), actor=cashier, **kwargs
            )
        assert _code(exc) == code, code
    with pytest.raises(DomainError) as exc:
        pay.cash_handover(shift, D("10.00"), "safe", actor=other)
    assert _code(exc) == "SHIFT_NOT_YOURS"
    h = pay.cash_handover(shift, D("200.00"), "next_shift", actor=cashier, to_shift=next_shift)
    assert (h.to_user, h.handed_by) == (other, cashier)
    assert pay.expected_cash(shift) == D("600.00")
    assert pay.expected_cash(next_shift) == D("0.00")  # not received yet
    with pytest.raises(DomainError) as exc:
        pay.receive_handover(h, actor=cashier)
    assert _code(exc) == "HANDOVER_SELF_RECEIPT"
    received = pay.receive_handover(h, actor=other)
    assert received.received_by == other
    assert pay.expected_cash(next_shift) == D("200.00")
    with pytest.raises(DomainError) as exc:
        pay.receive_handover(h, actor=other)
    assert _code(exc) == "HANDOVER_ALREADY_RECEIVED"
    pay.close_shift(next_shift, D("200.00"), actor=other)
    with pytest.raises(DomainError) as exc:
        pay.cash_handover(shift, D("10.00"), "next_shift", actor=cashier, to_shift=next_shift)
    assert _code(exc) == "SHIFT_CLOSED"
    late = pay.cash_handover(
        shift, D("10.00"), "supervisor", actor=cashier, to_user=fin.staff("manager")
    )
    with pytest.raises(DomainError) as exc:
        pay.receive_handover(late, actor=other)
    assert _code(exc) == "HANDOVER_NOT_YOURS"


def test_cash_to_the_safe_or_a_supervisor_is_confirmed_by_someone_else(cashier, shift) -> None:
    """FEATURES 7.6, invariant 4: cash leaving the drawer is never confirmed by its sender."""
    pay.record_payment(shift, fin.patient(), "cash", D("300.00"), actor=cashier)
    other_cashier = fin.staff("cashier")
    supervisor = fin.staff("cashier_supervisor")
    accountant = fin.staff("accountant")
    cases = [
        ({"destination": "supervisor"}, "HANDOVER_TARGET_REQUIRED"),
        ({"destination": "supervisor", "to_user": cashier}, "HANDOVER_TO_ITSELF"),
        ({"destination": "supervisor", "to_user": other_cashier}, "HANDOVER_RECEIVER_INVALID"),
        ({"destination": "safe", "to_user": fin.staff("doctor")}, "HANDOVER_RECEIVER_INVALID"),
    ]
    for kwargs, code in cases:
        with pytest.raises(DomainError) as exc:
            pay.cash_handover(shift, D("10.00"), kwargs.pop("destination"), actor=cashier, **kwargs)
        assert _code(exc) == code, code

    to_sup = pay.cash_handover(shift, D("50.00"), "supervisor", actor=cashier, to_user=supervisor)
    to_safe = pay.cash_handover(shift, D("40.00"), "safe", actor=cashier)
    deposit = pay.cash_handover(
        shift, D("30.00"), "bank_deposit", actor=cashier, bank_reference="DEP-1"
    )
    for h in (to_sup, to_safe, deposit):
        with pytest.raises(DomainError) as exc:
            pay.receive_handover(h, actor=cashier)
        assert _code(exc) == "HANDOVER_SELF_RECEIPT"
    for h in (to_sup, to_safe):
        with pytest.raises(DomainError) as exc:
            pay.receive_handover(h, actor=other_cashier)
        assert _code(exc) == "HANDOVER_NOT_YOURS"
    with pytest.raises(DomainError) as exc:
        pay.receive_handover(to_sup, actor=accountant)
    assert _code(exc) == "HANDOVER_NOT_YOURS"
    assert pay.receive_handover(to_sup, actor=supervisor).received_by == supervisor
    assert pay.receive_handover(to_safe, actor=accountant).received_by == accountant
    assert pay.receive_handover(deposit, actor=supervisor).received_by == supervisor


# --- reports ---------------------------------------------------------------------------------


def test_shift_summary_and_overdue_transfers(cashier, shift, supervisor, bok) -> None:
    patient = fin.patient()
    doctor = fin.staff("doctor")
    visit = fin.visit(patient)
    fin.order(visit, doctor, fin.priced("lab", "100.00"))
    draft = billing.create_draft_invoice(visit, cashier)
    billing.apply_discount(
        draft.lines.get(), actor=cashier, approver=supervisor, reason="STAFF", amount=D("20.00")
    )
    billing.approve_invoice(draft, actor=cashier)
    t = _transfer(shift, patient, "80.00", cashier, bok, auto=True)
    later = timezone.localdate() + timedelta(days=5)
    summary = pay.shift_summary(shift, today=later)
    assert [(p.payment_id, p.age_days) for p in summary.pending] == [(t.pk, 5)]
    assert [(d.user_id, d.amount) for d in summary.discounts] == [(supervisor.pk, D("20.00"))]
    assert summary.expected_cash == D("500.00")
    accountant = fin.staff("accountant")
    assert pay.notify_overdue_transfers(7, today=later) == 0
    assert pay.notify_overdue_transfers(3, today=later) >= 2
    note = Notification.objects.get(user=accountant, kind="transfers_pending_overdue")
    assert note.payload["payments"][0]["age"] == 5
