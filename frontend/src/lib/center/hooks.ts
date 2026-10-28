import { useTranslation } from "react-i18next";

import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";
import { formatClock, nextOpening, weekdayName } from "@/lib/weekdays";

import { useCenterPage, type CenterHours, type CenterToday } from "./api";

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

/**
 * The public status line: the same as `useTodayText`, and, once the center is closed for the
 * day, when it opens next ("Closed today. Opens Saturday at 8:00 AM").
 */
export function useOpenStatusText(today: CenterToday | null | undefined, hours: readonly CenterHours[]): string {
  const { t } = useTranslation("portal");
  const language = useLanguage();
  const base = useTodayText(today);
  if (!today || today.state === "open" || today.state === "opens_later") return base;
  const next = nextOpening(hours, today.weekday);
  if (!next) return base;
  const day = next.daysAhead === 1 ? t("center.tomorrow") : weekdayName(next.weekday, language);
  return `${base} · ${t("center.today.reopens", { day, time: formatClock(next.opens, language) })}`;
}
