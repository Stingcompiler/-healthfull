import { Link, useParams } from "@tanstack/react-router";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { DateText } from "@/components/DateText";
import { ChevronNext } from "@/components/icons";
import { MoneyText } from "@/components/MoneyText";
import { Skeleton } from "@/components/ui/skeleton";
import { useTranslateError } from "@/lib/api/translate-error";
import { isZeroAmount } from "@/lib/format";
import { cn } from "@/lib/utils";

import { useVisitTimeline } from "../api";
import { PortalPage, Pill } from "../components/PortalPage";
import { BOOKING_TONE, ORDER_TONE, PAYMENT_TONE, VISIT_TONE } from "../lib/tones";
import { usePick } from "../lib/ui";
import type { PortalVisitTimeline } from "../types";

const linkClass =
  "inline-flex min-h-11 w-fit items-center gap-1 rounded-control px-1 text-sm font-medium text-primary-strong focus-ring";

/** One step of the timeline: a marker on the line at the start side, a title and its content. */
function Step({
  title,
  done,
  last = false,
  testId,
  children,
}: {
  title: ReactNode;
  done: boolean;
  last?: boolean;
  testId: string;
  children: ReactNode;
}) {
  return (
    <li className="relative flex gap-3 pb-6 last:pb-0" data-testid={testId} data-done={done ? "true" : undefined}>
      {last ? null : <span className="absolute start-[5px] top-5 bottom-0 w-0.5 bg-border" aria-hidden="true" />}
      {/* The step's dot on the line: filled once the step happened, hollow while it waits. */}
      <span
        className={cn(
          "relative mt-1.5 size-3 shrink-0 rounded-full border-2",
          done ? "border-primary bg-primary" : "border-border-strong bg-surface",
        )}
        aria-hidden="true"
      />
      <div className="flex min-w-0 flex-1 flex-col gap-2">
        <h2 className="text-base font-semibold text-fg">{title}</h2>
        {children}
      </div>
    </li>
  );
}

