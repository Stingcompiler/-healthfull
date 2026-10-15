import { CircleAlert, Info, TriangleAlert, type LucideIcon } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { DirAlert } from "./data";

export const TONE_ICON: Record<DirAlert["tone"], LucideIcon> = {
  danger: CircleAlert,
  warning: TriangleAlert,
  info: Info,
};

/** The alert's translated sentence (the same keys as the real dashboard). */
export function useAlertText() {
  const { t } = useTranslation("dashboard");
  return (alert: DirAlert) => t(`alerts.${alert.key}`);
}
