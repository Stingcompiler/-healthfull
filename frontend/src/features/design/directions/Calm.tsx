import { useTranslation } from "react-i18next";

import { MoneyText } from "@/components/MoneyText";
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import { formatNumber } from "@/lib/format";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";
import { cn } from "@/lib/utils";

import { ALERTS, KPI, LINES, PATIENT, TOTALS, type DirLine } from "./data";
import { LineFlags, OpenButton, PatientStrip } from "./parts";
import { TONE_ICON, useAlertText } from "./tones";

/*
 * Direction A, calm and precise: one bordered surface per job, no shadow, no icon tiles.
 * The figure that matters (confirmed collections) is the largest; the rest are one step down.
 * Colour is spent on the one thing that needs a decision (pending transfers).
 */

export function CalmDashboard() {
  const { t } = useTranslation("dashboard");
  const language = useLanguage();
  const alertText = useAlertText();
  const cell = "flex min-w-0 flex-col gap-1.5 bg-surface p-4 md:p-5";
  const label = "text-sm font-medium text-muted";
  const value = "tabular text-xl leading-tight font-semibold text-fg md:text-2xl";
  return (
    <div className="flex min-w-0 flex-col gap-6">
      <section
        aria-label={t("kpi.title")}
        className="grid grid-cols-2 gap-px overflow-hidden rounded-card border border-border bg-border xl:grid-cols-[minmax(0,1.6fr)_repeat(3,minmax(0,1fr))]"
      >
        <div className={cn(cell, "col-span-2 xl:col-span-1")}>
          <h2 className={label}>{t("kpi.collectedToday")}</h2>
          <div className="tabular text-3xl leading-tight font-bold text-fg md:text-4xl">
            <MoneyText value={KPI.collected} currency={false} />
          </div>
          <p className="flex flex-wrap gap-x-4 gap-y-0.5 text-xs text-muted">
            <span>
              {t("kpi.cash")} <MoneyText value={KPI.cash} currency={false} />
            </span>
            <span>
              {t("kpi.transfers")} <MoneyText value={KPI.bank} currency={false} />
            </span>
          </p>
        </div>
        <div className={cell}>
          <h2 className={label}>{t("kpi.pendingTransfers")}</h2>
          <div className={cn(value, "text-warning-fg")}>
            <MoneyText value={KPI.pending} currency={false} />
          </div>
          <p className="text-xs text-muted">{t("kpi.pendingCount", { n: formatNumber(KPI.pendingCount, language) })}</p>
        </div>
        <div className={cell}>
          <h2 className={label}>{t("kpi.queueWaiting")}</h2>
          <div className={value}>{formatNumber(KPI.queueWaiting, language)}</div>
          <p className="text-xs text-muted">{t("kpi.withDoctor", { n: formatNumber(KPI.withDoctor, language) })}</p>
        </div>
        <div className={cn(cell, "col-span-2 xl:col-span-1")}>
          <h2 className={label}>{t("kpi.netRevenueToday")}</h2>
          <div className={value}>
            <MoneyText value={KPI.netRevenue} currency={false} />
          </div>
          <p className="text-xs text-muted">{t("kpi.visitsToday", { n: formatNumber(KPI.visits, language) })}</p>
        </div>
      </section>

      <section className="flex flex-col gap-2">
        <h2 className="text-base font-semibold text-fg">{t("alerts.title")}</h2>
        <ul className="divide-y divide-border overflow-hidden rounded-card border border-border bg-surface">
          {ALERTS.map((alert) => {
            const Icon = TONE_ICON[alert.tone];
            return (
              <li key={alert.key} className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3">
                <Icon
                  className={cn(
                    "size-4 shrink-0",
                    alert.tone === "danger" && "text-danger",
                    alert.tone === "warning" && "text-warning",
                    alert.tone === "info" && "text-info",
                  )}
                  aria-hidden="true"
                />
                <p className="min-w-0 flex-1 basis-56 text-sm text-fg">
                  <span className="tabular font-semibold">{formatNumber(alert.count, language)}</span>{" "}
                  {alertText(alert)}
                  {alert.amount !== null ? (
                    <span className="text-muted">
                      {" · "}
                      <MoneyText value={alert.amount} />
                    </span>
                  ) : null}
                </p>
                <OpenButton />
              </li>
            );
          })}
        </ul>
      </section>
    </div>
  );
}

function CalmLine({ line }: { line: DirLine }) {
  const { t } = useTranslation("cashier");
  const language = useLanguage();
  const cancelled = line.state === "cancelled";
  return (
    <li className="grid gap-x-6 gap-y-2 px-4 py-3 md:grid-cols-[minmax(0,1fr)_auto_11rem] md:items-center">
      <div className="min-w-0">
        <h3 className={cn("text-sm leading-snug font-medium text-fg", cancelled && "text-muted line-through")}>
          {pickName(line.service, language)}
        </h3>
        <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted">
          <bdi className="tabular">{line.code}</bdi>
          <span aria-hidden="true">·</span>
          <span className="tabular">
            {t("invoice.qty")} {formatNumber(line.quantity, language)}
          </span>
          <LineFlags line={line} />
        </div>
      </div>
      <StatusBadge status={line.state} className="justify-self-start" />
      <dl className={cn("grid gap-0.5 text-sm md:text-end", cancelled && "text-muted")}>
        <div className="flex items-baseline justify-between gap-3 text-xs text-muted">
          <dt>{t("invoice.payerShare")}</dt>
          <dd>
            <MoneyText value={line.payerShare} currency={false} />
          </dd>
        </div>
        <div className="flex items-baseline justify-between gap-3">
          <dt className="text-xs text-muted">{t("invoice.patientShare")}</dt>
          <dd className={cn("font-semibold", cancelled && "line-through")}>
            <MoneyText value={line.patientShare} currency={false} />
          </dd>
        </div>
      </dl>
    </li>
  );
}

export function CalmCashier() {
  const { t } = useTranslation(["cashier", "design"]);
  return (
    <section className="overflow-hidden rounded-card border border-border bg-surface">
      <div className="p-4 md:p-5">
        <PatientStrip patient={PATIENT} />
      </div>
      <ul className="divide-y divide-border border-t border-border">
        {LINES.map((line) => (
          <CalmLine key={line.id} line={line} />
        ))}
      </ul>
      <footer className="flex flex-wrap items-end justify-between gap-4 border-t border-border bg-subtle px-4 py-4 md:px-5">
        <dl className="flex flex-wrap gap-x-8 gap-y-2 text-sm">
          <div>
            <dt className="text-xs text-muted">{t("cashier:invoice.grossTotal")}</dt>
            <dd>
              <MoneyText value={TOTALS.gross} />
            </dd>
          </div>
          <div>
            <dt className="text-xs text-muted">{t("cashier:invoice.discountTotal")}</dt>
            <dd>
              <MoneyText value={`-${TOTALS.discount}`} />
            </dd>
          </div>
          <div>
            <dt className="text-xs text-muted">{t("cashier:invoice.payerTotal")}</dt>
            <dd>
              <MoneyText value={TOTALS.payerShare} />
            </dd>
          </div>
          <div>
            <dt className="text-xs text-muted">{t("design:directions.toCollect")}</dt>
            <dd className="text-xl font-bold text-fg">
              <MoneyText value={TOTALS.patientShare} />
            </dd>
          </div>
        </dl>
        <Button>{t("cashier:invoice.approve")}</Button>
      </footer>
    </section>
  );
}
