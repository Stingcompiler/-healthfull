import { useTranslation } from "react-i18next";

import { DEFAULT_LANGUAGE, directionOf, isLanguage, type Language } from "@/lib/preferences";

/** Current UI language; re-renders on change. */
export function useLanguage(): Language {
  const { i18n } = useTranslation();
  return isLanguage(i18n.language) ? i18n.language : DEFAULT_LANGUAGE;
}

export function useDirection(): "rtl" | "ltr" {
  return directionOf(useLanguage());
}
