import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { MoneyText } from "@/components/MoneyText";
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableFooter, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatNumber } from "@/lib/format";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";
import { cn } from "@/lib/utils";

import { ALERTS, KPI, LINES, PATIENT, TOTALS, type DirLine } from "./data";
import { LineFlags, OpenButton, PatientStrip } from "./parts";
import { TONE_ICON, useAlertText } from "./tones";

/*
 * Direction B, flat operating units: no card surfaces at all. Structure comes from whitespace
 * and hairlines; figures sit in the open; invoice lines are a dense table that collapses to
 * stacked rows on a phone. Built for the all-day operator on the 1280 desktop.
 */

function Figure({
  label,
  hint,
  children,
  size = "md",
  tone,
}: {
  label: string;
  hint?: ReactNode;
  children: ReactNode;
  size?: "md" | "lg";
  tone?: "warning";
}) {
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <h2 className="text-sm font-medium text-muted">{label}</h2>
      <div
        className={cn(
          "tabular leading-tight font-semibold text-fg",
          size === "lg" ? "text-3xl font-bold md:text-4xl" : "text-xl md:text-2xl",
          tone === "warning" && "text-warning-fg",
        )}
      >
        {children}
      </div>
      {hint ? <p className="text-xs text-muted">{hint}</p> : null}
    </div>
  );
}

