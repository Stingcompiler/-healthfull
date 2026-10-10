import { pickName } from "@/lib/names";

import type { ReportCellValue, ReportColumnKind } from "../types";

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
