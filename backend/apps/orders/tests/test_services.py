"""Service line write path: ordering, work lists, perform-first, cancelling (ARCHITECTURE 4.4)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.utils import timezone

from api.errors import PermissionRequired
from apps.billing import services as billing
from apps.billing.models import CreditNote, Invoice, InvoiceLine
from apps.core.models import Policy
from apps.core.tests import builders as b
from apps.orders import services as orders
from apps.orders.models import PerformAuthorization, PrescriptionDetail
from apps.payments import services as pay
from apps.payments.models import Refund
from apps.payments.tests import fin
from domain.errors import DomainError

D = Decimal
pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _seed() -> None:
    fin.seed()


@pytest.fixture
def doctor():
    return fin.staff("doctor")


@pytest.fixture
def cashier():
    return fin.staff("cashier")


@pytest.fixture
def supervisor():
    return fin.staff("cashier_supervisor")


def _code(exc: pytest.ExceptionInfo[DomainError]) -> str:
    return exc.value.code


def _paid(visit, cashier, *lines):
    """Invoice ``lines`` and pay them in cash from the cashier's shift."""
    inv = fin.invoice(visit, cashier, lines or None)
    shift = pay.current_shift(cashier) or pay.open_shift(cashier, D("0.00"))
    if inv.patient_total > 0:
        pay.record_payment(shift, inv.patient, "cash", inv.patient_total, actor=cashier, auto=True)
    return inv


# --- ordering --------------------------------------------------------------------------------


def test_create_lines_copies_service_payer_and_department(doctor) -> None:
    lab_dept, clinic = b.department(), b.department()
    insurer = fin.payer(percent="50")
    visit = fin.visit(payer_obj=insurer, department=clinic)
    cbc = fin.priced("lab", department=lab_dept)
    consult = fin.priced("consultation")  # no department: falls back to the visit's
    drug = fin.priced("drug")
    a, c, d = orders.create_service_lines(
        visit,
        [
            {"service": cbc, "pre_approval_ref": " PA-1 "},
            orders.LineInput(service=consult.pk, order_source="consultation_fee"),
            {
                "service": drug,
                "quantity": 20,
                "prescription": {"dose": "1 tab", "duration_days": 5},
            },
        ],
        doctor,
    )
    assert (a.kind, a.department, a.payer, a.pre_approval_ref) == ("lab", lab_dept, insurer, "PA-1")
    assert (a.billing_status, a.fulfilment_status, a.ordered_by) == ("unbilled", "pending", doctor)
    assert (c.department, c.order_source) == (clinic, "consultation_fee")
    assert d.quantity == D("20")
    assert PrescriptionDetail.objects.get(line=d).duration_days == 5
    assert orders.line_state(a) == "requested"


@pytest.mark.parametrize(
    ("item", "code"),
    [
        ({"quantity": 0}, "INVALID_QUANTITY"),
        ({"quantity": D("1.5")}, "INVALID_QUANTITY"),
        ({"order_source": "magic"}, "INVALID_ORDER_SOURCE"),
        ({"prescription": {"dose": "1"}}, "PRESCRIPTION_NOT_DRUG"),
        ({"colour": "red"}, "INVALID_ORDER_LINE"),
    ],
)
def test_create_lines_refuses_bad_input(doctor, item, code) -> None:
    visit = fin.visit()
    with pytest.raises(DomainError) as exc:
        orders.create_service_lines(visit, [{"service": fin.priced("lab"), **item}], doctor)
    assert _code(exc) == code


def test_create_lines_refuses_empty_inactive_and_closed_visit(doctor) -> None:
    visit = fin.visit()
    with pytest.raises(DomainError) as exc:
        orders.create_service_lines(visit, [], doctor)
    assert _code(exc) == "ORDER_EMPTY"
    with pytest.raises(DomainError) as exc:
        orders.create_service_lines(visit, [{"service": fin.priced(active=False)}], doctor)
    assert _code(exc) == "SERVICE_INACTIVE"
    closed = fin.visit(status="closed", closed_at=timezone.now(), closed_by=doctor)
    with pytest.raises(DomainError) as exc:
        orders.create_service_lines(closed, [{"service": fin.priced()}], doctor)
    assert _code(exc) == "VISIT_NOT_OPEN"


