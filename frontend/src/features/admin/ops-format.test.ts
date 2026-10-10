import { describe, expect, it } from "vitest";

import { formatBytes } from "./ops-format";

describe("formatBytes", () => {
  it("picks the largest unit that keeps the value at least 1", () => {
    expect(formatBytes(0, "en")).toBe("0 byte");
    expect(formatBytes(512, "en")).toBe("512 byte");
    expect(formatBytes(2048, "en")).toBe("2 kB");
    expect(formatBytes(1.5 * 1024 ** 3, "en")).toBe("1.5 GB");
    expect(formatBytes(-5, "en")).toBe("0 byte");
  });

  it("localizes the number and unit", () => {
    expect(formatBytes(3 * 1024 ** 2, "ar")).toMatch(/3/);
  });
});
