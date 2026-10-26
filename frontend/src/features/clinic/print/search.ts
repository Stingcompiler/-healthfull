import type { PrintLang } from "./ClinicPrintFrame";

/** Search params of a clinic printout: the paper's language (default the screen's). */
export interface ClinicPrintSearch {
  lang?: PrintLang;
}

export function parseClinicPrintSearch(search: Record<string, unknown>): ClinicPrintSearch {
  return search.lang === "ar" || search.lang === "en" ? { lang: search.lang } : {};
}
