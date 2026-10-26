# ruff: noqa: F811  (pytest fixtures imported from test_api)
"""Printed prescription and referral letter (FEATURES 3.5, 3.9; inspection F03): what the
doctor hands to the patient carries the center's identity and print template, the patient,
the visit and the clinical content, and never a price."""

from __future__ import annotations

from typing import Any

import pytest

from apps.clinical.tests.test_api import (  # noqa: F401  (fixtures)
    assert_no_prices,
    client_as,
    doctor,
    doctor_client,
    entry,
    err,
    ok,
)
from apps.core.models import CenterProfile, PrintTemplate
from apps.core.tests import builders as b

pytestmark = pytest.mark.django_db


def _prescribe(client: Any, visit_id: int) -> list[dict[str, Any]]:
    paracetamol = b.item(generic_name="Paracetamol")
    order = {
        "items": [
            {"service_id": b.service("lab").pk},
            {
                "service_id": paracetamol.service_id,
                "prescription": {
                    "dose": "1 tablet",
                    "dose_quantity": "1",
                    "frequency_code": "TID",
                    "duration_days": 5,
                    "instructions": "After meals",
                },
            },
        ]
    }
    return list(ok(client.post(f"/api/orders/visits/{visit_id}/lines", order), 201))


@pytest.fixture
def center() -> CenterProfile:
    c = CenterProfile.load()
    c.name_ar, c.name_en, c.address, c.phone = "مركز النيل", "Nile Center", "Khartoum", "0912"
    c.save()
    PrintTemplate.objects.create(
        document="prescription", paper="a4", header_ar="رأس الوصفة", footer_en="Rx footer"
    )
    PrintTemplate.objects.create(document="referral", paper="a4", footer_ar="ذيل الإحالة")
    return c


def test_prescription_print_has_the_drugs_and_no_price(doctor_client, entry, center) -> None:
    _prescribe(doctor_client, entry.visit_id)
    body = ok(doctor_client.get(f"/api/clinical/visits/{entry.visit_id}/prescription/print"))
    assert body["center"] == {
        "name_ar": "مركز النيل",
        "name_en": "Nile Center",
        "address": "Khartoum",
        "phone": "0912",
        "has_logo": False,
    }
    assert body["template"]["header_ar"] == "رأس الوصفة"
    assert body["template"]["footer_en"] == "Rx footer"
    assert body["patient"]["full_name_en"] == "Khalid Osman"
    assert body["visit_number"] == entry.visit.number
    (item,) = body["items"]  # the lab test is not on the prescription
    assert (item["dose"], item["frequency_code"], item["duration_days"]) == ("1 tablet", "TID", 5)
    assert item["instructions"] == "After meals"
    assert item["quantity"] == 15
    assert body["prescriber"]["name_en"]
    assert_no_prices(body)


def test_prescription_print_without_drugs_is_refused(doctor_client, entry) -> None:
    err(
        doctor_client.get(f"/api/clinical/visits/{entry.visit_id}/prescription/print"),
        409,
        "NO_PRESCRIPTION",
    )
    err(doctor_client.get("/api/clinical/visits/999999/prescription/print"), 404, "NOT_FOUND")


def test_referral_letter_prints_until_cancelled(doctor_client, entry, center) -> None:
    referral = ok(
        doctor_client.post(
            f"/api/clinical/visits/{entry.visit_id}/referrals",
            {
                "kind": "external",
                "external_facility": "Khartoum Teaching Hospital",
                "reason": "Suspected appendicitis",
                "clinical_summary": "RLQ pain 2 days",
                "urgency": "urgent",
            },
        ),
        201,
    )
    body = ok(doctor_client.get(f"/api/clinical/referrals/{referral['id']}/print"))
    assert body["referral"]["external_facility"] == "Khartoum Teaching Hospital"
    assert body["referral"]["urgency"] == "urgent"
    assert body["template"]["footer_ar"] == "ذيل الإحالة"
    assert body["patient"]["file_no"] == entry.visit.patient.file_no
    assert_no_prices(body)
    ok(
        doctor_client.post(
            f"/api/clinical/referrals/{referral['id']}/cancel", {"reason": "Written in error"}
        )
    )
    err(
        doctor_client.get(f"/api/clinical/referrals/{referral['id']}/print"), 409, "REFERRAL_CLOSED"
    )


def test_prints_need_the_clinical_record(make_user, doctor_client, entry) -> None:
    _prescribe(doctor_client, entry.visit_id)
    cashier = client_as(make_user, "cash", ["cashier"])
    body = err(
        cashier.get(f"/api/clinical/visits/{entry.visit_id}/prescription/print"),
        403,
        "PERMISSION_DENIED",
    )
    assert body["details"] == {"permission": "clinical.view"}
    nurse = client_as(make_user, "nurse1", ["nurse"])
    ok(nurse.get(f"/api/clinical/visits/{entry.visit_id}/prescription/print"))
