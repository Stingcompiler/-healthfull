import { useTranslation } from "react-i18next";

import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";
import { formatClock } from "@/lib/weekdays";

import { useCenterPage, type CenterToday } from "./api";

/** The center's name in the UI language, or the generic product name until one is set. */
export function useCenterName(): string {
  const { t } = useTranslation();
  const language = useLanguage();
  const center = useCenterPage();
  const name = center.data ? pickName({ ar: center.data.name_ar, en: center.data.name_en }, language) : "";
  return name || t("appShortName");
}

/** "Open now, until 8:00 pm", "Opens today at 8:00 am", "Closed now" or "Closed today". */
export function useTodayText(today: CenterToday | null | undefined): string {
  const { t } = useTranslation("portal");
  const language = useLanguage();
  if (!today) return "";
  const time = (value: string | null) => (value ? formatClock(value, language) : "");
  switch (today.state) {
    case "open":
      return t("center.today.open", { time: time(today.closes) });
    case "opens_later":
      return t("center.today.opensLater", { time: time(today.opens) });
    case "closed_now":
      return t("center.today.closedNow");
    default:
      return t("center.today.closedToday");
  }
}
