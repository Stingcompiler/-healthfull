import { describe, expect, it } from "vitest";

import { centerDate } from "./dates";

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
