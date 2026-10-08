import { useNavigate } from "@tanstack/react-router";
import type { ColumnDef } from "@tanstack/react-table";
import { CheckCircle2, FileMinus, Undo2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { DataTable, type DataTableRowAction } from "@/components/DataTable";
import { DateText } from "@/components/DateText";
import { EmptyState } from "@/components/EmptyState";
import { CheckboxField, Form } from "@/components/form";
import { MoneyText } from "@/components/MoneyText";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useTranslateError } from "@/lib/api/translate-error";
import { usePermission } from "@/lib/auth/hooks";

import { PAGE_SIZE, useApproveCreditNote, useCreditNotes } from "../api";
import { CashierNav } from "../components/CashierNav";
import { Pager } from "../components/Pager";
import { RefundRequestDialog } from "../components/RefundRequestDialog";
import { isPositiveAmount } from "../lib/money";
import { useNames } from "../lib/use-names";
import type { CreditNote, DocStatus } from "../types";

type Filter = "draft" | "approved" | "all";

/** Credit notes (FEATURES 5.11): the supervisor's approval queue and refund requests. */
export function CreditNotesPage() {
  const { t } = useTranslation(["cashier", "errors"]);
  const translateError = useTranslateError();
  const names = useNames();
  const navigate = useNavigate();
  const [filter, setFilter] = useState<Filter>("draft");
  const [page, setPage] = useState(1);
  const notes = useCreditNotes(filter === "all" ? undefined : (filter as DocStatus), page);
  const canApprove = usePermission("billing.approve_credit_note");
  const canRefund = usePermission("payments.request_refund");
  const [approving, setApproving] = useState<CreditNote | null>(null);
  const [refunding, setRefunding] = useState<CreditNote | null>(null);

  const actions = (cn: CreditNote): DataTableRowAction[] => {
    const out: DataTableRowAction[] = [];
    if (canApprove && cn.status === "draft")
      out.push({
        label: t("creditNotes.approve"),
        icon: <CheckCircle2 />,
        onSelect: () => {
          setApproving(cn);
        },
      });
    const openRefund = cn.refunds.some((r) => r.status === "requested" || r.status === "approved");
    if (canRefund && cn.status === "approved" && isPositiveAmount(cn.refundable) && !openRefund)
      out.push({
        label: t("refunds.request"),
        icon: <Undo2 />,
        onSelect: () => {
          setRefunding(cn);
        },
      });
    out.push({
      label: t("creditNotes.openVisit"),
      onSelect: () => {
        void navigate({ to: "/cashier", search: { q: cn.patient.file_no } });
      },
      separated: out.length > 0,
    });
    return out;
  };

  const columns = useMemo<ColumnDef<CreditNote>[]>(
    () => [
      {
        id: "number",
        header: t("creditNotes.columns.number"),
        meta: { label: t("creditNotes.columns.number") },
        cell: ({ row }) => (
          <span className="flex flex-col gap-1">
            <bdi className="font-medium">{row.original.number ?? t("invoice.draft")}</bdi>
            <Badge variant={row.original.status === "approved" ? "success" : "warning"}>
              {t(`invoice.status.${row.original.status}`)}
            </Badge>
          </span>
        ),
      },
      {
        id: "invoice",
        header: t("creditNotes.columns.invoice"),
        meta: { label: t("creditNotes.columns.invoice") },
        cell: ({ row }) => <bdi>{row.original.invoice_number}</bdi>,
      },
      {
        id: "patient",
        header: t("creditNotes.columns.patient"),
        meta: { label: t("creditNotes.columns.patient") },
        cell: ({ row }) => names.patient(row.original.patient),
      },
      {
        id: "reason",
        header: t("creditNotes.columns.reason"),
        meta: { label: t("creditNotes.columns.reason") },
        cell: ({ row }) => names.label(row.original.reason),
      },
      {
        id: "amount",
        header: t("creditNotes.columns.patientAmount"),
        meta: { label: t("creditNotes.columns.patientAmount"), align: "end" },
        cell: ({ row }) => <MoneyText value={row.original.patient_total} />,
      },
      {
        id: "refundable",
        header: t("creditNotes.refundable"),
        meta: { label: t("creditNotes.refundable"), align: "end" },
        cell: ({ row }) => <MoneyText value={row.original.refundable} />,
      },
    ],
    [t, names],
  );

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <PageHeader title={t("creditNotes.title")} description={t("creditNotes.description")} icon={<FileMinus />} />
      <CashierNav />
      <Tabs
        value={filter}
        onValueChange={(v) => {
          setFilter(v as Filter);
          setPage(1);
        }}
      >
        <TabsList aria-label={t("creditNotes.filter")}>
          <TabsTrigger value="draft">{t("creditNotes.filters.draft")}</TabsTrigger>
          <TabsTrigger value="approved">{t("creditNotes.filters.approved")}</TabsTrigger>
          <TabsTrigger value="all">{t("creditNotes.filters.all")}</TabsTrigger>
        </TabsList>
      </Tabs>
      {notes.isError ? (
        <AlertCard variant="danger" title={t("errors:title")}>
          {translateError(notes.error)}
        </AlertCard>
      ) : (
        <>
          <DataTable
            columns={columns}
            data={notes.data?.items ?? []}
            loading={notes.isPending}
            getRowId={(r) => String(r.id)}
            caption={t("creditNotes.title")}
            rowActions={actions}
            pageSize={PAGE_SIZE}
            pageSizeOptions={[PAGE_SIZE]}
            minTableWidth={820}
            emptyState={<EmptyState bare size="compact" icon={<FileMinus />} title={t("creditNotes.empty")} />}
            renderCard={(cn, ctx) => (
              <div className="card-surface flex flex-col gap-2 p-4" data-testid="credit-note-row">
                <div className="flex items-start justify-between gap-2">
                  <span className="flex min-w-0 flex-col gap-1">
                    <bdi className="font-semibold">{cn.number ?? t("invoice.draft")}</bdi>
                    <Badge variant={cn.status === "approved" ? "success" : "warning"}>
                      {t(`invoice.status.${cn.status}`)}
                    </Badge>
                  </span>
                  {ctx.actions}
                </div>
                <span className="text-sm">{names.patient(cn.patient)}</span>
                <span className="flex flex-wrap gap-x-3 gap-y-1 text-sm text-muted">
                  <bdi>{cn.invoice_number}</bdi>
                  <span>{names.label(cn.reason)}</span>
                  <DateText value={cn.created_at} format="datetime" />
                </span>
                <span className="flex flex-wrap justify-between gap-2 text-sm">
                  <MoneyText value={cn.patient_total} />
                  <span>
                    {t("creditNotes.refundable")} <MoneyText value={cn.refundable} />
                  </span>
                </span>
              </div>
            )}
          />
          <Pager page={page} pageSize={PAGE_SIZE} count={notes.data?.count ?? 0} onPage={setPage} />
        </>
      )}
      <ApproveDialog
        creditNote={approving}
        onOpenChange={(o) => {
          if (!o) setApproving(null);
        }}
      />
      <RefundRequestDialog
        creditNote={refunding}
        onOpenChange={(o) => {
          if (!o) setRefunding(null);
        }}
      />
    </div>
  );
}

