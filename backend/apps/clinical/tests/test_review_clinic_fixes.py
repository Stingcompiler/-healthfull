"""Regression tests for the second clinic review: the withdrawal answer is clinical, completing
a consultation keeps to the permission matrix, cancelling a referral and withdrawing clinical
safety data record a reason (invariant 4), and a favorite keeps a drug's route and dose."""

from __future__ import annotations

import pghistory.models
import pytest
from django.utils import timezone

from apps.clinical import services as cs
from apps.clinical.models import Diagnosis, Referral
from apps.core.models import DoctorProfile, Role, RolePermission
from apps.core.services import holds_permission
from apps.core.tests import builders as b
from apps.visits import services as vs
from apps.visits.models import Visit
from conftest import ApiClient

from .test_api import client_as, err, ok

pytestmark = pytest.mark.django_db


@pytest.fixture
def dept():
    return b.department()


def _doctor(make_user, username: str, dept) -> tuple[ApiClient, DoctorProfile]:
    user = make_user(username, roles=["doctor"])
    profile = DoctorProfile.objects.create(user=user, department=dept)
    client = ApiClient()
    ok(client.login(username))
    return client, profile


@pytest.fixture
def entry(dept):
    visit = b.visit(b.patient(), department=dept)
    return vs.enqueue(visit, actor=b.user())


def _contexts(reason_prefix: str) -> list[dict]:
    return [
        c.metadata
        for c in pghistory.models.Context.objects.all()
        if str(c.metadata.get("reason", "")).startswith(reason_prefix)
    ]


# --- the withdrawal answer is part of the clinical record -------------------------------------


def test_non_clinical_roles_cannot_withdraw_a_doctors_order(make_user, dept, entry) -> None:
    doctor, _ = _doctor(make_user, "dra", dept)
    item = b.item(generic_name="Paracetamol")
    (line,) = ok(
        doctor.post(
            f"/api/orders/visits/{entry.visit_id}/lines",
            {
                "items": [
                    {
                        "service_id": item.service_id,
                        "prescription": {
                            "dose": "1 tab",
                            "dose_quantity": "1",
                            "frequency_code": "TID",
                            "duration_days": 3,
                        },
                    }
                ]
            },
        ),
        201,
    )
    path = f"/api/orders/lines/{line['id']}/withdraw"
    for role in ("cashier", "cashier_supervisor", "pharmacist", "lab_supervisor", "manager"):
        client = client_as(make_user, f"u_{role}", [role])
        body = err(client.post(path, {"reason_code": "ORDER_ERROR"}), 403, "PERMISSION_DENIED")
        assert body["details"]["permission"] == "clinical.view"
        assert "prescription" not in body
    withdrawn = ok(doctor.post(path, {"reason_code": "ORDER_ERROR"}))
    assert withdrawn["status"] == "cancelled"


# --- completing a consultation keeps to the permission matrix ---------------------------------


def test_completing_through_the_clinic_needs_finish_consultation(make_user, dept, entry) -> None:
    doctor, profile = _doctor(make_user, "dra", dept)
    RolePermission.objects.create(
        role=Role.objects.get(code="doctor"), code="visits.finish_consultation", allowed=False
    )
    assert not holds_permission(profile.user, "visits.finish_consultation")
    path = f"/api/clinical/worklist/{entry.pk}/action"
    ok(doctor.post(path, {"action": "call"}))
    ok(doctor.post(path, {"action": "start"}))
    body = err(doctor.post(path, {"action": "complete"}), 403, "PERMISSION_DENIED")
    assert body["details"]["permission"] == "visits.finish_consultation"
    entry.refresh_from_db()
    assert entry.status == "in_progress"


# --- cancelling a referral records reason, who and when ---------------------------------------


def _referral(client: ApiClient, visit_id: int) -> dict:
    return ok(
        client.post(
            f"/api/clinical/visits/{visit_id}/referrals",
            {"kind": "external", "reason": "Needs a CT scan", "external_facility": "Soba"},
        ),
        201,
    )


def test_cancelling_a_referral_needs_a_reason_and_records_it(make_user, dept, entry) -> None:
    doctor, profile = _doctor(make_user, "dra", dept)
    referral = _referral(doctor, entry.visit_id)
    path = f"/api/clinical/referrals/{referral['id']}/cancel"
    err(doctor.post(path, {"reason": "   "}), 409, "REASON_REQUIRED")
    assert Referral.objects.get(pk=referral["id"]).status == "issued"

    cancelled = ok(doctor.post(path, {"reason": "Patient prefers to wait"}))
    assert cancelled["status"] == "cancelled"
    assert cancelled["cancel_reason"] == "Patient prefers to wait"
    assert cancelled["cancelled_by"]["id"] == profile.user_id
    assert cancelled["cancelled_at"] is not None
    row = Referral.objects.get(pk=referral["id"])
    assert (row.cancel_reason, row.cancelled_by_id) == ("Patient prefers to wait", profile.user_id)
    assert row.cancelled_at is not None
    err(doctor.post(path, {"reason": "again"}), 409, "REFERRAL_CLOSED")


def test_only_the_referrer_cancels_and_never_on_a_closed_visit(make_user, dept, entry) -> None:
    doctor_a, _ = _doctor(make_user, "dra", dept)
    doctor_b, _ = _doctor(make_user, "drb", dept)
    referral = _referral(doctor_a, entry.visit_id)
    path = f"/api/clinical/referrals/{referral['id']}/cancel"
    err(doctor_b.post(path, {"reason": "not mine"}), 409, "REFERRAL_NOT_AUTHOR")
    Visit.objects.filter(pk=entry.visit_id).update(status="closed", closed_at=timezone.now())
    err(doctor_a.post(path, {"reason": "too late"}), 409, "VISIT_NOT_OPEN")
    assert Referral.objects.get(pk=referral["id"]).status == "issued"


