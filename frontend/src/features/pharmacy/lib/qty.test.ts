import { describe, expect, it } from "vitest";

import { normalizeDigits, parseCost, parseSigned, parseWhole } from "./qty";

describe("pharmacy quantities", () => {
  it("reads Arabic-Indic digits", () => {
    expect(normalizeDigits("١٢ ٣")).toBe("123");
    expect(parseWhole("٣٠")).toBe(30);
  });

  it("accepts whole numbers from the minimum only", () => {
    expect(parseWhole("0")).toBeNull();
    expect(parseWhole("0", 0)).toBe(0);
    expect(parseWhole("2.5")).toBeNull();
    expect(parseWhole("")).toBeNull();
    expect(parseWhole("-3")).toBeNull();
  });

  it("reads signed changes, never zero", () => {
    expect(parseSigned("-4")).toBe(-4);
    expect(parseSigned("−4")).toBe(-4);
    expect(parseSigned("7")).toBe(7);
    expect(parseSigned("0")).toBeNull();
  });

  it("reads costs with up to four decimals", () => {
    expect(parseCost("2.5")).toBe("2.5");
    expect(parseCost("٢٫٥")).toBe("2.5");
    expect(parseCost("1.23456")).toBeNull();
    expect(parseCost("abc")).toBeNull();
  });
});
