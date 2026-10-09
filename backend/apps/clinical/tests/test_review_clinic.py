"""Regression tests for the wave a clinic review: who reads a visit's orders, claiming an
unassigned queue entry, prescription quantities, allergy override reasons, the estimated
cost option (FEATURES 3.8) and drug class lookups owned by the service."""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.catalog.models import CoverageRule
from apps.catalog.tests import engine
from apps.clinical.models import AllergyOverride
from apps.core.models import DoctorProfile, Policy, Role, RolePermission
from apps.core.tests import builders as b
from apps.orders.models import ServiceLine
from apps.pharmacy.models import DrugClass
from apps.visits import services as vs
from apps.visits.models import Visit
from conftest import ApiClient
from domain.errors import DomainError

from .test_api import client_as, err, ok

pytestmark = pytest.mark.django_db
D = Decimal


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
def unassigned(dept):
    visit = b.visit(b.patient(), department=dept)
    return vs.enqueue(visit, actor=b.user())


# --- who reads a visit's orders ---------------------------------------------------------------


def test_visit_orders_are_clinical_records(make_user, dept, unassigned) -> None:
    """Prescriptions, results and allergy override reasons never reach non-clinical roles."""
    doctor, _ = _doctor(make_user, "dra", dept)
    path = f"/api/orders/visits/{unassigned.visit_id}/lines"
    ok(doctor.post(path, {"items": [{"service_id": b.service("lab").pk}]}), 201)
    for role in ("receptionist", "cashier", "cashier_supervisor", "pharmacist", "lab_tech"):
        client = client_as(make_user, f"u_{role}", [role])
        body = err(client.get(path), 403, "PERMISSION_DENIED")
        assert body["details"]["permission"] == "clinical.view"
    nurse = client_as(make_user, "nurse1", ["nurse"])
    assert len(ok(nurse.get(path))) == 1
    assert len(ok(doctor.get(path))) == 1


# --- claiming an unassigned queue entry ---------------------------------------------------


def test_calling_an_unassigned_entry_claims_it(make_user, dept, unassigned) -> None:
    doctor_a, profile_a = _doctor(make_user, "dra", dept)
    doctor_b, _ = _doctor(make_user, "drb", dept)
    assert [r["id"] for r in ok(doctor_b.get("/api/clinical/worklist"))] == [unassigned.pk]

    called = ok(doctor_a.post("/api/clinical/worklist/call-next"))
    assert called["id"] == unassigned.pk
    unassigned.refresh_from_db()
    assert unassigned.doctor_id == profile_a.pk
    assert Visit.objects.get(pk=unassigned.visit_id).doctor_id == profile_a.pk

    assert ok(doctor_b.get("/api/clinical/worklist")) == []
    for action in ("start", "complete", "no_show"):
        err(
            doctor_b.post(f"/api/clinical/worklist/{unassigned.pk}/action", {"action": action}),
            409,
            "QUEUE_OTHER_DOCTOR",
        )
    started = ok(
        doctor_a.post(f"/api/clinical/worklist/{unassigned.pk}/action", {"action": "start"})
    )
    assert started["status"] == "in_progress"


def test_a_claim_under_the_lock_refuses_a_stale_entry(make_user, dept, unassigned) -> None:
    """Doctor B acting on an entry loaded before A claimed it is refused under the lock."""
    from apps.clinical import services as cs

    _, profile_a = _doctor(make_user, "dra", dept)
    _, profile_b = _doctor(make_user, "drb", dept)
    stale = type(unassigned).objects.get(pk=unassigned.pk)
    cs.queue_action(unassigned, "call", actor=profile_a.user)
    with pytest.raises(DomainError) as exc:
        vs.start_consultation(stale, actor=profile_b.user, doctor=profile_b)
    assert exc.value.code == "QUEUE_OTHER_DOCTOR"


def test_starting_an_unassigned_entry_keeps_the_visit_doctor(make_user, dept) -> None:
    _, profile_a = _doctor(make_user, "dra", dept)
    doctor_b, profile_b = _doctor(make_user, "drb", dept)
    visit = b.visit(b.patient(), department=dept, doctor=profile_a)
    entry = vs.enqueue(visit, actor=b.user())
    entry.doctor = None
    entry.save(update_fields=["doctor"])
    ok(doctor_b.post(f"/api/clinical/worklist/{entry.pk}/action", {"action": "call"}))
    entry.refresh_from_db()
    assert entry.doctor_id == profile_b.pk
    # The visit's own doctor is never overwritten by a claim.
    assert Visit.objects.get(pk=visit.pk).doctor_id == profile_a.pk


# --- prescriptions ----------------------------------------------------------------------------


@pytest.fixture
def amoxicillin():
    return b.item(generic_name="Amoxicillin", brand_name="Amoxil")


