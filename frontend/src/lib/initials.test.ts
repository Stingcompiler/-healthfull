import { describe, expect, it } from "vitest";

import { initialsOf } from "./initials";

describe("initialsOf", () => {
  it("takes the first letters of the first two words", () => {
    expect(initialsOf("Amal Hassan Omer")).toBe("A‌H");
  });

  it("skips titles and generic place words", () => {
    expect(initialsOf("Dr. Amal Hassan")).toBe("A‌H");
    expect(initialsOf("Al Noor Medical Center")).toBe("A‌N");
    expect(initialsOf("د. أحمد علي")).toBe("أ‌ع");
    expect(initialsOf("مركز النور الطبي")).toBe("ن");
  });

  it("falls back to the raw words when nothing else is left", () => {
    expect(initialsOf("Clinic")).toBe("C");
  });

  it("handles empty input and a single word", () => {
    expect(initialsOf("   ")).toBe("");
    expect(initialsOf("Salma")).toBe("S");
  });
});
