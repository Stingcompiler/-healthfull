import { describe, expect, it } from "vitest";

import { lineTotal, sumAmounts } from "./money";

describe("sale basket totals", () => {
  it("multiplies exactly in cents", () => {
    expect(lineTotal("300.00", 3)).toBe("900.00");
    expect(lineTotal("0.10", 3)).toBe("0.30");
    expect(lineTotal("1500", 2)).toBe("3000.00");
  });

  it("refuses what is not an amount", () => {
    expect(lineTotal("abc", 2)).toBeNull();
    expect(lineTotal("1.234", 2)).toBeNull();
    expect(lineTotal("10.00", -1)).toBeNull();
  });

  it("sums lines and refuses a missing price", () => {
    expect(sumAmounts(["900.00", "0.30"])).toBe("900.30");
    expect(sumAmounts([])).toBe("0.00");
    expect(sumAmounts(["1.00", null])).toBeNull();
  });
});
