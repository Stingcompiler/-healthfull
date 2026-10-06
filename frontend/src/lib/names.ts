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
