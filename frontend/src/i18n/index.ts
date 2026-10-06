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
