import type { ColumnDef } from "@tanstack/react-table";
import { BadgeCheck, Ban, Landmark } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { DataTable, type DataTableRowAction } from "@/components/DataTable";
import { DateText } from "@/components/DateText";
import { EmptyState } from "@/components/EmptyState";
import { MoneyText } from "@/components/MoneyText";
import { PageHeader } from "@/components/PageHeader";
import { ReasonDialog } from "@/components/ReasonDialog";
import { StatusBadge } from "@/components/StatusBadge";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useTranslateError } from "@/lib/api/translate-error";
import { usePermission } from "@/lib/auth/hooks";

import { PAGE_SIZE, useConfirmTransfer, useReasons, useRejectTransfer, useTransfers } from "../api";
import { CashierNav } from "../components/CashierNav";
import { NoteDialog } from "../components/NoteDialog";
import { Pager } from "../components/Pager";
import { useNames } from "../lib/use-names";
import type { Rejection, Transfer, Verification } from "../types";

function verificationStatus(v: Verification) {
  return v === "pending" ? "pending_verification" : v;
}

/**
 * Transfers, QR and card payments waiting for a bank check (FEATURES 6.3, 6.4): a cashier
 * supervisor or an accountant confirms with a note or rejects with a reason. A rejection after
 * the shift closed books its reversal in the checker's own open shift (6.8).
 */
