import { Building2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { EmptyState } from "@/components/EmptyState";
import { MoneyText } from "@/components/MoneyText";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";

import type { ReportDashboard } from "@/features/reports/types";

/**
 * Today's net revenue per department (billed, not collected), largest first.
 *
 * Plain rows (name, a proportional bar, the amount) instead of an SVG axis chart: the names are
 * real text that follows the page direction, so they cannot collide with the neighbouring
 * chart in Arabic, and the exact amount is printed instead of an axis to estimate from.
 */
export function DepartmentChart({ departments }: { departments: ReportDashboard["departments"] }) {
  const { t } = useTranslation("dashboard");
  const language = useLanguage();
  const rows = departments.slice(0, 8).map((d) => ({
    key: pickName(d.department, language),
    name: pickName(d.department, language),
    net: Number(d.net),
    netText: d.net,
  }));
  const max = Math.max(...rows.map((r) => r.net), 0);

  return (
    <figure className="card-surface flex min-w-0 flex-col gap-3 p-4 md:p-5" data-testid="chart-departments">
      <figcaption className="flex flex-col gap-1">
        <h2 className="text-base font-semibold text-fg">{t("charts.departmentsTitle")}</h2>
        <span className="text-xs text-muted">{t("charts.departmentsHint")}</span>
      </figcaption>
      {rows.length === 0 ? (
        <EmptyState bare size="compact" icon={<Building2 />} title={t("charts.departmentsEmpty")} />
      ) : (
        <ul className="flex flex-col gap-3">
          {rows.map((row) => (
            <li key={row.key} className="grid min-w-0 gap-1">
              <div className="flex min-w-0 items-baseline justify-between gap-3 text-sm">
                <span className="min-w-0 break-words text-fg">{row.name}</span>
                <MoneyText value={row.netText} currency={false} className="shrink-0 text-muted" />
              </div>
              <div className="h-2 w-full overflow-hidden rounded-full bg-subtle" aria-hidden="true">
                <div
                  className="h-full rounded-full bg-primary"
                  style={{ width: `${String(max > 0 ? Math.max(2, (row.net / max) * 100) : 0)}%` }}
                />
              </div>
            </li>
          ))}
        </ul>
      )}
    </figure>
  );
}
