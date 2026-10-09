"""The doctor's workspace services: queue, registry updates, diagnoses, favorites, history,
approved results (FEATURES 2.3, 3.1-3.7)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.clinical import services as cs
from apps.clinical.models import Diagnosis
from apps.core.models import DoctorProfile
from apps.core.tests import builders as b
from apps.lab import services as ls
from apps.lab.models import LabParameter, LabTest, ReferenceRange
from apps.orders.models import OrderSource, PerformAuthorization
from apps.patients import services as ps
from apps.visits import services as vs
from domain.errors import DomainError

pytestmark = pytest.mark.django_db


@pytest.fixture
def clinic(make_user):
    """A doctor (a user who logs in, with a doctor profile) and their department."""
    user = make_user(roles=["doctor"])
    profile = DoctorProfile.objects.create(user=user, department=b.department())
    return user, profile


def queued(profile, *, doctor=True, unpaid=False, priority=0):
    """A visit with a queue entry today; ``unpaid`` adds an unsettled consultation fee."""
    visit = b.visit(department=profile.department, doctor=profile if doctor else None)
    if unpaid:
        b.service_line(visit, b.service("consultation"), order_source=OrderSource.CONSULTATION_FEE)
    return vs.enqueue(visit, actor=b.user(), priority=priority)


def _code(fn) -> str | None:
    try:
        fn()
    except DomainError as exc:
        return exc.code
    return None


# --- the doctor's queue ---------------------------------------------------------------------


def test_doctor_queue_lists_only_my_ready_patients_in_serving_order(clinic, make_user) -> None:
    user, profile = clinic
    first = queued(profile)
    unassigned = queued(profile, doctor=False)
    urgent = queued(profile, priority=10)
    queued(profile, unpaid=True)  # consultation not paid: not ready
    other = b.doctor(profile.department)
    queued(other)  # another doctor's patient
    elsewhere = b.doctor()
    queued(elsewhere, doctor=False)  # unassigned in another department
    assert [e.pk for e in cs.doctor_queue(user)] == [urgent.pk, first.pk, unassigned.pk]
    # Not a doctor: no queue.
    assert cs.doctor_queue(make_user(roles=["nurse"])) == []


def test_call_next_start_and_complete(clinic) -> None:
    user, profile = clinic
    entry = queued(profile)
    fee = b.service_line(
        entry.visit, b.service("consultation"), order_source=OrderSource.CONSULTATION_FEE
    )
    # A consultation line that is neither paid nor authorized blocks the entry.
    assert _code(lambda: cs.call_next(user)) == "QUEUE_EMPTY"
    auth = PerformAuthorization.objects.create(
        visit=entry.visit,
        kind="emergency",
        reason_code=b.reason("perform_first"),
        authorized_by=b.user(),
        authorized_at=timezone.now(),
    )
    fee.authorization = auth
    fee.save(update_fields=["authorization"])
    called = cs.call_next(user)
    assert called.pk == entry.pk
    assert called.status == "called"
    assert called.called_by == user
    started = cs.queue_action(called, "start", actor=user)
    assert started.status == "in_progress"
    done = cs.queue_action(started, "complete", actor=user)
    assert done.status == "done"
    fee.refresh_from_db()
    assert fee.fulfilment_status == "performed"  # the consultation is performed
    entry.visit.refresh_from_db()
    assert entry.visit.status == "open"  # the visit stays open for billing and results
    # Seen today follows the active entries.
    later = queued(profile)
    assert [e.pk for e in cs.doctor_queue(user)] == [later.pk, entry.pk]
    assert [e.pk for e in cs.doctor_queue(user, include_done=False)] == [later.pk]
    current = cs.visit_queue_entry(entry.visit)
    assert current is not None
    assert current.pk == entry.pk


def test_queue_actions_are_for_my_own_queue(clinic, make_user) -> None:
    user, profile = clinic
    theirs = queued(b.doctor(profile.department))
    assert _code(lambda: cs.queue_action(theirs, "call", actor=user)) == "QUEUE_OTHER_DOCTOR"
    elsewhere = queued(b.doctor(), doctor=False)
    assert _code(lambda: cs.queue_action(elsewhere, "call", actor=user)) == "QUEUE_OTHER_DOCTOR"
    mine = queued(profile)
    nurse = make_user(roles=["nurse"])
    assert _code(lambda: cs.queue_action(mine, "call", actor=nurse)) == "DOCTOR_PROFILE_REQUIRED"
    assert _code(lambda: cs.call_next(nurse)) == "DOCTOR_PROFILE_REQUIRED"
    assert _code(lambda: cs.queue_action(mine, "teleport", actor=user)) == "INVALID_QUEUE_ACTION"
    assert _code(lambda: cs.queue_action(mine, "complete", actor=user)) == (
        "QUEUE_TRANSITION_INVALID"
    )
    no_show = cs.queue_action(mine, "no_show", actor=user)
    assert no_show.status == "no_show"
    assert cs.queue_action(no_show, "requeue", actor=user).status == "waiting"
    idle = make_user(roles=["doctor"])
    DoctorProfile.objects.create(user=idle, department=b.department())
    assert _code(lambda: cs.call_next(idle)) == "QUEUE_EMPTY"


# --- registry updates -----------------------------------------------------------------------


def test_update_allergy_and_condition(clinic) -> None:
    user, _ = clinic
    patient = b.patient()
    allergy = cs.record_allergy(patient, actor=user, allergen_type="food", substance="peanut")
    changed = cs.update_allergy(allergy, actor=user, severity="severe", reaction=" hives ")
    assert (changed.severity, changed.reaction, changed.status) == ("severe", "hives", "active")
    assert cs.update_allergy(allergy, actor=user, status="inactive").status == "inactive"
    assert _code(lambda: cs.update_allergy(allergy, actor=user)) == "NOTHING_TO_CHANGE"
    assert _code(lambda: cs.update_allergy(allergy, actor=user, status="gone")) == (
        "INVALID_STATUS"
    )
    assert _code(lambda: cs.update_allergy(allergy, actor=user, severity="mega")) == (
        "INVALID_SEVERITY"
    )
    assert cs.allergies_recorded(patient)
    assert cs.active_allergies(patient) == []
    assert not cs.allergies_recorded(b.patient())

    condition = cs.record_condition(patient, actor=user, name="Asthma")
    updated = cs.update_condition(condition, actor=user, note=" since childhood ")
    assert updated.note == "since childhood"
    assert cs.update_condition(condition, actor=user, status="inactive").status == "inactive"
    assert _code(lambda: cs.update_condition(condition, actor=user)) == "NOTHING_TO_CHANGE"


def test_active_allergies_follow_merged_files(clinic, make_user) -> None:
    user, _ = clinic
    survivor, duplicate = b.patient(), b.patient()
    old = cs.record_allergy(duplicate, actor=user, allergen_type="food", substance="egg")
    ps.merge_patients(duplicate, survivor, actor=make_user(roles=["manager"]), reason_note="d")
    assert [a.pk for a in cs.active_allergies(survivor)] == [old.pk]


def test_remove_diagnosis(clinic, make_user) -> None:
    user, _ = clinic
    visit = b.visit()
    diagnosis = cs.add_diagnosis(visit, actor=user, icd10_code="B54")
    other = make_user(roles=["doctor"])
    assert (
        _code(lambda: cs.remove_diagnosis(diagnosis, actor=other, reason="x"))
        == "DIAGNOSIS_NOT_AUTHOR"
    )
    cs.remove_diagnosis(diagnosis, actor=user, reason="recorded in error")
    assert not Diagnosis.objects.filter(pk=diagnosis.pk).exists()
    kept = cs.add_diagnosis(visit, actor=user, text="viral fever")
    vs.close_visit(visit, actor=user)
    assert _code(lambda: cs.remove_diagnosis(kept, actor=user, reason="x")) == "VISIT_NOT_OPEN"


def test_favorites_are_removed_only_by_their_owner(clinic, make_user) -> None:
    user, profile = clinic
    lab = b.service("lab")
    favorite = cs.create_order_set(
        name_ar="مفضلة", name_en="Fav", items=[{"service": lab}], actor=user
    )
    shared = cs.create_order_set(
        name_ar="مشتركة", name_en="Shared", items=[{"service": lab}], actor=user, personal=False
    )
    assert _code(lambda: cs.deactivate_order_set(shared, actor=user)) == "ORDER_SET_NOT_OWNER"
    other = make_user(roles=["doctor"])
    assert _code(lambda: cs.deactivate_order_set(favorite, actor=other)) == "ORDER_SET_NOT_OWNER"
    assert cs.deactivate_order_set(favorite, actor=user).active is False
    assert _code(lambda: cs.deactivate_order_set(favorite, actor=user)) == "ORDER_SET_INACTIVE"
    assert list(cs.order_sets_for(user, department=profile.department)) == [shared]


# --- history and results ----------------------------------------------------------------------


def test_patient_history_has_diagnoses_notes_and_clinical_orders(clinic) -> None:
    user, _ = clinic
    patient = b.patient()
    old = b.visit(patient)
    cs.add_diagnosis(old, actor=user, icd10_code="I10")
    cs.save_note(old, actor=user, complaint="headache")
    b.service_line(old, b.service("consultation"), order_source=OrderSource.CONSULTATION_FEE)
    lab = b.service_line(old, b.service("lab"))
    new = b.visit(patient)
    cancelled = b.visit(patient)
    vs.cancel_visit(cancelled, actor=b.user(), reason_code="PATIENT_LEFT")
    history = cs.patient_history(patient)
    assert [h.visit.pk for h in history] == [new.pk, old.pk]
    past = history[1]
    assert [d.icd10.code for d in past.diagnoses if d.icd10] == ["I10"]
    assert [n.complaint for n in past.notes] == ["headache"]
    assert [ln.pk for ln in past.lines] == [lab.pk]  # no consultation fee
    assert len(cs.patient_history(patient, limit=1)) == 1


def test_approved_results_only(make_user) -> None:
    tech = make_user(roles=["lab_tech"])
    supervisor = make_user(roles=["lab_supervisor"])
    test = LabTest.objects.create(
        service=b.service("lab"), code=f"GLU{b.n()}", sample_type="whole_blood"
    )
    glucose = LabParameter.objects.create(
        test=test, code="GLU", name_ar="سكر", name_en="Glucose", unit="mg/dL"
    )
    ReferenceRange.objects.create(parameter=glucose, low=Decimal(70), high=Decimal(110))
    patient = b.patient(date_of_birth=date(1980, 1, 1))
    visit = b.visit(patient)
    approved_line = b.billed_line(visit, test.service)
    draft_line = b.billed_line(visit, test.service)
    sample = ls.collect_sample(visit=visit, lines=[approved_line, draft_line], actor=tech)
    ls.receive_sample(sample, actor=tech)
    ls.enter_results(approved_line, values={"GLU": "180"}, actor=tech)
    ls.enter_results(draft_line, values={"GLU": "90"}, actor=tech)
    version = ls.approve_results(approved_line, actor=supervisor)
    results = cs.approved_results(patient)
    assert [r.pk for r in results] == [version.pk]
    (value,) = list(results[0].values.all())
    assert (value.parameter.code, value.flag) == ("GLU", "high")
    assert [r.pk for r in cs.approved_results(patient, visit=b.visit(patient))] == []
    assert [r.pk for r in cs.patient_summary(patient).latest_results] == [version.pk]
