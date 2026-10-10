import { Link } from "@tanstack/react-router";
import { Banknote, ChartColumn, CircleCheck, Clock3, Hourglass, TrendingUp } from "lucide-react";
import { useTranslation } from "react-i18next";

import { visibleNav } from "@/app/nav";
import { AlertCard } from "@/components/AlertCard";
import { DateText } from "@/components/DateText";
import { ChevronNext } from "@/components/icons";
import { KpiCard } from "@/components/KpiCard";
import { MoneyText } from "@/components/MoneyText";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useTranslateError } from "@/lib/api/translate-error";
import { useCurrentUser, usePermission } from "@/lib/auth/hooks";
import { formatNumber } from "@/lib/format";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";

import type { ReportAlert, ReportDashboard } from "@/features/reports/types";

import { useManagerDashboard } from "../api";
import { CollectionChart } from "../components/CollectionChart";
import { DepartmentChart } from "../components/DepartmentChart";

/** Alerts the dashboard knows how to name (the server sends the key). */
const ALERT_KEYS = [
  "stale_transfers",
  "unreviewed_variances",
  "paid_not_performed",
  "requested_not_invoiced",
  "performed_by_authorization",
  "expiring_stock",
  "low_stock",
] as const;
type AlertKey = (typeof ALERT_KEYS)[number];

function isAlertKey(key: string): key is AlertKey {
  return (ALERT_KEYS as readonly string[]).includes(key);
}

/** The variant of each alert tone (the server sends the tone). */
const ALERT_VARIANT = {
  neutral: "info",
  primary: "info",
  info: "info",
  success: "success",
  warning: "warning",
  danger: "danger",
} as const;

/**
 * Home. Everyone is greeted by name; a manager (reports.view_dashboard) sees today at a
 * glance (FEATURES 12.10): confirmed collection, pending transfers kept apart, the queue,
 * what needs attention, and two charts. Everyone else gets the modules they work in.
 */
export function DashboardPage() {
  const { t } = useTranslation("dashboard");
  const language = useLanguage();
  const me = useCurrentUser();
  const isManager = usePermission("reports.view_dashboard");
  const name = me ? pickName({ ar: me.full_name_ar, en: me.full_name_en }, language) || me.username : "";

  return (
    <div className="flex min-w-0 flex-col gap-6">
      <PageHeader
        eyebrow={<DateText value={new Date()} format="long" />}
        title={t("greeting", { name })}
        description={isManager ? t("subtitle") : t("staff.subtitle")}
        actions={
          isManager ? (
            <Button asChild variant="outline">
              <Link to="/reports">
                <ChartColumn aria-hidden="true" />
                {t("allReports")}
              </Link>
            </Button>
          ) : undefined
        }
      />
      {isManager ? <ManagerDashboard /> : <StaffHome />}
    </div>
  );
}

function metricValue(data: ReportDashboard, key: string): string | number | null {
  const found = data.metrics.find((m) => m.key === key)?.value;
  return typeof found === "string" || typeof found === "number" ? found : null;
}

