import { Banknote, Clock3, Landmark, Scale } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { DateText } from "@/components/DateText";
import { KpiCard } from "@/components/KpiCard";
import { MoneyText } from "@/components/MoneyText";
import { StatusBadge } from "@/components/StatusBadge";
import { Badge } from "@/components/ui/badge";

import { negate } from "../lib/money";
import { useNames } from "../lib/use-names";
import type { ShiftReport } from "../types";

function Row({
  label,
  value,
  strong = false,
  testId,
}: {
  label: ReactNode;
  value: string;
  strong?: boolean;
  testId?: string;
}) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1" data-testid={testId}>
      <dt className="text-muted">{label}</dt>
      <dd className={strong ? "font-semibold" : undefined}>
        <MoneyText value={value} toneNegative />
      </dd>
    </div>
  );
}

function Block({ title, children, testId }: { title: ReactNode; children: ReactNode; testId?: string }) {
  return (
    <section className="card-surface flex min-w-0 flex-col gap-2 p-4 md:p-5" data-testid={testId}>
      <h3 className="text-base font-semibold">{title}</h3>
      {children}
    </section>
  );
}

/**
 * A shift report (FLOW 9, FEATURES 7.3): cash, confirmed bank money and pending transfers
 * apart (pending money is never shown as collected), discounts by approver, cancellations,
 * refunds and handovers. A closed shift's report is the snapshot taken at close.
 */
