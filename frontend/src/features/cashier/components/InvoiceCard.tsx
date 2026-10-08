import { Link } from "@tanstack/react-router";
import type { ColumnDef } from "@tanstack/react-table";
import { BadgePercent, CheckCircle2, FileMinus, Printer, Trash2, XCircle } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Can } from "@/components/Can";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { DataTable, type DataTableRowAction } from "@/components/DataTable";
import { DateText } from "@/components/DateText";
import { KbdCombo } from "@/components/Kbd";
import { MoneyText } from "@/components/MoneyText";
import { ReasonDialog } from "@/components/ReasonDialog";
import { StatusBadge } from "@/components/StatusBadge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { usePermission } from "@/lib/auth/hooks";
import { useShortcut } from "@/lib/hooks/use-shortcut";

import { useApproveInvoice, useCancelDraftLine, useReasons, useRemoveDraftLine, useVoidInvoice } from "../api";
import { negate } from "../lib/money";
import { useNames } from "../lib/use-names";
import type { Invoice, InvoiceLine, PaymentMethod } from "../types";
import { CreditNoteDialog } from "./CreditNoteDialog";
import { DiscountDialog } from "./DiscountDialog";
import { NoteDialog } from "./NoteDialog";
import { PreapprovalDialog } from "./PreapprovalDialog";

export const APPROVE_SHORTCUT = "f8";

function Amount({ label, value, strong = false }: { label: ReactNode; value: string; strong?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="text-muted">{label}</dt>
      <dd className={strong ? "font-semibold" : undefined}>
        <MoneyText value={value} />
      </dd>
    </div>
  );
}

