import { zodResolver } from "@hookform/resolvers/zod";
import { Link, useParams } from "@tanstack/react-router";
import type { ColumnDef } from "@tanstack/react-table";
import { Package, Plus } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useForm, type Control } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { z } from "zod";

import { AlertCard } from "@/components/AlertCard";
import { DataTable } from "@/components/DataTable";
import { DateText } from "@/components/DateText";
import { EmptyState } from "@/components/EmptyState";
import { Form, SwitchField, TextField } from "@/components/form";
import { ChevronPrev } from "@/components/icons";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useTranslateError } from "@/lib/api/translate-error";
import { usePermission } from "@/lib/auth/hooks";
import { formatNumber } from "@/lib/format";
import { vmsg } from "@/lib/validation";

import { useAddUnit, useItem, usePharmacyOptions, useStockCard, useUpdateItem } from "../api";
import { ErrorAlert, ExpiryBadge, QtyText, StoreSelect } from "../components/common";
import { ItemFields } from "../components/ItemFields";
import { PharmacyNav } from "../components/PharmacyNav";
import { parseWhole } from "../lib/qty";
import { itemFieldsSchema, unitCodeSchema, type ItemFieldValues } from "../lib/schemas";
import { useNames } from "../lib/use-names";
import type { BatchStock, StockCardRow, StockItem } from "../types";

type ItemValues = z.infer<typeof itemFieldsSchema> & { active: boolean };

/** One item: master data, pack units, batches on hand and its stock card (FEATURES 8.1, 8.2). */
export function ItemPage() {
  const { itemId } = useParams({ from: "/_app/pharmacy/items/$itemId" });
  const id = Number(itemId);
  const { t } = useTranslation(["pharmacy", "errors"]);
  const translateError = useTranslateError();
  const item = useItem(id);
  const title = item.data ? [item.data.generic_name, item.data.strength].filter(Boolean).join(" ") : t("item.title");

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <PageHeader
        title={title}
        description={item.data?.brand_name}
        icon={<Package />}
        eyebrow={
          <Link
            to="/pharmacy/items"
            className="inline-flex items-center gap-1 text-sm text-primary-strong hover:underline"
          >
            <ChevronPrev className="size-4" />
            {t("item.back")}
          </Link>
        }
      />
      <PharmacyNav />
      {item.isError ? (
        <AlertCard variant="danger" title={t("errors:title")}>
          {translateError(item.error)}
        </AlertCard>
      ) : item.isPending ? (
        <Skeleton className="h-64" />
      ) : (
        <ItemBody item={item.data} />
      )}
    </div>
  );
}

function ItemBody({ item }: { item: StockItem }) {
  const { t } = useTranslation("pharmacy");
  const names = useNames();
  const canManage = usePermission("pharmacy.manage_items");
  const unit = names.baseUnit(item);
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <section className="card-surface grid gap-3 p-4 md:p-5" aria-labelledby="item-summary" data-testid="item-summary">
        <h2 id="item-summary" className="text-base font-semibold">
          {t("item.summary")}
        </h2>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
          <dt className="text-muted">{t("items.columns.onHand")}</dt>
          <dd className="flex flex-wrap items-center gap-2">
            <QtyText value={item.on_hand} unit={unit} className="font-semibold" />
            {item.low ? <Badge variant="warning">{t("items.low")}</Badge> : null}
          </dd>
          <dt className="text-muted">{t("items.columns.minStock")}</dt>
          <dd>
            <QtyText value={item.min_stock} unit={unit} />
          </dd>
          <dt className="text-muted">{t("items.fields.reorderQty")}</dt>
          <dd>
            <QtyText value={item.reorder_qty} unit={unit} />
          </dd>
          <dt className="text-muted">{t("items.columns.code")}</dt>
          <dd>
            <bdi>{item.service.code}</bdi>
          </dd>
          <dt className="text-muted">{t("items.fields.form")}</dt>
          <dd>{t(`forms.${item.form}`)}</dd>
          <dt className="text-muted">{t("items.fields.storage")}</dt>
          <dd>{t(`storage.${item.storage}`)}</dd>
          <dt className="text-muted">{t("items.fields.barcode")}</dt>
          <dd>
            <bdi>{item.barcode || "—"}</bdi>
          </dd>
        </dl>
        <h3 className="mt-2 text-sm font-semibold">{t("item.units")}</h3>
        <ul className="grid gap-1.5 text-sm" data-testid="item-units">
          <li className="flex justify-between gap-2">
            <span>{unit}</span>
            <span className="text-muted">{t("item.baseUnit")}</span>
          </li>
          {item.units.map((u) => (
            <li key={u.id} className="flex flex-wrap justify-between gap-2">
              <span>
                {names.name(u)} <bdi className="text-muted">{u.barcode}</bdi>
              </span>
              <span className="text-muted">
                {t("item.unitFactor", { factor: formatNumber(u.factor, names.language), unit })}
                {!u.is_dispensable ? ` · ${t("item.notDispensed")}` : ""}
              </span>
            </li>
          ))}
        </ul>
        {canManage ? <AddUnitForm itemId={item.id} /> : null}
      </section>
      {canManage ? <EditItemForm item={item} /> : null}
      <BatchesSection item={item} />
      <StockCardSection item={item} />
    </div>
  );
}