function Timeline({ visit }: { visit: PortalVisitTimeline }) {
  const { t } = useTranslation("portal");
  const pick = usePick();
  const ended = visit.status !== "open";

  return (
    <ol className="card-surface flex flex-col p-(--d-card-pad)" data-testid="visit-timeline">
      {visit.booking ? (
        <Step title={t("timeline.steps.booking")} done testId="timeline-booking">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <p className="text-sm text-fg">
              <DateText value={visit.booking.starts_at} format="long" />
              {" · "}
              <DateText value={visit.booking.starts_at} format="time" />
              <span className="block text-muted">
                {pick(visit.booking.doctor.name_ar, visit.booking.doctor.name_en)}
              </span>
            </p>
            <Pill tone={BOOKING_TONE[visit.booking.display_status]}>
              {t(`appointments.display.${visit.booking.display_status}`)}
            </Pill>
          </div>
        </Step>
      ) : null}

      <Step title={t("timeline.steps.arrived")} done testId="timeline-arrived">
        <p className="text-sm text-fg">
          <DateText value={visit.opened_at} format="datetime" />
          <span className="block text-muted">
            {[
              pick(visit.department_ar, visit.department_en),
              visit.doctor ? pick(visit.doctor.name_ar, visit.doctor.name_en) : "",
            ]
              .filter(Boolean)
              .join(" · ")}
          </span>
        </p>
      </Step>

      <Step title={t("timeline.steps.orders")} done={visit.orders.length > 0} testId="timeline-orders">
        {visit.orders.length === 0 ? (
          <p className="text-sm text-muted">{t("timeline.noOrders")}</p>
        ) : (
          <ul className="flex flex-col divide-y divide-border">
            {visit.orders.map((order) => (
              <li
                key={order.line_id}
                className="flex flex-col gap-1 py-2"
                data-testid="timeline-order"
                data-line={order.line_id}
                data-status={order.display_status}
              >
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <p className="min-w-0 text-sm">
                    <span className="block font-medium break-words text-fg">{pick(order.name_ar, order.name_en)}</span>
                    <span className="text-xs text-muted">
                      {t(`timeline.kind.${order.kind}`)}
                      {order.quantity > 1 ? ` · ${t("timeline.quantity", { count: order.quantity })}` : null}
                    </span>
                  </p>
                  <Pill tone={ORDER_TONE[order.display_status]}>{t(`timeline.order.${order.display_status}`)}</Pill>
                </div>
                {order.result_line_id !== null ? (
                  <Link
                    to="/portal/results/$lineId"
                    params={{ lineId: String(order.result_line_id) }}
                    className={linkClass}
                    data-testid="timeline-open-result"
                  >
                    {t("timeline.openResult")}
                    <ChevronNext className="size-4" aria-hidden="true" />
                  </Link>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </Step>

      <Step title={t("timeline.steps.payments")} done={visit.invoices.length > 0} testId="timeline-payments">
        {visit.invoices.length === 0 ? (
          <p className="text-sm text-muted">{t("timeline.noInvoices")}</p>
        ) : (
          <ul className="flex flex-col divide-y divide-border">
            {visit.invoices.map((invoice) => (
              <li
                key={invoice.id}
                className="flex flex-col gap-1 py-2"
                data-testid="timeline-invoice"
                data-status={invoice.display_status}
              >
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <p className="min-w-0 text-sm text-fg">
                    <span className="block font-medium">{t("bills.invoice", { number: invoice.number })}</span>
                    <span className="text-xs text-muted">
                      {t("timeline.yourShare")} <MoneyText value={invoice.patient_due} />
                    </span>
                    {isZeroAmount(invoice.outstanding) ? null : (
                      <span className="block text-xs text-muted">
                        {t("timeline.outstanding")} <MoneyText value={invoice.outstanding} />
                      </span>
                    )}
                  </p>
                  <Pill tone={PAYMENT_TONE[invoice.display_status]}>
                    {t(`timeline.payment.${invoice.display_status}`)}
                  </Pill>
                </div>
                <Link
                  to="/portal/invoices/$invoiceId"
                  params={{ invoiceId: String(invoice.id) }}
                  className={linkClass}
                  data-testid="timeline-open-invoice"
                >
                  {t("timeline.openInvoice")}
                  <ChevronNext className="size-4" aria-hidden="true" />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Step>

      <Step title={t("timeline.steps.end")} done={ended} last testId="timeline-end">
        <p className="text-sm text-fg">
          {visit.status === "open"
            ? t("timeline.endOpen")
            : visit.status === "cancelled"
              ? t("timeline.endCancelled")
              : t("timeline.endClosed")}
          {visit.closed_at ? (
            <span className="block text-xs text-muted">
              <DateText value={visit.closed_at} format="datetime" />
            </span>
          ) : null}
        </p>
      </Step>
    </ol>
  );
}

/** One visit as a timeline (public site Phase 5, plan section 5): what the patient sees only. */
export function VisitTimelinePage() {
  const { t } = useTranslation(["portal", "errors"]);
  const translateError = useTranslateError();
  const { visitId } = useParams({ strict: false });
  const visit = useVisitTimeline(Number(visitId));
  const title = visit.data ? t("timeline.title", { number: visit.data.number }) : t("timeline.titleShort");

  return (
    <PortalPage
      title={title}
      back={{ to: "/portal/appointments", label: t("timeline.back") }}
      description={
        visit.data ? (
          <span className="flex flex-wrap items-center gap-2">
            <Pill tone={VISIT_TONE[visit.data.display_status]} testId="visit-status">
              {t(`timeline.visit.${visit.data.display_status}`)}
            </Pill>
            <DateText value={visit.data.opened_at} format="long" />
          </span>
        ) : null
      }
    >
      {visit.isPending ? (
        <Skeleton className="h-96" />
      ) : visit.isError ? (
        <AlertCard variant="danger" title={t("errors:title")}>
          {translateError(visit.error)}
        </AlertCard>
      ) : (
        <Timeline visit={visit.data} />
      )}
    </PortalPage>
  );
}
