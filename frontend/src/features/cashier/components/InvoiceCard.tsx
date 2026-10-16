import { Link } from "@tanstack/react-router";
import { BadgePercent, CheckCircle2, FileMinus, MoreHorizontal, Printer, Trash2, XCircle } from "lucide-react";
import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Can } from "@/components/Can";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { type DataTableRowAction } from "@/components/DataTable";
import { DateText } from "@/components/DateText";
import { KbdCombo } from "@/components/Kbd";
import { MoneyText } from "@/components/MoneyText";
import { AlertCard } from "@/components/AlertCard";
import { ReasonDialog } from "@/components/ReasonDialog";
import { StatusBadge } from "@/components/StatusBadge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useTranslateError } from "@/lib/api/translate-error";
import { usePermission } from "@/lib/auth/hooks";
import { useShortcut } from "@/lib/hooks/use-shortcut";

import { useApproveInvoice, useCancelDraftLine, useReasons, useRemoveDraftLine, useVoidInvoice } from "../api";
import { negate } from "../lib/money";
import { useNames } from "../lib/use-names";
import type { Invoice, InvoiceLine, PaymentMethod } from "../types";
import { CreditNoteDialog } from "./CreditNoteDialog";
import { DiscountDialog, type DiscountTarget } from "./DiscountDialog";
import { NoteDialog } from "./NoteDialog";
import { InvoiceLines, type InvoiceLineRow } from "./InvoiceLines";
import { PreapprovalDialog } from "./PreapprovalDialog";

export const APPROVE_SHORTCUT = "f8";

function Figure({
  label,
  value,
  emphasis = false,
  testId,
}: {
  label: ReactNode;
  value: string;
  /** The amount to collect: the strongest figure of the bar. */
  emphasis?: boolean;
  testId?: string;
}) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5" data-testid={testId}>
      <dt className="text-xs text-muted">{label}</dt>
      <dd className={emphasis ? "text-xl leading-tight font-bold text-fg" : "text-sm text-fg"}>
        <MoneyText value={value} className={emphasis ? "font-bold" : "font-normal"} />
      </dd>
    </div>
  );
}

