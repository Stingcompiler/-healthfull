"""``/api/lab`` contract: work list, samples, results, approval, amendment, cancellation,
catalog, turnaround report, and a generated permission sweep over every lab operation.

The rules themselves are tested in ``test_services.py`` and ``test_bench.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pytest

from apps.catalog.tests import engine
from apps.core.models import User
from apps.core.permissions import effective_permissions
from apps.core.tests import builders as b
from apps.lab.models import LabParameter, LabTest, ResultVersion
from apps.lab.tests.test_services import adult, lab_line
from apps.payments.tests.test_permission_matrix import _request, _required_permissions, _schema
from conftest import TEST_PASSWORD, ApiClient, router_operations

pytestmark = pytest.mark.django_db


@dataclass
class Who:
    user: User
    api: ApiClient


def _login(make_user: Any, username: str, *roles: str) -> Who:
    user = make_user(username, roles=list(roles))
    client = ApiClient()
    assert client.login(username, TEST_PASSWORD).status_code == 200
    return Who(user, client)


@dataclass
class Bench:
    tech: Who
    sup: Who
    doctor: Who
    cashsup: Who


@pytest.fixture
def lab(make_user: Any) -> Bench:
    return Bench(
        tech=_login(make_user, "tech", "lab_tech"),
        sup=_login(make_user, "labsup", "lab_supervisor"),
        doctor=_login(make_user, "doc", "doctor"),
        cashsup=_login(make_user, "cashsup", "cashier_supervisor"),
    )


def ok(response: Any, status: int = 200) -> Any:
    assert response.status_code == status, response.content
    return response.json()


def err(response: Any, status: int, code: str) -> Any:
    assert response.status_code == status, response.content
    body = response.json()
    assert body["code"] == code, body
    return body


def _received(lab: Bench, line_id: int) -> dict[str, Any]:
    return ok(lab.tech.api.post("/api/lab/samples", {"line_ids": [line_id]}), 201)


# --- surface ---------------------------------------------------------------------------------


def test_router_surface_and_permissions() -> None:
    ops = {(op_id, perm) for _, _, op_id, perm in router_operations("/lab")}
    assert ops == {
        ("lab_get_ping", None),
        ("lab_list_worklist", "lab.view_worklist"),
        ("lab_get_result", "lab.view_worklist"),
        ("lab_enter_results", "lab.enter_results"),
        ("lab_approve_results", "lab.approve_results"),
        ("lab_amend_results", "lab.amend_results"),
        ("lab_get_result_print", "lab.print_results"),
        ("lab_cancel_test", "lab.cancel_test"),
        ("lab_list_approvals", "lab.approve_results"),
        ("lab_collect_sample", "lab.collect_sample"),
        ("lab_receive_sample", "lab.receive_sample"),
        ("lab_reject_sample", "lab.receive_sample"),
        ("lab_get_sample_label", "lab.collect_sample"),
        ("lab_mark_label_printed", "lab.collect_sample"),
        ("lab_list_tests", "lab.manage_tests"),
        ("lab_get_test", "lab.manage_tests"),
        ("lab_list_unlinked_services", "lab.manage_tests"),
        ("lab_create_test", "lab.manage_tests"),
        ("lab_update_test", "lab.manage_tests"),
        ("lab_create_parameter", "lab.manage_tests"),
        ("lab_update_parameter", "lab.manage_tests"),
        ("lab_create_range", "lab.manage_tests"),
        ("lab_update_range", "lab.manage_tests"),
        ("lab_delete_range", "lab.manage_tests"),
        ("lab_get_turnaround_report", "lab.view_reports"),
    }


PROBE_ROLES = (
    "doctor",
    "nurse",
    "receptionist",
    "cashier",
    "cashier_supervisor",
    "pharmacist",
    "lab_tech",
    "manager",
    "accountant",
)


def test_every_lab_operation_refuses_roles_without_its_permission(make_user: Any) -> None:
    schema = _schema()
    required = _required_permissions()
    probes = {role: _login(make_user, f"probe_{role}", role) for role in PROBE_ROLES}
    held = {role: effective_permissions(p.user) for role, p in probes.items()}
    checked: set[tuple[str, str]] = set()
    ops = [
        (path, method, op)
        for path, item in schema["paths"].items()
        for method, op in item.items()
        if path.startswith("/api/lab/") and not path.endswith("/ping")
    ]
    for path, method, op in ops:
        op_id = op["operationId"]
        code = required[op_id]
        url, body = _request(schema, path, op)
        for role, probe in probes.items():
            if code in held[role]:
                continue
            response = probe.api.request(method.upper(), url, body)
            assert response.status_code == 403, (op_id, role, response.content)
            assert response.json()["details"]["permission"] == code, (op_id, role)
            checked.add((op_id, role))
    every = {op["operationId"] for _, _, op in ops}
    assert {op_id for op_id, _ in checked} == every
    # Doctors reach only the printout of approved results; cashiers reach nothing of the lab.
    doctor_ops = every - {op_id for op_id, role in checked if role == "doctor"}
    assert doctor_ops == {"lab_get_result_print"}
    assert {op_id for op_id, role in checked if role == "cashier"} == every


# --- work list -------------------------------------------------------------------------------


def test_worklist_shows_paid_tests_only(lab: Bench, cbc: LabTest) -> None:
    visit = b.visit(adult())
    paid = lab_line(visit, cbc)
    invoiced = lab_line(visit, cbc, billing_status="invoiced")
    unbilled = lab_line(visit, cbc, billing_status="unbilled")
    body = ok(lab.tech.api.get("/api/lab/worklist"))
    ids = {row["line_id"] for row in body["items"]}
    assert paid.pk in ids
    assert invoiced.pk not in ids
    assert unbilled.pk not in ids
    (row,) = [r for r in body["items"] if r["line_id"] == paid.pk]
    assert row["stage"] == "to_collect"
    assert row["authorized"] is False
    assert body["counts"]["to_collect"] >= 1
    # A file number search and a stage filter narrow the list.
    found = ok(lab.tech.api.get(f"/api/lab/worklist?q={visit.patient.file_no}&status=to_collect"))
    assert [r["line_id"] for r in found["items"]] == [paid.pk]
    assert ok(lab.tech.api.get("/api/lab/worklist?status=to_approve"))["count"] == 0
    # The unpaid test cannot be worked on through the API either (invariant 1).
    err(
        lab.tech.api.post("/api/lab/samples", {"line_ids": [invoiced.pk]}),
        409,
        "LINE_NOT_ELIGIBLE",
    )


def test_receive_enter_flag_approve_and_doctor_print(lab: Bench, cbc: LabTest) -> None:
    visit = b.visit(adult())
    line = lab_line(visit, cbc)
    detail = _received(lab, line.pk)
    assert detail["stage"] == "to_enter"
    assert detail["line"]["fulfilment_status"] == "in_progress"
    sample = detail["sample"]
    assert sample["status"] == "received"
    hb = next(p for p in detail["parameters"] if p["code"] == "HB")
    assert hb["range"] == {
        "low": "13",
        "high": "17",
        "critical_low": "7",
        "critical_high": "20",
        "normal_text": "",
    }
    label = ok(lab.tech.api.get(f"/api/lab/samples/{sample['id']}/label"))
    assert label["sample"]["accession_no"] == sample["accession_no"]
    assert [t["code"] for t in label["tests"]] == ["CBC"]
    printed = ok(lab.tech.api.post(f"/api/lab/samples/{sample['id']}/label-printed"))
    assert printed["sample"]["label_printed_at"] is not None

    # Drafts are never printed.
    err(lab.doctor.api.get(f"/api/lab/lines/{line.pk}/result/print"), 409, "RESULT_NOT_APPROVED")
    entered = ok(
        lab.tech.api.request(
            "PUT", f"/api/lab/lines/{line.pk}/result", {"values": {"HB": "6.2", "BG": "O"}}
        )
    )
    assert entered["stage"] == "to_approve"
    (draft,) = entered["versions"]
    flags = {v["parameter_code"]: (v["value"], v["flag"]) for v in draft["values"]}
    assert flags == {"HB": ("6.2", "critical_low"), "BG": ("O", "none")}
    err(
        lab.tech.api.request("PUT", f"/api/lab/lines/{line.pk}/result", {"values": {"HB": "x"}}),
        409,
        "RESULT_VALUE_INVALID",
    )
    queue = ok(lab.sup.api.get("/api/lab/approvals"))
    (row,) = [r for r in queue["items"] if r["line_id"] == line.pk]
    assert (row["critical_count"], row["amendment"]) == (1, False)

    err(
        lab.sup.api.post(f"/api/lab/lines/{line.pk}/result/approve", {"revision": "stale"}),
        409,
        "RESULT_CHANGED",
    )
    approved = ok(
        lab.sup.api.post(
            f"/api/lab/lines/{line.pk}/result/approve", {"revision": draft["revision"]}
        )
    )
    assert approved["stage"] == "done"
    assert approved["line"]["fulfilment_status"] == "performed"
    assert approved["versions"][0]["revision"] is None
    printout = ok(lab.doctor.api.get(f"/api/lab/lines/{line.pk}/result/print"))
    assert printout["current"] is True
    assert printout["version"]["approved_by"]["username"] == "labsup"
    done = ok(lab.tech.api.get("/api/lab/worklist?status=done"))
    assert line.pk in {r["line_id"] for r in done["items"]}
    # Doctors never read the bench (drafts stay in the lab).
    err(lab.doctor.api.get(f"/api/lab/lines/{line.pk}/result"), 403, "PERMISSION_DENIED")


def test_amendment_keeps_the_original(lab: Bench, cbc: LabTest) -> None:
    visit = b.visit(adult())
    line = lab_line(visit, cbc)
    _received(lab, line.pk)
    first = ok(
        lab.tech.api.request(
            "PUT", f"/api/lab/lines/{line.pk}/result", {"values": {"HB": "14", "BG": "A"}}
        )
    )
    rev = first["versions"][0]["revision"]
    ok(lab.sup.api.post(f"/api/lab/lines/{line.pk}/result/approve", {"revision": rev}))
    err(
        lab.tech.api.post(f"/api/lab/lines/{line.pk}/result/amend", {"reason": "ENTRY_ERROR"}),
        403,
        "PERMISSION_DENIED",
    )
    amended = ok(
        lab.sup.api.post(
            f"/api/lab/lines/{line.pk}/result/amend",
            {"reason": "ENTRY_ERROR", "note": "HB typed wrong"},
        )
    )
    assert amended["stage"] == "to_approve"
    v1, v2 = amended["versions"]
    assert (v1["status"], v2["status"], v2["amends_version_no"]) == ("approved", "draft", 1)
    queue = ok(lab.sup.api.get("/api/lab/approvals"))
    assert any(r["line_id"] == line.pk and r["amendment"] for r in queue["items"])
    changed = ok(
        lab.sup.api.request("PUT", f"/api/lab/lines/{line.pk}/result", {"values": {"HB": "15"}})
    )
    rev2 = changed["versions"][1]["revision"]
    final = ok(lab.sup.api.post(f"/api/lab/lines/{line.pk}/result/approve", {"revision": rev2}))
    v1, v2 = final["versions"]
    assert (v1["status"], v2["status"]) == ("amended", "approved")
    assert v1["superseded_by"]["username"] == "labsup"
    assert next(v for v in v1["values"] if v["parameter_code"] == "HB")["value"] == "14.0"
    old = ok(lab.sup.api.get(f"/api/lab/lines/{line.pk}/result/print?version_id={v1['id']}"))
    assert old["current"] is False
    # The original stays as it was in the database too (trigger-protected).
    assert ResultVersion.objects.get(pk=v1["id"]).values.get(
        parameter__code="HB"
    ).value_numeric == (Decimal("14.0"))


def test_cannot_perform_a_paid_test_with_a_billing_approver(lab: Bench, cbc: LabTest) -> None:
    line = engine.settled_line(cbc.service, 1, lab.sup.user)
    url = f"/api/lab/lines/{line.pk}/cannot-perform"
    err(lab.sup.api.post(url, {"reason": "EQUIPMENT_DOWN"}), 409, "CANCEL_NEEDS_BILLING_APPROVER")
    err(
        lab.sup.api.post(
            url,
            {"reason": "EQUIPMENT_DOWN", "approver": {"username": "cashsup", "password": "wrong"}},
        ),
        409,
        "APPROVER_INVALID",
    )
    err(lab.sup.api.post(url, {"reason": "NOPE"}), 409, "REASON_UNKNOWN")
    body = ok(
        lab.sup.api.post(
            url,
            {
                "reason": "EQUIPMENT_DOWN",
                "note": "Analyzer down",
                "approver": {"username": "cashsup", "password": TEST_PASSWORD},
            },
        )
    )
    assert body["stage"] == "cancelled"
    assert body["line"]["billing_status"] == "credited"
    assert body["line"]["cancel_reason"]["code"] == "EQUIPMENT_DOWN"
    err(lab.tech.api.post(url, {"reason": "EQUIPMENT_DOWN"}), 403, "PERMISSION_DENIED")


def test_reject_sample_sends_the_test_back(lab: Bench, cbc: LabTest) -> None:
    visit = b.visit(adult())
    line = lab_line(visit, cbc)
    detail = ok(
        lab.tech.api.post("/api/lab/samples", {"line_ids": [line.pk], "receive": False}), 201
    )
    assert detail["stage"] == "to_receive"
    sample_id = detail["sample"]["id"]
    rejected = ok(
        lab.tech.api.post(f"/api/lab/samples/{sample_id}/reject", {"reason": "HEMOLYZED"})
    )
    assert rejected["sample"]["status"] == "rejected"
    assert ok(lab.tech.api.get(f"/api/lab/lines/{line.pk}/result"))["stage"] == "to_collect"
    err(lab.tech.api.post(f"/api/lab/samples/{sample_id}/receive"), 409, "SAMPLE_NOT_COLLECTED")


def test_companion_tests_share_a_sample(lab: Bench, cbc: LabTest) -> None:
    visit = b.visit(adult())
    one = lab_line(visit, cbc)
    two = lab_line(visit, cbc)
    detail = ok(lab.tech.api.get(f"/api/lab/lines/{one.pk}/result"))
    assert [c["line_id"] for c in detail["companions"]] == [two.pk]
    both = ok(lab.tech.api.post("/api/lab/samples", {"line_ids": [one.pk, two.pk]}), 201)
    after = ok(lab.tech.api.get(f"/api/lab/lines/{two.pk}/result"))
    assert after["sample"]["id"] == both["sample"]["id"]
    assert ok(lab.tech.api.get(f"/api/lab/samples/{both['sample']['id']}/label"))["tests"]


# --- catalog and report ----------------------------------------------------------------------


def test_catalog_editing(lab: Bench) -> None:
    service = b.service("lab")
    options = ok(lab.sup.api.get("/api/lab/services-available"))
    assert service.pk in {o["id"] for o in options}
    test = ok(
        lab.sup.api.post(
            "/api/lab/tests",
            {"service_id": service.pk, "code": "LIPID", "sample_type": "serum"},
        ),
        201,
    )
    err(
        lab.sup.api.post(
            "/api/lab/tests", {"service_id": service.pk, "code": "LIPID", "sample_type": "serum"}
        ),
        409,
        "LAB_TEST_EXISTS",
    )
    tid = test["id"]
    test = ok(lab.sup.api.patch(f"/api/lab/tests/{tid}", {"turnaround_minutes": 120}))
    assert test["turnaround_minutes"] == 120
    test = ok(
        lab.sup.api.post(
            f"/api/lab/tests/{tid}/parameters",
            {"code": "chol", "name_ar": "الكوليسترول", "name_en": "Cholesterol", "unit": "mg/dL"},
        ),
        201,
    )
    (param,) = test["parameters"]
    assert param["code"] == "CHOL"
    err(
        lab.sup.api.post(
            f"/api/lab/parameters/{param['id']}/ranges", {"low": "200", "high": "100"}
        ),
        409,
        "INVALID_REFERENCE_RANGE",
    )
    test = ok(
        lab.sup.api.post(
            f"/api/lab/parameters/{param['id']}/ranges",
            {"low": "0", "high": "200", "critical_high": "400", "note": "Adults"},
        ),
        201,
    )
    (rng,) = test["parameters"][0]["ranges"]
    assert (rng["high"], rng["critical_high"], rng["note"]) == ("200", "400", "Adults")
    test = ok(
        lab.sup.api.request(
            "PUT", f"/api/lab/ranges/{rng['id']}", {"sex": "female", "low": "0", "high": "190"}
        )
    )
    rng = test["parameters"][0]["ranges"][0]
    assert (rng["sex"], rng["high"], rng["critical_high"]) == ("female", "190", None)
    test = ok(lab.sup.api.patch(f"/api/lab/parameters/{param['id']}", {"active": False}))
    assert test["parameters"][0]["active"] is False
    test = ok(lab.sup.api.request("DELETE", f"/api/lab/ranges/{rng['id']}"))
    assert test["parameters"][0]["ranges"] == []
    listed = ok(lab.sup.api.get("/api/lab/tests"))
    assert {"code": "LIPID", "parameter_count": 0}.items() <= next(
        t for t in listed if t["id"] == tid
    ).items()
    assert service.pk not in {o["id"] for o in ok(lab.sup.api.get("/api/lab/services-available"))}
    err(lab.tech.api.get("/api/lab/tests"), 403, "PERMISSION_DENIED")
    assert LabParameter.objects.get(pk=param["id"]).active is False


def test_turnaround_report(lab: Bench, cbc: LabTest, make_user: Any) -> None:
    manager = _login(make_user, "mgr", "manager")
    body = ok(manager.api.get("/api/lab/reports/turnaround"))
    assert (body["date_to"] > body["date_from"]) is True
    assert "CBC" in {r["test"]["code"] for r in body["rows"]}
    assert body["total"]["count"] == 0
    err(
        manager.api.get("/api/lab/reports/turnaround?date_from=2026-10-09&date_to=2026-10-01"),
        409,
        "INVALID_DATE_RANGE",
    )
    err(lab.tech.api.get("/api/lab/reports/turnaround"), 403, "PERMISSION_DENIED")
