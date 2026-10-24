/**
 * Chart colors: theme tokens only (ARCHITECTURE 5.1), so the charts follow light, dark and
 * warm without a single raw color. SVG attributes accept CSS variables.
 *
 * Series use the categorical --chart-1..5 tokens in order (Design Reference 2.2 section 16.4):
 * never success/warning/danger, which are reserved for status, and never amber, so a series is
 * not read as a warning. The first series is the brand color; a series keeps its token on every
 * page. Color is not the only signal: the pending series is hatched (PENDING_PATTERN_ID).
 */
export const CHART_COLORS = {
  collected: "var(--chart-1)",
  pending: "var(--chart-2)",
  revenue: "var(--chart-1)",
  grid: "var(--border)",
  axis: "var(--fg-muted)",
  cursor: "var(--accent)",
} as const;

/** SVG pattern id of the hatched fill for a "waiting" series. */
export const PENDING_PATTERN_ID = "chart-pending-hatch";

/** Axis numbers in short form (12K, 1.5M) in the current locale. */
export function compactNumber(value: number, locale: string): string {
  return new Intl.NumberFormat(locale, { notation: "compact", maximumFractionDigits: 1 }).format(value);
}