# --- work lists, start, perform --------------------------------------------------------------


def test_unpaid_lines_never_reach_work_or_worklists(doctor, cashier) -> None:
    """Invariant 1: no performance without a settled line or an authorization."""
    visit = fin.visit()
    (line,) = fin.order(visit, doctor, fin.priced("lab"))
    assert not orders.worklist("lab").exists()
    for action in (orders.start_line, orders.perform_line):
        with pytest.raises(DomainError) as exc:
            action(line, doctor)
        assert _code(exc) == "LINE_NOT_ELIGIBLE"
    fin.invoice(visit, cashier)  # invoiced but not paid: still not eligible
    with pytest.raises(DomainError) as exc:
        orders.perform_line(line, doctor)
    assert _code(exc) == "LINE_NOT_ELIGIBLE"


def test_paid_line_moves_through_work(doctor, cashier) -> None:
    lab_dept = b.department()
    visit = fin.visit()
    line, other = fin.order(
        visit, doctor, fin.priced("lab", department=lab_dept), fin.priced("lab")
    )
    _paid(visit, cashier, line)
    assert list(orders.worklist("lab")) == [line]
    assert list(orders.worklist(["lab", "drug"], department=lab_dept.pk)) == [line]
    assert not orders.worklist("lab", department=b.department().pk).exists()
    tech = fin.staff("lab_tech")
    started = orders.start_line(line, tech)
    assert (started.fulfilment_status, started.started_by) == ("in_progress", tech)
    with pytest.raises(DomainError) as exc:
        orders.start_line(line, tech)
    assert _code(exc) == "LINE_ALREADY_STARTED"
    assert list(orders.worklist("lab")) == [line]  # in progress stays on the list
    done = orders.perform_line(line, tech, note="ok")
    assert (done.fulfilment_status, done.performed_by, done.performed_note) == (
        "performed",
        tech,
        "ok",
    )
    assert done.performed_at is not None
    assert orders.line_state(done) == "performed"
    assert not orders.worklist("lab").exists()
    with pytest.raises(DomainError) as exc:
        orders.perform_line(line, tech)
    assert _code(exc) == "LINE_ALREADY_PERFORMED"
    assert other.billing_status == "unbilled"


def test_performed_quantity_is_bounded(doctor, cashier) -> None:
    visit = fin.visit()
    (line,) = fin.order(visit, doctor, fin.priced("drug", "10.00"), quantity=10)
    _paid(visit, cashier)
    for bad in (0, 11):
        with pytest.raises(DomainError) as exc:
            orders.perform_line(line, doctor, performed_quantity=bad)
        assert _code(exc) == "INVALID_QUANTITY"
    assert orders.perform_line(line, doctor, performed_quantity=6).performed_quantity == D("6")


# --- perform-first ---------------------------------------------------------------------------


def test_perform_first_authorization_opens_work_and_bills_later(doctor, cashier, supervisor):
    visit = fin.visit()
    line, untouched = fin.order(visit, doctor, fin.priced("procedure", "300.00"), fin.priced())
    auth = orders.authorize_perform_first(
        [line], actor=supervisor, reason="EMERGENCY", kind="emergency", note="bleeding"
    )
    assert (auth.authorized_by, auth.reason_code.code, auth.reason_note) == (
        supervisor,
        "EMERGENCY",
        "bleeding",
    )
    assert list(orders.worklist("procedure")) == [line]
    nurse = fin.staff("nurse")
    performed = orders.perform_line(line, nurse)
    assert (performed.billing_status, performed.fulfilment_status) == ("unbilled", "performed")
    # Billed afterwards from the same unbilled line.
    inv = fin.invoice(visit, cashier, [line])
    line.refresh_from_db()
    assert (line.billing_status, inv.patient_total) == ("invoiced", D("300.00"))
    untouched.refresh_from_db()
    assert untouched.authorization is None


