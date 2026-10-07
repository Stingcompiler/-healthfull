"""``manage.py e2e_fixture``: named e2e data builders over the services."""

from __future__ import annotations

import io
import json
from decimal import Decimal
from io import StringIO
from typing import Any

import pytest
from django.core.management import CommandError, call_command
from django.db import DatabaseError

from apps.core.e2e import fixtures
from apps.orders.models import ServiceLine
from apps.payments.models import Shift, ShiftStatus
from apps.visits.models import QueueEntry

pytestmark = pytest.mark.django_db


@pytest.fixture
def seeded(settings: Any) -> None:
    settings.DEBUG = True
    call_command("seed_e2e", stdout=StringIO())


def run(name: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    out = StringIO()
    call_command("e2e_fixture", name, params=json.dumps(params or {}), as_json=True, stdout=out)
    payload = json.loads(out.getvalue())
    assert payload["ok"] is True
    assert payload["fixture"] == name
    result: dict[str, Any] = payload["result"]
    return result


def fail(name: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    out = StringIO()
    with pytest.raises(CommandError) as info:
        call_command("e2e_fixture", name, params=json.dumps(params or {}), as_json=True, stdout=out)
    assert info.value.returncode == 2
    payload = json.loads(out.getvalue())
    assert payload["ok"] is False
    error: dict[str, Any] = payload["error"]
    return error


def shares(invoice: dict[str, Any]) -> dict[str, tuple[str, str]]:
    return {ln["service"]: (ln["payer_share"], ln["patient_share"]) for ln in invoice["lines"]}


# --- command contract ---------------------------------------------------------------------------


def test_refuses_without_debug(settings: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    settings.DEBUG = False
    monkeypatch.delenv("ALLOW_SEED_E2E", raising=False)
    with pytest.raises(CommandError, match="Refusing"):
        call_command("e2e_fixture", "catalog", stdout=StringIO())


def test_refuses_a_database_that_is_not_a_test_one(
    settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from django.db import connection

    settings.DEBUG = True
    monkeypatch.delenv("ALLOW_SEED_E2E", raising=False)
    monkeypatch.setitem(connection.settings_dict, "NAME", "hospital_dev")
    with pytest.raises(CommandError, match="hospital_dev"):
        call_command("e2e_fixture", "catalog", stdout=StringIO())


def test_list_names_every_fixture(seeded: None) -> None:
    out = StringIO()
    call_command("e2e_fixture", list=True, stdout=out)
    text = out.getvalue()
    for name in (
        "catalog",
        "patient",
        "coverage",
        "visit",
        "order",
        "invoice",
        "approve_invoice",
        "open_shift",
        "pay",
        "close_shift",
        "paid_visit",
    ):
        assert f"{name}: " in text


def test_unknown_fixture_and_parameters_fail_loudly(seeded: None) -> None:
    assert fail("nope")["code"] == "FIXTURE_UNKNOWN"
    error = fail("patient", {"ful_name_ar": "typo"})
    assert error["code"] == "FIXTURE_PARAM_UNKNOWN"
    assert error["details"]["unknown"] == ["ful_name_ar"]
    assert fail("visit", {"patient": "PT-NOPE"})["code"] == "FIXTURE_REF_NOT_FOUND"
    assert fail("visit", {})["code"] == "FIXTURE_PARAM_INVALID"
    # Money is never a float (ARCHITECTURE 4.3).
    error = fail("open_shift", {"opening_float": 1.5})
    assert (error["code"], error["details"]["param"]) == ("FIXTURE_PARAM_INVALID", "opening_float")
    out = StringIO()
    with pytest.raises(CommandError):
        call_command("e2e_fixture", "patient", params="[1]", as_json=True, stdout=out)
    assert json.loads(out.getvalue())["error"]["code"] == "FIXTURE_PARAMS_INVALID"


def test_params_from_stdin(seeded: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"full_name_en": "Stdin Person"})))
    out = StringIO()
    call_command("e2e_fixture", "patient", params="-", as_json=True, stdout=out)
    assert json.loads(out.getvalue())["result"]["patient"]["full_name_en"] == "Stdin Person"


def test_output_without_json_flag_is_indented_unicode(seeded: None) -> None:
    out = StringIO()
    call_command(
        "e2e_fixture", "patient", params=json.dumps({"full_name_ar": "آمنة علي"}), stdout=out
    )
    assert "آمنة علي" in out.getvalue()
    assert out.getvalue().startswith("{\n")


def test_the_acting_user_needs_the_endpoint_permission(seeded: None) -> None:
    patient = run("patient")["patient"]
    visit = run("visit", {"patient": patient["id"]})["visit"]
    error = fail(
        "order", {"visit": visit["id"], "items": [{"service": "LAB-CBC"}], "as": "cashier"}
    )
    assert (error["code"], error["details"]["permission"]) == ("PERMISSION_DENIED", "orders.create")
    run("approve_invoice", {"visit": visit["id"]})
    error = fail("pay", {"visit": visit["id"], "as": "doctor"})
    assert error["details"]["permission"] == "payments.take_payment"
    assert fail("open_shift", {"as": "ghost"})["code"] == "FIXTURE_REF_NOT_FOUND"


def test_a_refused_step_leaves_nothing_behind(seeded: None) -> None:
    patient = run("patient")["patient"]
    visit = run("visit", {"patient": patient["id"]})["visit"]
    before = ServiceLine.objects.count()
    error = fail(
        "order",
        {"visit": visit["id"], "items": [{"service": "LAB-CBC"}, {"service": "NO-SUCH"}]},
    )
    assert error["code"] == "FIXTURE_REF_NOT_FOUND"
    assert ServiceLine.objects.count() == before


def test_database_guard_messages_become_error_codes() -> None:
    error = fixtures._db_error(DatabaseError("APPEND_ONLY: rows never change\nCONTEXT: x"))
    assert (error.code, error.message) == ("APPEND_ONLY", "rows never change")
    assert fixtures._db_error(DatabaseError("boom")).code == "DATABASE_ERROR"


def test_fixtures_registered_elsewhere_run_too(seeded: None) -> None:
    @fixtures.fixture("probe_e2e", summary="test only", params=("value",))
    def probe(p: fixtures.Params) -> dict[str, Any]:
        return {"value": p.text("value"), "actor": p.actor("nurse").username}

    try:
        assert run("probe_e2e", {"value": "x"}) == {"value": "x", "actor": "nurse"}
        with pytest.raises(ValueError, match="twice"):
            fixtures.fixture("probe_e2e", summary="again", params=())(lambda p: {})
    finally:
        fixtures.REGISTRY.pop("probe_e2e", None)


# --- the money cycle --------------------------------------------------------------------------


def test_catalog_lookup(seeded: None) -> None:
    data = run("catalog")
    assert data["services"]["CONS-GEN"]["cash_price"] == "15000.00"
    assert data["doctors"]["pediatrician"]["consultation_service"] == "CONS-PED"
    assert data["payers"]["AMAN"]["price_list"] == "AMAN"
    amox = data["items"]["DRG-AMOX500"]
    assert amox["units"] == {"strip": 10, "box": 20}
    assert [b["stock"]["PHA"] for b in amox["batches"]] == [40, 200]
    assert set(data["stores"]) == {"MAIN", "PHA"}
    assert data["beds"]["F-04"]["status"] == "maintenance"


def test_full_cycle_with_a_percentage_payer_and_an_exclusion(seeded: None) -> None:
    made = run("patient", {"payer": "AMAN"})
    patient, coverage = made["patient"], made["coverage"]
    assert coverage["payer"] == "AMAN"
    assert coverage["card_number"].startswith("AMAN-")
    assert patient["file_no"]
    assert patient["full_name_ar"]
    assert patient["full_name_en"]

    opened = run("visit", {"patient": patient["file_no"]})
    visit = opened["visit"]
    assert (visit["payer"], visit["doctor"], visit["department"]) == ("AMAN", "doctor", "GEN")
    assert [(ln["service"], ln["state"]) for ln in opened["lines"]] == [("CONS-GEN", "requested")]
    assert opened["queue_entry"]["ready"] is False

    ordered = run(
        "order",
        {
            "visit": visit["number"],
            "items": [
                {"service": "LAB-CBC"},
                {
                    "service": "DRG-AMOX500",
                    "prescription": {
                        "dose": "500 mg",
                        "dose_quantity": "1",
                        "frequency_per_day": 3,
                        "duration_days": 7,
                        "frequency_code": "TID",
                    },
                },
                {"service": "DEN-FILL"},
            ],
        },
    )["lines"]
    assert [(ln["service"], ln["quantity"]) for ln in ordered] == [
        ("LAB-CBC", 1),
        ("DRG-AMOX500", 21),
        ("DEN-FILL", 1),
    ]

    invoice = run("approve_invoice", {"visit": visit["id"]})["invoice"]
    assert invoice["status"] == "approved"
    assert invoice["number"].startswith("INV-")
    # AMAN list = cash x 0.90; AMAN pays 70%; dental fillings are excluded (100% patient).
    assert shares(invoice) == {
        "CONS-GEN": ("9450.00", "4050.00"),
        "LAB-CBC": ("7560.00", "3240.00"),
        "DRG-AMOX500": ("3969.00", "1701.00"),
        "DEN-FILL": ("0.00", "27000.00"),
    }
    assert invoice["outstanding"] == invoice["patient_total"] == "35991.00"

    opened_shift = run("open_shift", {"opening_float": "5000"})["shift"]
    assert opened_shift["expected_cash"] == "5000.00"
    paid = run("pay", {"invoice": invoice["number"]})
    assert paid["payment"]["amount"] == "35991.00"
    assert paid["payment"]["verification"] == "confirmed"
    assert paid["allocations"] == [{"invoice_id": invoice["id"], "amount": "35991.00"}]
    assert paid["invoices"][0]["outstanding"] == "0.00"
    assert {ln["state"] for ln in paid["lines"]} == {"paid"}
    assert paid["shift"]["expected_cash"] == "40991.00"

    closed = run("close_shift")["shift"]
    assert (closed["status"], closed["counted_cash"], closed["variance"]) == (
        "closed",
        "40991.00",
        "0.00",
    )


def test_copay_and_ceiling_payers(seeded: None) -> None:
    nakheel = run("patient", {"payer": "NAKHEEL"})["patient"]
    visit = run("visit", {"patient": nakheel["id"]})["visit"]
    invoice = run("approve_invoice", {"visit": visit["id"]})["invoice"]
    assert shares(invoice) == {"CONS-GEN": ("13000.00", "2000.00")}

    rahma = run("patient", {"payer": "RAHMA"})["patient"]
    visit = run("visit", {"patient": rahma["id"]})["visit"]
    run("order", {"visit": visit["id"], "items": [{"service": "LAB-CBC"}]})
    result = run("approve_invoice", {"visit": visit["id"]})
    # RAHMA list = cash x 0.80; RAHMA pays up to 10,000 a line.
    assert shares(result["invoice"]) == {
        "CONS-GEN": ("10000.00", "2000.00"),
        "LAB-CBC": ("9600.00", "0.00"),
    }
    states = {ln["service"]: ln["state"] for ln in result["lines"]}
    assert states == {"CONS-GEN": "invoiced", "LAB-CBC": "paid"}  # zero patient share settles


def test_preapproval_rule_and_cash_visit_on_a_covered_file(seeded: None) -> None:
    patient = run("patient", {"payer": "AMAN", "sex": "female"})["patient"]
    visit = run("visit", {"patient": patient["id"], "doctor": "gynecologist"})["visit"]
    run("order", {"visit": visit["id"], "items": [{"service": "GYN-US"}], "as": "gynecologist"})
    assert fail("approve_invoice", {"visit": visit["id"]})["code"] == "PREAPPROVAL_REQUIRED"

    other = run("visit", {"patient": patient["id"], "doctor": "dentist", "coverage": "cash"})
    assert other["visit"]["payer"] is None
    run(
        "order",
        {
            "visit": other["visit"]["id"],
            "items": [{"service": "GYN-US", "pre_approval_ref": "PA-1"}],
            "as": "dentist",
        },
    )
    invoice = run("approve_invoice", {"visit": other["visit"]["id"]})["invoice"]
    assert shares(invoice) == {
        "CONS-DEN": ("0.00", "15000.00"),
        "GYN-US": ("0.00", "20000.00"),
    }


def test_invoice_selection_draft_then_approve(seeded: None) -> None:
    patient = run("patient")["patient"]
    visit = run("visit", {"patient": patient["id"], "coverage": "cash"})["visit"]
    lines = run(
        "order",
        {"visit": visit["id"], "items": [{"service": "LAB-RBS"}, {"service": "PRC-INJ"}]},
    )["lines"]
    draft = run("invoice", {"visit": visit["id"], "services": ["LAB-RBS"]})["invoice"]
    assert (draft["status"], draft["number"], draft["outstanding"]) == ("draft", None, None)
    assert [ln["service"] for ln in draft["lines"]] == ["LAB-RBS"]
    approved = run("approve_invoice", {"invoice": draft["id"]})["invoice"]
    assert approved["patient_total"] == "3500.00"
    rest = run("invoice", {"visit": visit["id"], "lines": [lines[1]["id"]], "approve": True})
    assert rest["invoice"]["status"] == "approved"
    assert [ln["service"] for ln in rest["invoice"]["lines"]] == ["PRC-INJ"]
    assert fail("invoice", {"visit": visit["id"], "services": ["LAB-RBS"]})["code"] == (
        "FIXTURE_PARAM_INVALID"
    )


def test_transfer_payment_is_pending_and_still_settles(seeded: None) -> None:
    patient = run("patient")["patient"]
    visit = run("visit", {"patient": patient["id"]})["visit"]
    run("approve_invoice", {"visit": visit["id"]})
    paid = run("pay", {"visit": visit["id"], "method": "bank_transfer"})
    payment = paid["payment"]
    assert (payment["method"], payment["verification"], payment["bank"]) == (
        "bank_transfer",
        "pending",
        "BOK",
    )
    assert payment["reference"].startswith("E2E")
    assert {ln["state"] for ln in paid["lines"]} == {"paid"}
    # Transfers are not drawer cash.
    assert paid["shift"]["expected_cash"] == "0.00"


def test_pay_a_patient_with_credit_left_over(seeded: None) -> None:
    patient = run("patient")["patient"]
    visit = run("visit", {"patient": patient["id"]})["visit"]
    run("approve_invoice", {"visit": visit["id"]})
    paid = run("pay", {"patient": patient["id"], "amount": "20000"})
    assert paid["allocations"] == [{"invoice_id": paid["invoices"][0]["id"], "amount": "15000.00"}]
    credit_only = run("pay", {"patient": patient["id"], "amount": 500, "allocate": "none"})
    assert credit_only["allocations"] == []
    assert fail("pay", {"patient": patient["id"]})["code"] == "FIXTURE_PARAM_INVALID"


def test_shift_reuse_close_and_variance(seeded: None) -> None:
    first = run("open_shift")["shift"]
    assert fail("open_shift")["code"] == "SHIFT_ALREADY_OPEN"
    assert run("open_shift", {"if_open": "reuse"})["shift"]["id"] == first["id"]
    second = run("open_shift", {"if_open": "close", "opening_float": "1000"})["shift"]
    assert second["id"] != first["id"]
    assert Shift.objects.get(pk=first["id"]).status == ShiftStatus.CLOSED
    assert fail("close_shift", {"counted": "900"})["code"] == "VARIANCE_EXPLANATION_REQUIRED"
    closed = run("close_shift", {"counted": "900", "reason": "COUNTING_ERROR"})["shift"]
    assert (closed["variance"], closed["expected_cash"]) == ("-100.00", "1000.00")
    assert fail("close_shift")["code"] == "SHIFT_NOT_OPEN"
    patient = run("patient")["patient"]
    error = fail("pay", {"patient": patient["id"], "amount": "1", "open_shift": False})
    assert error["code"] == "SHIFT_NOT_OPEN"


def test_paid_visit_waits_ready_in_the_doctors_queue(seeded: None) -> None:
    made = run(
        "paid_visit",
        {"doctor": "pediatrician", "patient_fields": {"sex": "male", "age_years": 4}},
    )
    assert made["visit"]["department"] == "PED"
    assert made["invoice"]["outstanding"] == "0.00"
    assert made["payment"]["amount"] == "20000.00"
    assert made["queue_entry"]["ready"] is True
    assert made["queue_entry"]["doctor"] == "pediatrician"
    assert [ln["state"] for ln in made["lines"]] == ["paid"]
    entry = QueueEntry.objects.get(pk=made["queue_entry"]["id"])
    assert entry.visit_id == made["visit"]["id"]
    # A second visit with the same doctor within the follow-up window is free: no fee to pay.
    again = run("paid_visit", {"patient": made["patient"]["id"], "doctor": "pediatrician"})
    assert again["visit"]["visit_type"] == "follow_up"
    assert again["invoice"] is None
    assert again["queue_entry"]["ready"] is True


def test_emergency_registration_and_explicit_names(seeded: None) -> None:
    emergency = run(
        "patient", {"emergency": True, "full_name_en": "Unknown male", "sex": "unknown"}
    )
    assert emergency["patient"]["is_incomplete"] is True
    named = run(
        "patient",
        {
            "full_name_ar": "عثمان النور",
            "full_name_en": "Osman Alnour",
            "sex": "male",
            "date_of_birth": "1980-05-01",
            "phone": "0912345678",
        },
    )["patient"]
    assert (named["date_of_birth"], named["phone"]) == ("1980-05-01", "0912345678")
    # The duplicate check is skipped by default and applies when asked for.
    error = fail(
        "patient",
        {
            "full_name_en": "Osman Alnour",
            "sex": "male",
            "phone": "0912345678",
            "confirm_not_duplicate": False,
        },
    )
    assert error["code"] == "DUPLICATE_PATIENT"


def test_amounts_are_strings_with_two_decimals(seeded: None) -> None:
    made = run("paid_visit")
    for key in ("gross_total", "payer_total", "patient_total", "outstanding"):
        assert Decimal(made["invoice"][key]) == Decimal(made["invoice"][key]).quantize(
            Decimal("0.01")
        )
        assert isinstance(made["invoice"][key], str)
    assert made["shift"]["status"] == "open"


def test_allergies_on_file_drive_the_prescribing_alert(seeded: None) -> None:
    made = run(
        "patient",
        {"allergies": ["PENICILLIN", {"substance": "Peanuts", "allergen_type": "food"}]},
    )
    assert [(a["allergen_type"], a["drug_class"], a["substance"]) for a in made["allergies"]] == [
        ("drug_class", "PENICILLIN", ""),
        ("food", None, "Peanuts"),
    ]
    assert run("patient")["allergies"] == []
    visit = run("visit", {"patient": made["patient"]["id"]})["visit"]
    items = [{"service": "DRG-AMOX500", "quantity": 21}]
    error = fail("order", {"visit": visit["id"], "items": items})
    assert error["code"] == "ALLERGY_ALERT"
    lines = run("order", {"visit": visit["id"], "items": items, "acknowledge_allergies": True})
    assert [ln["service"] for ln in lines["lines"]] == ["DRG-AMOX500"]
    # Reception cannot record allergies; the default recorder is the nurse.
    denied = fail("patient", {"allergies": ["NSAID"], "allergies_as": "reception"})
    assert denied["details"]["permission"] == "clinical.manage_allergies"
