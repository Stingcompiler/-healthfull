"""Schemas of ``/api/reports`` (names start with ``Report``: unique across apps).

Every report has the same shape (``ReportOut``): metrics on top, then sections of typed rows.
A cell is a string (money as ``"10000.00"``, percent as ``"87.5"``, dates and times in ISO
8601, text and codes), an integer (counts, days, minutes), a bilingual name, or null; the
column ``kind`` says which.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from ninja import Field, Schema

ReportColumnKind = Literal[
    "text", "code", "name", "money", "int", "days", "minutes", "percent", "date", "datetime"
]
ReportTone = Literal["neutral", "primary", "success", "warning", "danger", "info"]
ReportFilterName = Literal["dates", "as_of", "department", "user", "days"]
ReportArea = Literal["finance", "exceptions", "payers", "stock", "visits", "lab"]


class ReportNameOut(Schema):
    ar: str
    en: str


ReportCell = str | int | ReportNameOut | None


class ReportColumnOut(Schema):
    key: str
    kind: ReportColumnKind
    label: ReportNameOut


class ReportSectionOut(Schema):
    key: str
    label: ReportNameOut
    columns: list[ReportColumnOut]
    rows: list[dict[str, ReportCell]]
    totals: dict[str, ReportCell] | None
    truncated: bool = Field(..., description="More rows exist than the section returns.")


class ReportMetricOut(Schema):
    key: str
    kind: ReportColumnKind
    tone: ReportTone
    label: ReportNameOut
    value: ReportCell


class ReportOptionOut(Schema):
    id: int
    name: ReportNameOut


class ReportFiltersOut(Schema):
    date_from: date
    date_to: date
    department_id: int | None
    user_id: int | None
    days: int | None


class ReportOut(Schema):
    key: str
    area: ReportArea
    title: ReportNameOut
    center: ReportNameOut
    filters_available: list[ReportFilterName]
    filters: ReportFiltersOut
    metrics: list[ReportMetricOut]
    sections: list[ReportSectionOut]
    departments: list[ReportOptionOut]
    users: list[ReportOptionOut]
    max_rows: int
    generated_at: datetime


class ReportAlertOut(Schema):
    key: str
    tone: ReportTone
    count: int
    amount: str | None
    report: str | None = Field(..., description="Report key with the detail, if any.")


class ReportTrendDayOut(Schema):
    date: date
    collected: str
    pending: str
    visits: int


class ReportDepartmentRevenueOut(Schema):
    department: ReportNameOut
    net: str


class ReportDashboardOut(Schema):
    date: date
    metrics: list[ReportMetricOut]
    alerts: list[ReportAlertOut]
    trend: list[ReportTrendDayOut]
    departments: list[ReportDepartmentRevenueOut]
    generated_at: datetime
