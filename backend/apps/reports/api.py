"""``/api/reports``: the manager dashboard and every report, as JSON and as Excel.

Routers stay thin (ARCHITECTURE 4.2): authentication, one ``require_perm``, query
parameters in, one call into ``apps.reports`` out. For each report of
``apps.reports.registry.REPORTS`` there are two operations behind that report's single
``reports.view_*`` code: ``GET /api/reports/<key>`` (``reports_get_<key>``) and
``GET /api/reports/<key>/export`` (``reports_export_<key>``, an ``.xlsx`` attachment).
Reports never write. The printable view is the SPA's ``/reports/<key>/print`` page over
the JSON (server PDF is not built: WeasyPrint needs system libraries, ADR 0013).
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from django.http import HttpRequest, HttpResponse
from ninja import Field, Query, Router, Schema

from api.permissions import require_perm
from api.ping import add_ping
from api.schemas import ERROR_RESPONSES
from apps.reports import export, labels, queries, serialize
from apps.reports.registry import REPORTS, ReportSpec
from apps.reports.schemas import ReportDashboardOut, ReportOut

reports_router = Router(tags=["reports"])
add_ping(reports_router, "reports")

_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class ReportParams(Schema):
    date_from: date | None = Field(None, description="First day (local); default per report.")
    date_to: date | None = Field(None, description="Last day, or the 'as of' day; default today.")
    department_id: int | None = Field(None, ge=1)
    user_id: int | None = Field(None, ge=1)
    days: int | None = Field(None, ge=0, le=3650, description="Expiry window in days.")


class ReportExportParams(ReportParams):
    language: Literal["ar", "en"] = "ar"


def _run(spec: ReportSpec, params: ReportParams) -> Any:
    filters = serialize.filters_for(
        spec,
        date_from=params.date_from,
        date_to=params.date_to,
        department_id=params.department_id,
        user_id=params.user_id,
        days=params.days,
    )
    return spec.run(filters)


@reports_router.get(
    "/dashboard",
    response={200: ReportDashboardOut, **ERROR_RESPONSES},
    operation_id="reports_get_dashboard",
    summary="Today at a glance for the manager: collection, pending transfers, queue, alerts",
)
@require_perm("reports.view_dashboard")
def get_dashboard(request: HttpRequest) -> Any:
    return serialize.dashboard_json(queries.dashboard())


def _add(spec: ReportSpec) -> None:
    title = labels.text(f"report.{spec.key}", "en")

    def read(request: HttpRequest, params: Query[ReportParams]) -> Any:
        return serialize.report_json(spec, _run(spec, params))

    def download(request: HttpRequest, params: Query[ReportExportParams]) -> HttpResponse:
        name, content = export.workbook(_run(spec, params), spec.filters, params.language)
        response = HttpResponse(content, content_type=_XLSX)
        response["Content-Disposition"] = f'attachment; filename="{name}"'
        return response

    read.__name__ = f"get_{spec.key}"
    download.__name__ = f"export_{spec.key}"
    reports_router.get(
        f"/{spec.key}",
        response={200: ReportOut, **ERROR_RESPONSES},
        operation_id=f"reports_get_{spec.key}",
        summary=title,
    )(require_perm(spec.permission)(read))
    reports_router.get(
        f"/{spec.key}/export",
        response={200: None, **ERROR_RESPONSES},
        operation_id=f"reports_export_{spec.key}",
        summary=f"{title} as an Excel workbook (.xlsx attachment)",
    )(require_perm(spec.permission)(download))


for _spec in REPORTS.values():
    _add(_spec)
