import type { ColumnDef } from "@tanstack/react-table";
import { CheckCircle2, Plus, Trash2, Truck, XCircle } from "lucide-react";
import { useMemo, useState, type SyntheticEvent } from "react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { DataTable, DataTableOpenButton, type DataTableRowAction } from "@/components/DataTable";
import { DateText } from "@/components/DateText";
import { EmptyState } from "@/components/EmptyState";
import { MoneyText } from "@/components/MoneyText";
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

import {
  PAGE_SIZE,
  useCreateReceipt,
  useCreateSupplier,
  usePharmacyOptions,
  useReceiptAction,
  useReceipts,
} from "../api";
import { DocStatusBadge, ErrorAlert, LabeledField, QtyText, StoreSelect } from "../components/common";
import { ItemPicker } from "../components/pickers";
import { PharmacyNav } from "../components/PharmacyNav";
import { parseCost, parseWhole } from "../lib/qty";
import { useNames } from "../lib/use-names";
import type { GoodsReceipt, GoodsReceiptLineIn, ReceiptStatus, StockItemListItem } from "../types";

type Filter = ReceiptStatus | "all";
const FILTERS: readonly Filter[] = ["draft", "posted", "cancelled", "all"];

/** Goods received from suppliers (FEATURES 8.5): drafted with batches, posted into a store. */
export function ReceiptsPage() {
  const { t } = useTranslation(["pharmacy", "errors"]);
  const translateError = useTranslateError();
  const names = useNames();
  const canReceive = usePermission("pharmacy.receive_goods");
  const [filter, setFilter] = useState<Filter>("all");
  const [page, setPage] = useState(1);
  const receipts = useReceipts(filter === "all" ? undefined : filter, page);
  const action = useReceiptAction();
  const [creating, setCreating] = useState(false);
  const [viewing, setViewing] = useState<GoodsReceipt | null>(null);
  const [confirm, setConfirm] = useState<{ receipt: GoodsReceipt; action: "post" | "cancel" } | null>(null);

  const actions = (r: GoodsReceipt): DataTableRowAction[] =>
    canReceive && r.status === "draft"
      ? [
          {
            label: t("receipts.post"),
            icon: <CheckCircle2 />,
            onSelect: () => {
              setConfirm({ receipt: r, action: "post" });
            },
          },
          {
            label: t("receipts.cancel"),
            icon: <XCircle />,
            destructive: true,
            onSelect: () => {
              setConfirm({ receipt: r, action: "cancel" });
            },
          },
        ]
      : [];

  const columns = useMemo<ColumnDef<GoodsReceipt>[]>(
    () => [
      {
        id: "number",
        header: t("receipts.columns.number"),
        meta: { label: t("receipts.columns.number") },
        cell: ({ row }) => (
          <span className="flex flex-col items-start gap-1">
            <bdi className="font-medium">{row.original.number}</bdi>
            <DocStatusBadge status={row.original.status} kind="receipt" />
          </span>
        ),
      },
      {
        id: "supplier",
        header: t("receipts.columns.supplier"),
        meta: { label: t("receipts.columns.supplier") },
        cell: ({ row }) => (
          <span className="flex flex-col">
            <span>{names.name(row.original.supplier)}</span>
            {row.original.supplier_invoice_no ? (
              <bdi className="text-xs text-muted">{row.original.supplier_invoice_no}</bdi>
            ) : null}
          </span>
        ),
      },
      {
        id: "store",
        header: t("receipts.columns.store"),
        meta: { label: t("receipts.columns.store") },
        cell: ({ row }) => names.name(row.original.store),
      },
      {
        id: "created",
        header: t("receipts.columns.created"),
        meta: { label: t("receipts.columns.created") },
        cell: ({ row }) => (
          <span className="flex flex-col">
            <span>{names.person(row.original.created_by)}</span>
            <DateText value={row.original.created_at} format="datetime" className="text-xs text-muted" />
          </span>
        ),
      },
      {
        id: "total",
        header: t("receipts.columns.total"),
        meta: { label: t("receipts.columns.total"), align: "end" },
        cell: ({ row }) => <MoneyText value={row.original.total_cost} />,
      },
    ],
    [t, names],
  );

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <PageHeader
        title={t("receipts.title")}
        description={t("receipts.description")}
        icon={<Truck />}
        actions={
          canReceive ? (
            <Button
              onClick={() => {
                setCreating(true);
              }}
              data-testid="receipt-new"
            >
              <Plus aria-hidden="true" />
              {t("receipts.new")}
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
              {f === "all" ? t("common.all") : t(`status.receipt.${f}`)}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>
      {receipts.isError ? (
        <AlertCard variant="danger" title={t("errors:title")}>
          {translateError(receipts.error)}
        </AlertCard>
      ) : (
        <DataTable
          columns={columns}
          data={receipts.data?.items ?? []}
          loading={receipts.isPending}
          getRowId={(r) => String(r.id)}
          caption={t("receipts.title")}
          rowActions={actions}
          onRowClick={setViewing}
          rowLabel={(r) => t("receipts.open", { number: r.number })}
          serverPagination={{ page, pageSize: PAGE_SIZE, count: receipts.data?.count ?? 0, onPageChange: setPage }}
          minTableWidth={820}
          emptyState={<EmptyState bare size="compact" icon={<Truck />} title={t("receipts.empty")} />}
          renderCard={(r, ctx) => (
            <div className="card-surface relative flex flex-col gap-2 p-4" data-testid="receipt-row">
              <div className="flex items-start justify-between gap-2">
                <span className="flex min-w-0 flex-col items-start gap-1">
                  {ctx.open ? (
                    <DataTableOpenButton onOpen={ctx.open} label={ctx.openLabel} className="font-semibold">
                      <bdi>{r.number}</bdi>
                    </DataTableOpenButton>
                  ) : null}
                  <DocStatusBadge status={r.status} kind="receipt" />
                </span>
                {ctx.actions}
              </div>
              <span className="text-sm">{names.name(r.supplier)}</span>
              <span className="flex flex-wrap gap-x-3 gap-y-1 text-sm text-muted">
                <span>{names.name(r.store)}</span>
                <DateText value={r.created_at} format="datetime" />
              </span>
              <MoneyText value={r.total_cost} className="text-base" />
            </div>
          )}
        />
      )}
      <NewReceiptDialog open={creating} onOpenChange={setCreating} onCreated={setViewing} />
      <ReceiptDialog
        receipt={viewing}
        onClose={() => {
          setViewing(null);
        }}
        onAction={(receipt, act) => {
          setConfirm({ receipt, action: act });
        }}
        canReceive={canReceive}
      />
      <ConfirmDialog
        open={confirm !== null}
        onOpenChange={(o) => {
          if (!o) setConfirm(null);
        }}
        title={
          confirm?.action === "post"
            ? t("receipts.postTitle", { number: confirm.receipt.number })
            : t("receipts.cancelTitle", { number: confirm?.receipt.number ?? "" })
        }
        description={confirm?.action === "post" ? t("receipts.postDescription") : t("receipts.cancelDescription")}
        confirmLabel={confirm?.action === "post" ? t("receipts.post") : t("receipts.cancel")}
        destructive={confirm?.action === "cancel"}
        onConfirm={async () => {
          if (!confirm) return;
          const updated = await action.mutateAsync({ receiptId: confirm.receipt.id, action: confirm.action });
          if (viewing?.id === updated.id) setViewing(updated);
        }}
      />
    </div>
  );
}

function ReceiptDialog({
  receipt,
  onClose,
  onAction,
  canReceive,
}: {
  receipt: GoodsReceipt | null;
  onClose: () => void;
  onAction: (receipt: GoodsReceipt, action: "post" | "cancel") => void;
  canReceive: boolean;
}) {
  const { t } = useTranslation(["pharmacy", "common"]);
  const names = useNames();
  return (
    <Dialog
      open={receipt !== null}
      onOpenChange={(o) => {
        if (!o) onClose();
      }}
    >
      <DialogContent className="max-h-[92dvh] overflow-y-auto sm:max-w-2xl" data-testid="receipt-detail">
        {receipt ? (
          <>
            <DialogHeader>
              <DialogTitle className="flex flex-wrap items-center gap-2">
                <bdi>{receipt.number}</bdi>
                <DocStatusBadge status={receipt.status} kind="receipt" />
              </DialogTitle>
              <DialogDescription>
                {names.name(receipt.supplier)} · {names.name(receipt.store)}
                {receipt.supplier_invoice_no ? (
                  <>
                    {" · "}
                    <bdi>{receipt.supplier_invoice_no}</bdi>
                  </>
                ) : null}
              </DialogDescription>
            </DialogHeader>
            <ul className="grid gap-2 text-sm">
              {receipt.lines.map((ln) => (
                <li key={ln.id} className="grid gap-1 rounded-control border border-border px-3 py-2">
                  <span className="flex flex-wrap justify-between gap-2">
                    <span className="font-medium">{ln.item_name}</span>
                    <MoneyText value={ln.line_total} />
                  </span>
                  <span className="flex flex-wrap gap-x-3 gap-y-1 text-muted">
                    <span>
                      {t("batch.number")} <bdi>{ln.batch_no}</bdi>
                    </span>
                    <span>
                      {t("batch.expiry")} <DateText value={ln.expiry_date} />
                    </span>
                    <QtyText value={ln.qty_base} unit={t("common.baseUnits")} />
                  </span>
                </li>
              ))}
            </ul>
            <p className="flex justify-between text-base font-semibold">
              <span>{t("receipts.total")}</span>
              <MoneyText value={receipt.total_cost} />
            </p>
            {receipt.posted_by ? (
              <p className="text-sm text-muted">
                {t("receipts.postedBy", { name: names.person(receipt.posted_by) })}{" "}
                {receipt.posted_at ? <DateText value={receipt.posted_at} format="datetime" /> : null}
              </p>
            ) : null}
            <DialogFooter>
              {canReceive && receipt.status === "draft" ? (
                <>
                  <Button
                    variant="destructive-soft"
                    onClick={() => {
                      onAction(receipt, "cancel");
                    }}
                  >
                    {t("receipts.cancel")}
                  </Button>
                  <Button
                    onClick={() => {
                      onAction(receipt, "post");
                    }}
                    data-testid="receipt-post"
                  >
                    {t("receipts.post")}
                  </Button>
                </>
              ) : (
                <Button variant="outline" onClick={onClose}>
                  {t("common:actions.close")}
                </Button>
              )}
            </DialogFooter>
          </>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

interface LineDraft {
  key: number;
  item: StockItemListItem | null;
  batchNo: string;
  expiry: string;
  qty: string;
  unit: string;
  cost: string;
}

let lineKey = 0;
function emptyLine(): LineDraft {
  lineKey += 1;
  return { key: lineKey, item: null, batchNo: "", expiry: "", qty: "", unit: "", cost: "" };
}

function lineProblem(line: LineDraft): "item" | "batch" | "expiry" | "qty" | "cost" | null {
  if (!line.item) return "item";
  if (!line.batchNo.trim()) return "batch";
  if (!line.expiry) return "expiry";
  if (parseWhole(line.qty) === null) return "qty";
  if (parseCost(line.cost) === null) return "cost";
  return null;
}

/** Mounted only while open, so every opening starts with an empty receipt. */
function NewReceiptDialog(props: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (r: GoodsReceipt) => void;
}) {
  return props.open ? <NewReceiptDialogOpen {...props} /> : null;
}

function NewReceiptDialogOpen({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (r: GoodsReceipt) => void;
}) {
  const { t } = useTranslation(["pharmacy", "common"]);
  const translateError = useTranslateError();
  const names = useNames();
  const options = usePharmacyOptions();
  const create = useCreateReceipt();
  const canAddSupplier = usePermission("pharmacy.manage_suppliers");
  const [supplierId, setSupplierId] = useState("");
  const [storeId, setStoreId] = useState<number | undefined>(undefined);
  const [invoiceNo, setInvoiceNo] = useState("");
  const [invoiceDate, setInvoiceDate] = useState("");
  const [lines, setLines] = useState<LineDraft[]>(() => [emptyLine()]);
  const [checked, setChecked] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [addingSupplier, setAddingSupplier] = useState(false);

  const setLine = (key: number, patch: Partial<LineDraft>) => {
    setLines((prev) => prev.map((l) => (l.key === key ? { ...l, ...patch } : l)));
  };

  const submit = async (e: SyntheticEvent) => {
    e.preventDefault();
    setChecked(true);
    setError(null);
    if (!supplierId || storeId === undefined || lines.some((l) => lineProblem(l) !== null)) return;
    const body: GoodsReceiptLineIn[] = lines.map((l) => ({
      item_id: l.item?.id ?? 0,
      batch_no: l.batchNo.trim(),
      expiry_date: l.expiry,
      quantity: parseWhole(l.qty) ?? 0,
      unit_code: l.unit || null,
      unit_cost: parseCost(l.cost) ?? "0",
    }));
    try {
      const receipt = await create.mutateAsync({
        supplier_id: Number(supplierId),
        store_id: storeId,
        supplier_invoice_no: invoiceNo.trim(),
        supplier_invoice_date: invoiceDate || null,
        note: "",
        lines: body,
      });
      onOpenChange(false);
      onCreated(receipt);
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
      <DialogContent className="max-h-[92dvh] overflow-y-auto sm:max-w-3xl" data-testid="receipt-dialog">
        <DialogHeader>
          <DialogTitle>{t("receipts.newTitle")}</DialogTitle>
          <DialogDescription>{t("receipts.newDescription")}</DialogDescription>
        </DialogHeader>
        <form onSubmit={(e) => void submit(e)} noValidate className="grid gap-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <LabeledField
              label={t("receipts.fields.supplier")}
              required
              error={checked && !supplierId ? t("common.required") : null}
            >
              {(id) => (
                <Select value={supplierId} onValueChange={setSupplierId}>
                  <SelectTrigger id={id} className="h-11 w-full md:h-10" data-testid="receipt-supplier">
                    <SelectValue placeholder={t("receipts.fields.supplierPlaceholder")} />
                  </SelectTrigger>
                  <SelectContent>
                    {(options.data?.suppliers ?? []).map((s) => (
                      <SelectItem key={s.id} value={String(s.id)}>
                        {names.name(s)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </LabeledField>
            <StoreSelect
              stores={options.data?.stores ?? []}
              value={storeId}
              onChange={setStoreId}
              label={t("receipts.fields.store")}
              testId="receipt-store"
            />
            <LabeledField label={t("receipts.fields.invoiceNo")}>
              {(id) => (
                <Input
                  id={id}
                  value={invoiceNo}
                  dir="ltr"
                  maxLength={60}
                  data-testid="receipt-invoice-no"
                  onChange={(e) => {
                    setInvoiceNo(e.target.value);
                  }}
                />
              )}
            </LabeledField>
            <LabeledField label={t("receipts.fields.invoiceDate")}>
              {(id) => (
                <Input
                  id={id}
                  type="date"
                  value={invoiceDate}
                  dir="ltr"
                  onChange={(e) => {
                    setInvoiceDate(e.target.value);
                  }}
                />
              )}
            </LabeledField>
          </div>
          {canAddSupplier ? (
            addingSupplier ? (
              <NewSupplierForm
                onDone={(id) => {
                  setAddingSupplier(false);
                  if (id !== null) setSupplierId(String(id));
                }}
              />
            ) : (
              <div>
                <Button
                  type="button"
                  variant="link"
                  onClick={() => {
                    setAddingSupplier(true);
                  }}
                >
                  {t("receipts.addSupplier")}
                </Button>
              </div>
            )
          ) : null}

          <fieldset className="grid gap-3">
            <legend className="mb-2 text-sm font-semibold">{t("receipts.lines")}</legend>
            {lines.map((line, index) => (
              <ReceiptLineEditor
                key={line.key}
                index={index}
                line={line}
                problem={checked ? lineProblem(line) : null}
                onChange={(patch) => {
                  setLine(line.key, patch);
                }}
                onRemove={
                  lines.length > 1
                    ? () => {
                        setLines((prev) => prev.filter((l) => l.key !== line.key));
                      }
                    : undefined
                }
              />
            ))}
            <div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => {
                  setLines((prev) => [...prev, emptyLine()]);
                }}
                data-testid="receipt-add-line"
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
            <Button type="submit" loading={create.isPending} data-testid="receipt-save">
              {t("receipts.saveDraft")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function ReceiptLineEditor({
  index,
  line,
  problem,
  onChange,
  onRemove,
}: {
  index: number;
  line: LineDraft;
  problem: ReturnType<typeof lineProblem>;
  onChange: (patch: Partial<LineDraft>) => void;
  onRemove?: () => void;
}) {
  const { t } = useTranslation("pharmacy");
  const names = useNames();
  const units = line.item?.units ?? [];
  const baseName = line.item ? names.baseUnit(line.item) : "";
  return (
    <div className="grid gap-3 rounded-control border border-border p-3" data-testid="receipt-line">
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm font-medium">{t("receipts.lineN", { n: index + 1 })}</p>
        {onRemove ? (
          <Button type="button" variant="ghost" size="icon-sm" onClick={onRemove} aria-label={t("receipts.removeLine")}>
            <Trash2 aria-hidden="true" />
          </Button>
        ) : null}
      </div>
      <ItemPicker
        label={t("receipts.fields.item")}
        value={line.item}
        onChange={(item) => {
          onChange({ item, unit: "" });
        }}
        testId="receipt-item"
        error={problem === "item" ? t("common.required") : null}
      />
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <LabeledField label={t("batch.number")} required error={problem === "batch" ? t("common.required") : null}>
          {(id) => (
            <Input
              id={id}
              value={line.batchNo}
              dir="ltr"
              maxLength={60}
              data-testid="receipt-batch"
              onChange={(e) => {
                onChange({ batchNo: e.target.value });
              }}
            />
          )}
        </LabeledField>
        <LabeledField label={t("batch.expiry")} required error={problem === "expiry" ? t("common.required") : null}>
          {(id) => (
            <Input
              id={id}
              type="date"
              value={line.expiry}
              dir="ltr"
              data-testid="receipt-expiry"
              onChange={(e) => {
                onChange({ expiry: e.target.value });
              }}
            />
          )}
        </LabeledField>
        <LabeledField label={t("receipts.fields.unit")}>
          {(id) => (
            <Select
              value={line.unit || "__base"}
              onValueChange={(v) => {
                onChange({ unit: v === "__base" ? "" : v });
              }}
              disabled={!line.item}
            >
              <SelectTrigger id={id} className="h-11 w-full md:h-10" data-testid="receipt-unit">
                <SelectValue placeholder={baseName} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__base">{baseName || t("common.baseUnits")}</SelectItem>
                {units.map((u) => (
                  <SelectItem key={u.unit_code} value={u.unit_code}>
                    {t("dispense.unitOf", { unit: names.name(u), factor: u.factor, base: baseName })}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        </LabeledField>
        <LabeledField
          label={t("receipts.fields.quantity")}
          required
          error={problem === "qty" ? t("validation.wholeNumber") : null}
        >
          {(id) => (
            <Input
              id={id}
              value={line.qty}
              inputMode="numeric"
              dir="ltr"
              data-testid="receipt-qty"
              onChange={(e) => {
                onChange({ qty: e.target.value });
              }}
            />
          )}
        </LabeledField>
        <LabeledField
          label={t("receipts.fields.unitCost")}
          hint={t("receipts.fields.unitCostHint")}
          required
          error={problem === "cost" ? t("validation.cost") : null}
        >
          {(id, describedBy) => (
            <Input
              id={id}
              value={line.cost}
              inputMode="decimal"
              dir="ltr"
              aria-describedby={describedBy}
              data-testid="receipt-cost"
              onChange={(e) => {
                onChange({ cost: e.target.value });
              }}
            />
          )}
        </LabeledField>
      </div>
    </div>
  );
}

function NewSupplierForm({ onDone }: { onDone: (id: number | null) => void }) {
  const { t } = useTranslation(["pharmacy", "common"]);
  const translateError = useTranslateError();
  const create = useCreateSupplier();
  const [code, setCode] = useState("");
  const [nameAr, setNameAr] = useState("");
  const [nameEn, setNameEn] = useState("");
  const [phone, setPhone] = useState("");
  const [error, setError] = useState<string | null>(null);
  const save = async () => {
    setError(null);
    if (!code.trim() || (!nameAr.trim() && !nameEn.trim())) {
      setError(t("receipts.supplierRequired"));
      return;
    }
    try {
      const s = await create.mutateAsync({
        code: code.trim(),
        name_ar: nameAr.trim(),
        name_en: nameEn.trim(),
        phone: phone.trim(),
        contact_name: "",
        address: "",
        tax_no: "",
      });
      onDone(s.id);
    } catch (e) {
      setError(translateError(e));
    }
  };
  return (
    <div className="grid gap-3 rounded-control border border-border p-3" data-testid="supplier-form">
      <p className="text-sm font-semibold">{t("receipts.newSupplier")}</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <LabeledField label={t("receipts.fields.supplierCode")} required>
          {(id) => (
            <Input
              id={id}
              value={code}
              dir="ltr"
              maxLength={30}
              onChange={(e) => {
                setCode(e.target.value);
              }}
            />
          )}
        </LabeledField>
        <LabeledField label={t("receipts.fields.phone")}>
          {(id) => (
            <Input
              id={id}
              value={phone}
              dir="ltr"
              inputMode="tel"
              onChange={(e) => {
                setPhone(e.target.value);
              }}
            />
          )}
        </LabeledField>
        <LabeledField label={t("receipts.fields.nameAr")}>
          {(id) => (
            <Input
              id={id}
              value={nameAr}
              dir="rtl"
              onChange={(e) => {
                setNameAr(e.target.value);
              }}
            />
          )}
        </LabeledField>
        <LabeledField label={t("receipts.fields.nameEn")}>
          {(id) => (
            <Input
              id={id}
              value={nameEn}
              dir="ltr"
              onChange={(e) => {
                setNameEn(e.target.value);
              }}
            />
          )}
        </LabeledField>
      </div>
      <ErrorAlert message={error} />
      <div className="flex flex-wrap justify-end gap-2">
        <Button
          type="button"
          variant="outline"
          onClick={() => {
            onDone(null);
          }}
        >
          {t("common:actions.cancel")}
        </Button>
        <Button type="button" loading={create.isPending} onClick={() => void save()}>
          {t("receipts.saveSupplier")}
        </Button>
      </div>
    </div>
  );
}