function ManagerDashboard() {
  const { t } = useTranslation(["dashboard", "errors"]);
  const translateError = useTranslateError();
  const language = useLanguage();
  const dashboard = useManagerDashboard(true);
  const data = dashboard.data;

  if (dashboard.isError) {
    return (
      <AlertCard variant="danger" title={t("errors:title")}>
        {translateError(dashboard.error)}
      </AlertCard>
    );
  }

  const money = (key: string) => String(data ? (metricValue(data, key) ?? "0.00") : "0.00");
  const count = (key: string) => formatNumber(Number(data ? (metricValue(data, key) ?? 0) : 0), language);
  const loading = !data;

  return (
    <div className="flex min-w-0 flex-col gap-6" data-testid="manager-dashboard">
      <section aria-label={t("kpi.title")} className="grid grid-cols-2 gap-3 md:gap-4 xl:grid-cols-4">
        <KpiCard
          label={t("kpi.collectedToday")}
          value={<MoneyText value={money("collected_today")} />}
          icon={<Banknote />}
          tone="success"
          loading={loading}
          hint={
            data ? (
              <>
                <span>
                  {t("kpi.cash")} <MoneyText value={money("cash_today")} currency={false} />
                </span>
                <span>
                  {t("kpi.transfers")} <MoneyText value={money("bank_today")} currency={false} />
                </span>
              </>
            ) : undefined
          }
        />
        <KpiCard
          label={t("kpi.pendingTransfers")}
          value={<MoneyText value={money("pending_transfers")} />}
          icon={<Hourglass />}
          tone="warning"
          loading={loading}
          hint={data ? t("kpi.pendingCount", { n: count("pending_count") }) : undefined}
        />
        <KpiCard
          label={t("kpi.queueWaiting")}
          value={count("queue_waiting")}
          icon={<Clock3 />}
          tone="info"
          loading={loading}
          hint={data ? t("kpi.withDoctor", { n: count("with_doctor") }) : undefined}
        />
        <KpiCard
          label={t("kpi.netRevenueToday")}
          value={<MoneyText value={money("net_revenue_today")} />}
          icon={<TrendingUp />}
          tone="primary"
          loading={loading}
          hint={data ? t("kpi.visitsToday", { n: count("visits_today") }) : undefined}
        />
      </section>

      <section aria-labelledby="dashboard-alerts" className="flex flex-col gap-3">
        <h2 id="dashboard-alerts" className="text-base font-semibold text-fg">
          {t("alerts.title")}
        </h2>
        {loading ? (
          <Skeleton className="h-20 w-full" />
        ) : data.alerts.length === 0 ? (
          <AlertCard variant="success" icon={<CircleCheck />} title={t("alerts.allClear")} />
        ) : (
          <ul className="grid grid-cols-1 gap-3 lg:grid-cols-2" data-testid="dashboard-alerts">
            {data.alerts.map((alert) => (
              <li key={alert.key} className="min-w-0">
                <AlertItem alert={alert} />
              </li>
            ))}
          </ul>
        )}
      </section>

      <div className="grid min-w-0 grid-cols-1 gap-4 lg:grid-cols-2">
        {loading ? (
          <>
            <Skeleton className="h-72 w-full" />
            <Skeleton className="h-72 w-full" />
          </>
        ) : (
          <>
            <CollectionChart trend={data.trend} />
            <DepartmentChart departments={data.departments} />
          </>
        )}
      </div>
    </div>
  );
}

function AlertItem({ alert }: { alert: ReportAlert }) {
  const { t } = useTranslation("dashboard");
  const language = useLanguage();
  return (
    <AlertCard
      variant={ALERT_VARIANT[alert.tone]}
      title={
        <span className="flex flex-wrap items-baseline gap-x-2">
          <span className="tabular text-lg font-bold">{formatNumber(alert.count, language)}</span>
          <span>{isAlertKey(alert.key) ? t(`alerts.${alert.key}`) : alert.key}</span>
        </span>
      }
      action={
        alert.report ? (
          <Button asChild variant="outline" size="sm">
            <Link to="/reports/$reportKey" params={{ reportKey: alert.report }}>
              {t("alerts.open")}
              <ChevronNext aria-hidden="true" />
            </Link>
          </Button>
        ) : undefined
      }
    >
      {alert.amount !== null ? <MoneyText value={alert.amount} /> : null}
    </AlertCard>
  );
}

/** For everyone else: the modules this user works in, as large links. */
function StaffHome() {
  const { t } = useTranslation(["dashboard", "nav"]);
  const me = useCurrentUser();
  const items = visibleNav(me).filter((item) => item.id !== "dashboard" && !item.hidden);
  return (
    <section aria-labelledby="staff-modules" className="flex flex-col gap-3">
      <h2 id="staff-modules" className="text-base font-semibold text-fg">
        {t("staff.modules")}
      </h2>
      <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3" data-testid="staff-modules">
        {items.map((item) => {
          const Icon = item.icon;
          return (
            <li key={item.id} className="min-w-0">
              <Link
                to={item.to}
                className="card-surface flex min-h-14 items-center gap-3 p-4 focus-ring transition-colors hover:border-primary/40"
              >
                <span className="flex size-10 shrink-0 items-center justify-center rounded-control bg-primary-soft text-primary-strong [&_svg]:size-5">
                  <Icon aria-hidden="true" className={item.flipInRtl ? "rtl:-scale-x-100" : undefined} />
                </span>
                <span className="min-w-0 flex-1 font-semibold text-fg">{t(`nav:items.${item.labelKey}`)}</span>
                <ChevronNext className="size-4 shrink-0 text-muted" aria-hidden="true" />
              </Link>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
