/**
 * Report filters live in the address (shareable, and the print view reads the same ones):
 * `?from=2026-10-01&to=2026-10-10&department=3&user=7&days=30`. Unknown or malformed values
 * are dropped; the server applies each report's defaults and its own checks.
 */
export interface ReportSearch {
  from?: string;
  to?: string;
  department?: number;
  user?: number;
  days?: number;
}

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

function isoDate(value: unknown): string | undefined {
  return typeof value === "string" && ISO_DATE.test(value) && !Number.isNaN(Date.parse(value)) ? value : undefined;
}

function positiveInt(value: unknown, max = Number.MAX_SAFE_INTEGER): number | undefined {
  const n = typeof value === "number" ? value : typeof value === "string" ? Number(value) : NaN;
  return Number.isInteger(n) && n >= 0 && n <= max ? n : undefined;
}

export function parseReportSearch(search: Record<string, unknown>): ReportSearch {
  const from = isoDate(search.from);
  const to = isoDate(search.to);
  const department = positiveInt(search.department);
  const user = positiveInt(search.user);
  const days = positiveInt(search.days, 3650);
  return {
    ...(from ? { from } : {}),
    ...(to ? { to } : {}),
    ...(department ? { department } : {}),
    ...(user ? { user } : {}),
    ...(days !== undefined ? { days } : {}),
  };
}

/** The API query of a report request. */
export function reportQuery(search: ReportSearch): {
  date_from?: string;
  date_to?: string;
  department_id?: number;
  user_id?: number;
  days?: number;
} {
  return {
    ...(search.from ? { date_from: search.from } : {}),
    ...(search.to ? { date_to: search.to } : {}),
    ...(search.department ? { department_id: search.department } : {}),
    ...(search.user ? { user_id: search.user } : {}),
    ...(search.days !== undefined ? { days: search.days } : {}),
  };
}

/** The same query as a URL query string (for the Excel download link). */
export function reportQueryString(search: ReportSearch, extra: Record<string, string> = {}): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(reportQuery(search))) params.set(key, String(value));
  for (const [key, value] of Object.entries(extra)) params.set(key, value);
  return params.toString();
}