/** One invoice: lines with coverage split, totals, and the actions its state allows. */
export function InvoiceCard({
  invoice,
  onApproved,
  primary = false,
}: {
  invoice: Invoice;
  onApproved?: (inv: Invoice) => void;
  /** The draft the F8 shortcut approves (the first draft of the visit). */
  primary?: boolean;
}) {
  const { t } = useTranslation(["cashier", "common", "errors"]);
  const translateError = useTranslateError();
  const names = useNames();
  const isDraft = invoice.status === "draft";
  const approved = invoice.status === "approved";
  const canEdit = usePermission("billing.create_invoice");
  const canDiscount = usePermission("billing.apply_discount");
  // Cancelling a draft line needs the billing desk's code and the cancel code (the server's rule).
  const canCancel = usePermission(["billing.create_invoice", "orders.cancel_line"], "all");
  const approve = useApproveInvoice();
  const voidInvoice = useVoidInvoice();
  const remove = useRemoveDraftLine();
  const cancel = useCancelDraftLine();
  const cancelReasons = useReasons("line_cancel", isDraft && canCancel);
  const [discountTarget, setDiscountTarget] = useState<DiscountTarget | null>(null);
  const [lineError, setLineError] = useState<string | null>(null);
  const [cancelLine, setCancelLine] = useState<InvoiceLine | null>(null);
  const [preapprovalLine, setPreapprovalLine] = useState<InvoiceLine | null>(null);
  const [voidOpen, setVoidOpen] = useState(false);
  const [creditOpen, setCreditOpen] = useState(false);
  const [approveOpen, setApproveOpen] = useState(false);
  const canApprove = usePermission("billing.approve_invoice");
  useShortcut(
    APPROVE_SHORTCUT,
    () => {
      setApproveOpen(true);
    },
    { enabled: primary && isDraft && canApprove && invoice.lines.length > 0, allowInInputs: true },
  );

  const rowActions = (line: InvoiceLine): DataTableRowAction[] => {
    if (!isDraft) return [];
    const out: DataTableRowAction[] = [];
    if (canDiscount)
      out.push({
        label: t("invoice.actions.discount"),
        icon: <BadgePercent />,
        onSelect: () => {
          setDiscountTarget({ kind: "line", line });
        },
      });
    if (canEdit && line.payer && line.requires_pre_approval)
      out.push({
        label: t("invoice.actions.preapproval"),
        onSelect: () => {
          setPreapprovalLine(line);
        },
      });
    if (canEdit)
      out.push({
        label: t("invoice.actions.remove"),
        icon: <Trash2 />,
        onSelect: () => {
          setLineError(null);
          remove.mutateAsync({ invoiceId: invoice.id, lineId: line.id }).catch((e: unknown) => {
            setLineError(translateError(e));
          });
        },
        separated: true,
      });
    if (canCancel)
      out.push({
        label: t("invoice.actions.cancel"),
        icon: <XCircle />,
        destructive: true,
        onSelect: () => {
          setCancelLine(line);
        },
      });
    return out;
  };

  // The coverage payer is shown once, in the header. A line repeats a payer badge only when it
  // differs from it (another payer, cash) or needs a decision (not covered, pre-approval).
  const payerIds = new Set(invoice.lines.filter((l) => l.payer).map((l) => l.payer?.id));
  const invoicePayer = payerIds.size === 1 ? (invoice.lines.find((l) => l.payer)?.payer ?? null) : null;
  const mixedPayers = payerIds.size > 1;

  return (
    <section
      className="card-surface flex min-w-0 flex-col gap-4 overflow-hidden pt-4 md:pt-5"
      data-testid={isDraft ? "draft-invoice" : "approved-invoice"}
      data-invoice-id={invoice.id}
      aria-label={invoice.number ?? t("invoice.draft")}
    >
      <header className="flex flex-wrap items-start justify-between gap-3 px-4 md:px-5">
        <div className="flex min-w-0 flex-col gap-1">
          <h3 className="flex flex-wrap items-center gap-2 text-base font-semibold">
            {invoice.number ? <bdi data-testid="invoice-number">{invoice.number}</bdi> : t("invoice.draft")}
            <Badge variant={isDraft ? "warning" : invoice.status === "void" ? "neutral" : "success"}>
              {t(`invoice.status.${invoice.status}`)}
            </Badge>
          </h3>
          <span className="text-sm text-muted">
            {approved && invoice.approved_at ? (
              <>
                {t("invoice.approvedBy", { name: names.user(invoice.approved_by) })}{" "}
                <DateText value={invoice.approved_at} format="datetime" />
              </>
            ) : (
              <DateText value={invoice.created_at} format="datetime" />
            )}
          </span>
          {invoice.lines.length > 0 && !mixedPayers ? (
            <span className="flex flex-wrap items-center gap-1.5 text-sm text-muted" data-testid="invoice-payer">
              {t("invoice.payer")}
              <Badge variant={invoicePayer ? "info" : "neutral"}>
                {invoicePayer ? names.name(invoicePayer) : t("invoice.cash")}
              </Badge>
            </span>
          ) : null}
        </div>
        {approved ? (
          <div className="flex flex-wrap gap-2">
            <Button asChild variant="outline" size="sm">
              <Link
                to="/cashier/invoices/$invoiceId/print"
                params={{ invoiceId: String(invoice.id) }}
                data-testid="print-invoice"
              >
                <Printer aria-hidden="true" />
                {t("invoice.print")}
              </Link>
            </Button>
            <Can permission="billing.create_credit_note">
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setCreditOpen(true);
                }}
                data-testid="open-credit-note"
              >
                <FileMinus aria-hidden="true" />
                {t("invoice.creditNote")}
              </Button>
            </Can>
          </div>
        ) : null}
      </header>

      {invoice.lines.length === 0 ? (
        <p className="px-4 text-sm text-muted md:px-5">{t("invoice.noLines")}</p>
      ) : (
        <InvoiceLines
          caption={t("invoice.linesCaption")}
          lines={invoice.lines.map((line): InvoiceLineRow => {
            const showPayer = mixedPayers || (invoicePayer !== null && line.payer?.id !== invoicePayer.id);
            const needsPreapproval = line.requires_pre_approval && !line.pre_approval_ref;
            return {
              id: line.id,
              name: names.name(line.service),
              meta:
                showPayer || line.excluded || needsPreapproval ? (
                  <>
                    {showPayer ? (
                      <Badge variant={line.payer ? "info" : "neutral"}>
                        {line.payer ? names.name(line.payer) : t("invoice.cash")}
                      </Badge>
                    ) : null}
                    {line.excluded ? <Badge variant="warning">{t("invoice.excluded")}</Badge> : null}
                    {needsPreapproval ? <Badge variant="warning">{t("invoice.needsPreapproval")}</Badge> : null}
                  </>
                ) : null,
              quantity: line.quantity,
              gross: line.gross,
              discount: line.discount,
              payerShare: line.payer_share,
              patientShare: line.patient_share,
              outstanding: approved ? line.outstanding : null,
              status: line.state,
              needsDecision: line.excluded || (line.requires_pre_approval && !line.pre_approval_ref),
              actions: isDraft ? <LineActions actions={rowActions(line)} name={names.name(line.service)} /> : null,
            };
          })}
        />
      )}

      {lineError ? (
        <div className="px-4 md:px-5">
          <AlertCard
            variant="danger"
            title={t("errors:title")}
            live
            onDismiss={() => {
              setLineError(null);
            }}
          >
            {lineError}
          </AlertCard>
        </div>
      ) : null}

      {approved && invoice.payments.length > 0 ? (
        <div className="flex flex-col gap-1 px-4 text-sm md:px-5">
          <h4 className="font-medium">{t("invoice.payments")}</h4>
          <ul className="flex flex-col gap-1">
            {invoice.payments.map((p) => (
              <li key={p.payment_id} className="flex flex-wrap items-center justify-between gap-2">
                <span className="flex min-w-0 flex-wrap items-center gap-2">
                  <bdi>{p.number}</bdi>
                  <span className="text-muted">{t(`payment.method.${p.method as PaymentMethod}`)}</span>
                  <StatusBadge
                    size="sm"
                    status={
                      p.verification === "pending"
                        ? "pending_verification"
                        : p.verification === "rejected"
                          ? "rejected"
                          : "confirmed"
                    }
                  />
                </span>
                <MoneyText value={p.amount} />
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {approved && invoice.credit_notes.length > 0 ? (
        <div className="flex flex-col gap-1 px-4 text-sm md:px-5">
          <h4 className="font-medium">{t("invoice.creditNotes")}</h4>
          <ul className="flex flex-col gap-1">
            {invoice.credit_notes.map((cn) => (
              <li key={cn.id} className="flex flex-wrap items-center justify-between gap-2">
                <span className="flex items-center gap-2">
                  <bdi>{cn.number ?? t("creditNotes.draft")}</bdi>
                  <Badge variant={cn.status === "approved" ? "success" : "warning"}>
                    {t(`invoice.status.${cn.status}`)}
                  </Badge>
                </span>
                <MoneyText value={negate(cn.patient_total)} toneNegative />
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <footer
        className="flex flex-wrap items-end justify-between gap-x-8 gap-y-4 border-t border-border bg-subtle px-4 py-4 md:px-5"
        data-slot="invoice-totals-bar"
      >
        <dl className="flex min-w-0 flex-wrap items-end gap-x-8 gap-y-3" data-testid="invoice-totals">
          <Figure label={t("invoice.grossTotal")} value={invoice.gross_total} />
          <Figure label={t("invoice.discountTotal")} value={negate(invoice.discount_total)} />
          <Figure label={t("invoice.payerTotal")} value={invoice.payer_total} />
          {approved && invoice.paid !== null ? <Figure label={t("invoice.paid")} value={invoice.paid} /> : null}
          {approved && invoice.outstanding !== null ? (
            <Figure label={t("invoice.outstanding")} value={invoice.outstanding} />
          ) : null}
          <Figure label={t("invoice.toCollect")} value={invoice.patient_total} emphasis />
        </dl>
        {isDraft ? (
          <div className="flex flex-wrap items-center gap-2">
            {canDiscount && invoice.lines.length > 0 ? (
              <Button
                variant="outline"
                onClick={() => {
                  setDiscountTarget({ kind: "invoice", invoice });
                }}
                data-testid="discount-invoice"
              >
                <BadgePercent aria-hidden="true" />
                {t("invoice.actions.discountInvoice")}
              </Button>
            ) : null}
            <Can permission="billing.void_draft">
              <Button
                variant="ghost"
                onClick={() => {
                  setVoidOpen(true);
                }}
              >
                {t("invoice.void")}
              </Button>
            </Can>
            <Can permission="billing.approve_invoice">
              <ConfirmDialog
                open={approveOpen}
                onOpenChange={setApproveOpen}
                trigger={
                  <Button data-testid="approve-invoice" disabled={invoice.lines.length === 0}>
                    <CheckCircle2 aria-hidden="true" />
                    {t("invoice.approve")}
                    <KbdCombo combo={APPROVE_SHORTCUT} className="ms-1 hidden md:inline-flex" />
                  </Button>
                }
                title={t("invoice.approveTitle")}
                description={t("invoice.approveDescription")}
                confirmLabel={t("invoice.approve")}
                onConfirm={async () => {
                  const inv = await approve.mutateAsync(invoice.id);
                  onApproved?.(inv);
                }}
              />
            </Can>
          </div>
        ) : null}
      </footer>

      <DiscountDialog
        invoiceId={invoice.id}
        target={discountTarget}
        open={discountTarget !== null}
        onOpenChange={(o) => {
          if (!o) setDiscountTarget(null);
        }}
      />
      <PreapprovalDialog
        invoiceId={invoice.id}
        line={preapprovalLine}
        onOpenChange={(o) => {
          if (!o) setPreapprovalLine(null);
        }}
      />
      <ReasonDialog
        open={cancelLine !== null}
        onOpenChange={(o) => {
          if (!o) setCancelLine(null);
        }}
        title={t("invoice.cancelTitle")}
        description={t("invoice.cancelDescription")}
        reasons={(cancelReasons.data ?? []).map((r) => ({ code: r.code, label: names.label(r) }))}
        noteRequired={false}
        destructive
        confirmLabel={t("invoice.actions.cancel")}
        onSubmit={async ({ code, note }) => {
          if (!cancelLine) return;
          await cancel.mutateAsync({ invoiceId: invoice.id, lineId: cancelLine.id, reason: code, note });
        }}
      >
        {cancelLine ? <p className="text-sm font-medium">{names.name(cancelLine.service)}</p> : null}
      </ReasonDialog>
      <NoteDialog
        open={voidOpen}
        onOpenChange={setVoidOpen}
        title={t("invoice.voidTitle")}
        description={t("invoice.voidDescription")}
        label={t("invoice.voidNote")}
        confirmLabel={t("invoice.void")}
        destructive
        onSubmit={(note) => voidInvoice.mutateAsync({ invoiceId: invoice.id, note })}
      />
      {approved ? <CreditNoteDialog invoice={invoice} open={creditOpen} onOpenChange={setCreditOpen} /> : null}
    </section>
  );
}

/** The actions of one draft line (discount, pre-approval, take off, cancel). */
function LineActions({ actions, name }: { actions: DataTableRowAction[]; name: string }) {
  const { t } = useTranslation("cashier");
  if (actions.length === 0) return null;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label={t("invoice.lineActionsFor", { name })}
          data-testid="line-actions"
        >
          <MoreHorizontal aria-hidden="true" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {actions.map((action) => (
          <div key={action.label}>
            {action.separated ? <DropdownMenuSeparator /> : null}
            <DropdownMenuItem
              onSelect={action.onSelect}
              disabled={action.disabled}
              variant={action.destructive ? "destructive" : "default"}
            >
              {action.icon}
              {action.label}
            </DropdownMenuItem>
          </div>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