export function TransfersPage() {
  const { t } = useTranslation(["cashier", "errors"]);
  const translateError = useTranslateError();
  const names = useNames();
  const [verification, setVerification] = useState<Verification>("pending");
  const [page, setPage] = useState(1);
  const transfers = useTransfers(verification, page);
  const canConfirm = usePermission("payments.confirm_transfer");
  const canReject = usePermission("payments.reject_transfer");
  const confirm = useConfirmTransfer();
  const reject = useRejectTransfer();
  const rejectReasons = useReasons("transfer_reject", canReject);
  const [confirming, setConfirming] = useState<Transfer | null>(null);
  const [rejecting, setRejecting] = useState<Transfer | null>(null);
  const [outcome, setOutcome] = useState<Rejection | null>(null);

  const actions = (row: Transfer): DataTableRowAction[] => {
    const out: DataTableRowAction[] = [];
    const v = row.payment.verification;
    if (canConfirm && v === "pending")
      out.push({
        label: t("transfers.confirm"),
        icon: <BadgeCheck />,
        onSelect: () => {
          setConfirming(row);
        },
      });
    if (canReject && v !== "rejected")
      out.push({
        label: t("transfers.reject"),
        icon: <Ban />,
        destructive: true,
        onSelect: () => {
          setRejecting(row);
        },
      });
    return out;
  };

  const columns = useMemo<ColumnDef<Transfer>[]>(
    () => [
      {
        id: "number",
        header: t("transfers.columns.payment"),
        meta: { label: t("transfers.columns.payment") },
        cell: ({ row }) => (
          <span className="flex flex-col gap-1">
            <bdi className="font-medium">{row.original.payment.number}</bdi>
            <StatusBadge status={verificationStatus(row.original.payment.verification)} size="sm" />
          </span>
        ),
      },
      {
        id: "patient",
        header: t("transfers.columns.patient"),
        meta: { label: t("transfers.columns.patient") },
        cell: ({ row }) => (
          <span className="flex flex-col">
            <span>{names.patient(row.original.payment.patient)}</span>
            <bdi className="text-xs text-muted">{row.original.payment.patient.file_no}</bdi>
          </span>
        ),
      },
      {
        id: "bank",
        header: t("transfers.columns.bank"),
        meta: { label: t("transfers.columns.bank") },
        cell: ({ row }) => (
          <span className="flex flex-col">
            <span>{names.name(row.original.payment.bank)}</span>
            <bdi className="text-xs text-muted" data-testid="transfer-reference">
              {row.original.payment.reference}
            </bdi>
            <TransferSender payment={row.original.payment} />
          </span>
        ),
      },
      {
        id: "amount",
        header: t("transfers.columns.amount"),
        meta: { label: t("transfers.columns.amount"), align: "end" },
        cell: ({ row }) => <MoneyText value={row.original.payment.amount} />,
      },
      {
        id: "age",
        header: t("transfers.columns.age"),
        meta: { label: t("transfers.columns.age"), align: "end" },
        cell: ({ row }) => t("report.ageDays", { count: row.original.payment.age_days }),
      },
      {
        id: "shift",
        header: t("transfers.columns.shift"),
        meta: { label: t("transfers.columns.shift") },
        cell: ({ row }) => (
          <span className="flex flex-col">
            <span>{names.user(row.original.cashier)}</span>
            <span className="flex items-center gap-1 text-xs text-muted">
              <bdi>{row.original.payment.shift_number}</bdi>
              {row.original.payment.shift_status === "closed" ? (
                <Badge variant="neutral">{t("shift.status.closed")}</Badge>
              ) : null}
            </span>
          </span>
        ),
      },
    ],
    [t, names],
  );

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <PageHeader title={t("transfers.title")} description={t("transfers.description")} icon={<Landmark />} />
      <CashierNav />
      <Tabs
        value={verification}
        onValueChange={(v) => {
          setVerification(v as Verification);
          setPage(1);
        }}
      >
        <TabsList aria-label={t("transfers.filter")}>
          <TabsTrigger value="pending">{t("transfers.filters.pending")}</TabsTrigger>
          <TabsTrigger value="confirmed">{t("transfers.filters.confirmed")}</TabsTrigger>
          <TabsTrigger value="rejected">{t("transfers.filters.rejected")}</TabsTrigger>
        </TabsList>
      </Tabs>
      {outcome ? (
        <AlertCard
          variant="warning"
          title={t("transfers.rejectedTitle", { number: outcome.payment.number })}
          live
          onDismiss={() => {
            setOutcome(null);
          }}
        >
          <span data-testid="rejection-outcome">
            {outcome.reversal
              ? t("transfers.reversalBooked", {
                  number: outcome.reversal.number,
                  shift: outcome.reversal.shift_number,
                })
              : t("transfers.reversedInShift")}
          </span>
        </AlertCard>
      ) : null}
      {transfers.isError ? (
        <AlertCard variant="danger" title={t("errors:title")}>
          {translateError(transfers.error)}
        </AlertCard>
      ) : (
        <>
          <DataTable
            columns={columns}
            data={transfers.data?.items ?? []}
            loading={transfers.isPending}
            getRowId={(r) => String(r.payment.id)}
            caption={t("transfers.title")}
            rowActions={actions}
            pageSize={PAGE_SIZE}
            pageSizeOptions={[PAGE_SIZE]}
            minTableWidth={820}
            emptyState={<EmptyState bare size="compact" icon={<Landmark />} title={t("transfers.empty")} />}
            renderCard={(r, ctx) => (
              <div className="card-surface flex flex-col gap-2 p-4" data-testid="transfer-row">
                <div className="flex items-start justify-between gap-2">
                  <span className="flex min-w-0 flex-col gap-1">
                    <bdi className="font-semibold">{r.payment.number}</bdi>
                    <StatusBadge status={verificationStatus(r.payment.verification)} size="sm" />
                  </span>
                  {ctx.actions}
                </div>
                <span className="text-sm">{names.patient(r.payment.patient)}</span>
                <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted">
                  <span>{names.name(r.payment.bank)}</span>
                  <bdi data-testid="transfer-reference">{r.payment.reference}</bdi>
                  <span>
                    {t("transfers.columns.age")}: {t("report.ageDays", { count: r.payment.age_days })}
                  </span>
                  <DateText value={r.payment.created_at} format="datetime" />
                </span>
                <TransferSender payment={r.payment} />
                <MoneyText value={r.payment.amount} className="text-base" />
              </div>
            )}
          />
          <Pager page={page} pageSize={PAGE_SIZE} count={transfers.data?.count ?? 0} onPage={setPage} />
        </>
      )}
      <NoteDialog
        open={confirming !== null}
        onOpenChange={(o) => {
          if (!o) setConfirming(null);
        }}
        title={t("transfers.confirmTitle", { number: confirming?.payment.number ?? "" })}
        description={t("transfers.confirmDescription")}
        label={t("transfers.checked")}
        confirmLabel={t("transfers.confirm")}
        testId="confirm-transfer-dialog"
        onSubmit={(note) => confirm.mutateAsync({ paymentId: confirming?.payment.id ?? 0, note })}
      >
        {confirming ? (
          <p className="flex flex-wrap items-center justify-between gap-2 rounded-control bg-subtle px-3 py-2 text-sm">
            <span>
              {names.name(confirming.payment.bank)} · <bdi>{confirming.payment.reference}</bdi>
            </span>
            <MoneyText value={confirming.payment.amount} />
          </p>
        ) : null}
      </NoteDialog>
      <ReasonDialog
        open={rejecting !== null}
        onOpenChange={(o) => {
          if (!o) setRejecting(null);
        }}
        title={t("transfers.rejectTitle", { number: rejecting?.payment.number ?? "" })}
        description={t("transfers.rejectDescription")}
        reasons={(rejectReasons.data ?? []).map((r) => ({ code: r.code, label: names.label(r) }))}
        noteRequired={false}
        destructive
        confirmLabel={t("transfers.reject")}
        onSubmit={async ({ code, note }) => {
          if (!rejecting) return;
          const result = await reject.mutateAsync({ paymentId: rejecting.payment.id, reason: code, note });
          setOutcome(result);
        }}
      />
    </div>
  );
}

/** What the supervisor matches against the bank statement besides the reference. */
function TransferSender({ payment }: { payment: Transfer["payment"] }) {
  const { t } = useTranslation("cashier");
  if (!payment.sender_name && !payment.transfer_date) return null;
  return (
    <span className="flex flex-wrap gap-x-2 text-xs text-muted" data-testid="transfer-sender">
      {payment.sender_name ? (
        <span>
          {t("transfers.sender")}: <bdi>{payment.sender_name}</bdi>
        </span>
      ) : null}
      {payment.transfer_date ? (
        <span>
          {t("transfers.sentOn")}: <DateText value={payment.transfer_date} format="date" />
        </span>
      ) : null}
    </span>
  );
}
