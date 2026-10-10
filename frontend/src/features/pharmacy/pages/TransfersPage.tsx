import type { ColumnDef } from "@tanstack/react-table";
import { ArrowLeftRight, PackageCheck, Plus, Send, Trash2, XCircle } from "lucide-react";
import { useMemo, useState, type SyntheticEvent } from "react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { ConfirmDialog } from "@/components/ConfirmDialog";
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
import { useTranslateError } from "@/lib/api/translate-error";
import { usePermission } from "@/lib/auth/hooks";
import { formatNumber } from "@/lib/format";

import {
  PAGE_SIZE,
  useCancelTransfer,
  useCreateTransfer,
  usePharmacyOptions,
  useReceiveTransfer,
  useSendTransfer,
  useTransfers,
} from "../api";
import { ApproverInputs, DocStatusBadge, ErrorAlert, LabeledField, StoreSelect } from "../components/common";
import { NoteDialog } from "../components/NoteDialog";
import { BatchPicker } from "../components/pickers";
import { PharmacyNav } from "../components/PharmacyNav";
import { approverPayload, NO_APPROVER, type ApproverState } from "../lib/approver";
import { parseWhole } from "../lib/qty";
import { useNames } from "../lib/use-names";
import type { StockTransfer, StoreBatch, TransferStatus } from "../types";

type Filter = TransferStatus | "all";
const FILTERS: readonly Filter[] = ["draft", "sent", "received", "cancelled", "all"];

/**
 * Transfers between stores (FEATURES 8.10): stock leaves the source when sent and enters the
 * destination when received; a shortage needs a reason and an approver (invariant 4).
 */
