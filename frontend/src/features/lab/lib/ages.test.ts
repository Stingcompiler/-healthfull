import { describe, expect, it } from "vitest";

import { splitDays, toDays } from "./ages";

describe("age bands", () => {
  it("shows whole years as years and anything else as days", () => {
    expect(splitDays(null)).toEqual({ value: "", unit: "years" });
    expect(splitDays(0)).toEqual({ value: "0", unit: "days" });
    expect(splitDays(365 * 18)).toEqual({ value: "18", unit: "years" });
    expect(splitDays(28)).toEqual({ value: "28", unit: "days" });
  });

  it("converts back to days", () => {
    expect(toDays("", "years")).toBeNull();
    expect(toDays("18", "years")).toBe(6570);
    expect(toDays("0.5", "years")).toBe(183);
    expect(toDays("28", "days")).toBe(28);
  });
});
