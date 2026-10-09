import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import { ReceiptText, ScanLine } from "lucide-react";
import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { DateText } from "@/components/DateText";
import { MoneyText } from "@/components/MoneyText";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { isApiError } from "@/lib/api/errors";
import { useTranslateError } from "@/lib/api/translate-error";

import { useReceiptCheck } from "../api";
import { CashierNav } from "../components/CashierNav";
import { parseCashierSearch } from "../lib/search";
import { useNames } from "../lib/use-names";
import type { ReceiptCheck } from "../types";

const STANDING_VARIANT = {
  valid: "success",
  pending: "warning",
  rejected: "danger",
  reversed: "danger",
  mismatch: "danger",
} as const;

function Row({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 py-1.5">
      <dt className="text-muted">{label}</dt>
      <dd className="min-w-0 text-end break-words">{children}</dd>
    </div>
  );
}

function CheckResult({ check }: { check: ReceiptCheck }) {
  const { t } = useTranslation(["cashier", "common"]);
  const names = useNames();
  const p = check.payment;
  return (
    <div className="flex min-w-0 flex-col gap-4" data-testid="receipt-check-result" data-standing={check.standing}>
      <AlertCard variant={STANDING_VARIANT[check.standing]} title={t(`receiptCheck.standing.${check.standing}`)} live>
        {t(`receiptCheck.standingHint.${check.standing}`, {
          number: p.reversal_number ?? p.reversal_of_number ?? "",
        })}
      </AlertCard>
      <section className="card-surface flex min-w-0 flex-col gap-2 p-4 md:p-5" aria-labelledby="receipt-check-title">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 id="receipt-check-title" className="text-base font-semibold">
            {t("receipt.number")} <bdi>{p.number}</bdi>
          </h2>
          <Button asChild variant="outline" size="sm">
            <Link to="/cashier/receipts/$paymentId" params={{ paymentId: String(p.id) }}>
              <ReceiptText aria-hidden="true" />
              {t("receiptCheck.openReceipt")}
            </Link>
          </Button>
        </div>
        <dl className="divide-y divide-border text-sm">
          <Row label={t("receipt.total")}>
            <MoneyText value={p.amount} className="font-semibold" />
          </Row>
          {check.standing === "mismatch" && check.code_amount && check.code_amount !== p.amount ? (
            <Row label={t("receiptCheck.codeAmount")}>
              <MoneyText value={check.code_amount} className="text-danger-fg" />
            </Row>
          ) : null}
          <Row label={t("receipt.date")}>
            <DateText value={p.created_at} format="datetime" />
          </Row>
          {check.standing === "mismatch" && check.code_day && check.code_day !== check.day ? (
            <Row label={t("receiptCheck.codeDay")}>
              <span className="text-danger-fg">
                <DateText value={check.code_day} format="date" />
              </span>
            </Row>
          ) : null}
          <Row label={t("receipt.patient")}>{names.patient(p.patient)}</Row>
          <Row label={t("common:patient.fileNo")}>
            <bdi>{p.patient.file_no}</bdi>
          </Row>
          <Row label={t("receipt.method")}>{t(`payment.method.${p.method}`)}</Row>
          {p.bank ? (
            <Row label={t("payment.bank")}>
              {names.name(p.bank)} · <bdi>{p.reference}</bdi>
            </Row>
          ) : null}
          <Row label={t("receipt.cashier")}>
            {names.user(p.created_by)} · <bdi>{p.shift_number}</bdi>
          </Row>
        </dl>
      </section>
    </div>
  );
}

/**
 * Check a printed receipt against the system (FEATURES 6.9, 15.1): scan its QR code (a scanner
 * types the code and Enter) or type the receipt number. Shows whether the money stands:
 * valid, waiting for the bank, rejected, reversed, or a code that does not match the payment.
 */
export function ReceiptCheckPage() {
  const { t } = useTranslation(["cashier", "errors"]);
  const translateError = useTranslateError();
  const navigate = useNavigate();
  const code = parseCashierSearch(useSearch({ strict: false })).q ?? "";
  const [draft, setDraft] = useState(code);
  const check = useReceiptCheck(code);

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <PageHeader title={t("receiptCheck.title")} description={t("receiptCheck.description")} icon={<ScanLine />} />
      <CashierNav />
      <form
        className="card-surface flex min-w-0 flex-col gap-3 p-4 md:p-5"
        onSubmit={(e) => {
          e.preventDefault();
          const next = draft.trim();
          void navigate({ to: "/cashier/receipt-check", search: next ? { q: next } : {}, replace: true });
        }}
        data-testid="receipt-check-form"
      >
        <Label htmlFor="receipt-check-code">{t("receiptCheck.label")}</Label>
        <div className="flex min-w-0 flex-wrap gap-2">
          <Input
            id="receipt-check-code"
            value={draft}
            onChange={(e) => {
              setDraft(e.target.value);
            }}
            dir="ltr"
            autoComplete="off"
            autoFocus
            maxLength={200}
            placeholder={t("receiptCheck.placeholder")}
            className="min-w-0 flex-1 basis-48"
          />
          <Button type="submit" data-testid="receipt-check-submit">
            {t("receiptCheck.submit")}
          </Button>
        </div>
        <p className="text-sm text-muted">{t("receiptCheck.hint")}</p>
      </form>
      {code === "" ? null : check.isPending ? (
        <Skeleton className="h-48 w-full rounded-card" />
      ) : check.isError ? (
        <AlertCard variant="danger" title={t("receiptCheck.notFoundTitle")} live>
          {isApiError(check.error) && check.error.code === "NOT_FOUND"
            ? t("receiptCheck.notFound")
            : translateError(check.error)}
        </AlertCard>
      ) : (
        <CheckResult check={check.data} />
      )}
    </div>
  );
}