function EditItemForm({ item }: { item: StockItem }) {
  const { t } = useTranslation(["pharmacy", "common"]);
  const translateError = useTranslateError();
  const update = useUpdateItem();
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const defaults = (it: StockItem): ItemValues => ({
    generic_name: it.generic_name,
    brand_name: it.brand_name,
    form: it.form,
    strength: it.strength,
    base_unit_name_ar: it.base_unit_name_ar,
    base_unit_name_en: it.base_unit_name_en,
    barcode: it.barcode,
    min_stock: String(it.min_stock),
    reorder_qty: String(it.reorder_qty),
    storage: it.storage,
    is_controlled: it.is_controlled,
    active: it.active,
  });
  const form = useForm<ItemValues>({
    resolver: zodResolver(itemFieldsSchema.extend({ active: z.boolean() })),
    defaultValues: defaults(item),
  });
  useEffect(() => {
    form.reset(defaults(item));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset when the saved item changes
  }, [item]);

  const submit = form.handleSubmit(async (v) => {
    setError(null);
    setSaved(false);
    try {
      await update.mutateAsync({
        itemId: item.id,
        body: { ...v, min_stock: parseWhole(v.min_stock, 0) ?? 0, reorder_qty: parseWhole(v.reorder_qty, 0) ?? 0 },
      });
      setSaved(true);
    } catch (e) {
      setError(translateError(e));
    }
  });

  return (
    <section className="card-surface grid gap-3 p-4 md:p-5" aria-labelledby="item-edit">
      <h2 id="item-edit" className="text-base font-semibold">
        {t("item.edit")}
      </h2>
      <Form {...form}>
        <form onSubmit={(e) => void submit(e)} noValidate className="grid gap-4" data-testid="item-edit-form">
          <ItemFields control={form.control as unknown as Control<ItemFieldValues>} />
          <SwitchField control={form.control} name="active" label={t("items.fields.active")} />
          <ErrorAlert message={error} />
          {saved ? (
            <p role="status" className="text-sm text-success-fg">
              {t("item.saved")}
            </p>
          ) : null}
          <div className="flex justify-end">
            <Button type="submit" loading={form.formState.isSubmitting} data-testid="item-edit-save">
              {t("common:actions.save")}
            </Button>
          </div>
        </form>
      </Form>
    </section>
  );
}

const unitSchema = z.object({
  unit_code: unitCodeSchema,
  name_ar: z.string().trim().min(1, vmsg("validation.required")).max(50),
  name_en: z.string().trim().min(1, vmsg("validation.required")).max(50),
  factor: z
    .string()
    .trim()
    .refine((v) => parseWhole(v, 2) !== null, vmsg("pharmacy:validation.factor")),
  barcode: z.string().trim().max(60),
  is_dispensable: z.boolean(),
});

type UnitValues = z.infer<typeof unitSchema>;

