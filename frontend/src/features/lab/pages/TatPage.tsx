import type { ColumnDef } from "@tanstack/react-table";
import { CheckCheck, Gauge, Hourglass, Timer } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { DataTable } from "@/components/DataTable";
import { EmptyState } from "@/components/EmptyState";
import { KpiCard } from "@/components/KpiCard";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useTranslateError } from "@/lib/api/translate-error";
import { formatNumber } from "@/lib/format";
import { useLanguage } from "@/lib/i18n-hooks";

import { useTurnaround } from "../api";
import { LabNav } from "../components/LabNav";
import { useLabNames } from "../lib/use-lab-names";
import type { TatReport } from "../types";

type Row = TatReport["rows"][number];

/** Minutes as the lab reads them: "45 min", "2 h 10 min". */
function useMinutes() {
  const { t } = useTranslation("lab");
  const language = useLanguage();
  return (value: number | null): string => {
    if (value === null) return "—";
    if (value < 60) return t("tat.minutes", { count: value });
    const h = Math.floor(value / 60);
    const m = value % 60;
    return t("tat.hoursMinutes", { hours: formatNumber(h, language), minutes: formatNumber(m, language) });
  };
}

/**
 * Turnaround time per test (FEATURES 9.8): minutes from sample receipt to first approval,
 * median and 90th percentile against each test's target, and tests waiting past it now.
 */
export function TatPage() {
  const { t } = useTranslation(["lab", "errors"]);
  const translateError = useTranslateError();
  const language = useLanguage();
  const names = useLabNames();
  const minutes = useMinutes();
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const report = useTurnaround(from, to);
  const total = report.data?.total;

  const columns = useMemo<ColumnDef<Row>[]>(
    () => [
      {
        id: "test",
        header: t("tat.columns.test"),
        meta: { label: t("tat.columns.test"), className: "whitespace-normal" },
        cell: ({ row }) => (
          <span className="flex flex-col">
            <span className="font-medium">{names.test(row.original.test)}</span>
            <span className="text-xs text-muted">
              {t("tat.target")}: {minutes(row.original.test.turnaround_minutes)}
            </span>
          </span>
        ),
      },
      {
        id: "count",
        header: t("tat.columns.count"),
        meta: { label: t("tat.columns.count"), align: "end" },
        cell: ({ row }) => <span className="tabular">{formatNumber(row.original.stats.count, language)}</span>,
      },
      {
        id: "median",
        header: t("tat.columns.median"),
        meta: { label: t("tat.columns.median"), align: "end" },
        cell: ({ row }) => <span className="tabular">{minutes(row.original.stats.median)}</span>,
      },
      {
        id: "p90",
        header: t("tat.columns.p90"),
        meta: { label: t("tat.columns.p90"), align: "end" },
        cell: ({ row }) => <span className="tabular">{minutes(row.original.stats.p90)}</span>,
      },
      {
        id: "within",
        header: t("tat.columns.within"),
        meta: { label: t("tat.columns.within"), align: "end" },
        cell: ({ row }) => {
          const pct = row.original.stats.within_target_percent;
          return (
            <span className="tabular">
              {pct === null ? "—" : formatNumber(pct / 100, language, { style: "percent" })}
            </span>
          );
        },
      },
      {
        id: "overdue",
        header: t("tat.columns.overdue"),
        meta: { label: t("tat.columns.overdue"), align: "end" },
        cell: ({ row }) =>
          row.original.open_overdue > 0 ? (
            <Badge variant="warning">{formatNumber(row.original.open_overdue, language)}</Badge>
          ) : (
            <span className="text-muted">0</span>
          ),
      },
    ],
    [t, names, minutes, language],
  );

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <PageHeader title={t("tat.title")} description={t("tat.description")} icon={<Timer />} />
      <LabNav />
      <div className="flex flex-wrap items-end gap-3">
        <div className="grid gap-1.5">
          <Label htmlFor="tat-from">{t("tat.from")}</Label>
          <Input
            id="tat-from"
            type="date"
            dir="ltr"
            max="9999-12-31"
            value={from || (report.data?.date_from ?? "")}
            onChange={(e) => {
              setFrom(e.target.value);
            }}
            className="w-44"
          />
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="tat-to">{t("tat.to")}</Label>
          <Input
            id="tat-to"
            type="date"
            dir="ltr"
            max="9999-12-31"
            value={to || (report.data?.date_to ?? "")}
            onChange={(e) => {
              setTo(e.target.value);
            }}
            className="w-44"
          />
        </div>
      </div>
      {report.isError ? (
        <AlertCard variant="danger" title={t("errors:title")}>
          {translateError(report.error)}
        </AlertCard>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4" data-testid="tat-totals">
            <KpiCard
              label={t("tat.kpi.completed")}
              value={total ? formatNumber(total.count, language) : "—"}
              icon={<CheckCheck />}
              loading={report.isPending}
            />
            <KpiCard
              label={t("tat.kpi.median")}
              value={minutes(total?.median ?? null)}
              icon={<Timer />}
              loading={report.isPending}
            />
            <KpiCard
              label={t("tat.kpi.p90")}
              value={minutes(total?.p90 ?? null)}
              icon={<Hourglass />}
              loading={report.isPending}
              tone="warning"
            />
            <KpiCard
              label={t("tat.kpi.within")}
              value={
                total?.within_target_percent != null
                  ? formatNumber(total.within_target_percent / 100, language, { style: "percent" })
                  : "—"
              }
              icon={<Gauge />}
              loading={report.isPending}
              tone="success"
            />
          </div>
          <DataTable
            columns={columns}
            data={report.data?.rows ?? []}
            loading={report.isPending}
            getRowId={(r) => String(r.test.id)}
            caption={t("tat.title")}
            pageSize={50}
            minTableWidth={720}
            emptyState={<EmptyState bare size="compact" icon={<Timer />} title={t("tat.empty")} />}
            renderCard={(r) => (
              <div className="card-surface flex flex-col gap-2 p-4" data-testid="tat-row">
                <span className="flex items-start justify-between gap-2">
                  <span className="font-semibold">{names.test(r.test)}</span>
                  {r.open_overdue > 0 ? (
                    <Badge variant="warning">{t("tat.overdueNow", { count: r.open_overdue })}</Badge>
                  ) : null}
                </span>
                <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-sm">
                  <dt className="text-muted">{t("tat.target")}</dt>
                  <dd className="text-end tabular">{minutes(r.test.turnaround_minutes)}</dd>
                  <dt className="text-muted">{t("tat.columns.count")}</dt>
                  <dd className="text-end tabular">{formatNumber(r.stats.count, language)}</dd>
                  <dt className="text-muted">{t("tat.columns.median")}</dt>
                  <dd className="text-end tabular">{minutes(r.stats.median)}</dd>
                  <dt className="text-muted">{t("tat.columns.p90")}</dt>
                  <dd className="text-end tabular">{minutes(r.stats.p90)}</dd>
                  <dt className="text-muted">{t("tat.columns.within")}</dt>
                  <dd className="text-end tabular">
                    {r.stats.within_target_percent === null
                      ? "—"
                      : formatNumber(r.stats.within_target_percent / 100, language, { style: "percent" })}
                  </dd>
                </dl>
              </div>
            )}
          />
        </>
      )}
    </div>
  );
}
