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
  const ZWNJ = "\u200C";

  it("takes the first letter of the first two words that contain letters", () => {
    expect(initials("مولود — طوارئ")).toBe(`م${ZWNJ}ط`);
    expect(initials("fatima osman mohamed")).toBe("FO");
  });

  it("skips the Arabic definite article", () => {
    // Not "ما" (the word "what").
    expect(initials("مدير النظام")).toBe(`م${ZWNJ}ن`);
    expect(initials("الحسن البشير")).toBe(`ح${ZWNJ}ب`);
    expect(initials("محمد الطيب")).toBe(`م${ZWNJ}ط`);
    // Short words keep their first letter (ال is not an article in a 3-letter word).
    expect(initials("آل بيت")).toBe(`آ${ZWNJ}ب`);
  });

  it("treats عبد and أبو compounds as one name", () => {
    expect(initials("عبد الرحمن محمد")).toBe(`ع${ZWNJ}م`);
    expect(initials("أبو بكر عثمان")).toBe(`أ${ZWNJ}ع`);
    expect(initials("عبدالله يوسف")).toBe(`ع${ZWNJ}ي`);
  });

  it("skips titles", () => {
    expect(initials("د. أحمد الطيب")).toBe(`أ${ZWNJ}ط`);
    expect(initials("Dr. Ahmed Altayeb")).toBe("AA");
  });

  it("keeps Arabic initials apart but joins Latin ones", () => {
    expect(initials("فاطمة عثمان").includes(ZWNJ)).toBe(true);
    expect(initials("Fatima Osman")).toBe("FO");
    expect(initials("سارة")).toBe("س");
    expect(initials("")).toBe("");
  });
});
