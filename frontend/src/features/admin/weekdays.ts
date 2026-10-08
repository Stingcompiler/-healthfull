/** Weekday numbers (0 = Monday ... 6 = Sunday) in the order a Sudanese week runs. */
export const WEEK_ORDER: readonly number[] = [5, 6, 0, 1, 2, 3, 4];

/** Distinct weekdays in week order (Saturday first), as the schedule editor lists them. */
export function sortWeekdays(days: readonly number[]): number[] {
  return [...new Set(days)].sort((a, b) => WEEK_ORDER.indexOf(a) - WEEK_ORDER.indexOf(b));
}
