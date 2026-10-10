import type { ColumnDef } from "@tanstack/react-table";
import { CheckCircle2, Plus, SlidersHorizontal, Trash2, XCircle } from "lucide-react";
import { useMemo, useState, type SyntheticEvent } from "react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { DataTable, type DataTableRowAction } from "@/components/DataTable";
import { DateText } from "@/components/DateText";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { useTranslateError } from "@/lib/api/translate-error";
import { usePermission } from "@/lib/auth/hooks";
import { formatNumber } from "@/lib/format";

import { PAGE_SIZE, useAdjustments, useDecideAdjustment, usePharmacyOptions, useRequestAdjustment } from "../api";
import { DocStatusBadge, ErrorAlert, LabeledField, StoreSelect } from "../components/common";
import { NoteDialog } from "../components/NoteDialog";
import { BatchPicker } from "../components/pickers";
import { PharmacyNav } from "../components/PharmacyNav";
import { parseWhole } from "../lib/qty";
import { useNames } from "../lib/use-names";
import type { AdjustmentStatus, StockAdjustment, StoreBatch } from "../types";

type Filter = AdjustmentStatus | "all";
const FILTERS: readonly Filter[] = ["draft", "approved", "rejected", "all"];

/**
 * Stock adjustments (FEATURES 8.6): requested with a reason, approved by a supervisor other
 * than the requester; stock moves only at approval and never below zero (invariant 5).
 */
