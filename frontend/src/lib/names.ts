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

const ARABIC_LETTER = /[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]/u;
/** Zero-width non-joiner: keeps two Arabic initials as separate letters ("م‌ن", not "من"). */
const ZWNJ = "\u200C";
/** First words that form one name with the word after them (عبد الله, أبو بكر). */
const COMPOUND_PREFIXES = new Set(["عبد", "ابو", "أبو", "abd", "abu"]);

/** A title or abbreviation ("د.", "Dr.", "أ."), never an initial. */
function isTitle(word: string): boolean {
  return word.endsWith(".") && Array.from(word).length <= 5;
}

/** First letter of a name word, skipping the Arabic definite article (الحسن -> ح). */
function initialOf(word: string): string {
  const letters = Array.from(word);
  if (letters.length > 3 && letters[0] === "ا" && letters[1] === "ل") return letters[2] ?? "";
  return letters[0] ?? "";
}

/**
 * Initials for avatars: the first letters of the first two name words. Titles are skipped,
 * compound names (عبد الرحمن) count as one word, the Arabic article "ال" is dropped (otherwise
 * "مدير النظام" gives "ما", the word "what"), and Arabic initials are kept apart with a ZWNJ
 * so they read as two letters instead of joining into a word.
 */
export function initials(name: string): string {
  // Only words that contain a letter count ("مولود — طوارئ" -> "م‌ط").
  const words = name
    .trim()
    .split(/\s+/)
    .filter((w) => /\p{L}/u.test(w))
    .filter((w) => !isTitle(w));
  const parts: string[] = [];
  for (let i = 0; i < words.length && parts.length < 2; i += 1) {
    const word = words[i] ?? "";
    parts.push(initialOf(word));
    if (COMPOUND_PREFIXES.has(word.toLowerCase()) && i + 1 < words.length) i += 1;
  }
  const arabic = parts.length > 0 && parts.every((p) => ARABIC_LETTER.test(p));
  return parts.join(arabic ? ZWNJ : "").toUpperCase();
}