export function TransfersPage() {
  const { t } = useTranslation(["pharmacy", "errors"]);
  const translateError = useTranslateError();
  const names = useNames();
  const canTransfer = usePermission("pharmacy.transfer_stock");
  const [filter, setFilter] = useState<Filter>("all");
  const [page, setPage] = useState(1);
  const transfers = useTransfers(filter === "all" ? undefined : filter, page);
  const send = useSendTransfer();
  const cancel = useCancelTransfer();
  const [creating, setCreating] = useState(false);
  const [sending, setSending] = useState<StockTransfer | null>(null);
  const [receiving, setReceiving] = useState<StockTransfer | null>(null);
  const [cancelling, setCancelling] = useState<StockTransfer | null>(null);

  const actions = (tr: StockTransfer): DataTableRowAction[] => {
    if (!canTransfer) return [];
    const out: DataTableRowAction[] = [];
    if (tr.status === "draft")
      out.push({
        label: t("transfers.send"),
        icon: <Send />,
        onSelect: () => {
          setSending(tr);
        },
      });
    if (tr.status === "sent")
      out.push({
        label: t("transfers.receive"),
        icon: <PackageCheck />,
        onSelect: () => {
          setReceiving(tr);
        },
      });
    if (tr.status === "draft" || tr.status === "sent")
      out.push({
        label: t("transfers.cancel"),
        icon: <XCircle />,
        destructive: true,
        onSelect: () => {
          setCancelling(tr);
        },
      });
    return out;
  };

  const lines = (tr: StockTransfer) =>
    tr.lines.map((ln) => (
      <span key={ln.id} className="flex flex-wrap gap-x-2">
        <span>{names.item(ln)}</span>
        <bdi className="text-muted">{ln.batch_no}</bdi>
        <bdi className="tabular">{formatNumber(ln.qty_base, names.language)}</bdi>
      </span>
    ));

  const columns = useMemo<ColumnDef<StockTransfer>[]>(
    () => [
      {
        id: "number",
        header: t("transfers.columns.number"),
        meta: { label: t("transfers.columns.number") },
        cell: ({ row }) => (
          <span className="flex flex-col items-start gap-1">
            <bdi className="font-medium">{row.original.number}</bdi>
            <DocStatusBadge status={row.original.status} kind="transfer" />
          </span>
        ),
      },
      {
        id: "route",
        header: t("transfers.columns.route"),
        meta: { label: t("transfers.columns.route") },
        cell: ({ row }) =>
          t("transfers.route", { from: names.name(row.original.from_store), to: names.name(row.original.to_store) }),
      },
      {
        id: "lines",
        header: t("transfers.columns.lines"),
        meta: { label: t("transfers.columns.lines") },
        cell: ({ row }) => <span className="flex flex-col gap-0.5 text-sm">{lines(row.original)}</span>,
      },
      {
        id: "created",
        header: t("transfers.columns.created"),
        meta: { label: t("transfers.columns.created") },
        cell: ({ row }) => (
          <span className="flex flex-col">
            <span>{names.person(row.original.created_by)}</span>
            <DateText value={row.original.created_at} format="datetime" className="text-xs text-muted" />
          </span>
        ),
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps -- lines depends on names only
    [t, names],
  );

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <PageHeader
        title={t("transfers.title")}
        description={t("transfers.description")}
        icon={<ArrowLeftRight />}
        actions={
          canTransfer ? (
            <Button
              onClick={() => {
                setCreating(true);
              }}
              data-testid="transfer-new"
            >
              <Plus aria-hidden="true" />
              {t("transfers.new")}
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
              {f === "all" ? t("common.all") : t(`status.transfer.${f}`)}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>
      {transfers.isError ? (
        <AlertCard variant="danger" title={t("errors:title")}>
          {translateError(transfers.error)}
        </AlertCard>
      ) : (
        <DataTable
          columns={columns}
          data={transfers.data?.items ?? []}
          loading={transfers.isPending}
          getRowId={(r) => String(r.id)}
          caption={t("transfers.title")}
          rowActions={actions}
          serverPagination={{ page, pageSize: PAGE_SIZE, count: transfers.data?.count ?? 0, onPageChange: setPage }}
          minTableWidth={820}
          emptyState={<EmptyState bare size="compact" icon={<ArrowLeftRight />} title={t("transfers.empty")} />}
          renderCard={(tr, ctx) => (
            <div className="card-surface flex flex-col gap-2 p-4" data-testid="transfer-row">
              <div className="flex items-start justify-between gap-2">
                <span className="flex min-w-0 flex-col items-start gap-1">
                  <bdi className="font-semibold">{tr.number}</bdi>
                  <DocStatusBadge status={tr.status} kind="transfer" />
                </span>
                {ctx.actions}
              </div>
              <span className="text-sm">
                {t("transfers.route", { from: names.name(tr.from_store), to: names.name(tr.to_store) })}
              </span>
              <span className="flex flex-col gap-0.5 text-sm text-muted">{lines(tr)}</span>
            </div>
          )}
        />
      )}
      <NewTransferDialog open={creating} onOpenChange={setCreating} />
      <ConfirmDialog
        open={sending !== null}
        onOpenChange={(o) => {
          if (!o) setSending(null);
        }}
        title={t("transfers.sendTitle", { number: sending?.number ?? "" })}
        description={t("transfers.sendDescription")}
        confirmLabel={t("transfers.send")}
        onConfirm={async () => {
          if (sending) await send.mutateAsync(sending.id);
        }}
      />
      <ReceiveDialog
        transfer={receiving}
        onClose={() => {
          setReceiving(null);
        }}
      />
      <NoteDialog
        open={cancelling !== null}
        onOpenChange={(o) => {
          if (!o) setCancelling(null);
        }}
        title={t("transfers.cancelTitle", { number: cancelling?.number ?? "" })}
        description={
          cancelling?.status === "sent" ? t("transfers.cancelSentDescription") : t("transfers.cancelDescription")
        }
        label={t("transfers.cancelNote")}
        confirmLabel={t("transfers.cancel")}
        destructive
        noteRequired={cancelling?.status === "sent"}
        onSubmit={(note) => cancel.mutateAsync({ transferId: cancelling?.id ?? 0, note })}
      />
    </div>
  );
}

interface TrLine {
  key: number;
  batch: StoreBatch | null;
  qty: string;
}

let trKey = 0;
function emptyTrLine(): TrLine {
  trKey += 1;
  return { key: trKey, batch: null, qty: "" };
}

function NewTransferDialog(props: { open: boolean; onOpenChange: (open: boolean) => void }) {
  return props.open ? <NewTransferDialogOpen {...props} /> : null;
}

function NewTransferDialogOpen({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const { t } = useTranslation(["pharmacy", "common"]);
  const translateError = useTranslateError();
  const options = usePharmacyOptions();
  const create = useCreateTransfer();
  const [fromId, setFromId] = useState<number | undefined>(undefined);
  const [toId, setToId] = useState<number | undefined>(undefined);
  const [lines, setLines] = useState<TrLine[]>(() => [emptyTrLine()]);
  const [checked, setChecked] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const stores = options.data?.stores ?? [];
  const sameStore = fromId !== undefined && fromId === toId;

  const setLine = (key: number, patch: Partial<TrLine>) => {
    setLines((prev) => prev.map((l) => (l.key === key ? { ...l, ...patch } : l)));
  };

  const submit = async (e: SyntheticEvent) => {
    e.preventDefault();
    setChecked(true);
    setError(null);
    if (fromId === undefined || toId === undefined || sameStore) return;
    if (lines.some((l) => !l.batch || parseWhole(l.qty) === null)) return;
    try {
      await create.mutateAsync({
        from_store_id: fromId,
        to_store_id: toId,
        note: "",
        lines: lines.map((l) => ({ batch_id: l.batch?.batch_id ?? 0, qty_base: parseWhole(l.qty) ?? 0 })),
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
      <DialogContent className="max-h-[92dvh] overflow-y-auto sm:max-w-2xl" data-testid="transfer-dialog">
        <DialogHeader>
          <DialogTitle>{t("transfers.newTitle")}</DialogTitle>
          <DialogDescription>{t("transfers.newDescription")}</DialogDescription>
        </DialogHeader>
        <form onSubmit={(e) => void submit(e)} noValidate className="grid gap-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <StoreSelect
              stores={stores}
              value={fromId}
              onChange={(v) => {
                setFromId(v);
                setLines([emptyTrLine()]);
              }}
              label={t("transfers.fields.from")}
              testId="transfer-from"
            />
            <StoreSelect
              stores={stores}
              value={toId}
              onChange={setToId}
              label={t("transfers.fields.to")}
              testId="transfer-to"
            />
          </div>
          {checked && (fromId === undefined || toId === undefined) ? (
            <p role="alert" className="text-xs font-medium text-danger-fg">
              {t("transfers.storesRequired")}
            </p>
          ) : null}
          {sameStore ? (
            <p role="alert" className="text-xs font-medium text-danger-fg">
              {t("transfers.sameStore")}
            </p>
          ) : null}
          <fieldset className="grid gap-3">
            <legend className="mb-2 text-sm font-semibold">{t("transfers.lines")}</legend>
            {lines.map((line) => (
              <div
                key={line.key}
                className="grid gap-3 rounded-control border border-border p-3"
                data-testid="transfer-line"
              >
                <BatchPicker
                  label={t("transfers.fields.batch")}
                  storeId={fromId}
                  value={line.batch}
                  onChange={(batch) => {
                    setLine(line.key, { batch });
                  }}
                  testId="transfer-batch"
                  error={checked && !line.batch ? t("common.required") : null}
                />
                <div className="flex items-end gap-2">
                  <LabeledField
                    label={t("transfers.fields.quantity")}
                    required
                    className="flex-1"
                    error={checked && parseWhole(line.qty) === null ? t("validation.wholeNumber") : null}
                  >
                    {(id) => (
                      <Input
                        id={id}
                        value={line.qty}
                        inputMode="numeric"
                        dir="ltr"
                        data-testid="transfer-qty"
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
                  setLines((prev) => [...prev, emptyTrLine()]);
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
            <Button type="submit" loading={create.isPending} data-testid="transfer-save">
              {t("transfers.saveDraft")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function ReceiveDialog({ transfer, onClose }: { transfer: StockTransfer | null; onClose: () => void }) {
  return transfer ? <ReceiveDialogOpen transfer={transfer} onClose={onClose} /> : null;
}

function ReceiveDialogOpen({ transfer, onClose }: { transfer: StockTransfer; onClose: () => void }) {
  const { t } = useTranslation(["pharmacy", "common"]);
  const translateError = useTranslateError();
  const names = useNames();
  const options = usePharmacyOptions();
  const receive = useReceiveTransfer();
  const [got, setGot] = useState<Record<number, string>>(() =>
    Object.fromEntries(transfer.lines.map((l) => [l.id, String(l.qty_base)])),
  );
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  const [approver, setApprover] = useState<ApproverState>(NO_APPROVER);
  const [checked, setChecked] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const parsed = transfer.lines.map((l) => ({ line: l, qty: parseWhole(got[l.id] ?? "", 0) }));
  const invalid = parsed.some((p) => p.qty === null || p.qty > p.line.qty_base);
  const short = parsed.some((p) => p.qty !== null && p.qty < p.line.qty_base);
  const reasons = options.data?.reasons_stock_adjust ?? [];

  const submit = async (e: SyntheticEvent) => {
    e.preventDefault();
    setChecked(true);
    setError(null);
    if (invalid || (short && !reason)) return;
    try {
      await receive.mutateAsync({
        transferId: transfer.id,
        body: {
          lines: short ? parsed.map((p) => ({ line_id: p.line.id, qty_base: p.qty ?? 0 })) : null,
          shortage_reason: short ? reason : null,
          shortage_note: short ? note.trim() : "",
          approver: short ? approverPayload(approver) : null,
        },
      });
      onClose();
    } catch (err) {
      setError(translateError(err));
    }
  };

  return (
    <Dialog
      open
      onOpenChange={(o) => {
        if (!o && !receive.isPending) onClose();
      }}
    >
      <DialogContent className="max-h-[92dvh] overflow-y-auto sm:max-w-2xl" data-testid="transfer-receive">
        <DialogHeader>
          <DialogTitle>{t("transfers.receiveTitle", { number: transfer.number })}</DialogTitle>
          <DialogDescription>
            {t("transfers.route", { from: names.name(transfer.from_store), to: names.name(transfer.to_store) })}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={(e) => void submit(e)} noValidate className="grid gap-4">
          <ul className="grid gap-2">
            {parsed.map(({ line, qty }) => (
              <li
                key={line.id}
                className="grid gap-2 rounded-control border border-border p-3 sm:grid-cols-[minmax(0,1fr)_9rem] sm:items-end"
              >
                <span className="grid gap-0.5 text-sm">
                  <span className="font-medium">{names.item(line)}</span>
                  <span className="text-muted">
                    <bdi>{line.batch_no}</bdi> ·{" "}
                    {t("transfers.sent", { qty: formatNumber(line.qty_base, names.language) })}
                  </span>
                </span>
                <LabeledField
                  label={t("transfers.arrived")}
                  error={
                    checked && (qty === null || qty > line.qty_base)
                      ? t("transfers.arrivedInvalid", { max: line.qty_base })
                      : null
                  }
                >
                  {(id) => (
                    <Input
                      id={id}
                      value={got[line.id] ?? ""}
                      inputMode="numeric"
                      dir="ltr"
                      data-testid="transfer-arrived"
                      onChange={(e) => {
                        setGot((prev) => ({ ...prev, [line.id]: e.target.value }));
                      }}
                    />
                  )}
                </LabeledField>
              </li>
            ))}
          </ul>
          {short ? (
            <div className="grid gap-3 rounded-control border border-warning-border bg-warning-bg p-3 text-warning-fg">
              <p className="text-sm font-medium">{t("transfers.shortage")}</p>
              <div className="grid gap-3 sm:grid-cols-2">
                <LabeledField
                  label={t("transfers.shortageReason")}
                  required
                  error={checked && !reason ? t("common.required") : null}
                >
                  {(id) => (
                    <Select value={reason} onValueChange={setReason}>
                      <SelectTrigger id={id} className="h-11 w-full md:h-10" data-testid="transfer-shortage-reason">
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
                <LabeledField label={t("transfers.shortageNote")}>
                  {(id) => (
                    <Input
                      id={id}
                      value={note}
                      maxLength={300}
                      onChange={(e) => {
                        setNote(e.target.value);
                      }}
                    />
                  )}
                </LabeledField>
              </div>
              <ApproverInputs
                value={approver}
                onChange={setApprover}
                description={t("transfers.approverDescription")}
              />
            </div>
          ) : null}
          <ErrorAlert message={error} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              {t("common:actions.cancel")}
            </Button>
            <Button type="submit" loading={receive.isPending} data-testid="transfer-receive-submit">
              {t("transfers.receive")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