function LineCard({ line, actions, approved }: { line: InvoiceLine; actions: ReactNode; approved: boolean }) {
  const { t } = useTranslation("cashier");
  const names = useNames();
  return (
    <div className="card-surface flex flex-col gap-2 p-4" data-testid="invoice-line">
      <div className="flex items-start justify-between gap-2">
        <div className="flex min-w-0 flex-col gap-1">
          <span className="font-medium break-words">{names.name(line.service)}</span>
          <span className="flex flex-wrap items-center gap-1.5">
            <StatusBadge status={line.state} size="sm" />
            <Badge variant={line.payer ? "info" : "neutral"}>
              {line.payer ? names.name(line.payer) : t("invoice.cash")}
            </Badge>
          </span>
        </div>
        {actions}
      </div>
      <dl className="grid gap-1 text-sm">
        <Amount label={t("invoice.qtyPrice", { qty: line.quantity })} value={line.gross} />
        {line.discount !== "0.00" ? <Amount label={t("invoice.discount")} value={negate(line.discount)} /> : null}
        <Amount label={t("invoice.payerShare")} value={line.payer_share} />
        <Amount label={t("invoice.patientShare")} value={line.patient_share} strong />
        {approved && line.outstanding !== null ? (
          <Amount label={t("invoice.outstanding")} value={line.outstanding} />
        ) : null}
      </dl>
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
  const { t } = useTranslation(["cashier", "common"]);
  const names = useNames();
  const isDraft = invoice.status === "draft";
  const approved = invoice.status === "approved";
  const canEdit = usePermission("billing.create_invoice");
  const canDiscount = usePermission("billing.apply_discount");
  const canCancel = usePermission("orders.cancel_line");
  const approve = useApproveInvoice();
  const voidInvoice = useVoidInvoice();
  const remove = useRemoveDraftLine();
  const cancel = useCancelDraftLine();
  const cancelReasons = useReasons("line_cancel", isDraft && canCancel);
  const [discountLine, setDiscountLine] = useState<InvoiceLine | null>(null);
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
          setDiscountLine(line);
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
          void remove.mutateAsync({ invoiceId: invoice.id, lineId: line.id });
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

  const columns = useMemo<ColumnDef<InvoiceLine>[]>(
    () => [
      {
        id: "service",
        header: t("invoice.service"),
        meta: { label: t("invoice.service") },
        cell: ({ row }) => (
          <div className="flex min-w-0 flex-col gap-1">
            <span className="font-medium">{names.name(row.original.service)}</span>
            <span className="flex flex-wrap items-center gap-1.5">
              <StatusBadge status={row.original.state} size="sm" />
              {row.original.excluded ? <Badge variant="warning">{t("invoice.excluded")}</Badge> : null}
              {row.original.requires_pre_approval && !row.original.pre_approval_ref ? (
                <Badge variant="warning">{t("invoice.needsPreapproval")}</Badge>
              ) : null}
            </span>
          </div>
        ),
      },
      {
        id: "payer",
        header: t("invoice.payer"),
        meta: { label: t("invoice.payer") },
        cell: ({ row }) => (row.original.payer ? names.name(row.original.payer) : t("invoice.cash")),
      },
      {
        id: "qty",
        header: t("invoice.qty"),
        meta: { label: t("invoice.qty"), align: "end" },
        cell: ({ row }) => <span className="tabular">{row.original.quantity}</span>,
      },
      {
        id: "gross",
        header: t("invoice.gross"),
        meta: { label: t("invoice.gross"), align: "end" },
        cell: ({ row }) => <MoneyText value={row.original.gross} currency={false} />,
      },
      {
        id: "discount",
        header: t("invoice.discount"),
        meta: { label: t("invoice.discount"), align: "end" },
        cell: ({ row }) => <MoneyText value={row.original.discount} currency={false} />,
      },
      {
        id: "payerShare",
        header: t("invoice.payerShare"),
        meta: { label: t("invoice.payerShare"), align: "end" },
        cell: ({ row }) => (
          <span data-testid="payer-share">
            <MoneyText value={row.original.payer_share} currency={false} />
          </span>
        ),
      },
      {
        id: "patientShare",
        header: t("invoice.patientShare"),
        meta: { label: t("invoice.patientShare"), align: "end" },
        cell: ({ row }) => (
          <span data-testid="patient-share" className="font-semibold">
            <MoneyText value={row.original.patient_share} currency={false} />
          </span>
        ),
      },
    ],
    [t, names],
  );

  return (
    <section
      className="card-surface flex min-w-0 flex-col gap-4 p-4 md:p-5"
      data-testid={isDraft ? "draft-invoice" : "approved-invoice"}
      data-invoice-id={invoice.id}
      aria-label={invoice.number ?? t("invoice.draft")}
    >
      <header className="flex flex-wrap items-start justify-between gap-3">
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

      <DataTable
        columns={columns}
        data={invoice.lines}
        getRowId={(l) => String(l.id)}
        caption={t("invoice.linesCaption")}
        rowActions={isDraft ? rowActions : undefined}
        pageSize={50}
        pageSizeOptions={[50]}
        minTableWidth={760}
        renderCard={(line, ctx) => <LineCard line={line} actions={ctx.actions} approved={approved} />}
        emptyState={<p className="p-4 text-sm text-muted">{t("invoice.noLines")}</p>}
      />

      <dl className="grid gap-1 text-sm sm:ms-auto sm:w-80" data-testid="invoice-totals">
        <Amount label={t("invoice.grossTotal")} value={invoice.gross_total} />
        <Amount label={t("invoice.discountTotal")} value={invoice.discount_total} />
        <Amount label={t("invoice.payerTotal")} value={invoice.payer_total} />
        <Amount label={t("invoice.patientTotal")} value={invoice.patient_total} strong />
        {approved && invoice.paid !== null ? <Amount label={t("invoice.paid")} value={invoice.paid} /> : null}
        {approved && invoice.outstanding !== null ? (
          <Amount label={t("invoice.outstanding")} value={invoice.outstanding} strong />
        ) : null}
      </dl>

      {approved && invoice.payments.length > 0 ? (
        <div className="flex flex-col gap-1 text-sm">
          <h4 className="font-medium">{t("invoice.payments")}</h4>
          <ul className="flex flex-col gap-1">
            {invoice.payments.map((p) => (
              <li key={p.payment_id} className="flex flex-wrap items-center justify-between gap-2">
                <span className="flex items-center gap-2">
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
        <div className="flex flex-col gap-1 text-sm">
          <h4 className="font-medium">{t("invoice.creditNotes")}</h4>
          <ul className="flex flex-col gap-1">
            {invoice.credit_notes.map((cn) => (
              <li key={cn.id} className="flex flex-wrap items-center justify-between gap-2">
                <span className="flex items-center gap-2">
                  <bdi>{cn.number ?? t("invoice.draft")}</bdi>
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

      {isDraft ? (
        <footer className="flex flex-wrap items-center justify-end gap-2 border-t border-border pt-4">
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
        </footer>
      ) : null}

      <DiscountDialog
        invoiceId={invoice.id}
        line={discountLine}
        open={discountLine !== null}
        onOpenChange={(o) => {
          if (!o) setDiscountLine(null);
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
