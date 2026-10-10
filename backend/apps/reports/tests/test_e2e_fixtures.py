"""The reports module's e2e builder (``apps/reports/e2e_fixtures.py``): its figures are what
the reports show for its doctor, visit and day."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from io import StringIO
from typing import Any

import pytest
from django.core.management import call_command

from apps.reports import queries
from apps.reports.kit import resolve_filters

pytestmark = pytest.mark.django_db

D = Decimal


def run(name: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    out = StringIO()
    call_command("e2e_fixture", name, params=json.dumps(params or {}), as_json=True, stdout=out)
    payload = json.loads(out.getvalue())
    assert payload["ok"] is True, payload
    result: dict[str, Any] = payload["result"]
    return result


def test_reports_day_matches_the_reports(settings: Any) -> None:
    settings.DEBUG = True
    call_command("seed_e2e", stdout=StringIO())
    made = run("reports_day")
    again = run("reports_day")
    assert again["doctor"]["username"] != made["doctor"]["username"]

    day = date.fromisoformat(made["day"])
    filters = resolve_filters(date_from=day, date_to=day)
    revenue = queries.revenue(filters)
    rows = {r["doctor"]["en"]: r for r in revenue.section("by_doctor").rows}  # type: ignore[index]
    mine = rows[made["doctor"]["name_en"]]
    expected = made["expected"]
    assert mine["gross"] == D(expected["gross"])
    assert mine["discount"] == D(expected["discount"])
    assert mine["net"] == D(expected["net"])

    paid = {
        r["service"]["en"]: r["amount"]  # type: ignore[index]
        for r in queries.paid_not_performed(filters).section("lines").rows
        if r["visit"] == made["visit"]["number"]
    }
    assert sorted(str(v) for v in paid.values()) == sorted(expected["paid_not_performed"].values())
    requested = [
        r
        for r in queries.requested_not_invoiced(filters).section("lines").rows
        if r["visit"] == made["visit"]["number"]
    ]
    assert len(requested) == 1
    pending = {
        r["payment"]: r["amount"]
        for r in queries.pending_transfers(filters).section("transfers").rows
    }
    assert pending[made["transfer"]["number"]] == D(expected["pending"])