# --- withdrawing clinical safety data states why ----------------------------------------------


def test_removing_a_diagnosis_needs_a_reason(make_user, dept, entry) -> None:
    doctor, _ = _doctor(make_user, "dra", dept)
    dx = ok(
        doctor.post(f"/api/clinical/visits/{entry.visit_id}/diagnoses", {"text": "Malaria"}), 201
    )
    path = f"/api/clinical/diagnoses/{dx['id']}"
    err(doctor.request("DELETE", path, {"reason": ""}), 409, "REASON_REQUIRED")
    assert Diagnosis.objects.filter(pk=dx["id"]).exists()
    ok(doctor.request("DELETE", path, {"reason": "Wrong patient"}), 204)
    assert not Diagnosis.objects.filter(pk=dx["id"]).exists()
    (ctx,) = _contexts("remove diagnosis")
    assert ctx["reason"] == "remove diagnosis: Wrong patient"


def test_allergy_or_condition_entered_in_error_needs_a_reason(make_user, dept, entry) -> None:
    doctor, profile = _doctor(make_user, "dra", dept)
    patient = entry.visit.patient
    allergy = cs.record_allergy(
        patient, actor=profile.user, allergen_type="food", substance="Peanuts"
    )
    path = f"/api/clinical/allergies/{allergy.pk}"
    err(doctor.patch(path, {"status": "entered_in_error"}), 409, "REASON_REQUIRED")
    marked = ok(doctor.patch(path, {"status": "entered_in_error", "reason": "Other patient"}))
    assert marked["status"] == "entered_in_error"
    assert _contexts("allergy entered_in_error")[-1]["reason"] == (
        "allergy entered_in_error: Other patient"
    )
    # Resolving is a clinical event, not a withdrawal: no reason needed.
    other = cs.record_allergy(patient, actor=profile.user, allergen_type="food", substance="Egg")
    ok(doctor.patch(f"/api/clinical/allergies/{other.pk}", {"status": "inactive"}))

    condition = cs.record_condition(patient, actor=profile.user, name="Hypertension")
    cpath = f"/api/clinical/conditions/{condition.pk}"
    err(doctor.patch(cpath, {"status": "entered_in_error"}), 409, "REASON_REQUIRED")
    ok(doctor.patch(cpath, {"status": "entered_in_error", "reason": "Typo"}))
    assert _contexts("condition entered_in_error")[-1]["reason"] == (
        "condition entered_in_error: Typo"
    )


# --- a favorite keeps the drug's route, dose quantity and as-needed flag ----------------------


def test_favorite_keeps_route_dose_quantity_and_as_needed(make_user, dept) -> None:
    doctor, _ = _doctor(make_user, "dra", dept)
    ceftriaxone = b.item(generic_name="Ceftriaxone")
    paracetamol = b.item(generic_name="Paracetamol")
    created = ok(
        doctor.post(
            "/api/clinical/order-sets",
            {
                "name_en": "Severe pneumonia",
                "items": [
                    {
                        "service_id": ceftriaxone.service_id,
                        "quantity": 10,
                        "dose": "1 g",
                        "dose_quantity": "1",
                        "route": "iv",
                        "frequency_code": "Q12H",
                        "duration_days": 5,
                    },
                    {
                        "service_id": paracetamol.service_id,
                        "quantity": 10,
                        "dose": "1 tab",
                        "as_needed": True,
                    },
                ],
            },
        ),
        201,
    )
    iv, prn = created["items"]
    assert (iv["route"], iv["dose_quantity"], iv["as_needed"]) == ("iv", "1", False)
    assert (prn["route"], prn["dose_quantity"], prn["as_needed"]) == ("oral", None, True)
    listed = next(o for o in ok(doctor.get("/api/clinical/order-sets")) if o["id"] == created["id"])
    assert listed["items"] == created["items"]

    from apps.clinical.models import OrderSet

    items = cs.order_set_items(OrderSet.objects.get(pk=created["id"]))
    assert items[0]["prescription"]["route"] == "iv"
    assert items[0]["prescription"]["dose_quantity"] == 1
    assert items[1]["prescription"]["as_needed"] is True


# --- an allergy match shows while the order is written, before it is placed -------------------


def test_allergy_check_flags_a_drug_before_it_is_ordered(make_user, dept, entry) -> None:
    from apps.pharmacy.models import DrugClass

    doctor, profile = _doctor(make_user, "dra", dept)
    penicillins = DrugClass.objects.create(code="PEN", name_ar="البنسلينات", name_en="Penicillins")
    amoxicillin = b.item(generic_name="Amoxicillin")
    amoxicillin.drug_classes.add(penicillins)
    paracetamol = b.item(generic_name="Paracetamol")
    patient = entry.visit.patient
    cs.record_allergy(
        patient, actor=profile.user, allergen_type="drug_class", drug_class=penicillins
    )
    path = f"/api/clinical/patients/{patient.pk}/allergy-alerts"
    alerts = ok(
        doctor.get(
            f"{path}?service_ids={amoxicillin.service_id}&service_ids={paracetamol.service_id}"
            f"&service_ids={b.service('lab').pk}"
        )
    )
    assert [(a["service_id"], a["match"], a["allergen"]) for a in alerts] == [
        (amoxicillin.service_id, "drug_class", "Penicillins")
    ]
    assert alerts[0]["allergen_ar"] == "البنسلينات"
    assert ok(doctor.get(f"{path}?service_ids={paracetamol.service_id}")) == []
    cashier = client_as(make_user, "cash1", ["cashier"])
    err(cashier.get(f"{path}?service_ids={amoxicillin.service_id}"), 403, "PERMISSION_DENIED")
