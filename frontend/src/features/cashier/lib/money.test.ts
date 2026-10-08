import { describe, expect, it } from "vitest";

import {
  compareAmounts,
  isAmount,
  isPositiveAmount,
  negate,
  normalizeAmountInput,
  subtractAmounts,
  sumAmounts,
  toCents,
} from "./money";

describe("cashier display money", () => {
  it("normalizes Arabic-Indic digits and separators", () => {
    expect(normalizeAmountInput("١٠٬٠٠٠٫٥")).toBe("10000.5");
    expect(normalizeAmountInput(" 2,500.50 ")).toBe("2500.50");
  });

  it("accepts at most two decimals", () => {
    expect(isAmount("15000")).toBe(true);
    expect(isAmount("15000.505")).toBe(false);
    expect(isAmount("abc")).toBe(false);
    expect(toCents("0.1")).toBe(10n);
  });

  it("computes change due exactly, without floats", () => {
    expect(subtractAmounts("10000", "7500.00")).toBe("2500.00");
    expect(subtractAmounts("0.30", "0.10")).toBe("0.20");
    expect(subtractAmounts("900", "1000.00")).toBe("-100.00");
    expect(subtractAmounts("x", "1")).toBeNull();
  });

  it("sums, compares and negates", () => {
    expect(sumAmounts(["0.10", "0.20", "1"])).toBe("1.30");
    expect(compareAmounts("2500.00", "2500")).toBe(0);
    expect(compareAmounts("-1", "0")).toBe(-1);
    expect(negate("0.00")).toBe("0.00");
    expect(negate("15.5")).toBe("-15.50");
    expect(isPositiveAmount("0")).toBe(false);
    expect(isPositiveAmount("0.01")).toBe(true);
  });
});
