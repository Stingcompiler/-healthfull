import { describe, expect, it } from "vitest";

import { formatClock, groupClinicDays, sortWeekdays, weekdayName } from "./weekdays";

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
});
