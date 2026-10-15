import { Banknote, Hourglass, Clock3, TrendingUp } from "lucide-react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { KpiCard } from "@/components/KpiCard";
import { MoneyText } from "@/components/MoneyText";
import { PatientCard } from "@/components/PatientCard";
import { ServiceLineCard } from "@/components/ServiceLineCard";
import { formatNumber } from "@/lib/format";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";

import { ALERTS, KPI, LINES, PATIENT, TOTALS, type DirLine } from "./data";
import { LineFlags, OpenButton } from "./parts";
import { useAlertText } from "./tones";

/** Today's shared components, fed with the same sample data as the candidates (the baseline). */
export function CurrentDashboard() {
  const { t } = useTranslation("dashboard");
  const language = useLanguage();
  const alertText = useAlertText();
  return (
    <div className="flex min-w-0 flex-col gap-6">
      <section aria-label={t("kpi.title")} className="grid grid-cols-2 gap-3 md:gap-4 xl:grid-cols-4">
        <KpiCard
          label={t("kpi.collectedToday")}
          value={<MoneyText value={KPI.collected} currency={false} />}
          icon={<Banknote />}
          tone="success"
          hint={
            <span className="inline-flex flex-wrap gap-x-3 gap-y-0.5">
              <span>
                {t("kpi.cash")} <MoneyText value={KPI.cash} currency={false} />
              </span>
              <span>
                {t("kpi.transfers")} <MoneyText value={KPI.bank} currency={false} />
              </span>
            </span>
          }
        />
        <KpiCard
          label={t("kpi.pendingTransfers")}
          value={<MoneyText value={KPI.pending} currency={false} />}
          icon={<Hourglass />}
          tone="warning"
          hint={t("kpi.pendingCount", { n: formatNumber(KPI.pendingCount, language) })}
        />
        <KpiCard
          label={t("kpi.queueWaiting")}
          value={formatNumber(KPI.queueWaiting, language)}
          icon={<Clock3 />}
          tone="info"
          hint={t("kpi.withDoctor", { n: formatNumber(KPI.withDoctor, language) })}
        />
        <KpiCard
          label={t("kpi.netRevenueToday")}
          value={<MoneyText value={KPI.netRevenue} currency={false} />}
          icon={<TrendingUp />}
          tone="primary"
          hint={t("kpi.visitsToday", { n: formatNumber(KPI.visits, language) })}
        />
      </section>
      <section className="flex flex-col gap-3">
        <h2 className="text-base font-semibold text-fg">{t("alerts.title")}</h2>
        <ul className="grid grid-cols-1 gap-3 lg:grid-cols-2">
          {ALERTS.map((alert) => (
            <li key={alert.key} className="min-w-0">
              <AlertCard
                variant={alert.tone}
                title={
                  <span className="flex flex-wrap items-baseline gap-x-2">
                    <span className="tabular text-lg font-bold">{formatNumber(alert.count, language)}</span>
                    <span>{alertText(alert)}</span>
                  </span>
                }
                action={<OpenButton />}
              >
                {alert.amount !== null ? <MoneyText value={alert.amount} /> : null}
              </AlertCard>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

function CurrentLine({ line }: { line: DirLine }) {
  const { t } = useTranslation("cashier");
  const language = useLanguage();
  return (
    <ServiceLineCard
      name={pickName(line.service, language)}
      quantity={line.quantity}
      unitPrice={line.unitPrice}
      status={line.state}
      className="h-full p-3 ps-4 shadow-none"
      meta={
        <span className="mt-1 flex flex-wrap items-center gap-1.5">
          <LineFlags line={line} />
        </span>
      }
    >
      <dl className="grid gap-1 text-sm">
        <Row label={t("invoice.gross")} value={line.gross} />
        {line.discount !== "0.00" ? <Row label={t("invoice.discount")} value={`-${line.discount}`} /> : null}
        <Row label={t("invoice.payerShare")} value={line.payerShare} />
        <Row label={t("invoice.patientShare")} value={line.patientShare} strong />
      </dl>
    </ServiceLineCard>
  );
}

function Row({ label, value, strong = false }: { label: string; value: string; strong?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="text-muted">{label}</dt>
      <dd className={strong ? "font-semibold" : undefined}>
        <MoneyText value={value} />
      </dd>
    </div>
  );
}

export function CurrentCashier() {
  const { t } = useTranslation("cashier");
  return (
    <div className="flex min-w-0 flex-col gap-4">
      <PatientCard patient={PATIENT} />
      <ul className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        {LINES.map((line) => (
          <li key={line.id} className="min-w-0">
            <CurrentLine line={line} />
          </li>
        ))}
      </ul>
      <dl className="card-surface grid gap-1 p-4 text-sm sm:ms-auto sm:w-80">
        <Row label={t("invoice.grossTotal")} value={TOTALS.gross} />
        <Row label={t("invoice.discountTotal")} value={`-${TOTALS.discount}`} />
        <Row label={t("invoice.payerTotal")} value={TOTALS.payerShare} />
        <Row label={t("invoice.patientTotal")} value={TOTALS.patientShare} strong />
      </dl>
    </div>
  );
}
