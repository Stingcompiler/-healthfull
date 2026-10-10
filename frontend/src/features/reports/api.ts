/**
 * TanStack Query hooks of the reports module (ARCHITECTURE 5.5). Reports are read-only: every
 * figure is the server's; these hooks only fetch what the screens show.
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";

import type { ReportKey } from "./catalog";
import { reportQuery, reportQueryString, type ReportSearch } from "./lib/search";

export const reportsKeys = {
  all: ["reports"] as const,
  report: (key: string, search: ReportSearch) => ["reports", key, search] as const,
};

/**
 * Every report has the same parameters and the same answer (ReportOut), so one typed path
 * stands for all of them.
 */
type ReportPath = "/api/reports/revenue";

function reportPath(key: ReportKey): ReportPath {
  return `/api/reports/${key}` as ReportPath;
}

export function useReport(key: ReportKey, search: ReportSearch) {
  return useQuery({
    queryKey: reportsKeys.report(key, search),
    queryFn: () => unwrap(api.GET(reportPath(key), { params: { query: reportQuery(search) } })),
    placeholderData: keepPreviousData,
  });
}

/** The Excel download address (a plain link: the session cookie goes with it). */
export function exportUrl(key: ReportKey, search: ReportSearch, language: "ar" | "en"): string {
  return `/api/reports/${key}/export?${reportQueryString(search, { language })}`;
}