def test_perform_first_rules(doctor, cashier, supervisor) -> None:
    visit = fin.visit()
    line, paid_line = fin.order(visit, doctor, fin.priced(), fin.priced())
    _paid(visit, cashier, paid_line)
    with pytest.raises(PermissionRequired):
        orders.authorize_perform_first([line], actor=cashier, reason="EMERGENCY")
    cases = [
        ({"reason": ""}, "REASON_REQUIRED"),
        ({"reason": "NOPE"}, "REASON_UNKNOWN"),
        ({"reason": "OTHER"}, "REASON_NOTE_REQUIRED"),
        ({"reason": "EMERGENCY", "kind": "whim"}, "INVALID_AUTHORIZATION_KIND"),
        (
            {"reason": "INSURANCE_APPROVED", "kind": "insurance_approval"},
            "APPROVAL_REFERENCE_REQUIRED",
        ),
    ]
    for kwargs, code in cases:
        with pytest.raises(DomainError) as exc:
            orders.authorize_perform_first([line], actor=supervisor, **kwargs)  # type: ignore[arg-type]
        assert _code(exc) == code, kwargs
    with pytest.raises(DomainError) as exc:
        orders.authorize_perform_first([paid_line], actor=supervisor, reason="EMERGENCY")
    assert _code(exc) == "LINE_ALREADY_SETTLED"
    (elsewhere,) = fin.order(fin.visit(), doctor, fin.priced())
    with pytest.raises(DomainError) as exc:
        orders.authorize_perform_first([line, elsewhere], actor=supervisor, reason="EMERGENCY")
    assert _code(exc) == "LINES_NOT_ONE_VISIT"
    with pytest.raises(DomainError) as exc:
        orders.authorize_perform_first([], actor=supervisor, reason="EMERGENCY")
    assert _code(exc) == "ORDER_EMPTY"
    orders.authorize_perform_first(
        [line],
        actor=supervisor,
        reason="INSURANCE_APPROVED",
        kind="insurance_approval",
        approval_reference="PA-9",
    )
    with pytest.raises(DomainError) as exc:
        orders.authorize_perform_first([line], actor=supervisor, reason="EMERGENCY")
    assert _code(exc) == "LINE_ALREADY_AUTHORIZED"


def test_perform_first_needs_a_policy_role(doctor, supervisor) -> None:
    (line,) = fin.order(fin.visit(), doctor, fin.priced())
    Policy.objects.update(perform_first_roles=["manager"])
    with pytest.raises(DomainError) as exc:
        orders.authorize_perform_first([line], actor=supervisor, reason="EMERGENCY")
    assert _code(exc) == "PERFORM_FIRST_NOT_ALLOWED"
    orders.authorize_perform_first([line], actor=fin.staff("manager"), reason="EMERGENCY")


def test_revoke_authorization(doctor, supervisor) -> None:
    visit = fin.visit()
    waiting, started, done = fin.order(visit, doctor, fin.priced(), fin.priced(), fin.priced())
    auth = orders.authorize_perform_first(
        [waiting, started, done], actor=supervisor, reason="EMERGENCY"
    )
    orders.start_line(started, doctor)
    orders.perform_line(done, doctor)
    with pytest.raises(DomainError) as exc:
        orders.revoke_authorization(auth, actor=supervisor, note=" ")
    assert _code(exc) == "REASON_REQUIRED"
    with pytest.raises(DomainError) as exc:
        orders.revoke_authorization(auth, actor=supervisor, note="no longer an emergency")
    assert _code(exc) == "AUTHORIZATION_IN_USE"
    orders.perform_line(started, doctor)
    orders.revoke_authorization(auth, actor=supervisor, note="no longer an emergency")
    auth.refresh_from_db()
    assert (auth.revoked_by, auth.revoke_note) == (supervisor, "no longer an emergency")
    assert not orders.worklist("lab").exists()
    with pytest.raises(DomainError) as exc:
        orders.perform_line(waiting, doctor)
    assert _code(exc) == "LINE_NOT_ELIGIBLE"
    # Work done before the revocation stays done and can still be billed.
    done.refresh_from_db()
    assert orders.line_status(done).authorized
    with pytest.raises(DomainError) as exc:
        orders.revoke_authorization(auth, actor=supervisor, note="again")
    assert _code(exc) == "AUTHORIZATION_REVOKED"
    with pytest.raises(PermissionRequired):
        orders.revoke_authorization(auth, actor=doctor, note="x")
    assert PerformAuthorization.objects.count() == 1


# --- cancelling ------------------------------------------------------------------------------


