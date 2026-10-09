import { describe, expect, it } from "vitest";

import { centerDate, CLOCK_TIME, normalizeClockTime } from "./dates";

describe("centerDate", () => {
  it("uses the center's calendar day, not the browser's", () => {
    // 23:30 UTC is already the next day in Khartoum (UTC+2).
    const now = new Date("2026-10-08T23:30:00Z");
    expect(centerDate(0, now)).toBe("2026-10-09");
    expect(centerDate(1, now)).toBe("2026-10-10");
  });

  it("crosses month ends", () => {
    expect(centerDate(1, new Date("2026-10-31T10:00:00Z"))).toBe("2026-11-01");
  });
});

describe("normalizeClockTime", () => {
  it("turns Arabic-Indic and Persian digits into Latin ones", () => {
    expect(normalizeClockTime("٠٨:٣٠")).toBe("08:30");
    expect(normalizeClockTime("۱۴:۰۰")).toBe("14:00");
  });

  it("accepts other separators and a bare HHMM", () => {
    expect(normalizeClockTime("08٫30")).toBe("08:30");
    expect(normalizeClockTime(" 1405 ")).toBe("14:05");
  });

  it("leaves what it cannot read for the validator to refuse", () => {
    expect(normalizeClockTime("8:30")).toBe("8:30");
    expect(CLOCK_TIME.test("8:30")).toBe(false);
    expect(CLOCK_TIME.test("24:00")).toBe(false);
    expect(CLOCK_TIME.test("23:59")).toBe(true);
  });
});
