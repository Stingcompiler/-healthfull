/** Age bands of reference ranges are stored in days; the editor speaks days or years. */
export type AgeUnit = "days" | "years";

export const DAYS_PER_YEAR = 365;

/** An age in days as the editor shows it: whole years when it is a multiple of a year. */
export function splitDays(days: number | null): { value: string; unit: AgeUnit } {
  if (days === null) return { value: "", unit: "years" };
  if (days > 0 && days % DAYS_PER_YEAR === 0) return { value: String(days / DAYS_PER_YEAR), unit: "years" };
  return { value: String(days), unit: "days" };
}

/** Days from an editor value; null for an empty field. */
export function toDays(value: string, unit: AgeUnit): number | null {
  const text = value.trim();
  if (text === "") return null;
  const n = Number(text);
  return unit === "years" ? Math.round(n * DAYS_PER_YEAR) : Math.round(n);
}
