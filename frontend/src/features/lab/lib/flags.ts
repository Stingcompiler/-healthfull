/**
 * Live flag preview on the result entry form (FEATURES 9.3). The stored flag is always decided
 * by the server when the values are saved (`domain.lab.flag`); this mirrors it only so the
 * technician sees a critical value while typing. Limits come from the server, which chose the
 * reference range for the patient's sex and age.
 */
import type { AppliedRange, Flag, ValueType } from "../types";

const ARABIC_INDIC = /[٠-٩۰-۹]/g;

/** Western digits and a dot for a number typed on an Arabic keyboard ("١٣٫٥" -> "13.5"). */
export function normalizeNumber(raw: string): string {
  return raw
    .trim()
    .replace(ARABIC_INDIC, (d) => String((d.codePointAt(0) ?? 0) & 0xf))
    .replace(/[٫,]/g, ".")
    .replace(/−/g, "-");
}

const NUMBER = /^-?(\d+(\.\d*)?|\.\d+)$/;

/** Whether `raw` is a number the server accepts. */
export function isNumber(raw: string): boolean {
  return NUMBER.test(normalizeNumber(raw));
}

function limit(value: string | null | undefined): number | null {
  return value === null || value === undefined || value === "" ? null : Number(value);
}

/**
 * The flag the server will store for `raw`, or null while the field is empty or not a number.
 * Critical limits are inclusive (`<=`, `>=`); the normal range is inclusive.
 */
export function previewFlag(raw: string, valueType: ValueType, range: AppliedRange | null): Flag | null {
  const text = raw.trim();
  if (!text) return null;
  if (valueType === "numeric") {
    if (!isNumber(text)) return null;
    if (!range) return "none";
    const value = Number(normalizeNumber(text));
    const criticalLow = limit(range.critical_low);
    const criticalHigh = limit(range.critical_high);
    const low = limit(range.low);
    const high = limit(range.high);
    if (criticalLow !== null && value <= criticalLow) return "critical_low";
    if (criticalHigh !== null && value >= criticalHigh) return "critical_high";
    if (low !== null && value < low) return "low";
    if (high !== null && value > high) return "high";
    return "normal";
  }
  const normal = range?.normal_text ?? "";
  if (!normal) return "none";
  return text.toLowerCase() === normal.toLowerCase() ? "normal" : "abnormal";
}

export function isCritical(flag: Flag | null | undefined): boolean {
  return flag === "critical_low" || flag === "critical_high";
}

/** Out of the normal range (critical included); "none" and "normal" are not flagged. */
export function isFlagged(flag: Flag | null | undefined): boolean {
  return flag !== null && flag !== undefined && flag !== "normal" && flag !== "none";
}

/** The reference range as one line: "13 - 17", "< 5", "> 150", or the normal text. */
export function rangeText(low: string | null, high: string | null, text = ""): string {
  if (low !== null && high !== null) return `${low} - ${high}`;
  if (high !== null) return `≤ ${high}`;
  if (low !== null) return `≥ ${low}`;
  return text;
}
