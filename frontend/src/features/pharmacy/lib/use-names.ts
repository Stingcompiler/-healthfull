import { useCallback } from "react";

import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";

interface Named {
  name_ar: string;
  name_en: string;
}

interface Labelled {
  label_ar: string;
  label_en: string;
}

interface Person {
  full_name_ar: string;
  full_name_en: string;
  username?: string;
}

interface ItemNamed {
  item_name: string;
  item_name_ar?: string;
}

interface Generic {
  generic_name: string;
  generic_name_ar?: string;
  strength?: string;
}

interface BaseUnit {
  base_unit_name_ar: string;
  base_unit_name_en: string;
}

/** Picks bilingual fields for the current language (ARCHITECTURE 4.11, with fallback). */
export function useNames() {
  const language = useLanguage();
  const name = useCallback(
    (row: Named | null | undefined): string => (row ? pickName({ ar: row.name_ar, en: row.name_en }, language) : ""),
    [language],
  );
  const label = useCallback(
    (row: Labelled | null | undefined): string =>
      row ? pickName({ ar: row.label_ar, en: row.label_en }, language) : "",
    [language],
  );
  const person = useCallback(
    (row: Person | null | undefined): string =>
      row ? pickName({ ar: row.full_name_ar, en: row.full_name_en }, language) || (row.username ?? "") : "",
    [language],
  );
  const baseUnit = useCallback(
    (row: BaseUnit | null | undefined): string =>
      row ? pickName({ ar: row.base_unit_name_ar, en: row.base_unit_name_en }, language) : "",
    [language],
  );
  /** A stock line's item: the Arabic generic name on Arabic screens when the item has one. */
  const item = useCallback(
    (row: ItemNamed | null | undefined): string =>
      row ? (language === "ar" && row.item_name_ar ? row.item_name_ar : row.item_name) : "",
    [language],
  );
  /** An item's generic name and strength in the current language (Latin fallback). */
  const generic = useCallback(
    (row: Generic | null | undefined): string => {
      if (!row) return "";
      const base = language === "ar" && row.generic_name_ar ? row.generic_name_ar : row.generic_name;
      return [base, row.strength].filter(Boolean).join(" ");
    },
    [language],
  );
  return { name, label, person, baseUnit, item, generic, language };
}
