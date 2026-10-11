/**
 * Contract guard: every column of the Excel/CSV imports (backend/domain/*_import.py) has a
 * label under `ops:imports.field`, so a row error never shows a raw column key such as
 * `generic_name_ar` beside its message.
 */
import { describe, expect, it } from "vitest";

import { ar, en } from "@/i18n/resources";

const sources = import.meta.glob<string>("../../../../backend/domain/*_import.py", {
  query: "?raw",
  import: "default",
  eager: true,
});

function columnKeys(): Set<string> {
  const keys = new Set<string>();
  for (const text of Object.values(sources)) {
    for (const match of text.matchAll(/\bColumn\(\s*"([a-z][a-z0-9_]*)"/g)) {
      if (match[1]) keys.add(match[1]);
    }
  }
  return keys;
}

describe.skipIf(Object.keys(sources).length === 0)("import column labels", () => {
  const keys = columnKeys();

  it("finds the import columns (the scan itself works)", () => {
    for (const key of ["service_code", "generic_name_ar", "full_name_ar", "price"]) {
      expect(keys.has(key), key).toBe(true);
    }
  });

  it("labels every column in both languages", () => {
    const labels = {
      en: en.ops.imports.field as Record<string, string>,
      ar: ar.ops.imports.field as Record<string, string>,
    };
    for (const [lang, field] of Object.entries(labels)) {
      const missing = [...keys].filter((key) => !field[key]);
      expect(missing, `add ops:imports.field.<key> (${lang})`).toEqual([]);
    }
  });
});
