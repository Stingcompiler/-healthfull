import { useNavigate, useSearch } from "@tanstack/react-router";
import type { ColumnDef } from "@tanstack/react-table";
import { Banknote, BadgeCheck, Plus, Undo2 } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { Can } from "@/components/Can";
import { DataTable, type DataTableRowAction } from "@/components/DataTable";
import { DateText } from "@/components/DateText";
import { EmptyState } from "@/components/EmptyState";
import { MoneyText } from "@/components/MoneyText";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { NoteDialog } from "@/features/cashier/components/NoteDialog";
import { useTranslateError } from "@/lib/api/translate-error";
import { usePermission } from "@/lib/auth/hooks";

import {
  PAGE_SIZE,
  useClaimOptions,
  useClearCheque,
  usePayerPayments,
  useReversePayerPayment,
  type PaymentFilter,
} from "../api";
import { PaymentStandingBadge } from "../components/ClaimBadges";
import { ClaimsNav } from "../components/ClaimsNav";
import { RecordPaymentDialog } from "../components/RecordPaymentDialog";
import { useClaimNames } from "../lib/names";
import type { ClaimsSearch } from "../lib/search";
import type { ClaimPayerPayment } from "../types";

const ALL = "all";

/** The claims a payment paid, "CLM-… · CLM-…" (each claim once). */
function PaidClaims({ payment }: { payment: ClaimPayerPayment }) {
  const numbers = [...new Set(payment.allocations.map((a) => a.claim_number))];
  return (
    <span className="flex flex-wrap gap-x-2 text-xs text-muted">
      {numbers.map((n) => (
        <bdi key={n}>{n}</bdi>
      ))}
    </span>
  );
}

/**
 * Payer payments (FEATURES 11.6): every payment with where its money stands (bank, a drawer,
 * a cheque still to clear, reversed) and the claims it paid. Cheques are cleared here, and a
 * bounced transfer or cheque is reversed with a reason.
 */
