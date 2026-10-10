import { describe, expect, it } from "vitest";

import type { AppliedRange } from "../types";
import { isCritical, isFlagged, isNumber, normalizeNumber, previewFlag, rangeText } from "./flags";

const HB: AppliedRange = { low: "13", high: "17", critical_low: "7", critical_high: "20", normal_text: "" };
const NEG: AppliedRange = { low: null, high: null, critical_low: null, critical_high: null, normal_text: "negative" };

describe("previewFlag", () => {
  it("mirrors the server's numeric flags, critical limits inclusive", () => {
    expect(previewFlag("7", "numeric", HB)).toBe("critical_low");
    expect(previewFlag("7.1", "numeric", HB)).toBe("low");
    expect(previewFlag("13", "numeric", HB)).toBe("normal");
    expect(previewFlag("17", "numeric", HB)).toBe("normal");
    expect(previewFlag("17.5", "numeric", HB)).toBe("high");
    expect(previewFlag("20", "numeric", HB)).toBe("critical_high");
  });

  it("has nothing to say about empty or malformed input, and no range means none", () => {
    expect(previewFlag("", "numeric", HB)).toBeNull();
    expect(previewFlag("abc", "numeric", HB)).toBeNull();
    expect(previewFlag("12", "numeric", null)).toBe("none");
  });

  it("reads numbers typed with Arabic-Indic digits", () => {
    expect(normalizeNumber("١٣٫٥")).toBe("13.5");
    expect(isNumber("٦")).toBe(true);
    expect(previewFlag("٦", "numeric", HB)).toBe("critical_low");
  });

  it("compares text results with the normal text, ignoring case", () => {
    expect(previewFlag("Negative", "pos_neg", NEG)).toBe("normal");
    expect(previewFlag("positive", "pos_neg", NEG)).toBe("abnormal");
    expect(previewFlag("clear", "text", null)).toBe("none");
  });
});

describe("helpers", () => {
  it("classifies flags", () => {
    expect(isCritical("critical_high")).toBe(true);
    expect(isCritical("high")).toBe(false);
    expect(isFlagged("low")).toBe(true);
    expect(isFlagged("normal")).toBe(false);
    expect(isFlagged("none")).toBe(false);
    expect(isFlagged(null)).toBe(false);
  });

  it("writes a range as one line", () => {
    expect(rangeText("13", "17")).toBe("13 - 17");
    expect(rangeText(null, "5")).toBe("≤ 5");
    expect(rangeText("150", null)).toBe("≥ 150");
    expect(rangeText(null, null, "nil")).toBe("nil");
  });
});