export function FlatDashboard() {
  const { t } = useTranslation("dashboard");
  const language = useLanguage();
  const alertText = useAlertText();
  return (
    <div className="flex min-w-0 flex-col gap-8">
      <section
        aria-label={t("kpi.title")}
        className="grid grid-cols-2 gap-x-6 gap-y-6 border-y border-border py-5 md:flex md:flex-wrap md:items-end md:gap-x-14"
      >
        <div className="col-span-2 md:col-span-1">
          <Figure
            size="lg"
            label={t("kpi.collectedToday")}
            hint={
              <span className="flex flex-wrap gap-x-4">
                <span>
                  {t("kpi.cash")} <MoneyText value={KPI.cash} currency={false} />
                </span>
                <span>
                  {t("kpi.transfers")} <MoneyText value={KPI.bank} currency={false} />
                </span>
              </span>
            }
          >
            <MoneyText value={KPI.collected} currency={false} />
          </Figure>
        </div>
        <Figure
          tone="warning"
          label={t("kpi.pendingTransfers")}
          hint={t("kpi.pendingCount", { n: formatNumber(KPI.pendingCount, language) })}
        >
          <MoneyText value={KPI.pending} currency={false} />
        </Figure>
        <Figure label={t("kpi.queueWaiting")} hint={t("kpi.withDoctor", { n: formatNumber(KPI.withDoctor, language) })}>
          {formatNumber(KPI.queueWaiting, language)}
        </Figure>
        <div className="col-span-2 md:col-span-1">
          <Figure
            label={t("kpi.netRevenueToday")}
            hint={t("kpi.visitsToday", { n: formatNumber(KPI.visits, language) })}
          >
            <MoneyText value={KPI.netRevenue} currency={false} />
          </Figure>
        </div>
      </section>

      <section className="flex flex-col gap-1">
        <h2 className="text-base font-semibold text-fg">{t("alerts.title")}</h2>
        <ul className="divide-y divide-border">
          {ALERTS.map((alert) => {
            const Icon = TONE_ICON[alert.tone];
            return (
              <li key={alert.key} className="flex flex-wrap items-center gap-x-3 gap-y-2 py-3">
                <Icon
                  className={cn(
                    "size-4 shrink-0",
                    alert.tone === "danger" && "text-danger",
                    alert.tone === "warning" && "text-warning",
                    alert.tone === "info" && "text-info",
                  )}
                  aria-hidden="true"
                />
                <span
                  className={cn(
                    "w-8 tabular text-lg font-bold",
                    alert.tone === "danger" && "text-danger-fg",
                    alert.tone === "warning" && "text-warning-fg",
                    alert.tone === "info" && "text-info-fg",
                  )}
                >
                  {formatNumber(alert.count, language)}
                </span>
                <p className="min-w-0 flex-1 basis-56 text-sm text-fg">
                  {alertText(alert)}
                  {alert.amount !== null ? (
                    <span className="ms-3 text-muted">
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

function StackedLine({ line }: { line: DirLine }) {
  const { t } = useTranslation("cashier");
  const language = useLanguage();
  const cancelled = line.state === "cancelled";
  return (
    <li className="flex flex-col gap-2 py-3">
      <div className="flex items-start justify-between gap-3">
        <h3 className={cn("min-w-0 text-sm leading-snug font-medium", cancelled && "text-muted line-through")}>
          {pickName(line.service, language)}
        </h3>
        <StatusBadge status={line.state} size="sm" />
      </div>
      <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted">
        <bdi className="tabular">{line.code}</bdi>
        <LineFlags line={line} />
      </div>
      <dl className="grid grid-cols-3 gap-2 text-xs">
        <div>
          <dt className="text-muted">{t("invoice.gross")}</dt>
          <dd className="tabular">
            <MoneyText value={line.gross} currency={false} />
          </dd>
        </div>
        <div>
          <dt className="text-muted">{t("invoice.payerShare")}</dt>
          <dd className="tabular">
            <MoneyText value={line.payerShare} currency={false} />
          </dd>
        </div>
        <div>
          <dt className="text-muted">{t("invoice.patientShare")}</dt>
          <dd className="tabular text-sm font-semibold">
            <MoneyText value={line.patientShare} currency={false} />
          </dd>
        </div>
      </dl>
    </li>
  );
}

export function FlatCashier() {
  const { t } = useTranslation(["cashier", "design"]);
  const language = useLanguage();
  const num = "text-end tabular";
  return (
    <div className="flex min-w-0 flex-col gap-5">
      <PatientStrip patient={PATIENT} className="border-b border-border pb-4" />

      <ul className="divide-y divide-border md:hidden">
        {LINES.map((line) => (
          <StackedLine key={line.id} line={line} />
        ))}
      </ul>

      <Table className="hidden md:table">
        <TableHeader>
          <TableRow>
            <TableHead>{t("design:directions.service")}</TableHead>
            <TableHead className={num}>{t("cashier:invoice.qty")}</TableHead>
            <TableHead className={num}>{t("cashier:invoice.gross")}</TableHead>
            <TableHead className={num}>{t("cashier:invoice.payerShare")}</TableHead>
            <TableHead className={num}>{t("cashier:invoice.patientShare")}</TableHead>
            <TableHead>{t("design:directions.status")}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {LINES.map((line) => {
            const cancelled = line.state === "cancelled";
            return (
              <TableRow key={line.id}>
                <TableCell className="py-2">
                  <div className={cn("font-medium", cancelled && "text-muted line-through")}>
                    {pickName(line.service, language)}
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-muted">
                    <bdi className="tabular">{line.code}</bdi>
                    <LineFlags line={line} />
                  </div>
                </TableCell>
                <TableCell className={num}>{formatNumber(line.quantity, language)}</TableCell>
                <TableCell className={num}>
                  <MoneyText value={line.gross} currency={false} />
                </TableCell>
                <TableCell className={num}>
                  <MoneyText value={line.payerShare} currency={false} />
                </TableCell>
                <TableCell className={cn(num, "font-semibold")}>
                  <MoneyText value={line.patientShare} currency={false} />
                </TableCell>
                <TableCell>
                  <StatusBadge status={line.state} size="sm" />
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
        <TableFooter>
          <TableRow>
            <TableCell>{t("design:directions.total")}</TableCell>
            <TableCell />
            <TableCell className={num}>
              <MoneyText value={TOTALS.gross} currency={false} />
            </TableCell>
            <TableCell className={num}>
              <MoneyText value={TOTALS.payerShare} currency={false} />
            </TableCell>
            <TableCell className={cn(num, "text-base font-bold")}>
              <MoneyText value={TOTALS.patientShare} />
            </TableCell>
            <TableCell />
          </TableRow>
        </TableFooter>
      </Table>

      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4 md:hidden">
        <p className="text-sm">
          <span className="text-muted">{t("design:directions.toCollect")} </span>
          <span className="text-lg font-bold">
            <MoneyText value={TOTALS.patientShare} />
          </span>
        </p>
        <Button>{t("cashier:invoice.approve")}</Button>
      </div>
      <div className="hidden justify-end md:flex">
        <Button>{t("cashier:invoice.approve")}</Button>
      </div>
    </div>
  );
}
