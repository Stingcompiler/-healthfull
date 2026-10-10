/**
 * Chart colors: theme tokens only (ARCHITECTURE 5.1), so the charts follow light, dark and
 * warm without a single raw color. SVG attributes accept CSS variables.
 */
export const CHART_COLORS = {
  collected: "var(--success)",
  pending: "var(--warning)",
  revenue: "var(--primary)",
  grid: "var(--border)",
  axis: "var(--fg-muted)",
  cursor: "var(--accent)",
} as const;

/** Axis numbers in short form (12K, 1.5M) in the current locale. */
export function compactNumber(value: number, locale: string): string {
  return new Intl.NumberFormat(locale, { notation: "compact", maximumFractionDigits: 1 }).format(value);
}
