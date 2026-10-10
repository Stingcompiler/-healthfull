/** Named aliases of the reports API schemas (generated from openapi.json, never hand-written). */
import type { components } from "@/lib/api/schema";

type S = components["schemas"];

export type ReportName = S["ReportNameOut"];
export type ReportColumn = S["ReportColumnOut"];
export type ReportColumnKind = ReportColumn["kind"];
export type ReportSection = S["ReportSectionOut"];
export type ReportMetric = S["ReportMetricOut"];
export type ReportOption = S["ReportOptionOut"];
export type ReportFilters = S["ReportFiltersOut"];
export type Report = S["ReportOut"];
export type ReportArea = Report["area"];
export type ReportFilterName = Report["filters_available"][number];
export type ReportRow = ReportSection["rows"][number];
export type ReportCellValue = ReportRow[string];
export type ReportTone = ReportMetric["tone"];
export type ReportDashboard = S["ReportDashboardOut"];
export type ReportAlert = S["ReportAlertOut"];
export type ReportTrendDay = S["ReportTrendDayOut"];
