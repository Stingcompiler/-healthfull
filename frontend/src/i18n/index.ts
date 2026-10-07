import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import {
  applyLanguageToDocument,
  DEFAULT_LANGUAGE,
  isLanguage,
  LANGUAGES,
  readCachedLanguage,
  type Language,
} from "@/lib/preferences";

import { NAMESPACES, resources } from "./resources";

function initialLanguage(): Language {
  if (typeof document !== "undefined" && isLanguage(document.documentElement.lang)) {
    // boot.js already applied the cached choice before first paint.
    return readCachedLanguage() ?? document.documentElement.lang;
  }
  return DEFAULT_LANGUAGE;
}

void i18n.use(initReactI18next).init({
  resources,
  lng: initialLanguage(),
  fallbackLng: DEFAULT_LANGUAGE,
  supportedLngs: [...LANGUAGES],
  ns: NAMESPACES,
  defaultNS: "common",
  interpolation: { escapeValue: false },
  returnNull: false,
  initAsync: false,
  react: { useSuspense: false },
});

/**
 * `{{value, bidi}}`: wraps an interpolated value in First Strong Isolate ... Pop Directional
 * Isolate (U+2068 ... U+2069). Use it for every ID, number or code placed inside translated
 * text: without it, "رقم الملف {{fileNo}}" shows the file number 2026-00412 as 00412-2026,
 * because after Arabic letters the digits take the Arabic direction and "-" is neutral.
 * (Components that render IDs on their own use <bdi> instead.)
 */
export const FSI = "\u2068";
export const PDI = "\u2069";
i18n.services.formatter?.add("bidi", (value: unknown) => `${FSI}${String(value)}${PDI}`);

i18n.on("languageChanged", (lng) => {
  if (isLanguage(lng) && typeof document !== "undefined") applyLanguageToDocument(lng);
});

if (typeof document !== "undefined" && isLanguage(i18n.language)) {
  applyLanguageToDocument(i18n.language);
}

export function currentLanguage(): Language {
  return isLanguage(i18n.language) ? i18n.language : DEFAULT_LANGUAGE;
}

export default i18n;