def test_cancel_unbilled_line_documents_and_leaves_the_draft(doctor, cashier) -> None:
    visit = fin.visit()
    keep, refused = fin.order(visit, doctor, fin.priced("lab", "40.00"), fin.priced("lab", "60.00"))
    draft = billing.create_draft_invoice(visit, cashier)
    assert draft.patient_total == D("100.00")
    cancelled = orders.cancel_line(refused, "PATIENT_REFUSED", cashier, note="cost")
    assert (cancelled.fulfilment_status, cancelled.billing_status) == ("cancelled", "unbilled")
    assert (cancelled.cancelled_by, fin.code(cancelled.cancel_reason), cancelled.cancel_note) == (
        cashier,
        "PATIENT_REFUSED",
        "cost",
    )
    assert cancelled.cancelled_at is not None
    draft.refresh_from_db()
    assert list(
        InvoiceLine.objects.filter(invoice=draft).values_list("service_line", flat=True)
    ) == [keep.pk]
    assert draft.patient_total == D("40.00")
    assert orders.line_state(cancelled) == "cancelled"
    with pytest.raises(DomainError) as exc:
        orders.cancel_line(refused, "PATIENT_REFUSED", cashier)
    assert _code(exc) == "LINE_ALREADY_CANCELLED"


@pytest.mark.parametrize(("reason", "code"), [("", "REASON_REQUIRED"), ("LOST", "REASON_UNKNOWN")])
def test_cancel_needs_a_line_cancel_reason(doctor, reason, code) -> None:
    (line,) = fin.order(fin.visit(), doctor, fin.priced())
    with pytest.raises(DomainError) as exc:
        orders.cancel_line(line, reason, doctor)
    assert _code(exc) == code
    with pytest.raises(DomainError) as exc:
        orders.cancel_line(line, "OTHER", doctor)
    assert _code(exc) == "REASON_NOTE_REQUIRED"


def test_cancel_invoiced_unpaid_line_credits_it_without_refund(doctor, cashier, supervisor):
    visit = fin.visit()
    line, _other = fin.order(visit, doctor, fin.priced("lab", "70.00"), fin.priced("lab", "30.00"))
    inv = fin.invoice(visit, cashier)
    # A doctor cancels; a billing supervisor approves the credit note (FEATURES 5.11).
    with pytest.raises(PermissionRequired):
        orders.cancel_line(line, "DOCTOR_CANCELLED", doctor)
    orders.cancel_line(line, "DOCTOR_CANCELLED", doctor, approver=supervisor)
    line.refresh_from_db()
    assert (line.billing_status, line.fulfilment_status) == ("credited", "cancelled")
    assert fin.code(line.cancel_reason) == "DOCTOR_CANCELLED"
    cn = CreditNote.objects.get(invoice=inv)
    assert (cn.status, cn.patient_total, cn.reason_code.code) == (
        "approved",
        D("70.00"),
        "SERVICE_CANCELLED",
    )
    assert cn.lines.get().cancels_service_line
    assert not Refund.objects.exists()
    assert billing.invoice_position(inv).outstanding == D("30.00")
    fin.assert_books_balance()
    fin.assert_positions_match_ledger(visit.patient)


def test_cancel_paid_line_turns_money_into_credit_with_a_refund_request(
    doctor, cashier, supervisor
) -> None:
    visit = fin.visit()
    line, other = fin.order(visit, doctor, fin.priced("lab", "70.00"), fin.priced("lab", "30.00"))
    _paid(visit, cashier)
    tech = fin.staff("lab_supervisor")
    orders.cancel_line(line, "SAMPLE_UNUSABLE", tech, approver=supervisor)
    refund = Refund.objects.get()
    assert (refund.amount, refund.status, refund.service_line, refund.requested_by) == (
        D("70.00"),
        "requested",
        line,
        tech,
    )
    assert pay.credit_balance(visit.patient) == D("70.00")
    other.refresh_from_db()
    assert other.billing_status == "settled"
    fin.assert_books_balance()
    fin.assert_positions_match_ledger(visit.patient)


def test_cancel_paid_line_without_refund_keeps_credit(doctor, cashier, supervisor) -> None:
    visit = fin.visit()
    (line,) = fin.order(visit, doctor, fin.priced("lab", "70.00"))
    _paid(visit, cashier)
    orders.cancel_line(line, "ORDER_ERROR", cashier, open_refund=False, approver=supervisor)
    assert not Refund.objects.exists()
    assert pay.credit_balance(visit.patient) == D("70.00")


