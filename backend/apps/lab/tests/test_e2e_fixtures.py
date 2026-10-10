"""The lab module's e2e builders (``apps/lab/e2e_fixtures.py``)."""

from __future__ import annotations

import json
from io import StringIO
from typing import Any

import pytest
from django.core.management import CommandError, call_command

from apps.lab.models import ResultVersion
from apps.orders.models import ServiceLine

pytestmark = pytest.mark.django_db


def run(name: str, params: dict[str, Any]) -> dict[str, Any]:
    out = StringIO()
    call_command("e2e_fixture", name, params=json.dumps(params), as_json=True, stdout=out)
    payload = json.loads(out.getvalue())
    assert payload["ok"] is True, payload
    result: dict[str, Any] = payload["result"]
    return result


def run_error(name: str, params: dict[str, Any]) -> dict[str, Any]:
    out = StringIO()
    with pytest.raises(CommandError):
        call_command("e2e_fixture", name, params=json.dumps(params), as_json=True, stdout=out)
    payload = json.loads(out.getvalue())
    assert payload["ok"] is False, payload
    error: dict[str, Any] = payload["error"]
    return error


def test_lab_order_and_progress(settings: Any) -> None:
    settings.DEBUG = True
    call_command("seed_e2e", stdout=StringIO())
    order = run("lab_order", {"tests": ["LAB-CBC", "LAB-BFMP"]})
    first, second = order["lab_lines"]
    assert (first["service"], first["billing_status"]) == ("LAB-CBC", "settled")
    done = run("lab_progress", {"line": first["id"], "stage": "amended"})
    assert done["stage"] == "done"
    assert [v["status"] for v in done["versions"]] == ["amended", "approved"]
    assert ServiceLine.objects.get(pk=first["id"]).fulfilment_status == "performed"
    entered = run("lab_progress", {"line": second["id"], "stage": "entered"})
    assert entered["stage"] == "to_approve"
    assert ResultVersion.objects.get(result_set__service_line_id=second["id"]).status == "draft"

    unpaid = run("lab_order", {"pay": False})
    (line,) = unpaid["lab_lines"]
    assert line["billing_status"] == "invoiced"
    error = run_error("lab_progress", {"line": line["id"], "stage": "received"})
    assert error["code"] == "LINE_NOT_ELIGIBLE"

    screens = run("lab_screens", {})
    assert screens["entered"]["stage"] == "to_approve"
    assert screens["amended"]["stage"] == "done"
