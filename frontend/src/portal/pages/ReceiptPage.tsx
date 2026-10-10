import { Link, useParams } from "@tanstack/react-router";
import { Printer } from "lucide-react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { DateText } from "@/components/DateText";
import { MoneyText } from "@/components/MoneyText";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useTranslateError } from "@/lib/api/translate-error";

import { useReceipt } from "../api";
import { PortalPage, PortalSection, Pill, Row } from "../components/PortalPage";
import { RECEIPT_TONE } from "../lib/tones";
import { usePick } from "../lib/ui";

/** One receipt of the patient: amount, status and the invoices it paid. */
export function ReceiptPage() {
  const { t } = useTranslation(["portal", "errors"]);
  const translateError = useTranslateError();
  const pick = usePick();
  const { paymentId } = useParams({ strict: false });
  const receipt = useReceipt(Number(paymentId));
  const title = receipt.data ? t("bills.receipt", { number: receipt.data.number }) : t("bills.receipts");

  return (
    <PortalPage
      title={title}
      back={{ to: "/portal/invoices", label: t("bills.back") }}
      actions={
        receipt.data ? (
          <Button variant="outline" onClick={() => window.print()}>
            <Printer aria-hidden="true" />
            {t("bills.print")}
          </Button>
        ) : null
      }
    >
      {receipt.isPending ? (
        <Skeleton className="h-48" />
      ) : receipt.isError ? (
        <AlertCard variant="danger" title={t("errors:title")}>
          {translateError(receipt.error)}
        </AlertCard>
      ) : (
        <PortalSection
          title={pick(receipt.data.center.name_ar, receipt.data.center.name_en)}
          action={<Pill tone={RECEIPT_TONE[receipt.data.status]}>{t(`bills.status.${receipt.data.status}`)}</Pill>}
          testId="receipt-detail"
        >
          <dl className="divide-y divide-border">
            <Row label={t("bills.date")}>
              <DateText value={receipt.data.date} />
            </Row>
            <Row label={t("bills.method")}>{t(`bills.methods.${receipt.data.method as "cash"}`)}</Row>
            <Row label={<span className="font-semibold text-fg">{t("bills.amount")}</span>}>
              <MoneyText value={receipt.data.amount} className="text-base" />
            </Row>
          </dl>
          {receipt.data.invoices.length > 0 ? (
            <>
              <h3 className="text-sm font-semibold text-fg">{t("bills.paidFor")}</h3>
              <ul className="flex flex-col divide-y divide-border">
                {receipt.data.invoices.map((inv) => (
                  <li key={inv.id}>
                    <Link
                      to="/portal/invoices/$invoiceId"
                      params={{ invoiceId: String(inv.id) }}
                      className="flex min-h-11 items-center justify-between gap-3 py-2 text-sm focus-ring-inset"
                    >
                      <bdi className="whitespace-nowrap text-primary-strong">{inv.number}</bdi>
                      <MoneyText value={inv.amount} />
                    </Link>
                  </li>
                ))}
              </ul>
            </>
          ) : null}
          {receipt.data.to_credit !== "0.00" ? (
            <dl>
              <Row label={t("bills.toCredit")}>
                <MoneyText value={receipt.data.to_credit} />
              </Row>
            </dl>
          ) : null}
        </PortalSection>
      )}
    </PortalPage>
  );
}