function ApproveDialog({
  creditNote,
  onOpenChange,
}: {
  creditNote: CreditNote | null;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useTranslation(["cashier", "common", "errors"]);
  const translateError = useTranslateError();
  const names = useNames();
  const approve = useApproveCreditNote();
  const [error, setError] = useState<string | null>(null);
  const form = useForm<{ openRefund: boolean; rebill: boolean }>({
    defaultValues: { openRefund: true, rebill: false },
  });
  const { reset } = form;
  useEffect(() => {
    if (creditNote) {
      reset({ openRefund: true, rebill: false });
      setError(null);
    }
  }, [creditNote, reset]);
  const submit = form.handleSubmit(async (v) => {
    if (!creditNote) return;
    setError(null);
    try {
      await approve.mutateAsync({
        creditNoteId: creditNote.id,
        body: { open_refund: v.openRefund, rebill: v.rebill },
      });
      onOpenChange(false);
    } catch (e) {
      setError(translateError(e));
    }
  });
  return (
    <Dialog open={creditNote !== null} onOpenChange={onOpenChange}>
      <DialogContent data-testid="approve-credit-note-dialog">
        <DialogHeader>
          <DialogTitle>{t("creditNotes.approveTitle")}</DialogTitle>
          <DialogDescription>{t("creditNotes.approveDescription")}</DialogDescription>
        </DialogHeader>
        {creditNote ? (
          <ul className="flex flex-col gap-1 rounded-control bg-subtle px-3 py-2 text-sm">
            {creditNote.lines.map((l) => (
              <li key={l.id} className="flex flex-wrap items-center justify-between gap-2">
                <span>{t("creditNotes.lineQty", { name: names.name(l.service), qty: l.quantity })}</span>
                <MoneyText value={l.patient_share} />
              </li>
            ))}
            <li className="text-muted">
              {names.label(creditNote.reason)}
              {creditNote.reason_note ? ` · ${creditNote.reason_note}` : ""}
            </li>
          </ul>
        ) : null}
        <Form {...form}>
          <form onSubmit={(e) => void submit(e)} noValidate className="grid gap-3">
            <CheckboxField control={form.control} name="openRefund" label={t("creditNotes.openRefund")} />
            <CheckboxField
              control={form.control}
              name="rebill"
              label={t("creditNotes.rebill")}
              description={t("creditNotes.rebillHint")}
            />
            {error ? (
              <AlertCard variant="danger" title={t("errors:title")} live>
                {error}
              </AlertCard>
            ) : null}
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  onOpenChange(false);
                }}
              >
                {t("common:actions.cancel")}
              </Button>
              <Button type="submit" loading={form.formState.isSubmitting} data-testid="approve-credit-note">
                {t("creditNotes.approve")}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
