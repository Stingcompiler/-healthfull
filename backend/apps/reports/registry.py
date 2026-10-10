"""The report catalog: key, area, permission, filters and default period of each report.

``apps.reports.api`` builds one read endpoint and one Excel endpoint per entry, each behind
the entry's single permission. The frontend catalog (``src/features/reports/catalog.ts``)
lists the same keys and codes; a frontend test reads this file and fails on any drift.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from apps.reports import queries
from apps.reports.kit import DefaultRange, FilterName, Filters, Report

Area = Literal["finance", "exceptions", "payers", "stock", "visits", "lab"]


@dataclass(frozen=True, slots=True)
class ReportSpec:
    key: str
    area: Area
    permission: str
    filters: tuple[FilterName, ...]
    default: DefaultRange
    run: Callable[[Filters], Report]


REPORTS: dict[str, ReportSpec] = {
    spec.key: spec
    for spec in (
        ReportSpec(
            "revenue",
            "finance",
            "reports.view_finance",
            ("dates", "department"),
            "today",
            queries.revenue,
        ),
        ReportSpec(
            "shift_variances",
            "finance",
            "reports.view_finance",
            ("dates", "user"),
            "month",
            queries.shift_variances,
        ),
        ReportSpec(
            "pending_transfers",
            "finance",
            "reports.view_finance",
            ("user",),
            "none",
            queries.pending_transfers,
        ),
        ReportSpec(
            "adjustments",
            "finance",
            "reports.view_finance",
            ("dates", "department", "user"),
            "month",
            queries.adjustments,
        ),
        ReportSpec(
            "payer_receivables",
            "payers",
            "reports.view_finance",
            ("as_of",),
            "none",
            queries.payer_receivables,
        ),
        ReportSpec(
            "requested_not_invoiced",
            "exceptions",
            "reports.view_exceptions",
            ("department",),
            "none",
            queries.requested_not_invoiced,
        ),
        ReportSpec(
            "paid_not_performed",
            "exceptions",
            "reports.view_exceptions",
            ("department",),
            "none",
            queries.paid_not_performed,
        ),
        ReportSpec(
            "performed_by_authorization",
            "exceptions",
            "reports.view_exceptions",
            ("dates", "department"),
            "month",
            queries.performed_by_authorization,
        ),
        ReportSpec(
            "stock_valuation",
            "stock",
            "reports.view_stock",
            (),
            "none",
            queries.stock_valuation,
        ),
        ReportSpec(
            "stock_movement",
            "stock",
            "reports.view_stock",
            ("dates",),
            "month",
            queries.stock_movement,
        ),
        ReportSpec(
            "stock_variance",
            "stock",
            "reports.view_stock",
            ("dates",),
            "month",
            queries.stock_variance,
        ),
        ReportSpec(
            "stock_expiry",
            "stock",
            "reports.view_stock",
            ("days",),
            "none",
            queries.stock_expiry,
        ),
        ReportSpec(
            "visits",
            "visits",
            "reports.view_visits",
            ("dates", "department", "user"),
            "week",
            queries.visits,
        ),
        ReportSpec(
            "lab_turnaround",
            "lab",
            "reports.view_lab",
            ("dates",),
            "week",
            queries.lab_turnaround,
        ),
    )
}
