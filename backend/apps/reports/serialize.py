"""Reports as JSON-ready dicts shaped like ``apps.reports.schemas`` (no rules here)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from django.utils import timezone

from apps.core.models import CenterProfile
from apps.reports import labels
from apps.reports.kit import MAX_ROWS, Cell, Filters, Metric, Option, Report, resolve_filters
from apps.reports.queries import Dashboard
from apps.reports.registry import ReportSpec

__all__ = ["DEFAULT_EXPIRY_DAYS", "dashboard_json", "filters_for", "report_json"]

#: Expiry window of the stock expiry report when none is asked for.
DEFAULT_EXPIRY_DAYS = 90


def cell(value: Cell) -> str | int | dict[str, str] | None:
    if value is None or isinstance(value, bool):
        return None if value is None else int(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return timezone.localtime(value).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, int | str):
        return value
    return {"ar": value.get("ar", ""), "en": value.get("en", "")}


def _metric(m: Metric) -> dict[str, Any]:
    return {
        "key": m.key,
        "kind": m.kind,
        "tone": m.tone,
        "label": labels.name(f"metric.{m.key}"),
        "value": cell(m.value),
    }


def _option(o: Option) -> dict[str, Any]:
    return {"id": o.id, "name": o.name}


def filters_for(
    spec: ReportSpec,
    *,
    date_from: date | None,
    date_to: date | None,
    department_id: int | None,
    user_id: int | None,
    days: int | None,
) -> Filters:
    """The filters a report accepts, with its default period; the rest are dropped.

    Raises:
        DomainError: ``INVALID_DATE_RANGE``, ``REPORT_RANGE_TOO_LONG``.
    """
    has = set(spec.filters)
    if "dates" in has:
        start, end = date_from, date_to
    elif "as_of" in has:
        end = date_to or timezone.localdate()
        start = end
    else:
        start = end = None
    return resolve_filters(
        date_from=start,
        date_to=end,
        department_id=department_id if "department" in has else None,
        user_id=user_id if "user" in has else None,
        days=(days if days is not None else DEFAULT_EXPIRY_DAYS) if "days" in has else None,
        default=spec.default,
    )


def report_json(spec: ReportSpec, report: Report) -> dict[str, Any]:
    center = CenterProfile.load()
    f = report.filters
    return {
        "key": report.key,
        "area": spec.area,
        "title": labels.name(f"report.{report.key}"),
        "center": {
            "ar": center.name_ar or center.name_en,
            "en": center.name_en or center.name_ar,
        },
        "filters_available": list(spec.filters),
        "filters": {
            "date_from": f.date_from,
            "date_to": f.date_to,
            "department_id": f.department_id,
            "user_id": f.user_id,
            "days": f.days,
        },
        "metrics": [_metric(m) for m in report.metrics],
        "sections": [
            {
                "key": s.key,
                "label": labels.name(f"section.{s.key}"),
                "columns": [
                    {"key": c.key, "kind": c.kind, "label": labels.name(f"column.{c.key}")}
                    for c in s.columns
                ],
                "rows": [{k: cell(v) for k, v in row.items()} for row in s.rows],
                "totals": None if s.totals is None else {k: cell(v) for k, v in s.totals.items()},
                "truncated": s.truncated,
            }
            for s in report.sections
        ],
        "departments": [_option(o) for o in report.departments],
        "users": [_option(o) for o in report.users],
        "max_rows": MAX_ROWS,
        "generated_at": report.generated_at,
    }


def dashboard_json(d: Dashboard) -> dict[str, Any]:
    return {
        "date": d.day,
        "metrics": [_metric(m) for m in d.metrics],
        "alerts": [
            {
                "key": a.key,
                "tone": a.tone,
                "count": a.count,
                "amount": None if a.amount is None else str(a.amount),
                "report": a.report,
            }
            for a in d.alerts
        ],
        "trend": [
            {
                "date": t["date"],
                "collected": str(t["collected"]),
                "pending": str(t["pending"]),
                "visits": t["visits"],
            }
            for t in d.trend
        ],
        "departments": [
            {"department": r["department"], "net": str(r["net"])} for r in d.departments
        ],
        "generated_at": d.generated_at,
    }
