import { useCallback } from "react";

import { localeFor } from "@/lib/format";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";
import type { Language } from "@/lib/preferences";

/** Picks the bilingual field for the UI language, with fallback (ARCHITECTURE 4.11). */
export function usePick(): (ar: string | null | undefined, en: string | null | undefined) => string {
  const language = useLanguage();
  return useCallback((ar, en) => pickName({ ar, en }, language), [language]);
}

/** A calendar day from the API ("2026-10-12"), shown as e.g. "Mon, 12 Oct" in the UI language. */
export function formatDay(day: string, language: Language): string {
  return new Intl.DateTimeFormat(localeFor(language), {
    weekday: "short",
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  }).format(new Date(`${day}T00:00:00Z`));
}

/** The public URL a receipt's QR opens to check it (FEATURES 15.1, ADR 0016). */
export function receiptVerifyUrl(token: string, number: string): string {
  return `${window.location.origin}/verify/${token}?r=${encodeURIComponent(number)}`;
}
