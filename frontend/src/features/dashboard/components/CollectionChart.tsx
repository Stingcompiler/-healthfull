import { ChartColumn } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { EmptyState } from "@/components/EmptyState";
import { MoneyText } from "@/components/MoneyText";
import { formatDate, localeFor } from "@/lib/format";
import { useDirection, useLanguage } from "@/lib/i18n-hooks";

import type { ReportTrendDay } from "@/features/reports/types";

import { CHART_COLORS, compactNumber } from "../lib/chart";

interface Point {
  date: string;
  label: string;
  collected: number;
  pending: number;
  collectedText: string;
  pendingText: string;
}

function TooltipBox({ active, payload }: { active?: boolean; payload?: readonly { payload?: Point }[] }) {
  const { t } = useTranslation("dashboard");
  const direction = useDirection();
  const point = payload?.[0]?.payload;
  if (!active || !point) return null;
  return (
    <div dir={direction} className="card-surface flex flex-col gap-1 p-3 text-xs shadow-raised">
      <span className="font-semibold text-fg">{point.label}</span>
      <span className="flex items-center gap-2">
        <span className="size-2.5 rounded-full bg-success" aria-hidden="true" />
        {t("charts.collected")}: <MoneyText value={point.collectedText} currency={false} />
      </span>
      <span className="flex items-center gap-2">
        <span className="size-2.5 rounded-full bg-warning" aria-hidden="true" />
        {t("charts.pending")}: <MoneyText value={point.pendingText} currency={false} />
      </span>
    </div>
  );
}

/**
 * Confirmed collection and transfers still pending, per day for the last two weeks. Pending
 * money is stacked on top in its own color: it is never part of the collected bar.
 */
export function CollectionChart({ trend }: { trend: readonly ReportTrendDay[] }) {
  const { t } = useTranslation("dashboard");
  const language = useLanguage();
  const rtl = useDirection() === "rtl";
  const locale = localeFor(language);
  const data: Point[] = trend.map((d) => ({
    date: d.date,
    label: formatDate(d.date, language, "date"),
    collected: Number(d.collected),
    pending: Number(d.pending),
    collectedText: d.collected,
    pendingText: d.pending,
  }));
  const empty = data.every((d) => d.collected === 0 && d.pending === 0);

  return (
    <figure className="card-surface flex min-w-0 flex-col gap-3 p-4 md:p-5" data-testid="chart-collections">
      <figcaption className="flex flex-col gap-1">
        <h2 className="text-base font-semibold text-fg">{t("charts.collectionsTitle")}</h2>
        <span className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
          <span className="inline-flex items-center gap-1.5">
            <span className="size-2.5 rounded-full bg-success" aria-hidden="true" />
            {t("charts.collected")}
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="size-2.5 rounded-full bg-warning" aria-hidden="true" />
            {t("charts.pending")}
          </span>
        </span>
      </figcaption>
      {empty ? (
        <EmptyState bare size="compact" icon={<ChartColumn />} title={t("charts.collectionsEmpty")} />
      ) : (
        <div className="h-56 w-full min-w-0" dir="ltr" role="img" aria-label={t("charts.collectionsTitle")}>
          <ResponsiveContainer width="100%" height="100%" minWidth={0}>
            <BarChart data={data} margin={{ top: 8, right: 4, bottom: 0, left: 4 }}>
              <CartesianGrid vertical={false} stroke={CHART_COLORS.grid} />
              <XAxis
                dataKey="label"
                reversed={rtl}
                tick={{ fill: CHART_COLORS.axis, fontSize: 11 }}
                tickLine={false}
                axisLine={{ stroke: CHART_COLORS.grid }}
                interval="preserveStartEnd"
                minTickGap={16}
              />
              <YAxis
                orientation={rtl ? "right" : "left"}
                tickFormatter={(v: number) => compactNumber(v, locale)}
                tick={{ fill: CHART_COLORS.axis, fontSize: 11 }}
                tickLine={false}
                axisLine={false}
                width={44}
              />
              <Tooltip content={<TooltipBox />} cursor={{ fill: CHART_COLORS.cursor }} />
              <Bar dataKey="collected" stackId="day" fill={CHART_COLORS.collected} isAnimationActive={false} />
              <Bar
                dataKey="pending"
                stackId="day"
                fill={CHART_COLORS.pending}
                radius={[4, 4, 0, 0]}
                isAnimationActive={false}
              />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </figure>
  );
}
