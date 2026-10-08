import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";

/** The name of a row in the UI language (name_ar / name_en with fallback). */
export function useLocalName(): (row: { name_ar?: string | null; name_en?: string | null }) => string {
  const language = useLanguage();
  return (row) => pickName({ ar: row.name_ar, en: row.name_en }, language);
}
