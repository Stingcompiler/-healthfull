import type { ColumnDef } from "@tanstack/react-table";
import { Banknote, CheckCircle2, Undo2, XCircle } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { DataTable, type DataTableRowAction } from "@/components/DataTable";
import { DateText } from "@/components/DateText";
import { EmptyState } from "@/components/EmptyState";
import { MoneyText } from "@/components/MoneyText";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useTranslateError } from "@/lib/api/translate-error";
import { usePermission } from "@/lib/auth/hooks";

import { PAGE_SIZE, useDecideRefund, usePayRefund, useRefunds } from "../api";
import { CashierNav } from "../components/CashierNav";
import { NoteDialog } from "../components/NoteDialog";
import { Pager } from "../components/Pager";
import { useNames } from "../lib/use-names";
import type { Refund, RefundStatus } from "../types";

type Filter = RefundStatus | "all";

const FILTERS: readonly Filter[] = ["requested", "approved", "paid", "rejected", "all"];

const STATUS_VARIANT = {
  requested: "warning",
  approved: "info",
  paid: "success",
  rejected: "neutral",
} as const;

/**
 * Refunds (FLOW 8, FEATURES 6.7): opened from a credit note, approved by a second person,
 * paid in cash from the paying cashier's own open shift.
 */
export function RefundsPage() {
  const { t } = useTranslation(["cashier", "errors"]);
  const translateError = useTranslateError();
  const names = useNames();
  const [filter, setFilter] = useState<Filter>("requested");
  const [page, setPage] = useState(1);
  const refunds = useRefunds(filter === "all" ? undefined : filter, page);
  const canApprove = usePermission("payments.approve_refund");
  const canPay = usePermission("payments.pay_refund");
  const decide = useDecideRefund();
  const pay = usePayRefund();
  const [deciding, setDeciding] = useState<{ refund: Refund; decision: "approve" | "reject" } | null>(null);
  const [paying, setPaying] = useState<Refund | null>(null);

  const actions = (r: Refund): DataTableRowAction[] => {
    const out: DataTableRowAction[] = [];
    if (canApprove && r.status === "requested") {
      out.push({
        label: t("refunds.approve"),
        icon: <CheckCircle2 />,
        onSelect: () => {
          setDeciding({ refund: r, decision: "approve" });
        },
      });
      out.push({
        label: t("refunds.reject"),
        icon: <XCircle />,
        destructive: true,
        onSelect: () => {
          setDeciding({ refund: r, decision: "reject" });
        },
      });
    }
    if (canPay && r.status === "approved")
      out.push({
        label: t("refunds.pay"),
        icon: <Banknote />,
        onSelect: () => {
          setPaying(r);
        },
      });
    return out;
  };

  const columns = useMemo<ColumnDef<Refund>[]>(
    () => [
      {
        id: "number",
        header: t("refunds.columns.number"),
        meta: { label: t("refunds.columns.number") },
        cell: ({ row }) => (
          <span className="flex flex-col gap-1">
            <bdi className="font-medium">{row.original.number}</bdi>
            <Badge variant={STATUS_VARIANT[row.original.status]}>{t(`refunds.status.${row.original.status}`)}</Badge>
          </span>
        ),
      },
      {
        id: "patient",
        header: t("refunds.columns.patient"),
        meta: { label: t("refunds.columns.patient") },
        cell: ({ row }) => names.patient(row.original.patient),
      },
      {
        id: "source",
        header: t("refunds.columns.creditNote"),
        meta: { label: t("refunds.columns.creditNote") },
        cell: ({ row }) => <bdi>{row.original.credit_note_number ?? "—"}</bdi>,
      },
      {
        id: "reason",
        header: t("refunds.columns.reason"),
        meta: { label: t("refunds.columns.reason") },
        cell: ({ row }) => names.label(row.original.reason),
      },
      {
        id: "requested",
        header: t("refunds.columns.requestedBy"),
        meta: { label: t("refunds.columns.requestedBy") },
        cell: ({ row }) => (
          <span className="flex flex-col">
            <span>{names.user(row.original.requested_by)}</span>
            <DateText value={row.original.requested_at} format="datetime" className="text-xs text-muted" />
          </span>
        ),
      },
      {
        id: "amount",
        header: t("refunds.columns.amount"),
        meta: { label: t("refunds.columns.amount"), align: "end" },
        cell: ({ row }) => <MoneyText value={row.original.amount} />,
      },
    ],
    [t, names],
  );

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <PageHeader title={t("refunds.title")} description={t("refunds.description")} icon={<Undo2 />} />
      <CashierNav />
      <Tabs
        value={filter}
        onValueChange={(v) => {
          setFilter(v as Filter);
          setPage(1);
        }}
      >
        <TabsList aria-label={t("refunds.filter")} className="flex h-auto flex-wrap">
          {FILTERS.map((f) => (
            <TabsTrigger key={f} value={f} className="h-9 flex-none">
              {f === "all" ? t("refunds.all") : t(`refunds.status.${f}`)}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>
      {refunds.isError ? (
        <AlertCard variant="danger" title={t("errors:title")}>
          {translateError(refunds.error)}
        </AlertCard>
      ) : (
        <>
          <DataTable
            columns={columns}
            data={refunds.data?.items ?? []}
            loading={refunds.isPending}
            getRowId={(r) => String(r.id)}
            caption={t("refunds.title")}
            rowActions={actions}
            pageSize={PAGE_SIZE}
            pageSizeOptions={[PAGE_SIZE]}
            minTableWidth={820}
            emptyState={<EmptyState bare size="compact" icon={<Undo2 />} title={t("refunds.empty")} />}
            renderCard={(r, ctx) => (
              <div className="card-surface flex flex-col gap-2 p-4" data-testid="refund-row">
                <div className="flex items-start justify-between gap-2">
                  <span className="flex min-w-0 flex-col gap-1">
                    <bdi className="font-semibold">{r.number}</bdi>
                    <Badge variant={STATUS_VARIANT[r.status]}>{t(`refunds.status.${r.status}`)}</Badge>
                  </span>
                  {ctx.actions}
                </div>
                <span className="text-sm">{names.patient(r.patient)}</span>
                <span className="flex flex-wrap gap-x-3 gap-y-1 text-sm text-muted">
                  <bdi>{r.credit_note_number}</bdi>
                  <span>{names.label(r.reason)}</span>
                  <span>{names.user(r.requested_by)}</span>
                </span>
                <MoneyText value={r.amount} className="text-base" />
              </div>
            )}
          />
          <Pager page={page} pageSize={PAGE_SIZE} count={refunds.data?.count ?? 0} onPage={setPage} />
        </>
      )}
      <NoteDialog
        open={deciding !== null}
        onOpenChange={(o) => {
          if (!o) setDeciding(null);
        }}
        title={deciding?.decision === "reject" ? t("refunds.rejectTitle") : t("refunds.approveTitle")}
        description={t("refunds.decisionDescription", { number: deciding?.refund.number ?? "" })}
        label={t("refunds.decisionNote")}
        confirmLabel={deciding?.decision === "reject" ? t("refunds.reject") : t("refunds.approve")}
        destructive={deciding?.decision === "reject"}
        noteRequired={deciding?.decision === "reject"}
        onSubmit={(note) =>
          decide.mutateAsync({
            refundId: deciding?.refund.id ?? 0,
            decision: deciding?.decision ?? "approve",
            note,
          })
        }
      />
      <ConfirmDialog
        open={paying !== null}
        onOpenChange={(o) => {
          if (!o) setPaying(null);
        }}
        title={t("refunds.payTitle", { number: paying?.number ?? "" })}
        description={t("refunds.payDescription")}
        confirmLabel={t("refunds.pay")}
        onConfirm={async () => {
          if (paying) await pay.mutateAsync(paying.id);
        }}
      >
        {paying ? (
          <p className="text-lg font-semibold">
            <MoneyText value={paying.amount} />
          </p>
        ) : null}
      </ConfirmDialog>
    </div>
  );
}