export function PayerPaymentsPage() {
  const { t } = useTranslation(["claims", "errors"]);
  const translateError = useTranslateError();
  const names = useClaimNames();
  const navigate = useNavigate();
  const search: ClaimsSearch = useSearch({ strict: false });
  const [filter, setFilter] = useState<PaymentFilter | typeof ALL>(ALL);
  const [page, setPage] = useState(1);
  const options = useClaimOptions();
  const payments = usePayerPayments({
    payerId: search.payer,
    standing: filter === ALL ? undefined : filter,
    page,
  });
  const canRecord = usePermission("claims.record_payer_payment");
  const clear = useClearCheque();
  const reverse = useReversePayerPayment();
  const [recording, setRecording] = useState(false);
  const [recorded, setRecorded] = useState<ClaimPayerPayment | null>(null);
  const [clearing, setClearing] = useState<ClaimPayerPayment | null>(null);
  const [reversing, setReversing] = useState<ClaimPayerPayment | null>(null);

  const actions = (row: ClaimPayerPayment): DataTableRowAction[] => {
    const out: DataTableRowAction[] = [];
    if (!canRecord) return out;
    if (row.standing === "cheque_pending")
      out.push({
        label: t("payments.clear"),
        icon: <BadgeCheck />,
        onSelect: () => {
          setClearing(row);
        },
      });
    if (row.standing !== "reversed" && row.standing !== "cash")
      out.push({
        label: t("payments.reverse"),
        icon: <Undo2 />,
        destructive: true,
        onSelect: () => {
          setReversing(row);
        },
      });
    return out;
  };

  const columns = useMemo<ColumnDef<ClaimPayerPayment>[]>(
    () => [
      {
        id: "number",
        header: t("payments.columns.number"),
        meta: { label: t("payments.columns.number") },
        cell: ({ row }) => (
          <span className="flex flex-col gap-1">
            <bdi className="font-medium">{row.original.number}</bdi>
            <PaymentStandingBadge standing={row.original.standing} />
          </span>
        ),
      },
      {
        id: "payer",
        header: t("payments.columns.payer"),
        meta: { label: t("payments.columns.payer"), className: "whitespace-normal" },
        cell: ({ row }) => (
          <span className="flex min-w-0 flex-col">
            <span>{names.name(row.original.payer)}</span>
            <PaidClaims payment={row.original} />
          </span>
        ),
      },
      {
        id: "method",
        header: t("payments.columns.method"),
        meta: { label: t("payments.columns.method"), className: "whitespace-normal" },
        cell: ({ row }) => <MethodCell payment={row.original} />,
      },
      {
        id: "received",
        header: t("payments.columns.received"),
        meta: { label: t("payments.columns.received") },
        cell: ({ row }) => <DateText value={row.original.received_on} />,
      },
      {
        id: "amount",
        header: t("payments.columns.amount"),
        meta: { label: t("payments.columns.amount"), align: "end" },
        cell: ({ row }) => <MoneyText value={row.original.amount} />,
      },
    ],
    [t, names],
  );

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <PageHeader
        title={t("payments.title")}
        description={t("payments.description")}
        icon={<Banknote />}
        actions={
          <Can permission="claims.record_payer_payment">
            <Button
              onClick={() => {
                setRecording(true);
              }}
              data-testid="record-payer-payment"
            >
              <Plus aria-hidden="true" />
              {t("payments.record")}
            </Button>
          </Can>
        }
      />
      <ClaimsNav />
      {recorded ? (
        <AlertCard
          variant="success"
          title={t("payments.recordedTitle", { number: recorded.number })}
          live
          onDismiss={() => {
            setRecorded(null);
          }}
        >
          <span className="flex flex-wrap items-center gap-x-2" data-testid="payment-recorded">
            <MoneyText value={recorded.amount} />
            <span>{t(`standingHint.${recorded.standing}`)}</span>
          </span>
        </AlertCard>
      ) : null}
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <Tabs
          value={filter}
          onValueChange={(v) => {
            setFilter(v as PaymentFilter | typeof ALL);
            setPage(1);
          }}
        >
          <TabsList aria-label={t("payments.filter")}>
            <TabsTrigger value={ALL}>{t("payments.all")}</TabsTrigger>
            <TabsTrigger value="cheque_pending">{t("standing.cheque_pending")}</TabsTrigger>
            <TabsTrigger value="reversed">{t("standing.reversed")}</TabsTrigger>
          </TabsList>
        </Tabs>
        <Select
          value={search.payer ? String(search.payer) : ALL}
          onValueChange={(v) => {
            setPage(1);
            void navigate({ to: "/claims/payments", search: v === ALL ? {} : { payer: Number(v) } });
          }}
        >
          <SelectTrigger className="h-11 w-full lg:w-72" aria-label={t("list.payerFilter")}>
            <SelectValue placeholder={t("list.allPayers")} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>{t("list.allPayers")}</SelectItem>
            {(options.data?.payers ?? []).map((p) => (
              <SelectItem key={p.id} value={String(p.id)}>
                {names.name(p)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      {payments.isError ? (
        <AlertCard variant="danger" title={t("errors:title")}>
          {translateError(payments.error)}
        </AlertCard>
      ) : (
        <DataTable
          columns={columns}
          data={payments.data?.items ?? []}
          loading={payments.isPending}
          getRowId={(r) => String(r.id)}
          caption={t("payments.title")}
          rowActions={actions}
          serverPagination={{ page, pageSize: PAGE_SIZE, count: payments.data?.count ?? 0, onPageChange: setPage }}
          minTableWidth={820}
          emptyState={<EmptyState bare size="compact" icon={<Banknote />} title={t("payments.empty")} />}
          renderCard={(r, ctx) => (
            <div className="card-surface flex flex-col gap-2 p-4" data-testid="payer-payment-row">
              <div className="flex items-start justify-between gap-2">
                <span className="flex min-w-0 flex-col gap-1">
                  <bdi className="font-semibold">{r.number}</bdi>
                  <PaymentStandingBadge standing={r.standing} />
                </span>
                {ctx.actions}
              </div>
              <span className="text-sm">{names.name(r.payer)}</span>
              <PaidClaims payment={r} />
              <MethodCell payment={r} />
              <span className="flex flex-wrap items-center justify-between gap-2 text-sm">
                <DateText value={r.received_on} />
                <MoneyText value={r.amount} className="text-base" />
              </span>
            </div>
          )}
        />
      )}
      <RecordPaymentDialog
        open={recording}
        payerId={search.payer}
        onOpenChange={setRecording}
        onRecorded={setRecorded}
      />
      <NoteDialog
        open={clearing !== null}
        onOpenChange={(o) => {
          if (!o) setClearing(null);
        }}
        title={t("payments.clearTitle", { number: clearing?.number ?? "" })}
        description={t("payments.clearDescription")}
        label={t("payments.clearNote")}
        confirmLabel={t("payments.clear")}
        noteRequired={false}
        testId="clear-cheque-dialog"
        onSubmit={(note) => clear.mutateAsync({ paymentId: clearing?.id ?? 0, note })}
      />
      <NoteDialog
        open={reversing !== null}
        onOpenChange={(o) => {
          if (!o) setReversing(null);
        }}
        title={t("payments.reverseTitle", { number: reversing?.number ?? "" })}
        description={t("payments.reverseDescription")}
        label={t("payments.reverseReason")}
        confirmLabel={t("payments.reverse")}
        destructive
        noteRequired
        testId="reverse-payment-dialog"
        onSubmit={(note) => reverse.mutateAsync({ paymentId: reversing?.id ?? 0, note })}
      />
    </div>
  );
}

/** How the money came: transfer (bank and reference), cheque (number), or cash (shift). */
function MethodCell({ payment }: { payment: ClaimPayerPayment }) {
  const { t } = useTranslation("claims");
  const names = useClaimNames();
  return (
    <span className="flex min-w-0 flex-col text-sm">
      <span>{t(`method.${payment.method}`)}</span>
      {payment.bank ? <span className="text-xs text-muted">{names.name(payment.bank)}</span> : null}
      {payment.reference ? (
        <span className="text-xs break-all text-muted">
          <bdi>{payment.reference}</bdi>
        </span>
      ) : null}
      {payment.shift ? (
        <span className="text-xs text-muted">
          {t("payments.shift")}: <bdi>{payment.shift.number}</bdi>
        </span>
      ) : null}
    </span>
  );
}
