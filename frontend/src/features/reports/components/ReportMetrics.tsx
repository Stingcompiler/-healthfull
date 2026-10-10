import { useTranslation } from "react-i18next";

import { KpiCard } from "@/components/KpiCard";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";

import type { ReportMetric } from "../types";
import { ReportCell } from "./ReportCell";

const TONES = {
  neutral: "primary",
  primary: "primary",
  success: "success",
  warning: "warning",
  danger: "danger",
  info: "info",
} as const;

/** The figures on top of a report, two per row on phones. */
export function ReportMetrics({ metrics }: { metrics: readonly ReportMetric[] }) {
  const { t } = useTranslation("reports");
  const language = useLanguage();
  if (metrics.length === 0) return null;
  return (
    <section
      aria-label={t("viewer.summary")}
      data-testid="report-metrics"
      className="grid grid-cols-2 gap-3 md:gap-4 lg:grid-cols-4"
    >
      {metrics.map((metric) => (
        <KpiCard
          key={metric.key}
          headingLevel="p"
          label={pickName(metric.label, language)}
          tone={TONES[metric.tone]}
          value={<ReportCell value={metric.value} kind={metric.kind} />}
        />
      ))}
    </section>
  );
}
