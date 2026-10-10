import { Building2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { EmptyState } from "@/components/EmptyState";
import { MoneyText } from "@/components/MoneyText";
import { localeFor } from "@/lib/format";
import { useDirection, useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";

import type { ReportDashboard } from "@/features/reports/types";

import { CHART_COLORS, compactNumber } from "../lib/chart";

interface Point {
  name: string;
  net: number;
  netText: string;
}

function TooltipBox({ active, payload }: { active?: boolean; payload?: readonly { payload?: Point }[] }) {
  const point = payload?.[0]?.payload;
  if (!active || !point) return null;
  return (
    <div className="card-surface flex flex-col gap-1 p-3 text-xs shadow-raised">
      <span className="font-semibold text-fg">{point.name}</span>
      <MoneyText value={point.netText} />
    </div>
  );
}

/** Today's net revenue per department (billed, not collected), largest first. */
export function DepartmentChart({ departments }: { departments: ReportDashboard["departments"] }) {
  const { t } = useTranslation("dashboard");
  const language = useLanguage();
  const rtl = useDirection() === "rtl";
  const locale = localeFor(language);
  const data: Point[] = departments.slice(0, 8).map((d) => ({
    name: pickName(d.department, language),
    net: Number(d.net),
    netText: d.net,
  }));
  const height = Math.max(160, data.length * 40 + 24);

  return (
    <figure className="card-surface flex min-w-0 flex-col gap-3 p-4 md:p-5" data-testid="chart-departments">
      <figcaption className="flex flex-col gap-1">
        <h2 className="text-base font-semibold text-fg">{t("charts.departmentsTitle")}</h2>
        <span className="text-xs text-muted">{t("charts.departmentsHint")}</span>
      </figcaption>
      {data.length === 0 ? (
        <EmptyState bare size="compact" icon={<Building2 />} title={t("charts.departmentsEmpty")} />
      ) : (
        <div className="w-full min-w-0" style={{ height }} role="img" aria-label={t("charts.departmentsTitle")}>
          <ResponsiveContainer width="100%" height="100%" minWidth={0}>
            <BarChart data={data} layout="vertical" margin={{ top: 0, right: 8, bottom: 0, left: 8 }}>
              <CartesianGrid horizontal={false} stroke={CHART_COLORS.grid} />
              <XAxis
                type="number"
                reversed={rtl}
                tickFormatter={(v: number) => compactNumber(v, locale)}
                tick={{ fill: CHART_COLORS.axis, fontSize: 11 }}
                tickLine={false}
                axisLine={false}
              />
              <YAxis
                type="category"
                dataKey="name"
                orientation={rtl ? "right" : "left"}
                width={96}
                tick={{ fill: CHART_COLORS.axis, fontSize: 11 }}
                tickLine={false}
                axisLine={false}
              />
              <Tooltip content={<TooltipBox />} cursor={{ fill: CHART_COLORS.cursor }} />
              <Bar dataKey="net" fill={CHART_COLORS.revenue} radius={4} barSize={20} isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </figure>
  );
}
