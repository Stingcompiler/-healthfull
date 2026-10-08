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
