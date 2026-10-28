import { describe, expect, it } from "vitest";

import { formatClock, groupClinicDays, nextOpening, sortWeekdays, weekdayName } from "./weekdays";

describe("weekdays", () => {
  it("names weekdays from Monday = 0", () => {
    expect(weekdayName(0, "en")).toBe("Monday");
    expect(weekdayName(5, "en", "short")).toBe("Sat");
    expect(weekdayName(4, "ar")).toBe("الجمعة");
  });

  it("orders a Sudanese week from Saturday", () => {
    expect(sortWeekdays([0, 4, 5, 5, 6])).toEqual([5, 6, 0, 4]);
  });

  it("formats a wall-clock time", () => {
    expect(formatClock("08:00", "en")).toMatch(/^8:00\sAM$/iu);
    expect(formatClock("20:30", "en")).toMatch(/^8:30\sPM$/iu);
  });

  it("groups days that share the same hours", () => {
    const groups = groupClinicDays([
      { weekday: 2, starts: "08:00", ends: "14:00" },
      { weekday: 0, starts: "08:00", ends: "14:00" },
      { weekday: 1, starts: "16:00", ends: "20:00" },
      { weekday: 5, starts: "08:00", ends: "14:00" },
      { weekday: 3, starts: "16:00", ends: "18:00" },
      { weekday: 3, starts: "08:00", ends: "12:00" },
    ]);
    expect(groups).toEqual([
      { weekdays: [5, 0, 2], spans: [{ starts: "08:00", ends: "14:00" }] },
      { weekdays: [1], spans: [{ starts: "16:00", ends: "20:00" }] },
      {
        weekdays: [3],
        spans: [
          { starts: "08:00", ends: "12:00" },
          { starts: "16:00", ends: "18:00" },
        ],
      },
    ]);
  });

  it("finds the next day the center opens, skipping days off", () => {
    const hours = [
      { weekday: 5, closed: false, opens: "08:00", closes: "14:00" },
      { weekday: 6, closed: true, opens: null, closes: null },
      { weekday: 0, closed: false, opens: "09:00", closes: "13:00" },
    ];
    // Saturday (5) -> Sunday is off -> Monday (0), two days ahead.
    expect(nextOpening(hours, 5)).toEqual({ weekday: 0, opens: "09:00", daysAhead: 2 });
    // Monday (0) -> next is Saturday, five days ahead.
    expect(nextOpening(hours, 0)).toEqual({ weekday: 5, opens: "08:00", daysAhead: 5 });
    expect(nextOpening([], 3)).toBeNull();
  });
});
