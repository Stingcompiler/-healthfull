import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { DateText } from "@/components/DateText";
import { DecisionList, DecisionRow } from "@/components/DecisionList";
import { ChevronNext } from "@/components/icons";
import { MoneyText } from "@/components/MoneyText";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useTranslateError } from "@/lib/api/translate-error";
import { isZeroAmount } from "@/lib/format";

import { usePortalMe, useSummary } from "../api";
import { PortalPage, PortalSection, Row } from "../components/PortalPage";
import { ResultStatus } from "../components/ResultStatus";
import { usePick } from "../lib/ui";

const viewAllClass =
  "inline-flex min-h-11 items-center gap-1 px-1 text-sm font-medium text-primary-strong focus-ring rounded-control";

/**
 * Home, in the order a patient acts: what needs action (money to pay and how, results outside
 * the normal range), then the next appointment, the latest results and the balance. Amber only
 * for what the patient should act on (D-0009); waiting money (a transfer the bank has not
 * confirmed) stays neutral.
 */
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
          <Skeleton className="h-20" />
          <Skeleton className="h-28" />
          <Skeleton className="h-28" />
        </div>
      ) : summary.isError ? (
        <AlertCard variant="danger" title={t("errors:title")}>
          {translateError(summary.error)}
        </AlertCard>
      ) : (
        (() => {
          const { balance, next_appointment: next, latest_results: results } = summary.data;
          const owes = !isZeroAmount(balance.outstanding);
          const abnormal = results.filter((r) => r.abnormal);
          return (
            <div className="flex flex-col gap-5">
              <section aria-labelledby="home-action-title" data-testid="home-action">
                <h2 id="home-action-title" className="mb-2 text-base font-semibold text-fg">
                  {t("home.actionTitle")}
                </h2>
                {owes || abnormal.length > 0 ? (
                  <DecisionList>
                    {owes ? (
                      <DecisionRow
                        tone="warning"
                        title={
                          <>
                            <span className="font-semibold">{t("home.toPay")}</span>{" "}
                            <MoneyText value={balance.outstanding} className="font-semibold" />
                            <span className="mt-0.5 block text-muted">{t("home.howToPay")}</span>
                          </>
                        }
                        action={
                          <Button asChild variant="outline" size="sm">
                            <Link to="/portal/invoices" data-testid="home-pay">
                              {t("home.seeBills")}
                            </Link>
                          </Button>
                        }
                      />
                    ) : null}
                    {abnormal.map((r) => (
                      <DecisionRow
                        key={r.line_id}
                        tone="warning"
                        title={
                          <>
                            <span className="font-semibold">{pick(r.test_name_ar, r.test_name_en)}</span>
                            <span className="mt-0.5 block text-muted">{t("home.abnormalHint")}</span>
                          </>
                        }
                        action={
                          <Button asChild variant="outline" size="sm">
                            <Link to="/portal/results/$lineId" params={{ lineId: String(r.line_id) }}>
                              {t("home.openResult")}
                            </Link>
                          </Button>
                        }
                      />
                    ))}
                  </DecisionList>
                ) : (
                  <p className="card-surface px-4 py-3 text-sm text-fg" data-testid="home-nothing">
                    {t("home.nothingToDo")}
                  </p>
                )}
              </section>

              <div className="grid gap-5 md:grid-cols-2 md:items-start">
                <PortalSection title={t("home.nextAppointment")} testId="home-appointment">
                  {next ? (
                    <div className="flex flex-col gap-1">
                      <p className="text-base font-semibold text-fg">
                        <DateText value={next.starts_at} format="long" />
                      </p>
                      <p className="text-sm text-fg">
                        <DateText value={next.starts_at} format="time" />
                        {" · "}
                        {pick(next.doctor.name_ar, next.doctor.name_en)}
                      </p>
                      <p className="text-xs text-muted">{pick(next.doctor.department_ar, next.doctor.department_en)}</p>
                    </div>
                  ) : (
                    <p className="text-sm text-muted">{t("home.noAppointment")}</p>
                  )}
                  <Button asChild variant={next ? "outline" : "default"} className="w-full">
                    <Link to="/portal/appointments/new" data-testid="home-book">
                      {t("home.book")}
                    </Link>
                  </Button>
                </PortalSection>

                <PortalSection
                  title={t("home.latestResults")}
                  testId="home-results"
                  action={
                    <Link to="/portal/results" className={viewAllClass}>
                      {t("home.viewAll")}
                      <ChevronNext className="size-4" aria-hidden="true" />
                    </Link>
                  }
                >
                  {results.length === 0 ? (
                    <p className="text-sm text-muted">{t("home.noResults")}</p>
                  ) : (
                    <ul className="flex flex-col divide-y divide-border">
                      {results.map((r) => (
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
                              <ResultStatus abnormal={r.abnormal} amended={r.amended} />
                              <ChevronNext className="size-4 text-muted" aria-hidden="true" />
                            </span>
                          </Link>
                        </li>
                      ))}
                    </ul>
                  )}
                </PortalSection>
              </div>

              <PortalSection title={t("home.balance")} testId="home-balance">
                {owes ? null : <p className="text-sm text-fg">{t("home.allPaid")}</p>}
                <dl className="divide-y divide-border">
                  <Row label={t("home.outstanding")}>
                    <MoneyText value={balance.outstanding} className="text-base font-semibold" />
                  </Row>
                  {isZeroAmount(balance.credit) ? null : (
                    <Row label={t("home.credit")}>
                      <MoneyText value={balance.credit} />
                    </Row>
                  )}
                  {isZeroAmount(balance.pending) ? null : (
                    <Row label={t("home.pending")}>
                      <MoneyText value={balance.pending} />
                    </Row>
                  )}
                </dl>
                <Link to="/portal/invoices" className={viewAllClass}>
                  {t("nav.bills")}
                  <ChevronNext className="size-4" aria-hidden="true" />
                </Link>
              </PortalSection>
            </div>
          );
        })()
      )}
    </PortalPage>
  );
}
