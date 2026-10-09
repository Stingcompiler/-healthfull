import { CENTER_TIME_ZONE } from "@/lib/format";

/** ISO date (YYYY-MM-DD) at the center, `offsetDays` from today. Price versions use center dates. */
export function centerDate(offsetDays = 0, now: Date = new Date()): string {
  const shifted = new Date(now.getTime() + offsetDays * 86_400_000);
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: CENTER_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(shifted);
}

/** A 24-hour clock time as HH:MM (00:00 to 23:59). */
export const CLOCK_TIME = /^([01]\d|2[0-3]):[0-5]\d$/;

/**
 * What was typed into a 24-hour time field, as Latin digits: Arabic-Indic and Persian digits
 * become 0-9, an Arabic decimal or full-width colon becomes ":", and "0830" becomes "08:30".
 * The native time input is avoided: it follows the browser locale (AM/PM), not the app language.
 */
export function normalizeClockTime(text: string): string {
  const latin = text
    .trim()
    .replace(/[٠-٩]/g, (d) => String(d.charCodeAt(0) - 0x0660))
    .replace(/[۰-۹]/g, (d) => String(d.charCodeAt(0) - 0x06f0))
    .replace(/[٫.：]/g, ":");
  return /^\d{4}$/.test(latin) ? `${latin.slice(0, 2)}:${latin.slice(2)}` : latin;
}