export function ShiftReportView({ report }: { report: ShiftReport }) {
  const { t } = useTranslation("cashier");
  const names = useNames();
  const s = report.shift;
  const m = report.movements;
  const c = report.collection;
  const closed = s.status === "closed";

  return (
    <div className="flex min-w-0 flex-col gap-4" data-testid="shift-report" data-frozen={report.frozen}>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted">
        <span className="flex items-center gap-2 text-base font-semibold text-fg">
          <bdi>{s.number}</bdi>
          <Badge variant={closed ? "neutral" : "success"}>{t(`shift.status.${s.status}`)}</Badge>
          {s.review ? (
            <Badge variant={s.review.outcome === "approved" ? "success" : "danger"}>
              {t(`review.outcome.${s.review.outcome}`)}
            </Badge>
          ) : null}
        </span>
        <span>{names.user(s.cashier)}</span>
        <span>
          {t("shift.openedAt")} <DateText value={s.opened_at} format="datetime" />
        </span>
        {s.closed_at ? (
          <span>
            {t("shift.closedAt")} <DateText value={s.closed_at} format="datetime" />
          </span>
        ) : null}
        {s.till ? <span>{names.name(s.till)}</span> : null}
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard
          label={t("report.expectedCash")}
          value={<MoneyText value={report.expected_cash} />}
          icon={<Banknote />}
          headingLevel="h3"
        />
        <KpiCard
          label={t("report.counted")}
          value={report.counted_cash !== null ? <MoneyText value={report.counted_cash} /> : t("report.notCounted")}
          hint={
            report.variance !== null ? (
              <span data-testid="report-variance">
                {t("report.variance")} <MoneyText value={report.variance} signed toneNegative />
              </span>
            ) : undefined
          }
          icon={<Scale />}
          tone={report.variance !== null && report.variance !== "0.00" ? "warning" : "primary"}
          headingLevel="h3"
        />
        <KpiCard
          label={t("report.confirmedTotal")}
          value={<MoneyText value={c.confirmed_total} />}
          icon={<Landmark />}
          tone="success"
          headingLevel="h3"
        />
        <KpiCard
          label={t("report.bankPending")}
          value={
            <span data-testid="report-bank-pending">
              <MoneyText value={c.bank_pending} />
            </span>
          }
          hint={t("report.pendingHint")}
          icon={<Clock3 />}
          tone={c.bank_pending !== "0.00" ? "warning" : "info"}
          headingLevel="h3"
        />
      </div>

      {s.variance_reason ? (
        <p className="text-sm">
          <span className="font-medium">{t("report.varianceReason")}</span> {names.label(s.variance_reason)}
          {s.variance_note ? ` · ${s.variance_note}` : ""}
        </p>
      ) : null}

      <div className="grid min-w-0 gap-4 lg:grid-cols-2">
        <Block title={t("report.cashTitle")}>
          <dl className="divide-y divide-border text-sm">
            <Row label={t("report.openingFloat")} value={m.opening_float} />
            <Row label={t("report.cashIn")} value={m.cash_in} />
            <Row label={t("report.cashRefunds")} value={negate(m.cash_refunds)} />
            <Row label={t("report.handoversOut")} value={negate(m.handovers_out)} />
            <Row label={t("report.handoversIn")} value={m.handovers_in} />
            <Row label={t("report.expectedCash")} value={report.expected_cash} strong />
          </dl>
        </Block>
        <Block title={t("report.collectionTitle")} testId="report-collection">
          <dl className="divide-y divide-border text-sm">
            <Row label={t("report.cashConfirmed")} value={c.cash_confirmed} />
            <Row label={t("report.bankConfirmed")} value={c.bank_confirmed} />
            <Row label={t("report.creditUsed")} value={c.credit_used} />
            <Row label={t("report.confirmedTotal")} value={c.confirmed_total} strong testId="report-confirmed-total" />
            <Row label={t("report.bankPending")} value={c.bank_pending} />
            <Row label={t("report.bankRejected")} value={c.bank_rejected} />
            <Row
              label={t("report.lateReversals")}
              value={negate(report.late_reversals)}
              testId="report-late-reversals"
            />
            <Row label={t("report.lateConfirmations")} value={report.late_confirmations} />
          </dl>
        </Block>
      </div>

      {report.pending.length === 0 ? null : (
        <Block title={t("report.pendingTitle", { count: report.pending.length })} testId="report-pending">
          <ul className="flex flex-col divide-y divide-border text-sm">
            {report.pending.map((p) => (
              <li key={p.payment_id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                <span className="flex flex-wrap items-center gap-2">
                  <bdi className="font-medium">{p.number}</bdi>
                  <StatusBadge status="pending_verification" size="sm" />
                  <span className="text-muted">
                    <bdi>{p.bank}</bdi> · <bdi>{p.reference}</bdi>
                  </span>
                  {p.age_days !== null ? (
                    <span className="text-muted">{t("report.ageDays", { count: p.age_days })}</span>
                  ) : null}
                </span>
                <MoneyText value={p.amount} />
              </li>
            ))}
          </ul>
        </Block>
      )}

      <div className="grid min-w-0 gap-4 lg:grid-cols-2">
        <Block title={t("report.confirmedTitle")}>
          {report.confirmed_transfers.length === 0 ? (
            <p className="text-sm text-muted">{t("report.none")}</p>
          ) : (
            <ul className="flex flex-col divide-y divide-border text-sm">
              {report.confirmed_transfers.map((p) => (
                <li key={p.payment_id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                  <span className="flex flex-wrap items-center gap-2">
                    <bdi>{p.number}</bdi>
                    <span className="text-muted">
                      <bdi>{p.bank}</bdi> · <bdi>{p.reference}</bdi>
                    </span>
                  </span>
                  <MoneyText value={p.amount} />
                </li>
              ))}
            </ul>
          )}
        </Block>
        <Block title={t("report.discountsTitle")}>
          {report.discounts.length === 0 ? (
            <p className="text-sm text-muted">{t("report.none")}</p>
          ) : (
            <dl className="divide-y divide-border text-sm">
              {report.discounts.map((d, i) => (
                <Row key={d.user?.id ?? i} label={names.user(d.user)} value={d.amount} />
              ))}
            </dl>
          )}
        </Block>
        <Block title={t("report.cancellationsTitle")} testId="report-cancellations">
          <dl className="divide-y divide-border text-sm">
            <Row label={t("report.creditNotes")} value={report.credit_notes} />
            {report.cancellations.map((r) => (
              <Row
                key={r.code}
                label={`${r.reason ? names.label(r.reason) : r.code} (${String(r.count)})`}
                value={r.amount}
              />
            ))}
            <Row label={t("report.creditFromCancellations")} value={report.credit_from_cancellations} />
            <Row label={t("report.creditUnallocated")} value={report.credit_unallocated} />
          </dl>
          {/* Desk cancellations before invoicing (FLOW 4) and voided drafts: no money moved,
              but the manager reviews them with the shift (FLOW 9). */}
          <h4 className="pt-2 text-sm font-medium">{t("report.lineCancellations")}</h4>
          {report.line_cancellations.length === 0 ? (
            <p className="text-sm text-muted">{t("report.none")}</p>
          ) : (
            <dl className="divide-y divide-border text-sm" data-testid="report-line-cancellations">
              {report.line_cancellations.map((r) => (
                <div key={r.code} className="flex items-baseline justify-between gap-3 py-1">
                  <dt className="min-w-0 text-muted">{r.reason ? names.label(r.reason) : r.code}</dt>
                  <dd className="tabular">{t("report.lineCount", { count: r.count })}</dd>
                </div>
              ))}
            </dl>
          )}
          <h4 className="pt-2 text-sm font-medium">{t("report.voidedDrafts")}</h4>
          {report.voided_drafts.length === 0 ? (
            <p className="text-sm text-muted">{t("report.none")}</p>
          ) : (
            <ul className="flex flex-col divide-y divide-border text-sm" data-testid="report-voided-drafts">
              {report.voided_drafts.map((v) => (
                <li key={v.invoice_id} className="flex flex-wrap items-baseline justify-between gap-2 py-1">
                  <span className="min-w-0 break-words text-muted">
                    {t("report.voidedDraftNote", { note: v.note })}
                  </span>
                  <MoneyText value={v.amount} />
                </li>
              ))}
            </ul>
          )}
        </Block>
        <Block title={t("report.refundsTitle")}>
          <dl className="divide-y divide-border text-sm">
            {report.refunds.map((r) => (
              <Row
                key={r.code}
                label={`${r.reason ? names.label(r.reason) : r.code} (${String(r.count)})`}
                value={r.amount}
              />
            ))}
            <Row label={t("report.refundsPaid")} value={report.refunds_paid} strong />
          </dl>
        </Block>
      </div>

      <Block title={t("report.handoversTitle")}>
        {report.handovers.length === 0 ? (
          <p className="text-sm text-muted">{t("report.none")}</p>
        ) : (
          <ul className="flex flex-col divide-y divide-border text-sm">
            {report.handovers.map((h) => (
              <li key={h.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                <span className="flex flex-wrap items-center gap-2">
                  <bdi>{h.number}</bdi>
                  <span>{t(`handover.destination.${h.destination}`)}</span>
                  {h.to_shift_number ? <bdi className="text-muted">{h.to_shift_number}</bdi> : null}
                  {h.to_user && h.destination !== "next_shift" ? (
                    <span className="text-muted">{names.user(h.to_user)}</span>
                  ) : null}
                  {/* Cash is in transit until someone else confirms it, whatever the destination. */}
                  <Badge variant={h.cancelled_at ? "neutral" : h.received_at ? "success" : "warning"}>
                    {h.cancelled_at
                      ? t("handover.state.cancelled")
                      : h.received_at
                        ? t("handover.state.received", { name: names.user(h.received_by) })
                        : t("handover.state.inTransit")}
                  </Badge>
                </span>
                <MoneyText value={h.shift_id === s.id ? negate(h.amount) : h.amount} toneNegative />
              </li>
            ))}
          </ul>
        )}
      </Block>

      {s.review ? (
        <Block title={t("review.title")}>
          <p className="text-sm">
            {t(`review.outcome.${s.review.outcome}`)} · {names.user(s.review.reviewed_by)} ·{" "}
            <DateText value={s.review.reviewed_at} format="datetime" />
          </p>
          {s.review.note ? <p className="text-sm text-muted">{s.review.note}</p> : null}
        </Block>
      ) : null}
    </div>
  );
}
