import { Link } from "@tanstack/react-router";
import { CalendarDays, FlaskConical, Wallet } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { DateText } from "@/components/DateText";
import { ChevronNext } from "@/components/icons";
import { MoneyText } from "@/components/MoneyText";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useTranslateError } from "@/lib/api/translate-error";

import { usePortalMe, useSummary } from "../api";
import { PortalPage, Pill, Row } from "../components/PortalPage";
import { usePick } from "../lib/ui";

function HomeCard({
  icon,
  title,
  action,
  children,
  testId,
}: {
  icon: ReactNode;
  title: string;
  action?: ReactNode;
  children: ReactNode;
  testId: string;
}) {
  return (
    <section className="card-surface flex min-w-0 flex-col gap-3 p-4 md:p-5" data-testid={testId}>
      <div className="flex items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 text-base font-semibold text-fg">
          <span className="flex size-8 items-center justify-center rounded-control bg-primary-soft text-primary-strong [&_svg]:size-4">
            {icon}
          </span>
          {title}
        </h2>
        {action}
      </div>
      {children}
    </section>
  );
}

/** Home: the next appointment, the latest approved results and the balance. */
export function HomePage() {
  const { t } = useTranslation(["portal", "errors"]);
  const translateError = useTranslateError();
  const pick = usePick();
  const me = usePortalMe();
  const summary = useSummary();
  const name = me.data ? pick(me.data.full_name_ar, me.data.full_name_en) : "";

  return (
    <PortalPage
      title={t("home.title")}
      description={
        me.data ? (
          <>
            <span className="block text-base font-semibold text-fg">{t("home.greeting", { name })}</span>
            {t("home.fileNo", { fileNo: me.data.file_no })}
          </>
        ) : null
      }
    >
      {summary.isPending ? (
        <div className="grid gap-3">
          <Skeleton className="h-28" />
          <Skeleton className="h-28" />
          <Skeleton className="h-28" />
        </div>
      ) : summary.isError ? (
        <AlertCard variant="danger" title={t("errors:title")}>
          {translateError(summary.error)}
        </AlertCard>
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          <HomeCard icon={<CalendarDays />} title={t("home.nextAppointment")} testId="home-appointment">
            {summary.data.next_appointment ? (
              <div className="flex flex-col gap-1">
                <p className="text-base font-semibold text-fg">
                  <DateText value={summary.data.next_appointment.starts_at} format="long" />
                </p>
                <p className="text-sm text-fg">
                  <DateText value={summary.data.next_appointment.starts_at} format="time" />
                  {" · "}
                  {pick(summary.data.next_appointment.doctor.name_ar, summary.data.next_appointment.doctor.name_en)}
                </p>
                <p className="text-xs text-muted">
                  {pick(
                    summary.data.next_appointment.doctor.department_ar,
                    summary.data.next_appointment.doctor.department_en,
                  )}
                </p>
              </div>
            ) : (
              <p className="text-sm text-muted">{t("home.noAppointment")}</p>
            )}
            <Button asChild variant="soft" className="w-full">
              <Link to="/portal/appointments/new" data-testid="home-book">
                {t("home.book")}
              </Link>
            </Button>
          </HomeCard>

          <HomeCard
            icon={<FlaskConical />}
            title={t("home.latestResults")}
            testId="home-results"
            action={
              <Link
                to="/portal/results"
                className="inline-flex min-h-11 items-center gap-1 px-1 text-sm font-medium text-primary-strong focus-ring"
              >
                {t("home.viewAll")}
                <ChevronNext className="size-4" aria-hidden="true" />
              </Link>
            }
          >
            {summary.data.latest_results.length === 0 ? (
              <p className="text-sm text-muted">{t("home.noResults")}</p>
            ) : (
              <ul className="flex flex-col divide-y divide-border">
                {summary.data.latest_results.map((r) => (
                  <li key={r.line_id}>
                    <Link
                      to="/portal/results/$lineId"
                      params={{ lineId: String(r.line_id) }}
                      className="flex min-h-11 items-center justify-between gap-2 py-2 focus-ring-inset"
                    >
                      <span className="min-w-0">
                        <span className="block truncate text-sm font-medium text-fg">
                          {pick(r.test_name_ar, r.test_name_en)}
                        </span>
                        {r.approved_at ? (
                          <span className="text-xs text-muted">
                            <DateText value={r.approved_at} />
                          </span>
                        ) : null}
                      </span>
                      <span className="flex shrink-0 items-center gap-1">
                        {r.abnormal ? <Pill tone="warning">{t("results.abnormal")}</Pill> : null}
                        <ChevronNext className="size-4 text-muted" aria-hidden="true" />
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </HomeCard>

          <HomeCard icon={<Wallet />} title={t("home.balance")} testId="home-balance">
            {summary.data.balance.outstanding === "0.00" ? (
              <p className="text-sm text-success-fg">{t("home.allPaid")}</p>
            ) : null}
            <dl className="divide-y divide-border">
              <Row label={t("home.outstanding")}>
                <MoneyText value={summary.data.balance.outstanding} className="text-base" />
              </Row>
              {summary.data.balance.credit !== "0.00" ? (
                <Row label={t("home.credit")}>
                  <MoneyText value={summary.data.balance.credit} />
                </Row>
              ) : null}
              {summary.data.balance.pending !== "0.00" ? (
                <Row label={t("home.pending")}>
                  <MoneyText value={summary.data.balance.pending} />
                </Row>
              ) : null}
            </dl>
            <Button asChild variant="outline" className="w-full">
              <Link to="/portal/invoices">{t("nav.bills")}</Link>
            </Button>
          </HomeCard>
        </div>
      )}
    </PortalPage>
  );
}