def test_performed_line_cannot_be_cancelled(doctor, cashier, supervisor) -> None:
    visit = fin.visit()
    paid, authorized = fin.order(visit, doctor, fin.priced(), fin.priced())
    _paid(visit, cashier, paid)
    orders.authorize_perform_first([authorized], actor=supervisor, reason="EMERGENCY")
    for line in (paid, authorized):
        orders.perform_line(line, doctor)
        with pytest.raises(DomainError) as exc:
            orders.cancel_line(line, "ORDER_ERROR", supervisor)
        assert _code(exc) == "LINE_ALREADY_PERFORMED"


def test_cancel_remainder_of_partly_dispensed_line(doctor, cashier, supervisor) -> None:
    visit = fin.visit()
    (line,) = fin.order(visit, doctor, fin.priced("drug", "10.00"), quantity=10)
    inv = _paid(visit, cashier)
    pharmacist = fin.staff("pharmacist")
    with pytest.raises(DomainError) as exc:
        orders.cancel_line_remainder(line, "OUT_OF_STOCK", pharmacist)
    assert _code(exc) == "LINE_NOT_PERFORMED"
    orders.perform_line(line, pharmacist, performed_quantity=6)
    orders.cancel_line_remainder(
        line, "OUT_OF_STOCK", pharmacist, note="4 short", approver=supervisor
    )
    line.refresh_from_db()
    assert (line.billing_status, line.fulfilment_status) == ("settled", "performed")
    assert (fin.code(line.cancel_reason), line.cancelled_by, line.cancel_note) == (
        "OUT_OF_STOCK",
        pharmacist,
        "4 short",
    )
    cn = CreditNote.objects.get(invoice=inv)
    (cl,) = cn.lines.all()
    assert (cl.quantity, cl.patient_share, cl.cancels_service_line) == (D("4"), D("40.00"), False)
    assert Refund.objects.get().amount == D("40.00")
    assert billing.invoice_position(inv).outstanding == D("0.00")
    with pytest.raises(DomainError) as exc:
        orders.cancel_line_remainder(line, "OUT_OF_STOCK", pharmacist)
    assert _code(exc) == "LINE_NOTHING_REMAINING"
    fin.assert_books_balance()
    fin.assert_positions_match_ledger(visit.patient)


def test_unbilled_partial_line_is_invoiced_for_what_was_given(doctor, cashier, supervisor):
    visit = fin.visit()
    (line,) = fin.order(visit, doctor, fin.priced("drug", "10.00"), quantity=10)
    orders.authorize_perform_first([line], actor=supervisor, reason="EMERGENCY")
    orders.perform_line(line, doctor, performed_quantity=3)
    with pytest.raises(DomainError) as exc:
        orders.cancel_line_remainder(
            fin.order(visit, doctor, fin.priced())[0], "OUT_OF_STOCK", doctor
        )
    assert _code(exc) == "LINE_NOT_PERFORMED"
    orders.cancel_line_remainder(line, "OUT_OF_STOCK", doctor, note="7 short")
    inv = fin.invoice(visit, cashier, [line])
    assert (inv.lines.get().quantity, inv.patient_total) == (D("3"), D("30.00"))
    assert not CreditNote.objects.filter(invoice=inv).exists()
    full_line = fin.order(visit, doctor, fin.priced("drug"), quantity=2)[0]
    orders.authorize_perform_first([full_line], actor=supervisor, reason="EMERGENCY")
    orders.perform_line(full_line, doctor, performed_quantity=2)
    with pytest.raises(DomainError) as exc:
        orders.cancel_line_remainder(full_line, "OUT_OF_STOCK", doctor)
    assert _code(exc) == "LINE_NOTHING_REMAINING"


def test_invoice_of_unknown_visit_line_is_refused(doctor, cashier) -> None:
    visit = fin.visit()
    (line,) = fin.order(fin.visit(), doctor, fin.priced())
    with pytest.raises(DomainError) as exc:
        billing.create_draft_invoice(visit, cashier, line_ids=[line.pk])
    assert _code(exc) == "LINE_NOT_ON_VISIT"
    assert not Invoice.objects.exists()
