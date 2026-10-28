import { localeFor } from "@/lib/format";
import type { Language } from "@/lib/preferences";

/** Weekday numbers (0 = Monday ... 6 = Sunday) in the order a Sudanese week runs. */
export const WEEK_ORDER: readonly number[] = [5, 6, 0, 1, 2, 3, 4];

/** Distinct weekdays in week order (Saturday first), as the schedule editor lists them. */
export function sortWeekdays(days: readonly number[]): number[] {
  return [...new Set(days)].sort((a, b) => WEEK_ORDER.indexOf(a) - WEEK_ORDER.indexOf(b));
}

/** The weekday's name in the UI language ("السبت", "Saturday"; short: "Sat"). */
export function weekdayName(weekday: number, language: Language, width: "long" | "short" = "long"): string {
  // 2026-10-19 is a Monday (weekday 0).
  const day = new Date(Date.UTC(2026, 9, 19 + weekday));
  return new Intl.DateTimeFormat(localeFor(language), { weekday: width, timeZone: "UTC" }).format(day);
}

/** A wall-clock time from the API ("08:00") in the UI language ("8:00 ص", "8:00 AM"). */
export function formatClock(hhmm: string, language: Language): string {
  const [h = 0, m = 0] = hhmm.split(":").map(Number);
  return new Intl.DateTimeFormat(localeFor(language), {
    hour: "numeric",
    minute: "2-digit",
    timeZone: "UTC",
  }).format(new Date(Date.UTC(2026, 0, 1, h, m)));
}

export interface DaySpan {
  weekday: number;
  starts: string;
  ends: string;
}

export interface SpanGroup {
  weekdays: number[];
  spans: { starts: string; ends: string }[];
}

/**
 * A doctor's clinic sessions grouped by days that share the same hours, in week order:
 * Sat/Mon/Wed 08:00-14:00 and Tue 16:00-20:00 become two groups.
 */
export function groupClinicDays(days: readonly DaySpan[]): SpanGroup[] {
  const byDay = new Map<number, { starts: string; ends: string }[]>();
  for (const d of days) {
    const spans = byDay.get(d.weekday) ?? [];
    spans.push({ starts: d.starts, ends: d.ends });
    byDay.set(d.weekday, spans);
  }
  const groups = new Map<string, SpanGroup>();
  for (const weekday of sortWeekdays([...byDay.keys()])) {
    const spans = [...(byDay.get(weekday) ?? [])].sort((a, b) => a.starts.localeCompare(b.starts));
    const key = spans.map((s) => `${s.starts}-${s.ends}`).join(",");
    const group = groups.get(key);
    if (group) group.weekdays.push(weekday);
    else groups.set(key, { weekdays: [weekday], spans });
  }
  return [...groups.values()];
}

export interface HoursDay {
  weekday: number;
  closed: boolean;
  opens?: string | null;
  closes?: string | null;
}

export interface NextOpening {
  weekday: number;
  opens: string;
  /** 1 = tomorrow ... 7 = the same weekday next week. */
  daysAhead: number;
}

/**
 * The next day after `from` (a weekday number, 0 = Monday) on which the center opens, with its
 * opening time; null when no later day has hours. Days off or without times are skipped.
 */
export function nextOpening(hours: readonly HoursDay[], from: number): NextOpening | null {
  const byDay = new Map(hours.map((h) => [h.weekday, h]));
  for (let ahead = 1; ahead <= 7; ahead += 1) {
    const weekday = (from + ahead) % 7;
    const day = byDay.get(weekday);
    if (day && !day.closed && day.opens && day.closes) return { weekday, opens: day.opens, daysAhead: ahead };
  }
  return null;
}
