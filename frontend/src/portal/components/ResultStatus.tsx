import { useTranslation } from "react-i18next";

import { Pill } from "./PortalPage";

/**
 * A result's status in words: outside the normal range (amber: discuss it with the doctor),
 * within the normal range (neutral), and corrected by the lab when it replaces an earlier one.
 */
export function ResultStatus({ abnormal, amended }: { abnormal: boolean; amended: boolean }) {
  const { t } = useTranslation("portal");
  return (
    <span className="flex flex-wrap items-center justify-end gap-1" data-testid="result-status">
      {amended ? <Pill tone="info">{t("results.amended")}</Pill> : null}
      {abnormal ? (
        <Pill tone="warning">{t("results.abnormal")}</Pill>
      ) : (
        <Pill tone="neutral">{t("results.withinRange")}</Pill>
      )}
    </span>
  );
}
