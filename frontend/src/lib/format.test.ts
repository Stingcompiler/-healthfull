import { describe, expect, it } from "vitest";

import {
  compareDecimal,
  formatDate,
  formatMoney,
  formatPercent,
  formatRelative,
  isNegativeAmount,
  isZeroAmount,
  toDecimalString,
} from "./format";

/** Strip bidi control marks Intl inserts around Arabic numbers/currency. */
const plain = (s: string) =>
  s
    .replace(/[\u200e\u200f\u061c\u00a0]/g, " ")
    .replace(/\s+/g, " ")
    .trim();

describe("formatMoney", () => {
  it("formats SDG in English with Latin digits and two decimals", () => {
    expect(plain(formatMoney("10000.00", "en"))).toBe("SDG 10,000.00");
    expect(plain(formatMoney("0.5", "en"))).toBe("SDG 0.50");
  });

  it("formats SDG in Arabic with Latin digits by default", () => {
    const text = plain(formatMoney("10000.00", "ar"));
    expect(text).toContain("10,000.00");
    expect(text).toContain("ج.س.");
    expect(text).not.toMatch(/[٠-٩]/);
  });

  it("uses Arabic-Indic digits when the center setting asks for them", () => {
    expect(formatMoney("10000.00", "ar", { digits: "arab" })).toMatch(/١٠٬٠٠٠٫٠٠/);
  });

  it("never rounds through float: large decimal strings stay exact", () => {
    expect(plain(formatMoney("12345678901.23", "en", { currency: false }))).toBe("12,345,678,901.23");
    expect(plain(formatMoney("0.10", "en", { currency: false }))).toBe("0.10");
  });

  it("formats negatives and signed deltas", () => {
    expect(plain(formatMoney("-250.00", "en"))).toBe("-SDG 250.00");
    expect(plain(formatMoney("250.00", "en", { signed: true }))).toBe("+SDG 250.00");
    expect(plain(formatMoney("0.00", "en", { signed: true }))).toBe("SDG 0.00");
  });

  it("can omit the currency", () => {
    expect(plain(formatMoney("1500", "en", { currency: false }))).toBe("1,500.00");
  });

  it("rejects values that are not decimal amounts", () => {
    expect(() => formatMoney("12abc", "en")).toThrow(RangeError);
    expect(() => formatMoney(Number.NaN, "en")).toThrow(RangeError);
  });
});

describe("money helpers", () => {
  it("normalizes inputs", () => {
    expect(toDecimalString(" 10.50 ")).toBe("10.50");
    expect(toDecimalString(0)).toBe("0.00");
    expect(toDecimalString(5n)).toBe("5");
    expect(isNegativeAmount("-1.00")).toBe(true);
    expect(isZeroAmount("0.00")).toBe(true);
    expect(isZeroAmount("-0")).toBe(true);
    expect(isZeroAmount("0.01")).toBe(false);
  });
});

describe("formatDate", () => {
  const iso = "2026-10-06T09:05:00Z"; // 11:05 in Khartoum (UTC+2)

  it("formats in the center time zone", () => {
    expect(plain(formatDate(iso, "en", "datetime"))).toBe("6 Oct 2026, 11:05 am");
    expect(plain(formatDate(iso, "en", "date"))).toBe("6 Oct 2026");
  });

  it("formats Arabic dates with Latin digits", () => {
    const text = plain(formatDate(iso, "ar", "date"));
    expect(text).toContain("2026");
    expect(text).toContain("أكتوبر");
  });

  it("formats relative times", () => {
    const now = new Date("2026-10-06T11:05:00Z");
    expect(formatRelative("2026-10-06T09:05:00Z", "en", now)).toBe("2 hours ago");
    expect(formatRelative("2026-10-05T11:05:00Z", "en", now)).toBe("yesterday");
  });
});

describe("compareDecimal", () => {
  it("orders decimal strings exactly", () => {
    expect(compareDecimal("10.00", "9.99")).toBe(1);
    expect(compareDecimal("9.99", "10")).toBe(-1);
    expect(compareDecimal("10.5", "10.50")).toBe(0);
    expect(compareDecimal("-1.00", "0.00")).toBe(-1);
    expect(compareDecimal("-2.00", "-1.00")).toBe(-1);
    expect(compareDecimal("-0.00", "0")).toBe(0);
    expect(compareDecimal("12345678901234567.01", "12345678901234567.02")).toBe(-1);
  });

  it("sorts a list like a human would", () => {
    const values = ["15000.00", "8500.00", "-250.00", "4750.50", "0.00", "4750.5"];
    expect([...values].sort(compareDecimal)).toEqual(["-250.00", "0.00", "4750.50", "4750.5", "8500.00", "15000.00"]);
  });
});

describe("formatPercent", () => {
  it("drops trailing zeros and places the sign and % by locale", () => {
    expect(formatPercent("10.00", "en")).toBe("10%");
    expect(formatPercent("70.50", "en")).toBe("70.5%");
    expect(formatPercent("10.00", "en", { signed: true })).toBe("+10%");
    expect(formatPercent("-5.25", "en", { signed: true })).toBe("-5.25%");
    expect(formatPercent("0.00", "en", { signed: true })).toBe("0%");
  });

  it("formats Arabic with the locale's percent sign and no trailing zeros", () => {
    const ar = formatPercent("10.00", "ar", { signed: true });
    expect(ar).not.toContain(".00");
    expect(ar).toMatch(/10/);
    expect(ar).toMatch(/[%٪]/);
  });
});
