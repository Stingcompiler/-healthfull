import { describe, expect, it } from "vitest";

import { dataCodewords, encodeQr, formatBits, rawDataModules, rsDivisor, rsRemainder } from "./qr";

/** Reference matrices from an independent encoder (Project Nayuki qrcodegen, Python), byte mode, level M, fixed mask. */
import reference from "./qr.reference.json";

describe("QR encoder", () => {
  it("computes Reed-Solomon codewords (HELLO WORLD, 1-M worked example)", () => {
    const data = [32, 91, 11, 120, 209, 114, 220, 77, 67, 64, 236, 17, 236, 17, 236, 17];
    expect(rsRemainder(data, rsDivisor(10))).toEqual([196, 35, 39, 119, 235, 215, 231, 226, 93, 23]);
  });

  it("has the standard format bits for level M", () => {
    expect(formatBits(0).toString(2).padStart(15, "0")).toBe("101010000010010");
    expect(formatBits(7).toString(2).padStart(15, "0")).toBe("100101010100000");
  });

  it("has the standard capacities", () => {
    expect(rawDataModules(1)).toBe(208);
    expect(dataCodewords(1)).toBe(16);
    expect(dataCodewords(3)).toBe(44);
    expect(dataCodewords(7)).toBe(124);
    expect(dataCodewords(10)).toBe(216);
  });

  it("picks the smallest version and draws the finder patterns", () => {
    const qr = encodeQr("RCP-2026-000123|3600.00|2026-10-08");
    expect(qr.version).toBe(3);
    expect(qr.size).toBe(29);
    const row = (y: number) => qr.modules[y]?.slice(0, 7).map((d) => (d ? 1 : 0));
    expect(row(0)).toEqual([1, 1, 1, 1, 1, 1, 1]);
    expect(row(1)).toEqual([1, 0, 0, 0, 0, 0, 1]);
    expect(row(3)).toEqual([1, 0, 1, 1, 1, 0, 1]);
  });

  it("matches an independent encoder module for module", () => {
    for (const ref of reference as { text: string; mask: number; rows: string[] }[]) {
      const qr = encodeQr(ref.text, { mask: ref.mask });
      const rows = qr.modules.map((r) => r.map((d) => (d ? "1" : "0")).join(""));
      expect(rows, `${ref.text} mask ${String(ref.mask)}`).toEqual(ref.rows);
    }
  });

  it("refuses a payload beyond version 10", () => {
    expect(() => encodeQr("x".repeat(300))).toThrow(RangeError);
  });
});
