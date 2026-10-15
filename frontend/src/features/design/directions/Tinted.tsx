import { useTranslation } from "react-i18next";

import { MoneyText } from "@/components/MoneyText";
import { PatientCard } from "@/components/PatientCard";
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import { formatNumber } from "@/lib/format";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";
import { cn } from "@/lib/utils";

import { ALERTS, KPI, LINES, PATIENT, TOTALS, type DirAlert, type DirLine } from "./data";
import { LineFlags, OpenButton } from "./parts";
import { useAlertText } from "./tones";

/*
 * Direction C, tinted bento: tile sizes follow priority (the collection figure is the big tile),
 * and a tinted surface is reserved for what needs a decision (pending transfers, danger and
 * warning alerts, lines that need pre-approval). Everything else stays on the neutral surface.
 */

const ALERT_TINT: Record<DirAlert["tone"], string> = {
  danger: "border-danger-border bg-danger-bg text-danger-fg",
  warning: "border-warning-border bg-warning-bg text-warning-fg",
  info: "border-card-border bg-surface text-fg",
};

export function TintedDashboard() {
  const { t } = useTranslation("dashboard");
  const language = useLanguage();
  const alertText = useAlertText();
  const tile = "flex min-w-0 flex-col gap-2 rounded-card border p-4 md:p-5";
  const label = "text-sm font-medium";
  const value = "tabular text-xl leading-tight font-semibold md:text-2xl";
  return (
    <div className="flex min-w-0 flex-col gap-6">
      <section
        aria-label={t("kpi.title")}
        className="grid grid-cols-2 gap-3 md:grid-cols-4 md:gap-4 xl:grid-rows-[auto_auto]"
      >
        <div
          className={cn(
            tile,
            "col-span-2 justify-between border-transparent bg-primary-soft text-fg md:row-span-2 xl:p-6",
          )}
        >
          <div className="flex flex-col gap-2">
            <h2 className={cn(label, "text-primary-strong")}>{t("kpi.collectedToday")}</h2>
            <div className="tabular text-3xl leading-tight font-bold md:text-4xl xl:text-5xl">
              <MoneyText value={KPI.collected} currency={false} />
            </div>
          </div>
          <dl className="grid grid-cols-2 gap-4 pt-4 text-sm">
            <div>
              <dt className="text-xs text-fg-muted">{t("kpi.cash")}</dt>
              <dd className="font-semibold">
                <MoneyText value={KPI.cash} currency={false} />
              </dd>
            </div>
            <div>
              <dt className="text-xs text-fg-muted">{t("kpi.transfers")}</dt>
              <dd className="font-semibold">
                <MoneyText value={KPI.bank} currency={false} />
              </dd>
            </div>
          </dl>
        </div>
        <div className={cn(tile, "col-span-2 border-warning-border bg-warning-bg text-warning-fg md:col-span-2")}>
          <h2 className={label}>{t("kpi.pendingTransfers")}</h2>
          <div className={value}>
            <MoneyText value={KPI.pending} currency={false} />
          </div>
          <p className="text-xs">{t("kpi.pendingCount", { n: formatNumber(KPI.pendingCount, language) })}</p>
        </div>
        <div className={cn(tile, "card-surface")}>
          <h2 className={cn(label, "text-muted")}>{t("kpi.queueWaiting")}</h2>
          <div className={value}>{formatNumber(KPI.queueWaiting, language)}</div>
          <p className="text-xs text-muted">{t("kpi.withDoctor", { n: formatNumber(KPI.withDoctor, language) })}</p>
        </div>
        <div className={cn(tile, "card-surface")}>
          <h2 className={cn(label, "text-muted")}>{t("kpi.netRevenueToday")}</h2>
          <div className={value}>
            <MoneyText value={KPI.netRevenue} currency={false} />
          </div>
          <p className="text-xs text-muted">{t("kpi.visitsToday", { n: formatNumber(KPI.visits, language) })}</p>
        </div>
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-base font-semibold text-fg">{t("alerts.title")}</h2>
        <ul className="grid grid-cols-1 gap-2 lg:grid-cols-2">
          {ALERTS.map((alert) => (
            <li
              key={alert.key}
              className={cn(
                "flex flex-wrap items-center gap-x-3 gap-y-2 rounded-card border px-4 py-3",
                ALERT_TINT[alert.tone],
              )}
            >
              <span className="tabular text-xl font-bold">{formatNumber(alert.count, language)}</span>
              <p className="min-w-0 flex-1 basis-48 text-sm">
                {alertText(alert)}
                {alert.amount !== null ? (
                  <span className="mt-0.5 block font-semibold">
                    <MoneyText value={alert.amount} />
                  </span>
                ) : null}
              </p>
              <OpenButton className="bg-surface" />
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

function TintedLine({ line }: { line: DirLine }) {
  const { t } = useTranslation("cashier");
  const language = useLanguage();
  const cancelled = line.state === "cancelled";
  const needsAction = line.flag === "preapproval";
  return (
    <article
      className={cn(
        "grid gap-3 rounded-card border p-4 md:grid-cols-[minmax(0,1fr)_minmax(0,17rem)] md:items-center",
        needsAction
          ? "border-warning-border bg-warning-bg"
          : cancelled
            ? "border-card-border bg-subtle"
            : "card-surface",
      )}
    >
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge status={line.state} />
          <bdi className="tabular text-xs text-muted">{line.code}</bdi>
          <span className="tabular text-xs text-muted">
            {t("invoice.qty")} {formatNumber(line.quantity, language)}
          </span>
        </div>
        <h3 className={cn("mt-2 text-base leading-snug font-semibold text-fg", cancelled && "text-muted line-through")}>
          {pickName(line.service, language)}
        </h3>
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          <LineFlags line={line} />
        </div>
      </div>
      <dl className="grid grid-cols-2 gap-3 rounded-control bg-surface/70 p-3 text-sm">
        <div>
          <dt className="text-xs text-muted">{t("invoice.payerShare")}</dt>
          <dd className="tabular">
            <MoneyText value={line.payerShare} currency={false} />
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted">{t("invoice.patientShare")}</dt>
          <dd className={cn("text-lg leading-tight font-bold", cancelled && "text-muted line-through")}>
            <MoneyText value={line.patientShare} currency={false} />
          </dd>
        </div>
      </dl>
    </article>
  );
}

export function TintedCashier() {
  const { t } = useTranslation(["cashier", "design"]);
  return (
    <div className="flex min-w-0 flex-col gap-4">
      <PatientCard patient={PATIENT} />
      <ul className="flex flex-col gap-3">
        {LINES.map((line) => (
          <li key={line.id} className="min-w-0">
            <TintedLine line={line} />
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap items-center justify-between gap-4 rounded-card bg-primary-soft p-4 md:p-5">
        <dl className="flex flex-wrap gap-x-8 gap-y-2 text-sm">
          <div>
            <dt className="text-xs text-fg-muted">{t("cashier:invoice.payerTotal")}</dt>
            <dd className="font-semibold">
              <MoneyText value={TOTALS.payerShare} />
            </dd>
          </div>
          <div>
            <dt className="text-xs text-fg-muted">{t("design:directions.toCollect")}</dt>
            <dd className="text-2xl leading-tight font-bold">
              <MoneyText value={TOTALS.patientShare} />
            </dd>
          </div>
        </dl>
        <Button>{t("cashier:invoice.approve")}</Button>
      </div>
    </div>
  );
}
