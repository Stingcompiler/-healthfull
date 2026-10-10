import { describe, expect, it } from "vitest";

import { CHART_COLORS, compactNumber } from "./chart";

describe("chart colors", () => {
  it("are theme tokens only, never raw colors", () => {
    for (const value of Object.values(CHART_COLORS)) {
      expect(value).toMatch(/^var\(--[a-z-]+\)$/);
    }
  });

  it("formats axis numbers compactly", () => {
    expect(compactNumber(12500, "en")).toBe("12.5K");
    expect(compactNumber(0, "en")).toBe("0");
  });
});
