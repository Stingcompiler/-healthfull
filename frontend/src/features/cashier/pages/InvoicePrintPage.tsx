import { Link, useParams } from "@tanstack/react-router";
import { FileText } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { DateText } from "@/components/DateText";
import { ArrowBack } from "@/components/icons";
import { MoneyText } from "@/components/MoneyText";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useTranslateError } from "@/lib/api/translate-error";

import { useInvoicePrint } from "../api";
import { PrintFrame, type PrintFormat } from "../components/PrintFrame";
import { useNames } from "../lib/use-names";
import type { InvoicePrint } from "../types";
import { DocHeader } from "./ReceiptPage";

function Line({ label, value, strong = false }: { label: ReactNode; value: string; strong?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <dt className={strong ? "font-semibold" : "text-muted"}>{label}</dt>
      <dd className={strong ? "font-semibold" : undefined}>
        <MoneyText value={value} />
      </dd>
    </div>
  );
}

function InvoiceBody({ data, format }: { data: InvoicePrint; format: PrintFormat }) {
  const { t } = useTranslation(["cashier", "common"]);
  const names = useNames();
  const inv = data.invoice;
  const thermal = format === "thermal";
  return (
    <div className="flex flex-col gap-3" data-testid="invoice-print">
      <DocHeader center={data.center} title={t("invoicePrint.title")} format={format} />
      <dl className="grid gap-0.5">
        <div className="flex justify-between gap-2">
          <dt className="text-muted">{t("invoicePrint.number")}</dt>
          <dd>
            <bdi>{inv.number}</bdi>
          </dd>
        </div>
        {inv.approved_at ? (
          <div className="flex justify-between gap-2">
            <dt className="text-muted">{t("receipt.date")}</dt>
            <dd>
              <DateText value={inv.approved_at} format="datetime" />
            </dd>
          </div>
        ) : null}
        <div className="flex justify-between gap-2">
          <dt className="text-muted">{t("receipt.patient")}</dt>
          <dd>{names.patient(inv.patient)}</dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-muted">{t("common:patient.fileNo")}</dt>
          <dd>
            <bdi>{inv.patient.file_no}</bdi>
          </dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-muted">{t("billing.visit")}</dt>
          <dd>
            <bdi>{inv.visit_number}</bdi>
          </dd>
        </div>
      </dl>
      {thermal ? (
        <ul className="flex flex-col gap-1.5 border-t border-border pt-2">
          {inv.lines.map((l) => (
            <li key={l.id} className="flex flex-col">
              <span className="font-medium">
                {t("receipt.lineQty", { name: names.text(l.description_ar, l.description_en), qty: l.quantity })}
              </span>
              {l.discount !== "0.00" ? (
                <span className="flex justify-between gap-2">
                  <span>{t("invoice.discount")}</span>
                  <MoneyText value={l.discount} />
                </span>
              ) : null}
              {l.payer ? (
                <span className="flex justify-between gap-2">
                  <span className="min-w-0">
                    {t("invoice.payerShare")} ({names.name(l.payer)})
                  </span>
                  <MoneyText value={l.payer_share} />
                </span>
              ) : null}
              <span className="flex justify-between gap-2 font-semibold">
                <span>{t("invoice.patientShare")}</span>
                <MoneyText value={l.patient_share} />
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <div className="min-w-0 overflow-x-auto">
          <table className="w-full border-collapse text-start">
            <thead>
              <tr className="border-b border-border text-muted">
                <th className="py-1 text-start font-medium">{t("invoice.service")}</th>
                <th className="py-1 text-end font-medium">{t("invoice.qty")}</th>
                <th className="py-1 text-end font-medium">{t("invoice.unitPrice")}</th>
                <th className="py-1 text-end font-medium">{t("invoice.discount")}</th>
                <th className="py-1 text-end font-medium">{t("invoice.payerShare")}</th>
                <th className="py-1 text-end font-medium">{t("invoice.patientShare")}</th>
              </tr>
            </thead>
            <tbody>
              {inv.lines.map((l) => (
                <tr key={l.id} className="border-b border-border">
                  <td className="py-1">
                    {names.text(l.description_ar, l.description_en)}
                    {l.payer ? <span className="block text-xs text-muted">{names.name(l.payer)}</span> : null}
                  </td>
                  <td className="py-1 text-end tabular">{l.quantity}</td>
                  <td className="py-1 text-end">
                    <MoneyText value={l.unit_price} currency={false} />
                  </td>
                  <td className="py-1 text-end">
                    <MoneyText value={l.discount} currency={false} />
                  </td>
                  <td className="py-1 text-end">
                    <MoneyText value={l.payer_share} currency={false} />
                  </td>
                  <td className="py-1 text-end">
                    <MoneyText value={l.patient_share} currency={false} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <dl className="ms-auto grid w-full max-w-72 gap-0.5 border-t border-border pt-2">
        <Line label={t("invoice.grossTotal")} value={inv.gross_total} />
        <Line label={t("invoice.discountTotal")} value={inv.discount_total} />
        <Line label={t("invoice.payerTotal")} value={inv.payer_total} />
        <Line label={t("invoice.patientTotal")} value={inv.patient_total} strong />
        {inv.paid !== null ? <Line label={t("invoice.paid")} value={inv.paid} /> : null}
        {inv.outstanding !== null ? <Line label={t("invoice.outstanding")} value={inv.outstanding} strong /> : null}
      </dl>
      <p className="text-center text-xs text-muted">{t("invoicePrint.payerNote")}</p>
    </div>
  );
}

/** An approved invoice for A4 or 80 mm printing (FEATURES 0.10). */
export function InvoicePrintPage() {
  const { t } = useTranslation(["cashier", "errors"]);
  const translateError = useTranslateError();
  const { invoiceId } = useParams({ strict: false });
  const data = useInvoicePrint(Number(invoiceId));
  return (
    <div className="flex min-w-0 flex-col gap-4">
      <PageHeader
        title={t("invoicePrint.pageTitle")}
        description={t("invoicePrint.pageDescription")}
        icon={<FileText />}
        className="print:hidden"
        actions={
          <Button asChild variant="outline">
            <Link to="/cashier" search={data.data ? { visit: data.data.invoice.visit_id } : {}}>
              <ArrowBack aria-hidden="true" />
              {t("receipt.back")}
            </Link>
          </Button>
        }
      />
      {data.isPending ? (
        <Skeleton className="mx-auto h-96 w-full max-w-[80mm]" />
      ) : data.isError ? (
        <AlertCard variant="danger" title={t("errors:title")}>
          {translateError(data.error)}
        </AlertCard>
      ) : (
        <PrintFrame>{(format) => <InvoiceBody data={data.data} format={format} />}</PrintFrame>
      )}
    </div>
  );
}
