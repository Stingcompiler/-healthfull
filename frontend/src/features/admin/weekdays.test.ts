import { describe, expect, it } from "vitest";

import { sortWeekdays } from "./weekdays";

describe("sortWeekdays", () => {
  it("lists each day once, Saturday first", () => {
    // Monday..Sunday as stored (0 = Monday), with a repeated day.
    expect(sortWeekdays([0, 1, 2, 3, 4, 5, 6, 0])).toEqual([5, 6, 0, 1, 2, 3, 4]);
    expect(sortWeekdays([3, 5])).toEqual([5, 3]);
    expect(sortWeekdays([])).toEqual([]);
  });
});
