import { Link, useParams } from "@tanstack/react-router";
import { Printer } from "lucide-react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { DateText } from "@/components/DateText";
import { MoneyText } from "@/components/MoneyText";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useTranslateError } from "@/lib/api/translate-error";

import { useInvoice } from "../api";
import { PortalPage, PortalSection, Row } from "../components/PortalPage";
import { usePick } from "../lib/ui";

/** One invoice: the patient's share per service, what was paid and by which receipts. */
export function InvoicePage() {
  const { t } = useTranslation(["portal", "errors"]);
  const translateError = useTranslateError();
  const pick = usePick();
  const { invoiceId } = useParams({ strict: false });
  const invoice = useInvoice(Number(invoiceId));
  const title = invoice.data ? t("bills.invoice", { number: invoice.data.number }) : t("bills.invoices");

  return (
    <PortalPage
      title={title}
      back={{ to: "/portal/invoices", label: t("bills.back") }}
      actions={
        invoice.data ? (
          <Button variant="outline" onClick={() => window.print()}>
            <Printer aria-hidden="true" />
            {t("bills.print")}
          </Button>
        ) : null
      }
    >
      {invoice.isPending ? (
        <Skeleton className="h-64" />
      ) : invoice.isError ? (
        <AlertCard variant="danger" title={t("errors:title")}>
          {translateError(invoice.error)}
        </AlertCard>
      ) : (
        <>
          <PortalSection title={pick(invoice.data.center.name_ar, invoice.data.center.name_en)} testId="invoice-detail">
            <dl className="divide-y divide-border">
              {invoice.data.date ? (
                <Row label={t("bills.date")}>
                  <DateText value={invoice.data.date} />
                </Row>
              ) : null}
              <Row label={t("bills.visit")}>
                <bdi>{invoice.data.visit_number}</bdi>
              </Row>
            </dl>
            <h3 className="text-sm font-semibold text-fg">{t("bills.lines")}</h3>
            <ul className="flex flex-col divide-y divide-border">
              {invoice.data.lines.map((line, i) => (
                <li key={i} className="flex items-baseline justify-between gap-3 py-2 text-sm">
                  <span className="min-w-0 break-words text-fg">
                    {t("bills.lineQty", { name: pick(line.description_ar, line.description_en), qty: line.quantity })}
                  </span>
                  <MoneyText value={line.patient_share} />
                </li>
              ))}
            </ul>
            <dl className="divide-y divide-border border-t border-border pt-1">
              <Row label={<span className="font-semibold text-fg">{t("bills.due")}</span>}>
                <MoneyText value={invoice.data.patient_due} className="text-base" />
              </Row>
              <Row label={t("bills.paid")}>
                <MoneyText value={invoice.data.paid} />
              </Row>
              <Row label={t("bills.outstanding")}>
                <MoneyText value={invoice.data.outstanding} />
              </Row>
            </dl>
          </PortalSection>
          {invoice.data.receipts.length > 0 ? (
            <PortalSection title={t("bills.paidBy")}>
              <ul className="flex flex-col divide-y divide-border">
                {invoice.data.receipts.map((r) => (
                  <li key={r.id}>
                    <Link
                      to="/portal/receipts/$paymentId"
                      params={{ paymentId: String(r.id) }}
                      className="flex min-h-11 items-center justify-between gap-3 py-2 text-sm focus-ring-inset"
                    >
                      <span className="text-primary-strong">{t("bills.receipt", { number: r.number })}</span>
                      <MoneyText value={r.amount} />
                    </Link>
                  </li>
                ))}
              </ul>
            </PortalSection>
          ) : null}
        </>
      )}
    </PortalPage>
  );
}
