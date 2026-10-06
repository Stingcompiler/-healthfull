import { describe, expect, it } from "vitest";

import { ar, en, NAMESPACES } from "./resources";

const PLURAL_SUFFIX = /_(zero|one|two|few|many|other)$/;

interface Tree {
  readonly [key: string]: string | Tree;
}

function flatten(tree: Tree, prefix = ""): Map<string, string> {
  const out = new Map<string, string>();
  for (const [key, value] of Object.entries(tree)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (typeof value === "string") out.set(path, value);
    else for (const [k, v] of flatten(value, path)) out.set(k, v);
  }
  return out;
}

/** Keys with plural suffixes collapsed: Arabic has six plural forms, English two. */
function baseKeys(keys: Iterable<string>): Set<string> {
  return new Set([...keys].map((k) => k.replace(PLURAL_SUFFIX, "")));
}

function placeholders(text: string): string[] {
  return [...text.matchAll(/\{\{\s*(\w+)\s*\}\}/g)].map((m) => m[1] ?? "").sort();
}

describe("i18n resources", () => {
  it("ar and en register the same namespaces", () => {
    expect(Object.keys(ar).sort()).toEqual(Object.keys(en).sort());
    expect(NAMESPACES.length).toBeGreaterThanOrEqual(17);
  });

  describe.each(NAMESPACES)("namespace %s", (ns) => {
    const arFlat = flatten(ar[ns]);
    const enFlat = flatten(en[ns]);

    it("has identical key sets in ar and en", () => {
      const arKeys = [...baseKeys(arFlat.keys())].sort();
      const enKeys = [...baseKeys(enFlat.keys())].sort();
      expect(arKeys).toEqual(enKeys);
    });

    it("has no empty translations", () => {
      for (const [lang, flat] of [
        ["ar", arFlat],
        ["en", enFlat],
      ] as const) {
        for (const [key, value] of flat) {
          expect(value.trim(), `${lang}:${ns}:${key}`).not.toBe("");
        }
      }
    });

    it("uses the same interpolation variables in both languages", () => {
      for (const [key, enValue] of enFlat) {
        const base = key.replace(PLURAL_SUFFIX, "");
        const arVariants = [...arFlat].filter(([k]) => k.replace(PLURAL_SUFFIX, "") === base);
        const enVars = new Set(placeholders(enValue).filter((v) => v !== "count"));
        for (const [arKey, arValue] of arVariants) {
          const arVars = new Set(placeholders(arValue).filter((v) => v !== "count"));
          expect([...arVars].sort(), `${ns}:${arKey}`).toEqual([...enVars].sort());
        }
      }
    });

    it("defines every plural form each language needs", () => {
      const required = { ar: ["zero", "one", "two", "few", "many", "other"], en: ["one", "other"] };
      for (const [lang, flat] of [
        ["ar", arFlat],
        ["en", enFlat],
      ] as const) {
        const plurals = [...flat.keys()].filter((k) => PLURAL_SUFFIX.test(k));
        for (const base of baseKeys(plurals)) {
          for (const form of required[lang]) {
            expect(flat.has(`${base}_${form}`), `${lang}:${ns}:${base}_${form}`).toBe(true);
          }
        }
      }
    });

    it("Arabic text is actually Arabic", () => {
      // Guards against copy-pasting English into the ar file. A value counts
      // as Arabic if it has at least one Arabic letter; short codes, numbers
      // and language names written in their own script are allowed.
      const allowed = /^(\d+|[A-Z0-9_ .-]+|English|[^A-Za-z]*)$/;
      for (const [key, value] of arFlat) {
        const hasArabic = /[؀-ۿ]/.test(value);
        expect(hasArabic || allowed.test(value), `ar:${ns}:${key} = "${value}"`).toBe(true);
      }
    });
  });
});
