"""``/api/orders/procedures`` contract (FEATURES 10.1, 10.2): happy path, the roles that may
not use it (403 sweep), and the domain error codes."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from apps.clinical import services as cs
from apps.core.tests import builders as b
from apps.orders.models import ServiceLine
from apps.payments import services as pay
from apps.payments.tests import fin
from conftest import ApiClient

pytestmark = pytest.mark.django_db

URL = "/api/orders/procedures"
FORBIDDEN_ROLES = [
    "receptionist",
    "cashier",
    "cashier_supervisor",
    "pharmacist",
    "lab_tech",
    "lab_supervisor",
    "accountant",
    "manager",
]


@pytest.fixture(autouse=True)
def _seed() -> None:
    fin.seed()


def _client(make_user: Any, role: str) -> ApiClient:
    user = make_user(roles=[role])
    api = ApiClient()
    assert api.login(user.username).status_code == 200
    return api


def _paid_procedure(note: str = "") -> ServiceLine:
    doctor, cashier = fin.staff("doctor"), fin.staff("cashier")
    visit = fin.visit(b.patient(full_name_en="Mona Saeed"))
    cs.record_allergy(
        visit.patient, actor=doctor, allergen_type="other", substance="Latex", severity="severe"
    )
    (line,) = fin.order(visit, doctor, fin.priced("procedure"), note=note)
    inv = fin.invoice(visit, cashier, [line])
    shift = pay.current_shift(cashier) or pay.open_shift(cashier, Decimal("0.00"))
    pay.record_payment(shift, inv.patient, "cash", inv.patient_total, actor=cashier, auto=True)
    return line


def test_nurse_sees_paid_procedure_marks_it_done_and_sees_it_in_done(make_user: Any) -> None:
    line = _paid_procedure(note="IM ceftriaxone")
    unpaid_visit = fin.visit()
    (unpaid,) = fin.order(unpaid_visit, fin.staff("doctor"), fin.priced("procedure"))
    nurse = _client(make_user, "nurse")

    rows = nurse.get(URL).json()
    assert [r["id"] for r in rows] == [line.pk]
    row = rows[0]
    assert row["note"] == "IM ceftriaxone"
    assert row["patient"]["full_name_en"] == "Mona Saeed"
    assert [a["label_en"] for a in row["allergies"]] == ["Latex"]
    assert row["authorized"] is False
    assert row["performed"] is False
    assert "price" not in str(rows)
    assert "gross" not in str(rows)
    assert unpaid.pk not in {r["id"] for r in rows}

    assert [r["id"] for r in nurse.get(f"{URL}?q=mona").json()] == [line.pk]
    assert nurse.get(f"{URL}?q=nobody-like-this").json() == []

    done = nurse.post(f"{URL}/{line.pk}/done", {"note": "left arm"})
    assert done.status_code == 200, done.content
    body = done.json()
    assert body["performed"] is True
    assert body["performed_note"] == "left arm"
    assert body["performed_by"]["id"] is not None
    assert body["performed_at"] is not None
    assert nurse.get(URL).json() == []
    assert [r["id"] for r in nurse.get(f"{URL}/done").json()] == [line.pk]

    again = nurse.post(f"{URL}/{line.pk}/done", {})
    assert again.status_code == 409
    assert again.json()["code"] == "LINE_ALREADY_PERFORMED"


def test_unpaid_and_other_kinds_are_refused(make_user: Any) -> None:
    doctor = fin.staff("doctor")
    visit = fin.visit()
    procedure, lab = fin.order(visit, doctor, fin.priced("procedure"), fin.priced("lab"))
    nurse = _client(make_user, "nurse")
    r = nurse.post(f"{URL}/{procedure.pk}/done", {})
    assert r.status_code == 409
    assert r.json()["code"] == "LINE_NOT_ELIGIBLE"
    r = nurse.post(f"{URL}/{lab.pk}/done", {})
    assert r.status_code == 409
    assert r.json()["code"] == "LINE_NOT_PROCEDURE"
    assert nurse.post(f"{URL}/999999/done", {}).status_code == 404


def test_doctor_may_mark_done(make_user: Any) -> None:
    line = _paid_procedure()
    doctor = _client(make_user, "doctor")
    assert doctor.post(f"{URL}/{line.pk}/done", {}).status_code == 200


@pytest.mark.parametrize("role", FORBIDDEN_ROLES)
def test_roles_without_the_permission_get_403(make_user: Any, role: str) -> None:
    line = _paid_procedure()
    api = _client(make_user, role)
    for method, path in (
        ("GET", URL),
        ("GET", f"{URL}/done"),
        ("POST", f"{URL}/{line.pk}/done"),
    ):
        r = api.request(method, path, None if method == "GET" else {})
        assert r.status_code == 403, (role, path, r.status_code)
        assert r.json()["code"] == "PERMISSION_DENIED"
    assert ServiceLine.objects.get(pk=line.pk).fulfilment_status == "pending"
