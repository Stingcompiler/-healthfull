"""Nursing services (FEATURES 3.4, 10.3): the nurse's list of today's visits and inpatients
that leads to vitals, the nursing chart of a visit, and nursing notes."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.clinical import nursing
from apps.clinical import services as cs
from apps.core.models import Room
from apps.core.tests import builders as b
from apps.payments.tests import fin
from apps.visits import services as vs
from apps.visits.models import Bed, Visit
from domain.errors import DomainError

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _seed() -> None:
    fin.seed()


@pytest.fixture
def nurse():
    return fin.staff("nurse")


def _bed() -> Bed:
    dept = b.department()
    room = Room.objects.create(department=dept, code=f"R{b.n()}", name_ar="عنبر", name_en="Ward")
    return Bed.objects.create(
        code=f"{room.code}-1",
        name_ar="سرير",
        name_en="Bed",
        room=room,
        bed_service=fin.priced("bed", department=dept),
    )


def _yesterday(visit: Visit) -> Visit:
    Visit.objects.filter(pk=visit.pk).update(created_at=timezone.now() - timedelta(days=1))
    visit.refresh_from_db()
    return visit


def test_today_lists_open_visits_and_inpatients(nurse) -> None:
    first = b.visit(b.patient(full_name_en="Amna Ali"))
    second = b.visit(b.patient(full_name_en="Omer Musa"))
    old = _yesterday(b.visit(b.patient()))
    closed = b.visit(b.patient(), status="closed", closed_at=timezone.now())
    sale = b.visit(b.patient(), visit_type="pharmacy_sale")
    admission = vs.admit_patient(
        b.patient(full_name_en="Huda Ahmed"),
        bed=_bed(),
        doctor=b.doctor(),
        actor=nurse,
        at=timezone.now() - timedelta(days=3),
    )
    _yesterday(admission.visit)

    rows = nursing.nursing_visits()
    ids = [r.visit.pk for r in rows]
    # Inpatients first, then today's visits in arrival order.
    assert ids == [admission.visit_id, first.pk, second.pk]
    assert old.pk not in ids and closed.pk not in ids and sale.pk not in ids
    inpatient = rows[0]
    assert inpatient.admission is not None and inpatient.bed is not None
    assert rows[1].admission is None


def test_search_and_vitals_flags(nurse) -> None:
    amna = b.visit(b.patient(full_name_en="Amna Ali"))
    b.visit(b.patient(full_name_en="Omer Musa"))
    assert [r.visit.pk for r in nursing.nursing_visits(q="amna")] == [amna.pk]
    assert [r.visit.pk for r in nursing.nursing_visits(q=amna.patient.file_no)] == [amna.pk]
    (row,) = nursing.nursing_visits(q="amna")
    assert (row.vitals_count, row.last_vitals_at) == (0, None)
    cs.record_vitals(amna, actor=nurse, pulse_bpm=80)
    (row,) = nursing.nursing_visits(q="amna")
    assert row.vitals_count == 1
    assert row.last_vitals_at is not None


def test_rows_carry_active_allergies_and_waiting_procedures(nurse) -> None:
    doctor, cashier = fin.staff("doctor"), fin.staff("cashier")
    visit = fin.visit(b.patient(full_name_en="Salwa Idris"))
    cs.record_allergy(
        visit.patient, actor=nurse, allergen_type="other", substance="Latex", severity="severe"
    )
    paid, unpaid = fin.order(visit, doctor, fin.priced("procedure"), fin.priced("procedure"))
    inv = fin.invoice(visit, cashier, [paid])
    from apps.payments import services as pay

    shift = pay.open_shift(cashier, fin.D("0.00"))
    pay.record_payment(shift, inv.patient, "cash", inv.patient_total, actor=cashier, auto=True)
    (row,) = nursing.nursing_visits(q="salwa")
    assert [a.substance for a in row.allergies] == ["Latex"]
    assert row.procedures_waiting == 1


def test_chart_has_vitals_notes_procedures_and_admission(nurse) -> None:
    doctor = fin.staff("doctor")
    visit = fin.visit()
    cs.record_vitals(visit, actor=nurse, temperature_c=fin.D("38.5"))
    cs.record_vitals(visit, actor=nurse, pulse_bpm=90)
    first = cs.add_nursing_note(visit, actor=nurse, text="Patient anxious")
    second = cs.add_nursing_note(visit, actor=nurse, text="Shift handover", kind="handover")
    (line,) = fin.order(visit, doctor, fin.priced("procedure"))
    fin.order(visit, doctor, fin.priced("lab"))
    chart = nursing.nursing_chart(visit)
    assert [v.pulse_bpm for v in chart.vitals] == [90, None]
    assert [n.pk for n in chart.notes] == [second.pk, first.pk]
    assert [ln.pk for ln in chart.procedures] == [line.pk]
    assert chart.admission is None


def test_nursing_note_rules(nurse) -> None:
    visit = b.visit()
    with pytest.raises(DomainError) as exc:
        cs.add_nursing_note(visit, actor=nurse, text="   ")
    assert exc.value.code == "NOTE_EMPTY"
    with pytest.raises(DomainError) as exc:
        cs.add_nursing_note(visit, actor=nurse, text="x", kind="bogus")
    assert exc.value.code == "INVALID_NOTE_KIND"
    cancelled = b.visit(
        status="cancelled",
        cancelled_at=timezone.now(),
        cancelled_by=nurse,
        cancel_reason=b.reason("visit_cancel"),
    )
    with pytest.raises(DomainError) as exc:
        cs.add_nursing_note(cancelled, actor=nurse, text="late note")
    assert exc.value.code == "VISIT_CANCELLED"
    # A closed visit still takes a late note (a discharge note after the visit closed).
    closed = b.visit(status="closed", closed_at=timezone.now())
    note = cs.add_nursing_note(closed, actor=nurse, text="Discharged walking")
    assert note.author == nurse