function AddUnitForm({ itemId }: { itemId: number }) {
  const { t } = useTranslation(["pharmacy", "common"]);
  const translateError = useTranslateError();
  const add = useAddUnit();
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const form = useForm<UnitValues>({
    resolver: zodResolver(unitSchema),
    defaultValues: { unit_code: "", name_ar: "", name_en: "", factor: "", barcode: "", is_dispensable: true },
  });
  if (!open) {
    return (
      <div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            setOpen(true);
          }}
          data-testid="unit-add"
        >
          <Plus aria-hidden="true" />
          {t("item.addUnit")}
        </Button>
      </div>
    );
  }
  const submit = form.handleSubmit(async (v) => {
    setError(null);
    try {
      await add.mutateAsync({ itemId, body: { ...v, factor: parseWhole(v.factor, 2) ?? 2, is_purchase_unit: false } });
      form.reset();
      setOpen(false);
    } catch (e) {
      setError(translateError(e));
    }
  });
  return (
    <Form {...form}>
      <form onSubmit={(e) => void submit(e)} noValidate className="grid gap-3 rounded-control border border-border p-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <TextField control={form.control} name="unit_code" label={t("item.unitCode")} dir="ltr" required />
          <TextField
            control={form.control}
            name="factor"
            label={t("item.factor")}
            inputMode="numeric"
            dir="ltr"
            required
          />
          <TextField control={form.control} name="name_ar" label={t("item.unitNameAr")} dir="rtl" required />
          <TextField control={form.control} name="name_en" label={t("item.unitNameEn")} dir="ltr" required />
          <TextField control={form.control} name="barcode" label={t("items.fields.barcode")} dir="ltr" />
        </div>
        <SwitchField control={form.control} name="is_dispensable" label={t("item.dispensable")} />
        <ErrorAlert message={error} />
        <div className="flex flex-wrap justify-end gap-2">
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              setOpen(false);
            }}
          >
            {t("common:actions.cancel")}
          </Button>
          <Button type="submit" loading={form.formState.isSubmitting}>
            {t("item.saveUnit")}
          </Button>
        </div>
      </form>
    </Form>
  );
}

function BatchesSection({ item }: { item: StockItem }) {
  const { t } = useTranslation("pharmacy");
  const names = useNames();
  const options = usePharmacyOptions();
  const stores = useMemo(() => new Map((options.data?.stores ?? []).map((s) => [s.id, s])), [options.data]);
  const unit = names.baseUnit(item);
  const columns = useMemo<ColumnDef<BatchStock>[]>(
    () => [
      {
        id: "batch",
        header: t("batch.number"),
        meta: { label: t("batch.number") },
        cell: ({ row }) => <bdi className="font-medium">{row.original.batch_no}</bdi>,
      },
      {
        id: "expiry",
        header: t("batch.expiry"),
        meta: { label: t("batch.expiry") },
        cell: ({ row }) => (
          <span className="flex flex-wrap items-center gap-2">
            <DateText value={row.original.expiry_date} />
            <ExpiryBadge daysLeft={row.original.days_left} />
          </span>
        ),
      },
      {
        id: "store",
        header: t("batch.store"),
        meta: { label: t("batch.store") },
        cell: ({ row }) => names.name(stores.get(row.original.store_id)),
      },
      {
        id: "qty",
        header: t("batch.onHand"),
        meta: { label: t("batch.onHand"), align: "end" },
        cell: ({ row }) => <QtyText value={row.original.on_hand} unit={unit} />,
      },
    ],
    [t, names, stores, unit],
  );
  return (
    <section className="card-surface grid min-w-0 gap-3 p-4 md:p-5 lg:col-span-2" aria-labelledby="item-batches">
      <h2 id="item-batches" className="text-base font-semibold">
        {t("item.batches")}
      </h2>
      <DataTable
        columns={columns}
        data={item.batches}
        getRowId={(r) => `${String(r.batch_id)}-${String(r.store_id)}`}
        caption={t("item.batches")}
        minTableWidth={560}
        emptyState={<EmptyState bare size="compact" title={t("item.noBatches")} />}
        renderCard={(r) => (
          <div className="card-surface flex flex-col gap-1 p-3 text-sm" data-testid="batch-row">
            <span className="flex flex-wrap items-center justify-between gap-2">
              <bdi className="font-semibold">{r.batch_no}</bdi>
              <ExpiryBadge daysLeft={r.days_left} />
            </span>
            <span className="text-muted">
              <DateText value={r.expiry_date} /> · {names.name(stores.get(r.store_id))}
            </span>
            <QtyText value={r.on_hand} unit={unit} className="font-medium" />
          </div>
        )}
      />
    </section>
  );
}

