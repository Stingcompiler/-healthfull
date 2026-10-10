"""No query per row: a report's query count does not grow with the data (large ranges)."""

from __future__ import annotations

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.reports import queries
from apps.reports.kit import Filters
from apps.reports.registry import REPORTS
from apps.reports.tests.scenario import build_day

pytestmark = pytest.mark.django_db


def _counts() -> dict[str, int]:
    today = timezone.localdate()
    out = {}
    for key, spec in REPORTS.items():
        days = 90 if "days" in spec.filters else None
        with CaptureQueriesContext(connection) as ctx:
            spec.run(Filters(today, today, days=days))
        out[key] = len(ctx.captured_queries)
    with CaptureQueriesContext(connection) as ctx:
        queries.dashboard()
    out["dashboard"] = len(ctx.captured_queries)
    return out


def test_query_counts_do_not_grow_with_rows() -> None:
    build_day()
    once = _counts()
    build_day()
    build_day()
    thrice = _counts()
    # Payer receivables reuse ``apps.claims.queries``, which reads per payer (each scenario
    # day adds a payer): it grows with the handful of payers, never with invoice lines.
    payers = thrice.pop("payer_receivables") - once.pop("payer_receivables")
    assert payers <= 2 * 4
    assert thrice == once


def test_reports_never_write() -> None:
    """Every report, its workbook and the dashboard only read (no INSERT/UPDATE/DELETE)."""
    from apps.reports import export

    build_day()
    today = timezone.localdate()
    with CaptureQueriesContext(connection) as ctx:
        for spec in REPORTS.values():
            report = spec.run(Filters(today, today, days=90 if "days" in spec.filters else None))
            export.workbook(report, spec.filters, "ar")
        queries.dashboard()
    writes = [
        q["sql"]
        for q in ctx.captured_queries
        if q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
    ]
    assert writes == []
