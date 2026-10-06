import type { Language } from "@/lib/preferences";

export interface BilingualName {
  ar?: string | null;
  en?: string | null;
}

/**
 * Picks the name for the UI language with fallback to the other one
 * (ARCHITECTURE 4.11: name_ar / name_en, fallback when one is missing).
 */
export function pickName(name: BilingualName, language: Language): string {
  const primary = (language === "ar" ? name.ar : name.en)?.trim() ?? "";
  const fallback = (language === "ar" ? name.en : name.ar)?.trim() ?? "";
  return primary === "" ? fallback : primary;
}

// Letters of right-to-left scripts: Hebrew, Arabic, Syriac, Thaana, NKo, Samaritan, Mandaic,
// Arabic Extended and the Arabic presentation forms.
const RTL_LETTER = /[\u0590-\u08FF\uFB1D-\uFDFF\uFE70-\uFEFF]/u;

/**
 * Base direction of a piece of text, from its first letter (the first-strong rule that
 * dir="auto" uses, limited to letters). Text with no letter follows `fallback`.
 */
export function textDirection(text: string, fallback: "rtl" | "ltr" = "ltr"): "rtl" | "ltr" {
  for (const char of text) {
    if (RTL_LETTER.test(char)) return "rtl";
    if (/\p{L}/u.test(char)) return "ltr";
  }
  return fallback;
}

/** Initials for avatars: first letters of the first two words. */
export function initials(name: string): string {
  // Only words that contain a letter count ("مولود — طوارئ" -> "مط").
  const words = name
    .trim()
    .split(/\s+/)
    .filter((w) => /\p{L}/u.test(w));
  return words
    .slice(0, 2)
    .map((w) => Array.from(w)[0] ?? "")
    .join("")
    .toUpperCase();
}
