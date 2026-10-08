import { FilePlus2, ListChecks } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { Can } from "@/components/Can";
import { EmptyState } from "@/components/EmptyState";
import { KbdCombo } from "@/components/Kbd";
import { MoneyText } from "@/components/MoneyText";
import { StatusBadge } from "@/components/StatusBadge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Skeleton } from "@/components/ui/skeleton";
import { useTranslateError } from "@/lib/api/translate-error";
import { usePermission } from "@/lib/auth/hooks";
import { useShortcut } from "@/lib/hooks/use-shortcut";

import { useCreateInvoice } from "../api";
import { useNames } from "../lib/use-names";
import type { ServiceLine, VisitBilling } from "../types";
import { InvoiceCard } from "./InvoiceCard";
import { LinePayerDialog } from "./LinePayerDialog";
import { PatientHeader } from "./PatientHeader";

export const INVOICE_SHORTCUT = "f4";

/** The visit's billing (FLOW step 4): requested lines, drafts and approved invoices. */
export function BillingPanel({ billing, loading }: { billing: VisitBilling | undefined; loading: boolean }) {
  const { t } = useTranslation("cashier");
  if (loading || !billing) {
    return (
      <div className="flex flex-col gap-3">
        <Skeleton className="h-24 w-full rounded-card" />
        <Skeleton className="h-48 w-full rounded-card" />
      </div>
    );
  }
  return (
    <section aria-label={t("billing.title")} className="flex min-w-0 flex-col gap-4" data-testid="billing-panel">
      <div className="card-surface flex min-w-0 flex-col gap-3 p-4 md:p-5">
        <PatientHeader
          patient={billing.patient}
          visitNumber={billing.visit.number}
          department={billing.visit.department}
          payer={billing.visit.payer}
        />
        <dl className="flex flex-wrap gap-x-5 gap-y-1 text-sm" data-testid="patient-balance">
          <div className="flex items-center gap-1.5">
            <dt className="text-muted">{t("billing.outstanding")}</dt>
            <dd className="font-semibold">
              <MoneyText value={billing.balance.outstanding} />
            </dd>
          </div>
          <div className="flex items-center gap-1.5">
            <dt className="text-muted">{t("billing.credit")}</dt>
            <dd>
              <MoneyText value={billing.balance.credit} toneNegative />
            </dd>
          </div>
          {billing.balance.pending !== "0.00" ? (
            <div className="flex items-center gap-1.5">
              <dt className="text-muted">{t("billing.pending")}</dt>
              <dd>
                <MoneyText value={billing.balance.pending} />
              </dd>
            </div>
          ) : null}
        </dl>
      </div>
      <UnbilledLines key={billing.visit.id} billing={billing} />
      {billing.drafts.map((inv, i) => (
        <InvoiceCard key={inv.id} invoice={inv} primary={i === 0} />
      ))}
      {billing.invoices.map((inv) => (
        <InvoiceCard key={inv.id} invoice={inv} />
      ))}
    </section>
  );
}

function UnbilledLines({ billing }: { billing: VisitBilling }) {
  const { t } = useTranslation(["cashier", "errors"]);
  const translateError = useTranslateError();
  const names = useNames();
  const canInvoice = usePermission("billing.create_invoice");
  const create = useCreateInvoice();
  const free = billing.unbilled.filter((l) => l.draft_invoice_id === null);
  const [unchecked, setUnchecked] = useState<ReadonlySet<number>>(new Set());
  const [payerLine, setPayerLine] = useState<ServiceLine | null>(null);
  const [error, setError] = useState<string | null>(null);
  const selected = free.filter((l) => !unchecked.has(l.id)).map((l) => l.id);

  const createInvoice = async () => {
    if (selected.length === 0) return;
    setError(null);
    try {
      await create.mutateAsync({ visit_id: billing.visit.id, line_ids: selected });
      setUnchecked(new Set());
    } catch (e) {
      setError(translateError(e));
    }
  };

  useShortcut(INVOICE_SHORTCUT, () => void createInvoice(), {
    enabled: canInvoice && selected.length > 0 && !create.isPending,
    allowInInputs: true,
  });

  if (billing.unbilled.length === 0) {
    if (billing.drafts.length > 0 || billing.invoices.length > 0) return null;
    return (
      <EmptyState
        icon={<ListChecks />}
        title={t("billing.nothingTitle")}
        description={t("billing.nothingDescription")}
        size="compact"
      />
    );
  }

  return (
    <section
      aria-labelledby="unbilled-title"
      className="card-surface flex min-w-0 flex-col gap-3 p-4 md:p-5"
      data-testid="unbilled-lines"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 id="unbilled-title" className="text-base font-semibold">
          {t("billing.unbilledTitle", { count: billing.unbilled.length })}
        </h3>
        <Can permission="billing.create_invoice">
          <Button
            onClick={() => void createInvoice()}
            disabled={selected.length === 0}
            loading={create.isPending}
            data-testid="create-invoice"
          >
            <FilePlus2 aria-hidden="true" />
            {t("billing.createInvoice", { count: selected.length })}
            <KbdCombo combo={INVOICE_SHORTCUT} className="ms-1 hidden md:inline-flex" />
          </Button>
        </Can>
      </div>
      <ul className="flex flex-col divide-y divide-border">
        {billing.unbilled.map((line) => {
          const onDraft = line.draft_invoice_id !== null;
          const checked = !onDraft && !unchecked.has(line.id);
          const checkboxId = `unbilled-${String(line.id)}`;
          return (
            <li key={line.id} className="flex min-w-0 flex-wrap items-center gap-3 py-2.5" data-testid="unbilled-line">
              {canInvoice ? (
                <Checkbox
                  id={checkboxId}
                  checked={checked}
                  disabled={onDraft}
                  onCheckedChange={(value) => {
                    setUnchecked((prev) => {
                      const next = new Set(prev);
                      if (value === true) next.delete(line.id);
                      else next.add(line.id);
                      return next;
                    });
                  }}
                  aria-label={names.name(line.service)}
                />
              ) : null}
              <label htmlFor={checkboxId} className="flex min-w-0 flex-1 flex-col gap-1">
                <span className="font-medium break-words">{names.name(line.service)}</span>
                <span className="flex flex-wrap items-center gap-1.5 text-xs text-muted">
                  <span className="tabular">{t("billing.qty", { count: line.quantity })}</span>
                  <StatusBadge status={line.state} size="sm" />
                  <Badge variant={line.payer ? "info" : "neutral"}>
                    {line.payer ? names.name(line.payer) : t("invoice.cash")}
                  </Badge>
                  {line.authorized ? <Badge variant="soft">{t("billing.authorized")}</Badge> : null}
                  {onDraft ? <Badge variant="warning">{t("billing.onDraft")}</Badge> : null}
                </span>
              </label>
              {canInvoice && !onDraft && (billing.payers.length > 0 || line.payer) ? (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setPayerLine(line);
                  }}
                >
                  {t("billing.changePayer")}
                </Button>
              ) : null}
            </li>
          );
        })}
      </ul>
      {error ? (
        <AlertCard variant="danger" title={t("errors:title")} live onDismiss={() => setError(null)}>
          {error}
        </AlertCard>
      ) : null}
      <LinePayerDialog
        line={payerLine}
        payers={billing.payers}
        onOpenChange={(o) => {
          if (!o) setPayerLine(null);
        }}
      />
    </section>
  );
}