export function AdjustmentsPage() {
  const { t } = useTranslation(["pharmacy", "errors"]);
  const translateError = useTranslateError();
  const names = useNames();
  const canRequest = usePermission("pharmacy.request_adjustment");
  const canApprove = usePermission("pharmacy.approve_adjustment");
  const [filter, setFilter] = useState<Filter>("draft");
  const [page, setPage] = useState(1);
  const adjustments = useAdjustments(filter === "all" ? undefined : filter, page);
  const decide = useDecideAdjustment();
  const [creating, setCreating] = useState(false);
  const [deciding, setDeciding] = useState<{ adj: StockAdjustment; decision: "approve" | "reject" } | null>(null);

  const actions = (a: StockAdjustment): DataTableRowAction[] =>
    canApprove && a.status === "draft"
      ? [
          {
            label: t("adjustments.approve"),
            icon: <CheckCircle2 />,
            onSelect: () => {
              setDeciding({ adj: a, decision: "approve" });
            },
          },
          {
            label: t("adjustments.reject"),
            icon: <XCircle />,
            destructive: true,
            onSelect: () => {
              setDeciding({ adj: a, decision: "reject" });
            },
          },
        ]
      : [];

  const lineSummary = (a: StockAdjustment) =>
    a.lines.map((ln) => (
      <span key={ln.id} className="flex flex-wrap gap-x-2">
        <span>{names.item(ln)}</span>
        <bdi className="text-muted">{ln.batch_no}</bdi>
        <bdi className={ln.qty_base < 0 ? "tabular text-danger-fg" : "tabular text-success-fg"}>
          {(ln.qty_base > 0 ? "+" : "") + formatNumber(ln.qty_base, names.language)}
        </bdi>
      </span>
    ));

  const columns = useMemo<ColumnDef<StockAdjustment>[]>(
    () => [
      {
        id: "number",
        header: t("adjustments.columns.number"),
        meta: { label: t("adjustments.columns.number") },
        cell: ({ row }) => (
          <span className="flex flex-col items-start gap-1">
            <bdi className="font-medium">{row.original.number}</bdi>
            <DocStatusBadge status={row.original.status} kind="adjustment" />
          </span>
        ),
      },
      {
        id: "lines",
        header: t("adjustments.columns.lines"),
        meta: { label: t("adjustments.columns.lines") },
        cell: ({ row }) => <span className="flex flex-col gap-0.5 text-sm">{lineSummary(row.original)}</span>,
      },
      {
        id: "reason",
        header: t("adjustments.columns.reason"),
        meta: { label: t("adjustments.columns.reason") },
        cell: ({ row }) => (
          <span className="flex flex-col">
            <span>{names.label(row.original.reason)}</span>
            {row.original.note ? <span className="text-xs text-muted">{row.original.note}</span> : null}
          </span>
        ),
      },
      {
        id: "requested",
        header: t("adjustments.columns.requested"),
        meta: { label: t("adjustments.columns.requested") },
        cell: ({ row }) => (
          <span className="flex flex-col">
            <span>{names.person(row.original.requested_by)}</span>
            <DateText value={row.original.requested_at} format="datetime" className="text-xs text-muted" />
          </span>
        ),
      },
      {
        id: "decided",
        header: t("adjustments.columns.decided"),
        meta: { label: t("adjustments.columns.decided") },
        cell: ({ row }) =>
          row.original.decided_by ? (
            <span className="flex flex-col">
              <span>{names.person(row.original.decided_by)}</span>
              {row.original.decision_note ? (
                <span className="text-xs text-muted">{row.original.decision_note}</span>
              ) : null}
            </span>
          ) : (
            "—"
          ),
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps -- lineSummary depends on names only
    [t, names],
  );

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <PageHeader
        title={t("adjustments.title")}
        description={t("adjustments.description")}
        icon={<SlidersHorizontal />}
        actions={
          canRequest ? (
            <Button
              onClick={() => {
                setCreating(true);
              }}
              data-testid="adjustment-new"
            >
              <Plus aria-hidden="true" />
              {t("adjustments.new")}
            </Button>
          ) : null
        }
      />
      <PharmacyNav />
      <Tabs
        value={filter}
        onValueChange={(v) => {
          setFilter(v as Filter);
          setPage(1);
        }}
      >
        <TabsList aria-label={t("common.filter")} className="flex h-auto flex-wrap">
          {FILTERS.map((f) => (
            <TabsTrigger key={f} value={f} className="h-9 flex-none">
              {f === "all" ? t("common.all") : t(`status.adjustment.${f}`)}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>
      {adjustments.isError ? (
        <AlertCard variant="danger" title={t("errors:title")}>
          {translateError(adjustments.error)}
        </AlertCard>
      ) : (
        <DataTable
          columns={columns}
          data={adjustments.data?.items ?? []}
          loading={adjustments.isPending}
          getRowId={(r) => String(r.id)}
          caption={t("adjustments.title")}
          rowActions={actions}
          serverPagination={{
            page,
            pageSize: PAGE_SIZE,
            count: adjustments.data?.count ?? 0,
            onPageChange: setPage,
          }}
          minTableWidth={900}
          emptyState={<EmptyState bare size="compact" icon={<SlidersHorizontal />} title={t("adjustments.empty")} />}
          renderCard={(a, ctx) => (
            <div className="card-surface flex flex-col gap-2 p-4" data-testid="adjustment-row">
              <div className="flex items-start justify-between gap-2">
                <span className="flex min-w-0 flex-col items-start gap-1">
                  <bdi className="font-semibold">{a.number}</bdi>
                  <DocStatusBadge status={a.status} kind="adjustment" />
                </span>
                {ctx.actions}
              </div>
              <span className="flex flex-col gap-0.5 text-sm">{lineSummary(a)}</span>
              <span className="flex flex-wrap gap-x-3 gap-y-1 text-sm text-muted">
                <span>{names.label(a.reason)}</span>
                <span>{names.person(a.requested_by)}</span>
              </span>
            </div>
          )}
        />
      )}
      <NewAdjustmentDialog open={creating} onOpenChange={setCreating} />
      <NoteDialog
        open={deciding !== null}
        onOpenChange={(o) => {
          if (!o) setDeciding(null);
        }}
        title={deciding?.decision === "reject" ? t("adjustments.rejectTitle") : t("adjustments.approveTitle")}
        description={t("adjustments.decisionDescription", { number: deciding?.adj.number ?? "" })}
        label={t("adjustments.decisionNote")}
        confirmLabel={deciding?.decision === "reject" ? t("adjustments.reject") : t("adjustments.approve")}
        destructive={deciding?.decision === "reject"}
        noteRequired={deciding?.decision === "reject"}
        testId="adjustment-decision"
        onSubmit={(note) =>
          decide.mutateAsync({
            adjustmentId: deciding?.adj.id ?? 0,
            decision: deciding?.decision ?? "approve",
            note,
          })
        }
      />
    </div>
  );
}

interface AdjLine {
  key: number;
  batch: StoreBatch | null;
  direction: "decrease" | "increase";
  qty: string;
}

let adjKey = 0;
function emptyAdjLine(): AdjLine {
  adjKey += 1;
  return { key: adjKey, batch: null, direction: "decrease", qty: "" };
}

function NewAdjustmentDialog(props: { open: boolean; onOpenChange: (open: boolean) => void }) {
  return props.open ? <NewAdjustmentDialogOpen {...props} /> : null;
}

function NewAdjustmentDialogOpen({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const { t } = useTranslation(["pharmacy", "common"]);
  const translateError = useTranslateError();
  const names = useNames();
  const options = usePharmacyOptions();
  const create = useRequestAdjustment();
  const [storeId, setStoreId] = useState<number | undefined>(undefined);
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  const [lines, setLines] = useState<AdjLine[]>(() => [emptyAdjLine()]);
  const [checked, setChecked] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const reasons = options.data?.reasons_stock_adjust ?? [];
  const chosenReason = reasons.find((r) => r.code === reason);
  const noteMissing = Boolean(chosenReason?.requires_note) && !note.trim();

  const setLine = (key: number, patch: Partial<AdjLine>) => {
    setLines((prev) => prev.map((l) => (l.key === key ? { ...l, ...patch } : l)));
  };

  const submit = async (e: SyntheticEvent) => {
    e.preventDefault();
    setChecked(true);
    setError(null);
    if (storeId === undefined || !reason || noteMissing) return;
    if (lines.some((l) => !l.batch || parseWhole(l.qty) === null)) return;
    try {
      await create.mutateAsync({
        store_id: storeId,
        reason_code: reason,
        note: note.trim(),
        lines: lines.map((l) => {
          const qty = parseWhole(l.qty) ?? 0;
          return { batch_id: l.batch?.batch_id ?? 0, qty_base: l.direction === "decrease" ? -qty : qty, note: "" };
        }),
      });
      onOpenChange(false);
    } catch (err) {
      setError(translateError(err));
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!create.isPending) onOpenChange(o);
      }}
    >
      <DialogContent className="max-h-[92dvh] overflow-y-auto sm:max-w-2xl" data-testid="adjustment-dialog">
        <DialogHeader>
          <DialogTitle>{t("adjustments.newTitle")}</DialogTitle>
          <DialogDescription>{t("adjustments.newDescription")}</DialogDescription>
        </DialogHeader>
        <form onSubmit={(e) => void submit(e)} noValidate className="grid gap-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <StoreSelect
              stores={options.data?.stores ?? []}
              value={storeId}
              onChange={(v) => {
                setStoreId(v);
                setLines([emptyAdjLine()]);
              }}
              label={t("adjustments.fields.store")}
              testId="adjustment-store"
            />
            <LabeledField
              label={t("adjustments.fields.reason")}
              required
              error={checked && !reason ? t("common.required") : null}
            >
              {(id) => (
                <Select value={reason} onValueChange={setReason}>
                  <SelectTrigger id={id} className="h-11 w-full md:h-10" data-testid="adjustment-reason">
                    <SelectValue placeholder={t("common.chooseReason")} />
                  </SelectTrigger>
                  <SelectContent>
                    {reasons.map((r) => (
                      <SelectItem key={r.code} value={r.code}>
                        {names.label(r)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </LabeledField>
          </div>
          <LabeledField
            label={t("adjustments.fields.note")}
            required={Boolean(chosenReason?.requires_note)}
            error={checked && noteMissing ? t("common.required") : null}
          >
            {(id) => (
              <Textarea
                id={id}
                rows={2}
                maxLength={1000}
                value={note}
                data-testid="adjustment-note"
                onChange={(e) => {
                  setNote(e.target.value);
                }}
              />
            )}
          </LabeledField>
          <fieldset className="grid gap-3">
            <legend className="mb-2 text-sm font-semibold">{t("adjustments.lines")}</legend>
            {lines.map((line) => (
              <div
                key={line.key}
                className="grid gap-3 rounded-control border border-border p-3"
                data-testid="adjustment-line"
              >
                <BatchPicker
                  label={t("adjustments.fields.batch")}
                  storeId={storeId}
                  value={line.batch}
                  onChange={(batch) => {
                    setLine(line.key, { batch });
                  }}
                  testId="adjustment-batch"
                  error={checked && !line.batch ? t("common.required") : null}
                />
                <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] sm:items-end">
                  <LabeledField label={t("adjustments.fields.direction")}>
                    {(id) => (
                      <Select
                        value={line.direction}
                        onValueChange={(v) => {
                          setLine(line.key, { direction: v as AdjLine["direction"] });
                        }}
                      >
                        <SelectTrigger id={id} className="h-11 w-full md:h-10" data-testid="adjustment-direction">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="decrease">{t("adjustments.decrease")}</SelectItem>
                          <SelectItem value="increase">{t("adjustments.increase")}</SelectItem>
                        </SelectContent>
                      </Select>
                    )}
                  </LabeledField>
                  <LabeledField
                    label={t("adjustments.fields.quantity")}
                    required
                    error={checked && parseWhole(line.qty) === null ? t("validation.wholeNumber") : null}
                  >
                    {(id) => (
                      <Input
                        id={id}
                        value={line.qty}
                        inputMode="numeric"
                        dir="ltr"
                        data-testid="adjustment-qty"
                        onChange={(e) => {
                          setLine(line.key, { qty: e.target.value });
                        }}
                      />
                    )}
                  </LabeledField>
                  {lines.length > 1 ? (
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      aria-label={t("receipts.removeLine")}
                      onClick={() => {
                        setLines((prev) => prev.filter((l) => l.key !== line.key));
                      }}
                    >
                      <Trash2 aria-hidden="true" />
                    </Button>
                  ) : null}
                </div>
              </div>
            ))}
            <div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => {
                  setLines((prev) => [...prev, emptyAdjLine()]);
                }}
              >
                <Plus aria-hidden="true" />
                {t("receipts.addLine")}
              </Button>
            </div>
          </fieldset>
          <ErrorAlert message={error} />
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
            <Button type="submit" loading={create.isPending} data-testid="adjustment-save">
              {t("adjustments.submit")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
