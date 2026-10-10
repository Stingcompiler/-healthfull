import { pickName } from "@/lib/names";

import type { ReportCellValue, ReportColumnKind, ReportRow } from "../types";

/** A sortable plain value of a cell (numbers for amounts and counts, text for names). */
export function sortValue(
  value: ReportCellValue | undefined,
  kind: ReportColumnKind,
  language: "ar" | "en",
): string | number {
  if (value === null || value === undefined)
    return kind === "text" || kind === "name" || kind === "code" ? "" : -Infinity;
  if (typeof value === "object") return pickName(value, language);
  if (kind === "money" || kind === "int" || kind === "days" || kind === "minutes" || kind === "percent") {
    return Number(value);
  }
  return String(value);
}

/** Columns aligned to the end (numbers). */
export function isNumeric(kind: ReportColumnKind): boolean {
  return kind === "money" || kind === "int" || kind === "days" || kind === "minutes" || kind === "percent";
}

/** Whether any text of a row (codes, names in both languages, notes) contains `query`. */
export function matchesRow(row: ReportRow, query: string): boolean {
  const needle = query.trim().toLocaleLowerCase();
  if (!needle) return true;
  return Object.values(row).some((value) => {
    if (value === null) return false;
    if (typeof value === "object") return `${value.ar} ${value.en}`.toLocaleLowerCase().includes(needle);
    return String(value).toLocaleLowerCase().includes(needle);
  });
}
