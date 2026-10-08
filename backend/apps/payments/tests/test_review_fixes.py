"""Regression tests for the Phase 1 review: frozen shift reports, cash outside the drawers,
handovers, refund duties, merged files, duplicate overrides and the money backstops
(invariants 3 and 4; FEATURES 1.4-1.5, 6.2, 6.7, 7.3-7.6).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.db import connection
from django.utils import timezone

from api.errors import PermissionRequired
from apps.core.tests import builders as b
from apps.ledger import services as ledger
from apps.ledger.models import Account, JournalEntry, JournalLine
from apps.orders import services as orders
from apps.patients import services as patients
from apps.payments import services as pay
from apps.payments.models import Allocation, Bank, CashHandover, Payment, Refund
from apps.payments.tests import fin
from domain.errors import DomainError
from domain.payments import normalize_reference

D = Decimal
pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _seed() -> None:
    fin.seed()


def _bok() -> Bank:
    return Bank.objects.get(code="BOK")


# --- a closed shift's report never changes (invariant 3, FEATURES 7.3) --------------------


def test_closed_shift_report_is_frozen_and_late_effects_go_to_the_acting_shift() -> None:
    """Review: a transfer confirmed or rejected after close rewrote the closed shift's report
    (bank_pending 130 -> 0, rejected 80, confirmed 50) and the rejection counted twice."""
    cashier = fin.staff("cashier")
    supervisor = fin.staff("cashier_supervisor")
    shift = pay.open_shift(cashier, D("500.00"))
    t1 = pay.record_payment(
        shift,
        fin.patient(),
        "bank_transfer",
        D("80.00"),
        actor=cashier,
        bank=_bok(),
        reference="A1",
    )
    t2 = pay.record_payment(
        shift,
        fin.patient(),
        "bank_transfer",
        D("50.00"),
        actor=cashier,
        bank=_bok(),
        reference="A2",
    )
    pay.close_shift(shift, D("500.00"), actor=cashier)
    before = pay.shift_summary(shift)
    assert before.frozen
    assert (before.collection.bank_pending, len(before.pending)) == (D("130.00"), 2)

    acting = pay.open_shift(supervisor, D("0.00"))
    pay.reject_transfer(t1, actor=supervisor, reason="NOT_RECEIVED", note="bounced")
    pay.confirm_transfer(t2, actor=supervisor, note="statement ok")
    assert pay.shift_summary(shift) == before
    late = pay.shift_summary(acting)
    assert (late.late_reversals, late.late_confirmations) == (D("80.00"), D("50.00"))


def test_shift_report_lists_references_reasons_and_credits() -> None:
    supervisor = fin.staff("cashier_supervisor")
    doctor = fin.staff("doctor")
    shift = pay.open_shift(supervisor, D("0.00"))
    patient = fin.patient()
    visit = fin.visit(patient)
    (line,) = fin.order(visit, doctor, fin.priced("lab", "70.00"))
    fin.invoice(visit, supervisor)
    t = pay.record_payment(
        shift,
        patient,
        "bank_transfer",
        D("70.00"),
        actor=supervisor,
        bank=_bok(),
        reference="R9",
        auto=True,
    )
    # A second checker confirms (ADR 0008: never the one who took it).
    pay.confirm_transfer(t, actor=fin.staff("accountant"), note="statement")
    pay.record_payment(shift, patient, "cash", D("25.00"), actor=supervisor)  # left as credit
    orders.cancel_line(line, "EQUIPMENT_DOWN", supervisor, note="analyser down")
    report = pay.shift_summary(shift)
    assert [(t.reference, t.amount) for t in report.confirmed_transfers] == [("R9", D("70.00"))]
    assert [(c.reason, c.count, c.amount) for c in report.cancellations] == [
        ("SERVICE_CANCELLED", 1, D("70.00"))
    ]
    assert report.credit_from_cancellations == D("70.00")
    assert report.credit_unallocated == D("25.00")


# --- cash outside the drawers (ADR 0006) --------------------------------------------------


def test_handover_to_the_bank_moves_ledger_cash_to_bank() -> None:
    """Review: 1000 cash handed over as a bank deposit stayed in ledger CASH forever."""
    cashier = fin.staff("cashier")
    shift = pay.open_shift(cashier, D("0.00"))
    pay.record_payment(shift, fin.patient(), "cash", D("1000.00"), actor=cashier)
    pay.cash_handover(shift, D("1000.00"), "bank_deposit", actor=cashier, bank_reference="DEP-1")
    assert ledger.account_balance("CASH", shift=shift) == D("0.00") == pay.expected_cash(shift)
    pay.close_shift(shift, D("0.00"), actor=cashier)
    assert ledger.account_balance("CASH") == D("0.00")
    assert ledger.account_balance("BANK") == D("1000.00")
    fin.assert_books_balance()


def test_ledger_cash_of_a_shift_is_its_drawer() -> None:
    """Review: after 300 in and 200 to the safe, the drawer held 100 but ledger CASH 300."""
    cashier = fin.staff("cashier")
    shift = pay.open_shift(cashier, D("50.00"))
    pay.record_payment(shift, fin.patient(), "cash", D("300.00"), actor=cashier)
    pay.cash_handover(shift, D("200.00"), "safe", actor=cashier)
    assert pay.expected_cash(shift) == D("150.00")
    assert ledger.account_balance("CASH", shift=shift) == D("150.00")
    assert ledger.account_balance("CASH_SAFE") == D("150.00")  # 200 in, the 50 float out
    pay.close_shift(shift, D("150.00"), actor=cashier)
    assert ledger.account_balance("CASH", shift=shift) == D("0.00")
    assert ledger.account_balance("CASH_SAFE") == D("300.00")


def test_unreceived_handover_blocks_the_receivers_close_and_can_be_cancelled() -> None:
    """Review: cash handed to the next shift vanished when that shift closed unreceived."""
    a, c = fin.staff("cashier"), fin.staff("cashier")
    sa = pay.open_shift(a, D("0.00"))
    sb = pay.open_shift(c, D("0.00"))
    pay.record_payment(sa, fin.patient(), "cash", D("300.00"), actor=a)
    h = pay.cash_handover(sa, D("300.00"), "next_shift", actor=a, to_shift=sb)
    with pytest.raises(DomainError) as exc:
        pay.close_shift(sb, D("0.00"), actor=c)
    assert exc.value.code == "HANDOVER_PENDING"
    with pytest.raises(DomainError) as exc:
        pay.cancel_handover(h, actor=a, note="")
    assert exc.value.code == "REASON_REQUIRED"
    pay.cancel_handover(h, actor=a, note="the next cashier is not in")
    assert pay.expected_cash(sa) == D("300.00") == ledger.account_balance("CASH", shift=sa)
    with pytest.raises(DomainError) as exc:
        pay.receive_handover(h, actor=c)
    assert exc.value.code == "HANDOVER_CANCELLED"
    pay.close_shift(sb, D("0.00"), actor=c)
    h2 = pay.cash_handover(sa, D("100.00"), "safe", actor=a)
    pay.close_shift(sa, D("200.00"), actor=a)
    with pytest.raises(DomainError) as exc:
        pay.cancel_handover(h2, actor=a, note="too late")
    assert exc.value.code == "SHIFT_CLOSED"
    fin.assert_books_balance()


def test_received_handover_enters_the_receiving_drawer() -> None:
    a, c = fin.staff("cashier"), fin.staff("cashier")
    sa = pay.open_shift(a, D("0.00"))
    sb = pay.open_shift(c, D("0.00"))
    pay.record_payment(sa, fin.patient(), "cash", D("120.00"), actor=a)
    h = pay.cash_handover(sa, D("120.00"), "next_shift", actor=a, to_shift=sb)
    pay.receive_handover(h, actor=c)
    assert ledger.account_balance("CASH", shift=sb) == D("120.00") == pay.expected_cash(sb)
    assert ledger.account_balance("CASH_SAFE") == D("0.00")


# --- refunds: segregation of duties (FLOW 8, invariant 4) ---------------------------------


def test_one_supervisor_cannot_request_approve_and_pay_their_own_refund() -> None:
    """Review: one supervisor cancelled a paid line, approved the refund it opened and paid
    it from their own shift."""
    sup = fin.staff("cashier_supervisor")
    shift = pay.open_shift(sup, D("1000.00"))
    patient = fin.patient()
    v = fin.visit(patient)
    (line,) = fin.order(v, fin.staff("doctor"), fin.priced("lab", "300.00"))
    inv = fin.invoice(v, sup)
    pay.record_payment(
        shift, patient, "cash", D("300.00"), actor=sup, allocations=[(inv, D("300"))]
    )
    orders.cancel_line(line, "PATIENT_REFUSED", sup)
    refund = Refund.objects.get(patient=patient)
    assert refund.requested_by == sup
    with pytest.raises(DomainError) as exc:
        pay.approve_refund(refund, actor=sup)
    assert exc.value.code == "SELF_APPROVAL_NOT_ALLOWED"
    approved = pay.approve_refund(refund, actor=fin.staff("accountant"))
    assert approved.decided_by != approved.requested_by
    paid = pay.pay_refund(approved, actor=sup)
    assert paid.status == "paid"


def test_refund_request_and_payment_need_their_permissions() -> None:
    doctor = fin.staff("doctor")
    sup = fin.staff("cashier_supervisor")
    shift = pay.open_shift(sup, D("100.00"))
    patient = fin.patient()
    v = fin.visit(patient)
    (line,) = fin.order(v, doctor, fin.priced("lab", "40.00"))
    inv = fin.invoice(v, sup)
    pay.record_payment(shift, patient, "cash", D("40.00"), actor=sup, allocations=[(inv, D("40"))])
    orders.cancel_line(line, "PATIENT_REFUSED", sup, open_refund=False)
    from apps.billing.models import CreditNote

    cn = CreditNote.objects.get(invoice=inv)
    with pytest.raises(PermissionRequired):
        pay.request_refund(
            patient, D("40.00"), credit_note=cn, actor=doctor, reason="OTHER", note="x"
        )
    refund = pay.request_refund(
        patient, D("40.00"), credit_note=cn, actor=sup, reason="SERVICE_CANCELLED"
    )
    pay.approve_refund(refund, actor=fin.staff("accountant"))
    with pytest.raises(PermissionRequired):
        pay.pay_refund(refund, actor=doctor)


def test_db_refuses_self_approved_and_rewritten_refunds() -> None:
    inv = b.approved_invoice()
    u = b.user()
    r = Refund.objects.create(
        number=f"RF-{b.n()}",
        patient=inv.patient,
        amount=D("50.00"),
        service_line=inv.lines.get().service_line,
        reason_code=b.reason("refund"),
        requested_by=u,
    )
    b.db_rejects(
        lambda: Refund.objects.filter(pk=r.pk).update(
            status="approved", decided_by=u, decided_at=timezone.now()
        ),
        "payments_refund_approver_not_requester",
    )
    Refund.objects.filter(pk=r.pk).update(
        status="approved", decided_by=b.user(), decided_at=timezone.now()
    )
    b.db_rejects(
        lambda: Refund.objects.filter(pk=r.pk).update(amount=D("5000.00")), "Cannot update"
    )


def test_db_refuses_moving_verification_back_to_pending() -> None:
    p = b.payment(method="bank_transfer")
    Payment.objects.filter(pk=p.pk).update(
        verification="confirmed", verified_by=b.user(), verified_at=timezone.now()
    )
    b.db_rejects(
        lambda: Payment.objects.filter(pk=p.pk).update(verification="pending"),
        "PAYMENT_VERIFICATION_TRANSITION",
    )


# --- closed-shift backstops (invariant 3) -------------------------------------------------


def test_db_refuses_changes_to_a_closed_shifts_handover() -> None:
    sh = b.shift()
    h = CashHandover.objects.create(
        number=f"HND-{b.n()}",
        shift=sh,
        destination="safe",
        amount=D("300.00"),
        handed_by=sh.cashier,
        handed_at=timezone.now(),
    )
    b.close_shift(sh)
    b.db_rejects(
        lambda: CashHandover.objects.filter(pk=h.pk).update(amount=D("1.00")), "HANDOVER_READONLY"
    )
    b.sql_rejects("DELETE FROM payments_cashhandover WHERE id = %s", [h.pk], "HANDOVER_PERMANENT")


def test_db_refuses_receiving_into_a_closed_shift() -> None:
    src, dst = b.shift(), b.shift()
    h = CashHandover.objects.create(
        number=f"HND-{b.n()}",
        shift=src,
        destination="next_shift",
        to_shift=dst,
        amount=D("300.00"),
        handed_by=src.cashier,
        handed_at=timezone.now(),
    )
    b.close_shift(dst)
    b.db_rejects(
        lambda: CashHandover.objects.filter(pk=h.pk).update(
            received_at=timezone.now(), received_by=dst.cashier
        ),
        "SHIFT_NOT_OPEN",
    )


def test_db_refuses_ledger_and_allocation_rows_on_a_closed_shift() -> None:
    from apps.ledger.chart import ensure_chart_of_accounts

    ensure_chart_of_accounts()
    sh = b.shift()
    payment = b.payment(sh, amount=D("100.00"))
    inv = b.approved_invoice()
    b.close_shift(sh)
    b.db_rejects(
        lambda: JournalEntry.objects.create(
            source_type="refund", source_id=1, entry_date=timezone.localdate(), shift=sh
        ),
        "SHIFT_NOT_OPEN",
    )
    with b.rolled_back():
        entry = JournalEntry.objects.create(
            source_type="refund", source_id=1, entry_date=timezone.localdate()
        )
        b.db_rejects(
            lambda: JournalLine.objects.create(
                entry=entry,
                account=Account.objects.get(code="CASH"),
                credit=D("50.00"),
                shift=sh,
            ),
            "SHIFT_NOT_OPEN",
        )
    b.db_rejects(
        lambda: Allocation.objects.create(
            payment=payment, invoice=inv, amount=D("100.00"), shift=sh, created_by=b.user()
        ),
        "SHIFT_NOT_OPEN",
    )


# --- merged files share their money (FEATURES 1.4, 1.5) -----------------------------------


def test_merged_files_money_shows_and_stays_usable_on_the_survivor() -> None:
    """Review: a duplicate's 500 credit vanished from the surviving file after a merge, and
    money could still be taken on the merged file."""
    from apps.core.models import Policy

    Policy.objects.update(allow_partial_payment=True)
    cashier = fin.staff("cashier")
    admin = fin.staff("admin")
    doctor = fin.staff("doctor")
    dup, survivor = fin.patient(), fin.patient()
    shift = pay.open_shift(cashier, D("0.00"))
    pay.record_payment(shift, dup, "cash", D("500.00"), actor=cashier)
    v = fin.visit(dup)
    (dup_line,) = fin.order(v, doctor, fin.priced("lab", "80.00"))
    dup_invoice = fin.invoice(v, cashier)
    patients.merge_patients(dup, survivor, actor=admin, reason_note="same person")
    balance = pay.patient_balance(patients.resolve(dup))
    assert (balance.credit, balance.spendable, balance.outstanding) == (
        D("500.00"),
        D("500.00"),
        D("80.00"),
    )
    with pytest.raises(DomainError) as exc:
        pay.record_payment(shift, dup, "cash", D("100.00"), actor=cashier)
    assert exc.value.code == "PATIENT_MERGED"
    # The survivor pays the duplicate's invoice; the duplicate's credit is spent from its file.
    pay.record_payment(
        shift, survivor, "cash", D("30.00"), actor=cashier, allocations=[(dup_invoice, D("30"))]
    )
    pay.record_payment(shift, dup, "patient_credit", D("50.00"), actor=cashier)
    from apps.billing import services as billing

    assert billing.invoice_position(dup_invoice).outstanding == D("0.00")
    assert pay.patient_balance(survivor).credit == D("450.00")
    fin.assert_positions_match_ledger(dup)
    # Cancelling the duplicate's paid line gives each file back what it paid.
    orders.cancel_line(dup_line, "PATIENT_REFUSED", cashier, approver=fin.staff("accountant"))
    refunds = {r.patient_id: r.amount for r in Refund.objects.filter(credit_note__isnull=False)}
    assert refunds == {survivor.pk: D("30.00"), dup.pk: D("50.00")}
    assert pay.credit_balance(survivor) == D("30.00")
    assert pay.credit_balance(dup) == D("500.00")
    fin.assert_positions_match_ledger(dup)
    fin.assert_books_balance()


# --- duplicate reference with a supervisor's approval (FEATURES 6.2) ----------------------


def test_cashier_records_a_duplicate_reference_with_a_supervisors_approval() -> None:
    cashier = fin.staff("cashier")
    supervisor = fin.staff("cashier_supervisor")
    shift = pay.open_shift(cashier, D("0.00"))
    pay.record_payment(
        shift,
        fin.patient(),
        "bank_transfer",
        D("10.00"),
        actor=cashier,
        bank=_bok(),
        reference="FT-77",
    )
    with pytest.raises(DomainError) as exc:
        pay.record_payment(
            shift,
            fin.patient(),
            "bank_transfer",
            D("10.00"),
            actor=cashier,
            bank=_bok(),
            reference="ft 77",
            override_reason="DUPLICATE_VERIFIED",
        )
    assert exc.value.code == "OVERRIDE_NOT_PERMITTED"
    with pytest.raises(PermissionRequired):
        pay.record_payment(
            shift,
            fin.patient(),
            "bank_transfer",
            D("10.00"),
            actor=cashier,
            bank=_bok(),
            reference="ft 77",
            override_reason="DUPLICATE_VERIFIED",
            override_approver=fin.staff("cashier"),
        )
    dup = pay.record_payment(
        shift,
        fin.patient(),
        "bank_transfer",
        D("10.00"),
        actor=cashier,
        bank=_bok(),
        reference="ft 77",
        override_reason="DUPLICATE_VERIFIED",
        override_approver=supervisor,
    )
    assert (dup.shift, dup.override_by, dup.duplicate_override) == (shift, supervisor, True)


# --- one definition of a reference (FEATURES 6.2) -----------------------------------------


@pytest.mark.parametrize(
    ("first", "second", "same"),
    [
        ("12345", "１２３４５", True),  # fullwidth digits are the ASCII reference
        ("حوالة-٥٥", "حوالة٥٥", True),  # Arabic letters stay, separators go
        ("حوالة-٥٥", "حوالة-٥٥ب", False),  # one more Arabic letter is another reference
        ("FT 12-3", "ft123", True),
    ],
)
def test_reference_uniqueness_uses_the_domain_normalization(first, second, same) -> None:
    """Review: the SQL normalizer dropped non-ASCII letters (false duplicates) and did no
    NFKC (fullwidth digits collided on '')."""
    cashier = fin.staff("cashier")
    shift = pay.open_shift(cashier, D("0.00"))
    p = pay.record_payment(
        shift,
        fin.patient(),
        "bank_transfer",
        D("1.00"),
        actor=cashier,
        bank=_bok(),
        reference=first,
    )
    assert p.reference_norm
    assert p.reference_norm == normalize_reference(first)
    if same:
        with pytest.raises(DomainError) as exc:
            pay.record_payment(
                shift,
                fin.patient(),
                "bank_transfer",
                D("1.00"),
                actor=cashier,
                bank=_bok(),
                reference=second,
            )
        assert exc.value.code == "DUPLICATE_REFERENCE"
    else:
        pay.record_payment(
            shift,
            fin.patient(),
            "bank_transfer",
            D("1.00"),
            actor=cashier,
            bank=_bok(),
            reference=second,
        )


# --- the trigger ignore hook and TRUNCATE ----------------------------------------------


def test_session_setting_cannot_switch_the_guards_off() -> None:
    """Review: SET LOCAL pgtrigger.ignore let an approved invoice go back to draft."""
    inv = b.approved_invoice(unit_price="100.00")
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT array_agg(tgname) FROM pg_trigger WHERE tgrelid = 'billing_invoice'::regclass"
        )
        names = cursor.fetchone()[0]
    ignore = "{" + ",".join(names) + "}"
    with b.rolled_back(), connection.cursor() as cursor:
        cursor.execute("SET LOCAL pgtrigger.ignore = %s", [ignore])
        b.sql_rejects(
            "UPDATE billing_invoice SET status = 'draft' WHERE id = %s", [inv.pk], "INVOICE_FROZEN"
        )


def test_truncate_of_a_protected_table_needs_the_owner() -> None:
    """Review: TRUNCATE wiped an append-only table. A role that is not the table owner (the
    production application role, ADR 0006) is refused even with the TRUNCATE grant."""
    role = f"hs_app_probe_{b.n()}"
    with b.rolled_back(), connection.cursor() as cursor:
        cursor.execute(f"CREATE ROLE {role} NOLOGIN")
        cursor.execute(f"GRANT USAGE ON SCHEMA public TO {role}")
        cursor.execute(f"GRANT TRUNCATE ON payments_allocation TO {role}")
        cursor.execute(f"SET LOCAL SESSION AUTHORIZATION {role}")
        b.sql_rejects("TRUNCATE payments_allocation", match="APPEND_ONLY")
