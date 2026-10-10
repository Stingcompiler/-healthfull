"""An admission made in error (FEATURES 10.5, invariant 4, ADR 0018): cancelled with a reason
and a second person's approval; unbilled bed nights are voided, invoiced nights block it
until the cashier credits them, and the database refuses every other change of a performed
line."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from api.errors import PermissionRequired
from apps.billing import services as billing
from apps.billing.models import Invoice, InvoiceLine
from apps.core.models import Room
from apps.core.tests import builders as b
from apps.orders.models import ServiceLine
from apps.payments.tests import fin
from apps.visits import services as vs
from apps.visits.models import Admission, Bed, BedCharge, BedStay, Visit
from domain.errors import DomainError

D = Decimal
pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _seed() -> None:
    fin.seed()


@pytest.fixture
def nurse():
    return fin.staff("nurse")


@pytest.fixture
def manager():
    return fin.staff("manager")


@pytest.fixture
def doctor():
    return b.doctor()


def _bed(price: str = "30000.00") -> Bed:
    dept = b.department()
    room = Room.objects.create(department=dept, code=f"W{b.n()}", name_ar="عنبر", name_en="Ward")
    return Bed.objects.create(
        code=f"{room.code}-1",
        name_ar="سرير",
        name_en="Bed",
        room=room,
        bed_service=fin.priced("bed", price, department=dept),
    )


def _admit(nurse, doctor, *, days: int = 0, visit: Visit | None = None) -> Admission:
    bed = _bed()
    patient = visit.patient if visit is not None else b.patient()
    adm = vs.admit_patient(
        patient,
        bed=bed,
        doctor=doctor,
        actor=nurse,
        visit=visit,
        at=timezone.now() - timedelta(days=days),
    )
    if days:
        vs.charge_bed_days(adm, actor=nurse)
    return adm


def _nights(adm: Admission) -> list[ServiceLine]:
    return list(ServiceLine.objects.filter(bed_charge__admission=adm).order_by("id"))


def _code(exc: pytest.ExceptionInfo[DomainError]) -> str:
    return exc.value.code


def test_cancel_frees_the_bed_and_records_who_approved_why_and_when(nurse, manager, doctor) -> None:
    adm = _admit(nurse, doctor)
    out = vs.cancel_admission(
        adm, actor=nurse, reason_code="WRONG_PATIENT", note=" wrong file ", approver=manager
    )
    out.refresh_from_db()
    assert out.status == "cancelled"
    assert out.cancelled_by == nurse
    assert out.cancel_approved_by == manager
    assert out.cancel_reason is not None
    assert out.cancel_reason.code == "WRONG_PATIENT"
    assert out.cancel_note == "wrong file"
    assert out.cancelled_at is not None
    stay = BedStay.objects.get(admission=adm)
    assert stay.ended_at is not None
    bed = Bed.objects.get(pk=stay.bed_id)
    assert bed.status == "available"
    assert out.authorization is not None
    out.authorization.refresh_from_db()
    assert out.authorization.revoked_by == nurse
    # The inpatient visit opened for it had nothing else: it is cancelled too.
    visit = Visit.objects.get(pk=adm.visit_id)
    assert visit.status == "cancelled"
    assert visit.cancel_reason is not None
    assert visit.cancel_reason.code == "REGISTRATION_ERROR"
    # The bed is free for the next patient, and a cancelled admission charges nothing.
    assert vs.charge_bed_days(out, actor=nurse) == []


def test_unbilled_nights_are_voided_and_leave_draft_invoices(nurse, manager, doctor) -> None:
    adm = _admit(nurse, doctor, days=2)
    nights = _nights(adm)
    assert [(n.billing_status, n.fulfilment_status) for n in nights] == [
        ("unbilled", "performed")
    ] * 2
    cashier = fin.staff("cashier")
    draft = billing.create_draft_invoice(adm.visit, cashier)
    assert InvoiceLine.objects.filter(invoice=draft).count() == 2
    vs.cancel_admission(adm, actor=nurse, reason_code="NOT_ADMITTED", approver=manager)
    for night in _nights(adm):
        assert (night.billing_status, night.fulfilment_status) == ("unbilled", "cancelled")
        assert night.cancelled_by == nurse
        assert night.cancel_reason is not None
        assert night.cancel_reason.code == "ORDER_ERROR"
        assert adm.number in night.cancel_note
    draft = Invoice.objects.get(pk=draft.pk)
    assert draft.status == "draft"
    assert not InvoiceLine.objects.filter(invoice=draft).exists()
    assert draft.patient_total == D("0.00")
    # Nights stay recorded as bed charges (history), but nothing is left to invoice.
    assert BedCharge.objects.filter(admission=adm).count() == 2


def test_invoiced_nights_block_until_the_cashier_credits_them(nurse, manager, doctor) -> None:
    adm = _admit(nurse, doctor, days=2)
    cashier = fin.staff("cashier")
    inv = fin.invoice(adm.visit, cashier, lines=_nights(adm)[:1])
    with pytest.raises(DomainError) as exc:
        vs.cancel_admission(adm, actor=nurse, reason_code="WRONG_PATIENT", approver=manager)
    assert _code(exc) == "ADMISSION_NIGHTS_INVOICED"
    assert exc.value.details["count"] == 1
    adm.refresh_from_db()
    assert adm.status == "admitted"  # nothing changed
    assert inv.status == "approved"
    # The cashier credits the invoiced night (invariant 2: a credit note, never an edit).
    supervisor = fin.staff("cashier_supervisor")
    il = InvoiceLine.objects.get(invoice=inv)
    note = billing.create_credit_note(inv, [(il, 1)], actor=cashier, reason="DUPLICATE_BILLING")
    billing.approve_credit_note(note, actor=supervisor)
    vs.cancel_admission(adm, actor=nurse, reason_code="WRONG_PATIENT", approver=manager)
    credited, voided = _nights(adm)
    assert (credited.billing_status, credited.fulfilment_status) == ("credited", "performed")
    assert (voided.billing_status, voided.fulfilment_status) == ("unbilled", "cancelled")
    # A credited performed night stays on the visit: it is closed, not cancelled.
    assert Visit.objects.get(pk=adm.visit_id).status == "closed"
    fin.assert_books_balance()


def test_a_second_person_with_the_permission_must_approve(nurse, manager, doctor) -> None:
    adm = _admit(nurse, doctor)
    with pytest.raises(DomainError) as exc:
        vs.cancel_admission(adm, actor=nurse, reason_code="WRONG_PATIENT", approver=None)
    assert _code(exc) == "SECOND_APPROVER_REQUIRED"
    with pytest.raises(DomainError) as exc:
        vs.cancel_admission(adm, actor=manager, reason_code="WRONG_PATIENT", approver=manager)
    assert _code(exc) == "SECOND_APPROVER_REQUIRED"
    with pytest.raises(DomainError) as exc:
        vs.cancel_admission(
            adm, actor=nurse, reason_code="WRONG_PATIENT", approver=fin.staff("nurse")
        )
    assert _code(exc) == "APPROVER_NOT_PERMITTED"
    assert exc.value.details["permission"] == "visits.approve_admission_cancel"
    with pytest.raises(PermissionRequired):
        vs.cancel_admission(
            adm, actor=fin.staff("cashier"), reason_code="WRONG_PATIENT", approver=manager
        )
    adm.refresh_from_db()
    assert adm.status == "admitted"


def test_reason_rules(nurse, manager, doctor) -> None:
    adm = _admit(nurse, doctor)
    for code, expected in (("", "REASON_REQUIRED"), ("NOPE", "REASON_UNKNOWN")):
        with pytest.raises(DomainError) as exc:
            vs.cancel_admission(adm, actor=nurse, reason_code=code, approver=manager)
        assert _code(exc) == expected
    with pytest.raises(DomainError) as exc:
        vs.cancel_admission(adm, actor=nurse, reason_code="OTHER", approver=manager)
    assert _code(exc) == "REASON_NOTE_REQUIRED"
    # A visit-cancel code is not an admission reason.
    with pytest.raises(DomainError) as exc:
        vs.cancel_admission(adm, actor=nurse, reason_code="PATIENT_LEFT", approver=manager)
    assert _code(exc) == "REASON_UNKNOWN"


def test_only_an_open_admission_is_cancelled(nurse, manager, doctor) -> None:
    adm = _admit(nurse, doctor)
    vs.discharge(adm, actor=nurse)
    with pytest.raises(DomainError) as exc:
        vs.cancel_admission(adm, actor=nurse, reason_code="WRONG_PATIENT", approver=manager)
    assert _code(exc) == "NOT_ADMITTED"
    other = _admit(nurse, doctor)
    vs.cancel_admission(other, actor=nurse, reason_code="WRONG_PATIENT", approver=manager)
    with pytest.raises(DomainError) as exc:
        vs.cancel_admission(other, actor=nurse, reason_code="WRONG_PATIENT", approver=manager)
    assert _code(exc) == "NOT_ADMITTED"


def test_an_outpatient_visit_the_admission_was_made_on_stays_open(nurse, manager, doctor) -> None:
    visit = b.visit(b.patient(), department=b.department())
    adm = _admit(nurse, doctor, visit=visit)
    vs.cancel_admission(adm, actor=nurse, reason_code="DUPLICATE_ADMISSION", approver=manager)
    assert Visit.objects.get(pk=visit.pk).status == "open"


def test_an_inpatient_visit_with_other_work_is_closed(nurse, manager, doctor) -> None:
    adm = _admit(nurse, doctor)
    fin.order(adm.visit, fin.staff("doctor"), fin.priced("lab", "5000.00"))
    vs.cancel_admission(adm, actor=nurse, reason_code="WRONG_PATIENT", approver=manager)
    assert Visit.objects.get(pk=adm.visit_id).status == "closed"


def test_the_board_counts_invoiced_nights_without_prices(nurse, doctor) -> None:
    adm = _admit(nurse, doctor, days=2)
    fin.invoice(adm.visit, fin.staff("cashier"), lines=_nights(adm)[:1])
    view = next(
        v for w in vs.bed_board().wards for v in w.beds if v.admission and v.admission.pk == adm.pk
    )
    assert view.nights_charged == 2
    assert view.nights_invoiced == 1


# --- database backstops -----------------------------------------------------------------------


def test_db_refuses_voiding_a_night_of_an_open_admission(nurse, doctor) -> None:
    adm = _admit(nurse, doctor, days=1)
    (night,) = _nights(adm)
    b.db_rejects(
        lambda: ServiceLine.objects.filter(pk=night.pk).update(
            fulfilment_status="cancelled",
            cancelled_at=timezone.now(),
            cancelled_by=nurse,
            cancel_reason=b.reason("line_cancel"),
        ),
        "LINE_TERMINAL",
    )


def test_db_still_refuses_cancelling_other_performed_lines(nurse, doctor) -> None:
    adm = _admit(nurse, doctor)
    (line,) = fin.order(adm.visit, fin.staff("doctor"), fin.priced("procedure", "2000.00"))
    from apps.orders import services as orders

    auth = adm.authorization
    assert auth is not None
    ServiceLine.objects.filter(pk=line.pk).update(authorization=auth)
    orders.perform_line(ServiceLine.objects.get(pk=line.pk), nurse)
    Admission.objects.filter(pk=adm.pk).update(
        status="cancelled",
        cancelled_at=timezone.now(),
        cancelled_by=nurse,
        cancel_approved_by=b.user(),
        cancel_reason=b.reason("admission_cancel"),
    )
    # Unbilled and performed under the stay, but not a bed night: still terminal.
    b.db_rejects(
        lambda: ServiceLine.objects.filter(pk=line.pk).update(
            fulfilment_status="cancelled",
            cancelled_at=timezone.now(),
            cancelled_by=nurse,
            cancel_reason=b.reason("line_cancel"),
        ),
        "LINE_TERMINAL",
    )


def test_db_requires_a_documented_second_person(nurse, doctor) -> None:
    adm = _admit(nurse, doctor)
    b.db_rejects(
        lambda: Admission.objects.filter(pk=adm.pk).update(status="cancelled"),
        "visits_admission_cancel_documented",
    )
    b.db_rejects(
        lambda: Admission.objects.filter(pk=adm.pk).update(
            status="cancelled",
            cancelled_at=timezone.now(),
            cancelled_by=nurse,
            cancel_approved_by=nurse,
            cancel_reason=b.reason("admission_cancel"),
        ),
        "visits_admission_cancel_documented",
    )