function StockCardSection({ item }: { item: StockItem }) {
  const { t } = useTranslation(["pharmacy", "errors"]);
  const translateError = useTranslateError();
  const names = useNames();
  const options = usePharmacyOptions();
  const [storeId, setStoreId] = useState<number | undefined>(undefined);
  const card = useStockCard(item.id, storeId);
  const unit = names.baseUnit(item);
  const columns = useMemo<ColumnDef<StockCardRow>[]>(
    () => [
      {
        id: "when",
        header: t("card.when"),
        meta: { label: t("card.when") },
        cell: ({ row }) => <DateText value={row.original.moved_at} format="datetime" />,
      },
      {
        id: "kind",
        header: t("card.kind"),
        meta: { label: t("card.kind") },
        cell: ({ row }) => t(`moves.${row.original.kind}`),
      },
      {
        id: "batch",
        header: t("batch.number"),
        meta: { label: t("batch.number") },
        cell: ({ row }) => <bdi>{row.original.batch_no}</bdi>,
      },
      {
        id: "store",
        header: t("batch.store"),
        meta: { label: t("batch.store") },
        cell: ({ row }) => names.name(row.original.store),
      },
      {
        id: "qty",
        header: t("card.change"),
        meta: { label: t("card.change"), align: "end" },
        cell: ({ row }) => (
          <span className={row.original.qty_base < 0 ? "tabular text-danger-fg" : "tabular text-success-fg"}>
            <bdi>{(row.original.qty_base > 0 ? "+" : "") + formatNumber(row.original.qty_base, names.language)}</bdi>
          </span>
        ),
      },
      {
        id: "balance",
        header: t("card.balance"),
        meta: { label: t("card.balance"), align: "end" },
        cell: ({ row }) => <QtyText value={row.original.balance} unit={unit} />,
      },
      {
        id: "by",
        header: t("card.by"),
        meta: { label: t("card.by") },
        cell: ({ row }) => names.person(row.original.created_by),
      },
    ],
    [t, names, unit],
  );
  return (
    <section className="card-surface grid min-w-0 gap-3 p-4 md:p-5 lg:col-span-2" aria-labelledby="item-card">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h2 id="item-card" className="text-base font-semibold">
          {t("card.title")}
        </h2>
        <StoreSelect
          stores={options.data?.stores ?? []}
          value={storeId}
          onChange={setStoreId}
          label={t("batch.store")}
          allowAll
          className="w-full sm:w-64"
        />
      </div>
      {card.isError ? (
        <ErrorAlert message={translateError(card.error)} />
      ) : (
        <DataTable
          columns={columns}
          data={card.data?.rows ?? []}
          loading={card.isPending}
          getRowId={(r) => String(r.id)}
          caption={t("card.title")}
          minTableWidth={820}
          pageSize={20}
          emptyState={<EmptyState bare size="compact" title={t("card.empty")} />}
          renderCard={(r) => (
            <div className="card-surface flex flex-col gap-1 p-3 text-sm" data-testid="card-row">
              <span className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-medium">{t(`moves.${r.kind}`)}</span>
                <span className={r.qty_base < 0 ? "tabular text-danger-fg" : "tabular text-success-fg"}>
                  <bdi>{(r.qty_base > 0 ? "+" : "") + formatNumber(r.qty_base, names.language)}</bdi>
                </span>
              </span>
              <span className="text-muted">
                <DateText value={r.moved_at} format="datetime" /> · <bdi>{r.batch_no}</bdi> · {names.name(r.store)}
              </span>
              <span>
                {t("card.balance")}: <QtyText value={r.balance} unit={unit} />
              </span>
            </div>
          )}
        />
      )}
    </section>
  );
}
