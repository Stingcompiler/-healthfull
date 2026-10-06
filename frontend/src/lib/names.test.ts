import { describe, expect, it } from "vitest";

import { initials, pickName, textDirection } from "./names";

describe("pickName", () => {
  it("prefers the UI language and falls back to the other name", () => {
    expect(pickName({ ar: "فاطمة", en: "Fatima" }, "ar")).toBe("فاطمة");
    expect(pickName({ ar: "فاطمة", en: "Fatima" }, "en")).toBe("Fatima");
    expect(pickName({ ar: "مولود", en: null }, "en")).toBe("مولود");
    expect(pickName({ ar: "  ", en: "Fatima" }, "ar")).toBe("Fatima");
  });
});

describe("textDirection", () => {
  it("follows the first letter", () => {
    expect(textDirection("فاطمة عثمان")).toBe("rtl");
    expect(textDirection("Fatima Osman")).toBe("ltr");
    expect(textDirection("Dr. أحمد")).toBe("ltr");
    expect(textDirection("د. Ahmed")).toBe("rtl");
  });

  it("skips digits, punctuation and spaces before the first letter", () => {
    expect(textDirection("  12 - مولود")).toBe("rtl");
    expect(textDirection("(2) Baby")).toBe("ltr");
  });

  it("uses the fallback when there is no letter", () => {
    expect(textDirection("2026-00412")).toBe("ltr");
    expect(textDirection("2026-00412", "rtl")).toBe("rtl");
    expect(textDirection("", "rtl")).toBe("rtl");
  });
});

describe("initials", () => {
  it("takes the first letter of the first two words that contain letters", () => {
    expect(initials("مولود — طوارئ")).toBe("مط");
    expect(initials("fatima osman mohamed")).toBe("FO");
  });
});
