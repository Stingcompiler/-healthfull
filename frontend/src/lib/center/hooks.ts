import { useTranslation } from "react-i18next";

import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";

import { useCenterPage } from "./api";

/** The center's name in the UI language, or the generic product name until one is set. */
export function useCenterName(): string {
  const { t } = useTranslation();
  const language = useLanguage();
  const center = useCenterPage();
  const name = center.data ? pickName({ ar: center.data.name_ar, en: center.data.name_en }, language) : "";
  return name || t("appShortName");
}