def _rx(service_id: int, **extra) -> dict:
    return {
        "items": [
            {
                "service_id": service_id,
                "prescription": {
                    "dose": "2 caps",
                    "dose_quantity": "2",
                    "frequency_code": "QID",
                    "duration_days": 10,
                },
                **extra,
            }
        ]
    }


def test_a_stated_quantity_never_falls_short_of_the_prescription(
    make_user, dept, unassigned, amoxicillin
) -> None:
    doctor, _ = _doctor(make_user, "dra", dept)
    path = f"/api/orders/visits/{unassigned.visit_id}/lines"
    body = err(
        doctor.post(path, _rx(amoxicillin.service_id, quantity=1)),
        409,
        "QUANTITY_BELOW_PRESCRIPTION",
    )
    assert (body["details"]["quantity"], body["details"]["computed"]) == (1, 80)
    assert not ServiceLine.objects.filter(visit_id=unassigned.visit_id).exists()
    (pack,) = ok(doctor.post(path, _rx(amoxicillin.service_id, quantity=84)), 201)
    assert pack["quantity"] == "84"
    (computed,) = ok(doctor.post(path, _rx(amoxicillin.service_id)), 201)
    assert computed["quantity"] == "80"


def test_an_allergy_override_needs_a_real_reason(make_user, dept, unassigned, amoxicillin) -> None:
    from apps.clinical import services as cs

    doctor, profile = _doctor(make_user, "dra", dept)
    cs.record_allergy(
        unassigned.visit.patient, actor=profile.user, allergen_type="drug", item=amoxicillin
    )
    path = f"/api/orders/visits/{unassigned.visit_id}/lines"
    for reason in ("x", " ab ", "  "):
        code = "ALLERGY_CONFLICT" if not reason.strip() else "ALLERGY_OVERRIDE_REASON_TOO_SHORT"
        body = err(
            doctor.post(path, {**_rx(amoxicillin.service_id), "allergy_override_reason": reason}),
            409,
            code,
        )
        if code == "ALLERGY_OVERRIDE_REASON_TOO_SHORT":
            assert body["details"]["min_length"] == cs.ALLERGY_OVERRIDE_REASON_MIN
    assert not AllergyOverride.objects.exists()
    ok(
        doctor.post(path, {**_rx(amoxicillin.service_id), "allergy_override_reason": "rash"}),
        201,
    )
    assert AllergyOverride.objects.get().reason == "rash"


# --- estimated cost (FEATURES 3.8) ------------------------------------------------------------


def test_estimated_cost_endpoint(make_user, dept) -> None:
    doctor, _ = _doctor(make_user, "dra", dept)
    svc = b.service("lab")
    engine.price_version().items.create(service=svc, unit_price=D("200.00"))
    payer = b.payer()
    CoverageRule.objects.create(payer=payer, rule_kind="percentage", payer_percent=D(75))
    visit = b.visit(b.patient(), department=dept, payer=payer)
    path = f"/api/orders/visits/{visit.pk}/estimate"
    body = {"items": [{"service_id": svc.pk, "quantity": 2}]}

    err(doctor.post(path, body), 409, "ESTIMATED_COST_DISABLED")
    Policy.objects.update(show_estimated_cost=True)
    denied = err(doctor.post(path, body), 403, "PERMISSION_DENIED")
    assert denied["details"]["permission"] == "clinical.view_estimated_cost"
    RolePermission.objects.create(
        role=Role.objects.get(code="doctor"), code="clinical.view_estimated_cost", allowed=True
    )
    estimate = ok(doctor.post(path, body))
    assert estimate == {
        "lines": [{"service_id": svc.pk, "quantity": 2, "patient_share": "100.00"}],
        "total": "100.00",
    }
    reception = client_as(make_user, "rec", ["receptionist"])
    err(reception.post(path, body), 403, "PERMISSION_DENIED")


# --- allergies and conditions resolved by the service -----------------------------------------


def test_a_retired_or_unknown_drug_class_is_a_domain_error(make_user, dept, unassigned) -> None:
    doctor, _ = _doctor(make_user, "dra", dept)
    retired = DrugClass.objects.create(code="OLD", name_ar="قديم", name_en="Old", active=False)
    path = f"/api/clinical/patients/{unassigned.visit.patient_id}/allergies"
    for class_id in (retired.pk, 999_999):
        body = err(
            doctor.post(path, {"allergen_type": "drug_class", "drug_class_id": class_id}),
            409,
            "DRUG_CLASS_INACTIVE",
        )
        assert body["details"]["id"] == class_id
    err(
        doctor.post(
            f"/api/clinical/patients/{unassigned.visit.patient_id}/conditions",
            {"icd10_code": "Z99.999"},
        ),
        409,
        "ICD10_UNKNOWN",
    )
