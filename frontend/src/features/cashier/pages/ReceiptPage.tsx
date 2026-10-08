import { Link, useParams } from "@tanstack/react-router";
import { ReceiptText } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { DateText } from "@/components/DateText";
import { ArrowBack } from "@/components/icons";
import { MoneyText } from "@/components/MoneyText";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useTranslateError } from "@/lib/api/translate-error";
import { cn } from "@/lib/utils";

import { useReceipt } from "../api";
import { PrintFrame, type PrintFormat } from "../components/PrintFrame";
import { QrCode } from "../components/QrCode";
import { useNames } from "../lib/use-names";
import type { Center, Receipt } from "../types";

export function DocHeader({ center, title, format }: { center: Center; title: ReactNode; format: PrintFormat }) {
  const names = useNames();
  return (
    <header className={cn("flex flex-col gap-0.5 border-b border-border pb-2", format === "thermal" ? "text-center" : "")}>
      <p className={cn("font-semibold", format === "thermal" ? "text-[14px]" : "text-lg")}>
        {names.text(center.name_ar, center.name_en)}
      </p>
      {center.address ? <p>{center.address}</p> : null}
      {center.phone ? (
        <p>
          <bdi>{center.phone}</bdi>
        </p>
      ) : null}
      <p className={cn("mt-1 font-semibold", format === "thermal" ? "" : "text-base")}>{title}</p>
    </header>
  );
}

function Line({ label, value }: { label: ReactNode; value: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <dt className="text-muted">{label}</dt>
      <dd className="text-end">{value}</dd>
    </div>
  );
}

function ReceiptBody({ receipt, format }: { receipt: Receipt; format: PrintFormat }) {
  const { t } = useTranslation(["cashier", "common"]);
  const names = useNames();
  const p = receipt.payment;
  const pending = p.verification === "pending";
  return (
    <div className="flex flex-col gap-3" data-testid="receipt">
      <DocHeader center={receipt.center} title={t("receipt.title")} format={format} />
      <dl className="grid gap-0.5">
        <Line label={t("receipt.number")} value={<bdi data-testid="receipt-number">{p.number}</bdi>} />
        <Line label={t("receipt.date")} value={<DateText value={p.created_at} format="datetime" />} />
        <Line label={t("receipt.patient")} value={names.patient(p.patient)} />
        <Line label={t("common:patient.fileNo")} value={<bdi>{p.patient.file_no}</bdi>} />
        <Line label={t("receipt.method")} value={t(`payment.method.${p.method}`)} />
        {p.bank ? <Line label={t("payment.bank")} value={names.name(p.bank)} /> : null}
        {p.reference ? <Line label={t("payment.reference")} value={<bdi>{p.reference}</bdi>} /> : null}
        <Line label={t("receipt.cashier")} value={names.user(receipt.cashier)} />
      </dl>
      {pending ? (
        <p className="flex flex-wrap items-center gap-2 rounded-control border border-warning-border p-2">
          <StatusBadge status="pending_verification" size="sm" withHint={false} />
          {t("receipt.pendingNote")}
        </p>
      ) : null}
      {receipt.invoices.map((inv) => (
        <section key={inv.id} className="flex flex-col gap-1 border-t border-border pt-2">
          <p className="font-semibold">
            {t("receipt.invoice")} <bdi>{inv.number}</bdi>
          </p>
          <ul className="flex flex-col gap-0.5">
            {inv.lines.map((l, i) => (
              <li key={i} className="flex items-baseline justify-between gap-2">
                <span className="min-w-0 break-words">
                  {t("receipt.lineQty", { name: names.text(l.description_ar, l.description_en), qty: l.quantity })}
                </span>
                <MoneyText value={l.patient_share} currency={false} />
              </li>
            ))}
          </ul>
          <dl className="grid gap-0.5">
            <Line label={t("receipt.applied")} value={<MoneyText value={inv.amount} />} />
            <Line label={t("receipt.remaining")} value={<MoneyText value={inv.outstanding} />} />
          </dl>
        </section>
      ))}
      <dl className="grid gap-0.5 border-t border-border pt-2">
        <Line
          label={<span className="font-semibold text-fg">{t("receipt.total")}</span>}
          value={<MoneyText value={p.amount} className={format === "thermal" ? "text-[14px]" : "text-lg"} />}
        />
        {p.unallocated !== "0.00" ? (
          <Line label={t("receipt.toCredit")} value={<MoneyText value={p.unallocated} />} />
        ) : null}
      </dl>
      <div className="flex flex-col items-center gap-1 border-t border-border pt-3">
        <QrCode value={receipt.verify_code} label={t("receipt.qrLabel")} className={format === "thermal" ? "size-32" : "size-36"} />
        <bdi className="text-[10px] break-all text-muted">{receipt.verify_code}</bdi>
        <p className="text-center text-[11px] text-muted">{t("receipt.verifyHint")}</p>
      </div>
    </div>
  );
}

/** A payment receipt for the 80 mm thermal printer or A4 (FEATURES 6.9), with its QR code. */
export function ReceiptPage() {
  const { t } = useTranslation(["cashier", "errors"]);
  const translateError = useTranslateError();
  const { paymentId } = useParams({ strict: false });
  const receipt = useReceipt(Number(paymentId));

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <PageHeader
        title={t("receipt.pageTitle")}
        description={t("receipt.pageDescription")}
        icon={<ReceiptText />}
        className="print:hidden"
        actions={
          <Button asChild variant="outline">
            <Link to="/cashier">
              <ArrowBack aria-hidden="true" />
              {t("receipt.back")}
            </Link>
          </Button>
        }
      />
      {receipt.isPending ? (
        <Skeleton className="mx-auto h-96 w-full max-w-[80mm]" />
      ) : receipt.isError ? (
        <AlertCard variant="danger" title={t("errors:title")}>
          {translateError(receipt.error)}
        </AlertCard>
      ) : (
        <PrintFrame>{(format) => <ReceiptBody receipt={receipt.data} format={format} />}</PrintFrame>
      )}
    </div>
  );
}
