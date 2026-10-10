import { formatNumber } from "@/lib/format";
import type { Language } from "@/lib/preferences";

const UNITS = ["byte", "kilobyte", "megabyte", "gigabyte", "terabyte"] as const;

/** A byte count in the largest unit that keeps it at or above 1 (1,024 steps), localized. */
export function formatBytes(bytes: number, language: Language): string {
  let value = Math.max(0, bytes);
  let unit = 0;
  while (value >= 1024 && unit < UNITS.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return formatNumber(value, language, {
    style: "unit",
    unit: UNITS[unit],
    unitDisplay: "short",
    maximumFractionDigits: unit === 0 ? 0 : 1,
  });
}
