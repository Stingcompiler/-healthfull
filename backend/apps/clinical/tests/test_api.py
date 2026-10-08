"""``/api/clinical`` and ``/api/orders`` contract for the doctor's workspace (FEATURES 2.3,
3.1-3.9, 4.1, 4.2): happy paths, permission denied, domain error codes, and that nothing a
doctor reads carries a price."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest

from apps.clinical.models import AllergyOverride, ClinicalNote, Diagnosis, OrderSet
from apps.core.models import DoctorProfile
from apps.core.tests import builders as b
from apps.lab import services as ls
from apps.lab.models import LabParameter, LabTest, ReferenceRange
from apps.orders.models import OrderSource, ServiceLine
from apps.pharmacy.models import DrugClass
from apps.visits import services as vs
from conftest import ApiClient

pytestmark = pytest.mark.django_db

#: Words that would betray a price or a billing amount in a doctor-facing answer.
PRICE_WORDS = ("price", "amount", "share", "gross", "discount", "total", "balance", "invoice")


def _keys(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, inner in value.items():
            found.add(str(key))
            found |= _keys(inner)
    elif isinstance(value, list):
        for inner in value:
            found |= _keys(inner)
    return found


def assert_no_prices(body: Any) -> None:
    leaked = {k for k in _keys(body) if any(word in k.lower() for word in PRICE_WORDS)}
    assert not leaked, leaked


def ok(response: Any, status: int = 200) -> Any:
    assert response.status_code == status, response.content
    return response.json() if response.content else None


def err(response: Any, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.content
    body: dict[str, Any] = response.json()
    assert body["code"] == code, body
    return body


@pytest.fixture
def doctor(make_user):
    user = make_user("dr", roles=["doctor"])
    profile = DoctorProfile.objects.create(user=user, department=b.department())
    return user, profile


@pytest.fixture
def doctor_client(doctor) -> ApiClient:
    client = ApiClient()
    ok(client.login("dr"))
    return client


def client_as(make_user, username: str, roles: list[str]) -> ApiClient:
    make_user(username, roles=roles)
    client = ApiClient()
    ok(client.login(username))
    return client


@pytest.fixture
def entry(doctor):
    _, profile = doctor
    visit = b.visit(
        b.patient(full_name_ar="خالد عثمان", full_name_en="Khalid Osman"),
        department=profile.department,
        doctor=profile,
    )
    return vs.enqueue(visit, actor=b.user())


@pytest.fixture
def penicillins():
    return DrugClass.objects.create(code="PEN", name_ar="البنسلينات", name_en="Penicillins")


@pytest.fixture
def amoxicillin(penicillins):
    it = b.item(generic_name="Amoxicillin", brand_name="Amoxil")
    it.drug_classes.add(penicillins)
    return it


# --- the queue ------------------------------------------------------------------------------


def test_worklist_call_next_start_complete(doctor_client, entry, penicillins, doctor) -> None:
    from apps.clinical import services as cs

    cs.record_allergy(
        entry.visit.patient, actor=doctor[0], allergen_type="drug_class", drug_class=penicillins
    )
    rows = ok(doctor_client.get("/api/clinical/worklist"))
    assert [r["id"] for r in rows] == [entry.pk]
    row = rows[0]
    assert row["status"] == "waiting"
    assert row["patient"]["file_no"] == entry.visit.patient.file_no
    assert row["allergies_recorded"] is True
    assert [a["label_en"] for a in row["allergies"]] == ["Penicillins"]
    assert [a["label_ar"] for a in row["allergies"]] == ["البنسلينات"]
    assert_no_prices(rows)

    called = ok(doctor_client.post("/api/clinical/worklist/call-next"))
    assert called["id"] == entry.pk
    assert called["status"] == "called"
    err(doctor_client.post("/api/clinical/worklist/call-next"), 409, "QUEUE_EMPTY")
    started = ok(
        doctor_client.post(f"/api/clinical/worklist/{entry.pk}/action", {"action": "start"})
    )
    assert started["status"] == "in_progress"
    done = ok(
        doctor_client.post(f"/api/clinical/worklist/{entry.pk}/action", {"action": "complete"})
    )
    assert done["status"] == "done"
    err(
        doctor_client.post(f"/api/clinical/worklist/{entry.pk}/action", {"action": "start"}),
        409,
        "QUEUE_TRANSITION_INVALID",
    )
    # An unknown action is a validation error.
    err(
        doctor_client.post(f"/api/clinical/worklist/{entry.pk}/action", {"action": "x"}),
        422,
        "VALIDATION_ERROR",
    )


def test_queue_of_another_doctor_is_refused(make_user, entry) -> None:
    other = make_user("dr2", roles=["doctor"])
    DoctorProfile.objects.create(user=other, department=b.department())
    client = ApiClient()
    ok(client.login("dr2"))
    assert ok(client.get("/api/clinical/worklist")) == []
    err(
        client.post(f"/api/clinical/worklist/{entry.pk}/action", {"action": "call"}),
        409,
        "QUEUE_OTHER_DOCTOR",
    )


def test_cashier_cannot_read_clinical_records(make_user, entry) -> None:
    cashier = client_as(make_user, "cash", ["cashier"])
    patient_id = entry.visit.patient_id
    for path in (
        "/api/clinical/worklist",
        f"/api/clinical/visits/{entry.visit_id}/workspace",
        f"/api/clinical/patients/{patient_id}/summary",
        f"/api/clinical/patients/{patient_id}/history",
        f"/api/clinical/patients/{patient_id}/allergies",
        "/api/clinical/icd10?q=malaria",
        "/api/orders/catalog",
    ):
        body = err(cashier.get(path), 403, "PERMISSION_DENIED")
        assert body["details"]["permission"]
    err(cashier.post("/api/clinical/worklist/call-next"), 403, "PERMISSION_DENIED")
    err(
        cashier.post(f"/api/orders/visits/{entry.visit_id}/lines", {"items": []}),
        403,
        "PERMISSION_DENIED",
    )


def test_unauthenticated_is_401(entry) -> None:
    client = ApiClient()
    err(client.get("/api/clinical/worklist"), 401, "NOT_AUTHENTICATED")


# --- workspace: notes, diagnoses, vitals, referrals -----------------------------------------


def test_note_diagnosis_vitals_referral(doctor_client, entry, doctor) -> None:
    visit_id = entry.visit_id
    note = ok(
        doctor_client.post(
            f"/api/clinical/visits/{visit_id}/notes",
            {"complaint": "Fever for 3 days", "examination": "T 38.5"},
        ),
        201,
    )
    assert note["status"] == "draft"
    note = ok(doctor_client.patch(f"/api/clinical/notes/{note['id']}", {"plan": "BFMP, CBC"}))
    assert note["plan"] == "BFMP, CBC"
    assert note["complaint"] == "Fever for 3 days"
    found = ok(doctor_client.get("/api/clinical/icd10?q=malaria"))
    assert "B54" in [c["code"] for c in found]
    dx = ok(
        doctor_client.post(
            f"/api/clinical/visits/{visit_id}/diagnoses",
            {"icd10_code": "b54", "note_id": note["id"]},
        ),
        201,
    )
    assert dx["icd10"]["code"] == "B54"
    assert dx["kind"] == "primary"
    err(
        doctor_client.post(f"/api/clinical/visits/{visit_id}/diagnoses", {"icd10_code": "Z99.99"}),
        409,
        "ICD10_UNKNOWN",
    )
    err(
        doctor_client.post(f"/api/clinical/visits/{visit_id}/diagnoses", {}),
        409,
        "DIAGNOSIS_REQUIRED",
    )
    signed = ok(doctor_client.post(f"/api/clinical/notes/{note['id']}/sign"))
    assert signed["status"] == "signed"
    assert signed["signed_at"]
    err(doctor_client.patch(f"/api/clinical/notes/{note['id']}", {"plan": "x"}), 409, "NOTE_SIGNED")
    vitals = ok(
        doctor_client.post(
            f"/api/clinical/visits/{visit_id}/vitals",
            {"temperature_c": "38.5", "pulse_bpm": 96, "bp_systolic": 120, "bp_diastolic": 80},
        ),
        201,
    )
    assert vitals["temperature_c"] == "38.5"
    err(doctor_client.post(f"/api/clinical/visits/{visit_id}/vitals", {}), 409, "VITALS_EMPTY")
    err(
        doctor_client.post(f"/api/clinical/visits/{visit_id}/vitals", {"bp_systolic": 120}),
        409,
        "BP_INCOMPLETE",
    )
    targets = ok(doctor_client.get("/api/clinical/referral-targets"))
    dept = targets["departments"][0]
    referral = ok(
        doctor_client.post(
            f"/api/clinical/visits/{visit_id}/referrals",
            {"kind": "internal", "reason": "Needs a specialist", "to_department_id": dept["id"]},
        ),
        201,
    )
    assert referral["status"] == "issued"
    err(
        doctor_client.post(
            f"/api/clinical/visits/{visit_id}/referrals", {"kind": "external", "reason": "x"}
        ),
        409,
        "FACILITY_REQUIRED",
    )
    cancelled = ok(doctor_client.post(f"/api/clinical/referrals/{referral['id']}/cancel"))
    assert cancelled["status"] == "cancelled"

    ws = ok(doctor_client.get(f"/api/clinical/visits/{visit_id}/workspace"))
    assert ws["visit"]["id"] == visit_id
    assert ws["queue_entry_id"] == entry.pk
    assert ws["queue_status"] == "waiting"
    assert [n["id"] for n in ws["notes"]] == [note["id"]]
    assert [d["id"] for d in ws["diagnoses"]] == [dx["id"]]
    assert len(ws["vitals"]) == 1
    assert len(ws["referrals"]) == 1
    assert_no_prices(ws)

    ok(doctor_client.request("DELETE", f"/api/clinical/diagnoses/{dx['id']}"), 204)
    assert not Diagnosis.objects.filter(pk=dx["id"]).exists()
    assert ClinicalNote.objects.get(pk=note["id"]).status == "signed"


def test_nurse_records_vitals_but_not_notes(make_user, entry) -> None:
    nurse = client_as(make_user, "nurse1", ["nurse"])
    ok(nurse.post(f"/api/clinical/visits/{entry.visit_id}/vitals", {"pulse_bpm": 80}), 201)
    err(
        nurse.post(f"/api/clinical/visits/{entry.visit_id}/notes", {"complaint": "x"}),
        403,
        "PERMISSION_DENIED",
    )


# --- allergies and conditions ---------------------------------------------------------------


def test_allergy_and_condition_registry(doctor_client, entry, penicillins) -> None:
    pid = entry.visit.patient_id
    summary = ok(doctor_client.get(f"/api/clinical/patients/{pid}/summary"))
    assert summary["allergies"] == []
    assert summary["allergies_recorded"] is False
    classes = ok(doctor_client.get("/api/clinical/drug-classes"))
    assert "PEN" in [c["code"] for c in classes]
    allergy = ok(
        doctor_client.post(
            f"/api/clinical/patients/{pid}/allergies",
            {"allergen_type": "drug_class", "drug_class_id": penicillins.pk, "severity": "severe"},
        ),
        201,
    )
    assert allergy["label_en"] == "Penicillins"
    assert allergy["status"] == "active"
    err(
        doctor_client.post(f"/api/clinical/patients/{pid}/allergies", {"allergen_type": "food"}),
        409,
        "ALLERGEN_REQUIRED",
    )
    food = ok(
        doctor_client.post(
            f"/api/clinical/patients/{pid}/allergies",
            {"allergen_type": "food", "substance": "Peanuts", "reaction": "Hives"},
        ),
        201,
    )
    resolved = ok(
        doctor_client.patch(f"/api/clinical/allergies/{food['id']}", {"status": "inactive"})
    )
    assert resolved["status"] == "inactive"
    err(doctor_client.patch(f"/api/clinical/allergies/{food['id']}", {}), 409, "NOTHING_TO_CHANGE")
    registry = ok(doctor_client.get(f"/api/clinical/patients/{pid}/allergies"))
    assert [a["id"] for a in registry] == [allergy["id"], food["id"]]

    condition = ok(
        doctor_client.post(
            f"/api/clinical/patients/{pid}/conditions", {"icd10_code": "e11.9", "name": ""}
        ),
        201,
    )
    assert condition["icd10"]["code"] == "E11.9"
    err(
        doctor_client.post(f"/api/clinical/patients/{pid}/conditions", {}),
        409,
        "CONDITION_NAME_REQUIRED",
    )
    named = ok(
        doctor_client.post(f"/api/clinical/patients/{pid}/conditions", {"name": "Asthma"}), 201
    )
    ok(
        doctor_client.patch(
            f"/api/clinical/conditions/{named['id']}", {"status": "entered_in_error"}
        )
    )
    conditions = ok(doctor_client.get(f"/api/clinical/patients/{pid}/conditions"))
    assert [c["id"] for c in conditions] == [condition["id"]]

    summary = ok(doctor_client.get(f"/api/clinical/patients/{pid}/summary"))
    assert summary["allergies_recorded"] is True
    assert [a["id"] for a in summary["allergies"]] == [allergy["id"]]
    assert [c["id"] for c in summary["conditions"]] == [condition["id"]]
    assert [v["id"] for v in summary["recent_visits"]] == [entry.visit_id]
    assert_no_prices(summary)


# --- orders ---------------------------------------------------------------------------------


def test_catalog_has_no_prices(doctor_client, amoxicillin) -> None:
    rows = ok(doctor_client.get("/api/orders/catalog?q=amox"))
    assert [r["code"] for r in rows] == [amoxicillin.service.code]
    drug = rows[0]["drug"]
    assert drug["generic_name"] == "Amoxicillin"
    assert [c["code"] for c in drug["classes"]] == ["PEN"]
    assert_no_prices(rows)
    lab = b.service("lab", code="LAB-XYZ")
    rows = ok(doctor_client.get("/api/orders/catalog?kind=lab&q=LAB-X"))
    assert [r["id"] for r in rows] == [lab.pk]
    # Consultations and beds are never ordered by hand.
    b.service("consultation", code="CONS-XYZ")
    assert ok(doctor_client.get("/api/orders/catalog?q=CONS-X")) == []
    err(doctor_client.get("/api/orders/catalog?kind=bed"), 422, "VALIDATION_ERROR")


def test_prescription_preview_and_frequencies(doctor_client) -> None:
    codes = [f["code"] for f in ok(doctor_client.get("/api/orders/frequencies"))]
    assert {"OD", "BID", "TID", "PRN", "STAT"} <= set(codes)
    preview = ok(
        doctor_client.post(
            "/api/orders/prescription-preview",
            {"dose_quantity": "1", "frequency_code": "tid", "duration_days": 7},
        )
    )
    assert preview == {"frequency_code": "TID", "frequency_per_day": "3", "quantity": 21}
    preview = ok(
        doctor_client.post(
            "/api/orders/prescription-preview",
            {"dose_quantity": "0.5", "frequency_code": "BID", "duration_days": 5},
        )
    )
    assert preview["quantity"] == 5
    prn = ok(
        doctor_client.post(
            "/api/orders/prescription-preview", {"dose_quantity": "1", "frequency_code": "PRN"}
        )
    )
    assert prn["quantity"] is None
    err(
        doctor_client.post("/api/orders/prescription-preview", {"frequency_code": "XYZ"}),
        409,
        "UNKNOWN_FREQUENCY",
    )


def test_order_lab_tests_and_prescription_with_allergy_override(
    doctor_client, entry, amoxicillin, penicillins, doctor
) -> None:
    from apps.clinical import services as cs

    visit_id = entry.visit_id
    cs.record_allergy(
        entry.visit.patient, actor=doctor[0], allergen_type="drug_class", drug_class=penicillins
    )
    cbc, bfmp, fbs = (b.service("lab") for _ in range(3))
    paracetamol = b.item(generic_name="Paracetamol")
    order = {
        "items": [
            {"service_id": cbc.pk},
            {"service_id": bfmp.pk},
            {"service_id": fbs.pk},
            {
                "service_id": paracetamol.service_id,
                "prescription": {
                    "dose": "1 tablet",
                    "dose_quantity": "1",
                    "frequency_code": "TID",
                    "duration_days": 5,
                },
            },
        ]
    }
    lines = ok(doctor_client.post(f"/api/orders/visits/{visit_id}/lines", order), 201)
    assert [ln["service_id"] for ln in lines] == [
        cbc.pk,
        bfmp.pk,
        fbs.pk,
        paracetamol.service_id,
    ]
    assert {ln["status"] for ln in lines} == {"requested"}
    assert lines[3]["quantity"] == "15"
    assert lines[3]["prescription"]["frequency_per_day"] == "3"
    assert all(ln["can_withdraw"] for ln in lines)
    assert_no_prices(lines)

    amox = {
        "items": [
            {
                "service_id": amoxicillin.service_id,
                "prescription": {
                    "dose": "500 mg",
                    "dose_quantity": "1",
                    "frequency_code": "TID",
                    "duration_days": 7,
                },
            }
        ]
    }
    conflict = err(
        doctor_client.post(f"/api/orders/visits/{visit_id}/lines", amox), 409, "ALLERGY_CONFLICT"
    )
    alert = conflict["details"]["alerts"][0]
    assert alert["service_id"] == amoxicillin.service_id
    assert alert["allergen"] == "Penicillins"
    assert alert["allergen_ar"] == "البنسلينات"
    assert not ServiceLine.objects.filter(visit_id=visit_id, service=amoxicillin.service).exists()
    # A blank reason is no reason.
    err(
        doctor_client.post(
            f"/api/orders/visits/{visit_id}/lines", {**amox, "allergy_override_reason": "  "}
        ),
        409,
        "ALLERGY_CONFLICT",
    )
    given = ok(
        doctor_client.post(
            f"/api/orders/visits/{visit_id}/lines",
            {**amox, "allergy_override_reason": "Mild rash only; no alternative"},
        ),
        201,
    )
    assert given[0]["quantity"] == "21"
    override = given[0]["allergy_overrides"][0]
    assert override["reason"] == "Mild rash only; no alternative"
    assert override["overridden_by"]["id"] == doctor[0].pk
    assert AllergyOverride.objects.filter(service_line_id=given[0]["id"]).count() == 1

    listed = ok(doctor_client.get(f"/api/orders/visits/{visit_id}/lines"))
    assert len(listed) == 5
    assert_no_prices(listed)


def test_withdraw_order(doctor_client, entry) -> None:
    lab = b.service("lab")
    (line,) = ok(
        doctor_client.post(
            f"/api/orders/visits/{entry.visit_id}/lines", {"items": [{"service_id": lab.pk}]}
        ),
        201,
    )
    reasons = ok(doctor_client.get("/api/orders/withdraw-reasons"))
    codes = [r["code"] for r in reasons]
    assert "ORDER_ERROR" in codes
    withdrawn = ok(
        doctor_client.post(
            f"/api/orders/lines/{line['id']}/withdraw",
            {"reason_code": "ORDER_ERROR", "note": "wrong test"},
        )
    )
    assert withdrawn["status"] == "cancelled"
    assert withdrawn["cancellation"]["reason_code"] == "ORDER_ERROR"
    assert withdrawn["cancellation"]["note"] == "wrong test"
    assert withdrawn["can_withdraw"] is False
    err(
        doctor_client.post(
            f"/api/orders/lines/{line['id']}/withdraw", {"reason_code": "ORDER_ERROR"}
        ),
        409,
        "LINE_ALREADY_CANCELLED",
    )
    # The consultation fee is not a clinical order.
    fee = b.service_line(
        entry.visit, b.service("consultation"), order_source=OrderSource.CONSULTATION_FEE
    )
    err(
        doctor_client.post(f"/api/orders/lines/{fee.pk}/withdraw", {"reason_code": "ORDER_ERROR"}),
        409,
        "LINE_NOT_CLINICAL",
    )


def test_reception_cannot_order(make_user, entry) -> None:
    reception = client_as(make_user, "rec", ["receptionist"])
    lab = b.service("lab")
    err(
        reception.post(
            f"/api/orders/visits/{entry.visit_id}/lines", {"items": [{"service_id": lab.pk}]}
        ),
        403,
        "PERMISSION_DENIED",
    )
    # Reception still sees the status of orders (no prices).
    ok(reception.get(f"/api/orders/visits/{entry.visit_id}/lines"))


# --- results and history --------------------------------------------------------------------


def test_approved_results_reach_the_doctor_drafts_do_not(doctor_client, entry, make_user) -> None:
    tech = make_user("tech", roles=["lab_tech"])
    supervisor = make_user("labsup", roles=["lab_supervisor"])
    test = LabTest.objects.create(service=b.service("lab"), code="GLU", sample_type="whole_blood")
    glucose = LabParameter.objects.create(
        test=test, code="GLU", name_ar="سكر", name_en="Glucose", unit="mg/dL"
    )
    ReferenceRange.objects.create(parameter=glucose, low=Decimal(70), high=Decimal(110))
    visit = entry.visit
    approved_line = b.billed_line(visit, test.service)
    draft_line = b.billed_line(visit, test.service)
    sample = ls.collect_sample(visit=visit, lines=[approved_line, draft_line], actor=tech)
    ls.receive_sample(sample, actor=tech)
    ls.enter_results(approved_line, values={"GLU": "180"}, actor=tech)
    ls.enter_results(draft_line, values={"GLU": "90"}, actor=tech)
    version = ls.approve_results(approved_line, actor=supervisor)

    rows = ok(doctor_client.get(f"/api/clinical/patients/{visit.patient_id}/results"))
    assert [r["id"] for r in rows] == [version.pk]
    (value,) = rows[0]["values"]
    assert (value["parameter_code"], value["value"], value["flag"]) == ("GLU", "180", "high")
    assert value["reference"] == "70 - 110"
    assert value["unit"] == "mg/dL"
    by_visit = ok(
        doctor_client.get(
            f"/api/clinical/patients/{visit.patient_id}/results?visit_id={b.visit().pk}"
        )
    )
    assert by_visit == []
    lines = {ln["id"]: ln for ln in ok(doctor_client.get(f"/api/orders/visits/{visit.pk}/lines"))}
    assert lines[approved_line.pk]["result"]["id"] == version.pk
    assert lines[draft_line.pk]["result"] is None
    summary = ok(doctor_client.get(f"/api/clinical/patients/{visit.patient_id}/summary"))
    assert [r["id"] for r in summary["latest_results"]] == [version.pk]
    assert_no_prices([rows, lines, summary])


def test_history_and_favorites(doctor_client, entry, doctor) -> None:
    lab = b.service("lab")
    ok(
        doctor_client.post(
            f"/api/orders/visits/{entry.visit_id}/lines", {"items": [{"service_id": lab.pk}]}
        ),
        201,
    )
    history = ok(doctor_client.get(f"/api/clinical/patients/{entry.visit.patient_id}/history"))
    assert history[0]["visit"]["id"] == entry.visit_id
    assert [ln["status"] for ln in history[0]["lines"]] == ["requested"]
    assert_no_prices(history)

    fav = ok(
        doctor_client.post(
            "/api/clinical/order-sets",
            {"name_en": "Fever work-up", "items": [{"service_id": lab.pk}]},
        ),
        201,
    )
    assert fav["personal"] is True
    assert [i["service_id"] for i in fav["items"]] == [lab.pk]
    shared = OrderSet.objects.create(name_ar="مشترك", name_en="Shared")
    sets = ok(doctor_client.get("/api/clinical/order-sets"))
    assert {fav["id"], shared.pk} <= {o["id"] for o in sets}
    err(
        doctor_client.request("DELETE", f"/api/clinical/order-sets/{shared.pk}"),
        409,
        "ORDER_SET_NOT_OWNER",
    )
    ok(doctor_client.request("DELETE", f"/api/clinical/order-sets/{fav['id']}"), 204)
    assert fav["id"] not in {o["id"] for o in ok(doctor_client.get("/api/clinical/order-sets"))}
    err(
        doctor_client.post(
            "/api/clinical/order-sets", {"name_en": "x", "items": [{"service_id": 0}]}
        ),
        409,
        "SERVICE_INACTIVE",
    )


def test_openapi_doctor_schemas_carry_no_prices() -> None:
    from apps.core.management.commands.export_openapi import render_schema

    schema = json.loads(render_schema())
    for path, item in schema["paths"].items():
        if not path.startswith(("/api/clinical/", "/api/orders/")):
            continue
        for op in item.values():
            body = op["responses"].get("200") or op["responses"].get("201")
            if body is None or "content" not in body:
                continue
            ref = json.dumps(body["content"])
            assert "Price" not in ref, path
    for name, component in schema["components"]["schemas"].items():
        if name in {"DoctorLineOut", "OrderableServiceOut", "PatientSummaryOut", "WorkspaceOut"}:
            assert_no_prices(component.get("properties", {}))
