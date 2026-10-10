import { Link } from "@tanstack/react-router";
import { ReceiptText } from "lucide-react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { DateText } from "@/components/DateText";
import { EmptyState } from "@/components/EmptyState";
import { ChevronNext } from "@/components/icons";
import { MoneyText } from "@/components/MoneyText";
import { Skeleton } from "@/components/ui/skeleton";
import { useTranslateError } from "@/lib/api/translate-error";

import { useBalance, useInvoices, useReceipts } from "../api";
import { PortalPage, PortalSection, Pill, Row } from "../components/PortalPage";
import { RECEIPT_TONE } from "../lib/tones";

/** Bills: the balance, the patient's share of each invoice, and every receipt. */
export function InvoicesPage() {
  const { t } = useTranslation(["portal", "errors"]);
  const translateError = useTranslateError();
  const balance = useBalance();
  const invoices = useInvoices();
  const receipts = useReceipts();

  return (
    <PortalPage title={t("bills.title")} description={t("bills.description")}>
      <PortalSection title={t("home.balance")} testId="bills-balance">
        {balance.isPending ? (
          <Skeleton className="h-16" />
        ) : balance.isError ? (
          <AlertCard variant="danger" title={translateError(balance.error)} />
        ) : (
          <dl className="divide-y divide-border">
            <Row label={t("home.outstanding")}>
              <MoneyText value={balance.data.outstanding} className="text-base" />
            </Row>
            {balance.data.credit !== "0.00" ? (
              <Row label={t("home.credit")}>
                <MoneyText value={balance.data.credit} />
              </Row>
            ) : null}
            {balance.data.pending !== "0.00" ? (
              <Row label={t("home.pending")}>
                <MoneyText value={balance.data.pending} />
              </Row>
            ) : null}
          </dl>
        )}
      </PortalSection>

      <PortalSection title={t("bills.invoices")} testId="bills-invoices">
        {invoices.isPending ? (
          <Skeleton className="h-24" />
        ) : invoices.isError ? (
          <AlertCard variant="danger" title={translateError(invoices.error)} />
        ) : invoices.data.length === 0 ? (
          <EmptyState bare size="compact" icon={<ReceiptText />} title={t("bills.noInvoices")} />
        ) : (
          <ul className="-mx-4 divide-y divide-border md:-mx-5">
            {invoices.data.map((inv) => (
              <li key={inv.id}>
                <Link
                  to="/portal/invoices/$invoiceId"
                  params={{ invoiceId: String(inv.id) }}
                  data-testid="invoice-row"
                  className="flex min-h-14 items-center justify-between gap-3 px-4 py-3 focus-ring-inset md:px-5"
                >
                  <span className="min-w-0">
                    <bdi className="block font-medium whitespace-nowrap text-fg">{inv.number}</bdi>
                    {inv.date ? (
                      <span className="text-xs text-muted">
                        <DateText value={inv.date} />
                      </span>
                    ) : null}
                  </span>
                  <span className="flex shrink-0 items-center gap-2">
                    <span className="flex flex-col items-end">
                      <MoneyText value={inv.patient_due} />
                      {inv.outstanding !== "0.00" ? (
                        <span className="text-xs text-warning-fg">
                          {t("bills.outstanding")}: <MoneyText value={inv.outstanding} />
                        </span>
                      ) : null}
                    </span>
                    <ChevronNext className="size-4 text-muted" aria-hidden="true" />
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </PortalSection>

      <PortalSection title={t("bills.receipts")} testId="bills-receipts">
        {receipts.isPending ? (
          <Skeleton className="h-24" />
        ) : receipts.isError ? (
          <AlertCard variant="danger" title={translateError(receipts.error)} />
        ) : receipts.data.length === 0 ? (
          <p className="text-sm text-muted">{t("bills.noReceipts")}</p>
        ) : (
          <ul className="-mx-4 divide-y divide-border md:-mx-5">
            {receipts.data.map((r) => (
              <li key={r.id}>
                <Link
                  to="/portal/receipts/$paymentId"
                  params={{ paymentId: String(r.id) }}
                  data-testid="receipt-row"
                  className="flex min-h-14 items-center justify-between gap-3 px-4 py-3 focus-ring-inset md:px-5"
                >
                  <span className="min-w-0">
                    <bdi className="block font-medium whitespace-nowrap text-fg">{r.number}</bdi>
                    <span className="text-xs text-muted">
                      <DateText value={r.date} />
                      {" · "}
                      {t(`bills.methods.${r.method as "cash"}`)}
                    </span>
                  </span>
                  <span className="flex shrink-0 items-center gap-2">
                    <span className="flex flex-col items-end gap-1">
                      <MoneyText value={r.amount} />
                      {r.status !== "valid" ? (
                        <Pill tone={RECEIPT_TONE[r.status]}>{t(`bills.status.${r.status}`)}</Pill>
                      ) : null}
                    </span>
                    <ChevronNext className="size-4 text-muted" aria-hidden="true" />
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </PortalSection>
    </PortalPage>
  );
}
