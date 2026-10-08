import { zodResolver } from "@hookform/resolvers/zod";
import { Link, useParams } from "@tanstack/react-router";
import type { ColumnDef } from "@tanstack/react-table";
import { CalendarPlus, Lock, Percent, Plus, Save, Trash2, Undo2 } from "lucide-react";
import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { z } from "zod";

import { AlertCard } from "@/components/AlertCard";
import { DataTable } from "@/components/DataTable";
import { DateText } from "@/components/DateText";
import { CheckboxField, SelectField, TextField } from "@/components/form";
import { ArrowBack } from "@/components/icons";
import { MoneyText } from "@/components/MoneyText";
import { SearchInput } from "@/components/SearchInput";
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
import { Input } from "@/components/ui/input";
import { useTranslateError } from "@/lib/api/translate-error";
import { cn } from "@/lib/utils";
import { vmsg } from "@/lib/validation";

import {
  useApplyBulk,
  useBulkPreview,
  useCreateVersion,
  usePriceItems,
  usePriceList,
  useServices,
  useSetPriceItems,
  type PriceItemFilters,
} from "../api";
import { AdminPage, QueryState } from "../components/AdminPage";
import { FilterBar, FilterSelect } from "../components/Filters";
import { DateField } from "../components/DateField";
import { Code, FormDialog } from "../components/FormDialog";
import { useLocalName } from "../hooks";
import { centerDate } from "../dates";
import {
  SERVICE_KINDS,
  type BulkPreviewOut,
  type BulkUpdateIn,
  type PriceItemOut,
  type PriceListOut,
  type ServiceKind,
  type VersionOut,
} from "../types";
import { KindBadge } from "./CatalogPage";

const PRICE = /^[0-9٠-٩۰-۹]+([.٫][0-9٠-٩۰-۹]{1,2})?$/;
const DATE = /^\d{4}-\d{2}-\d{2}$/;

export function PriceListPage() {
  const { t } = useTranslation("admin");
  const localName = useLocalName();
  const { priceListId } = useParams({ from: "/_app/administration/price-lists/$priceListId" });
  const id = Number(priceListId);
  const list = usePriceList(id);
  const [selected, setSelected] = useState<number | null>(null);
  const [dialog, setDialog] = useState<"version" | "bulk" | null>(null);

  const data = list.data;
  const versionId = selected ?? data?.next_version_id ?? data?.current_version_id ?? data?.versions[0]?.id ?? null;
  const version = data?.versions.find((v) => v.id === versionId) ?? null;

  return (
    <AdminPage
      section="priceLists"
      title={data ? localName(data) : t("sections.priceLists.title")}
      description={data ? <Code>{data.code}</Code> : undefined}
      documentTitle={data ? localName(data) : t("sections.priceLists.title")}
      actions={
        data ? (
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              onClick={() => {
                setDialog("version");
              }}
            >
              <CalendarPlus />
              {t("prices.newVersion")}
            </Button>
            <Button
              disabled={data.versions.length === 0}
              onClick={() => {
                setDialog("bulk");
              }}
            >
              <Percent />
              {t("prices.bulk")}
            </Button>
          </div>
        ) : undefined
      }
    >
      <div>
        <Button asChild variant="link">
          <Link to="/administration/price-lists">
            <ArrowBack />
            {t("prices.backToLists")}
          </Link>
        </Button>
      </div>
      <QueryState loading={list.isPending} error={list.error} onRetry={() => void list.refetch()}>
        {data ? (
          <div className="grid min-w-0 gap-4 2xl:grid-cols-[18rem_1fr] 2xl:items-start">
            <VersionTimeline versions={data.versions} selected={versionId} onSelect={setSelected} />
            {version ? (
              <VersionItems key={version.id} version={version} />
            ) : (
              <AlertCard variant="info" title={t("prices.noVersionsTitle")}>
                {t("prices.noVersions")}
              </AlertCard>
            )}
          </div>
        ) : null}
      </QueryState>
      {data && dialog === "version" ? (
        <NewVersionDialog
          list={data}
          onClose={(created) => {
            setDialog(null);
            if (created) setSelected(created);
          }}
        />
      ) : null}
      {data && dialog === "bulk" ? (
        <BulkDialog
          list={data}
          onClose={(created) => {
            setDialog(null);
            if (created) setSelected(created);
          }}
        />
      ) : null}
    </AdminPage>
  );
}

// --- Version timeline -------------------------------------------------------------------------

function StatusBadgeFor({ version }: { version: VersionOut }) {
  const { t } = useTranslation("admin");
  const variant = version.status === "current" ? "success" : version.status === "scheduled" ? "info" : "neutral";
  return <Badge variant={variant}>{t(`prices.status.${version.status}`)}</Badge>;
}

function VersionTimeline({
  versions,
  selected,
  onSelect,
}: {
  versions: readonly VersionOut[];
  selected: number | null;
  onSelect: (id: number) => void;
}) {
  const { t } = useTranslation("admin");
  return (
    <section className="card-surface p-3" aria-labelledby="timeline-title">
      <h2 id="timeline-title" className="px-1 pb-2 text-sm font-semibold text-fg">
        {t("prices.timeline")}
      </h2>
      {versions.length === 0 ? <p className="px-1 text-sm text-muted">{t("prices.noVersions")}</p> : null}
      <ol className="grid grid-cols-1 gap-1 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-1" data-testid="version-timeline">
        {versions.map((v) => (
          <li key={v.id}>
            <button
              type="button"
              aria-current={v.id === selected ? "true" : undefined}
              onClick={() => {
                onSelect(v.id);
              }}
              data-testid={`version-${v.effective_from}`}
              className={cn(
                "flex w-full flex-col gap-1 rounded-control border-s-4 px-3 py-2 text-start focus-ring transition-colors",
                v.status === "current" ? "border-success" : v.status === "scheduled" ? "border-info" : "border-border",
                v.id === selected ? "bg-primary-soft" : "hover:bg-accent",
              )}
            >
              <span className="flex flex-wrap items-center justify-between gap-2">
                <DateText value={v.effective_from} className="font-semibold text-fg" />
                <StatusBadgeFor version={v} />
              </span>
              <span className="flex flex-wrap gap-x-3 text-xs text-muted">
                <span>{t("prices.items", { count: v.item_count })}</span>
                {v.percent_change ? (
                  <bdi dir="ltr">{t("prices.percentChange", { value: v.percent_change })}</bdi>
                ) : null}
              </span>
              {v.note ? <span className="truncate text-xs text-fg-muted">{v.note}</span> : null}
            </button>
          </li>
        ))}
      </ol>
    </section>
  );
}

// --- Items of one version ---------------------------------------------------------------------

function VersionItems({ version }: { version: VersionOut }) {
  const { t, i18n } = useTranslation(["admin", "errors"]);
  const [filters, setFilters] = useState<PriceItemFilters>({});
  const items = usePriceItems(version.id, filters);
  const save = useSetPriceItems();
  const translateError = useTranslateError();
  const [drafts, setDrafts] = useState<ReadonlyMap<number, string | null>>(new Map());
  const [adding, setAdding] = useState(false);
  const editable = version.editable;
  const invalid = [...drafts.values()].some((v) => v !== null && !PRICE.test(v.trim()));

  const setDraft = (serviceId: number, value: string | null, original?: string) => {
    setDrafts((current) => {
      const next = new Map(current);
      if (value !== null && original !== undefined && value === original) next.delete(serviceId);
      else next.set(serviceId, value);
      return next;
    });
  };

  const columns = useMemo<ColumnDef<PriceItemOut>[]>(
    () => [
      {
        id: "service",
        accessorFn: (row) =>
          i18n.language === "ar"
            ? row.service_name_ar || row.service_name_en
            : row.service_name_en || row.service_name_ar,
        header: t("prices.service"),
        meta: { label: t("prices.service") },
        cell: ({ row, getValue }) => (
          <div className={cn("min-w-0", drafts.get(row.original.service_id) === null && "line-through opacity-60")}>
            <div className="truncate font-medium text-fg">{String(getValue())}</div>
            <Code>{row.original.service_code}</Code>
          </div>
        ),
      },
      {
        accessorKey: "service_kind",
        header: t("catalog.kind"),
        meta: { label: t("catalog.kind") },
        cell: ({ row }) => <KindBadge kind={row.original.service_kind} />,
      },
      {
        id: "price",
        accessorFn: (row) => Number(row.unit_price),
        header: t("prices.unitPrice"),
        meta: { label: t("prices.unitPrice"), align: "end" },
        cell: ({ row }) => {
          const item = row.original;
          if (!editable) return <MoneyText value={item.unit_price} />;
          const draft = drafts.get(item.service_id);
          if (draft === null) return <span className="text-muted">{t("prices.removed")}</span>;
          const value = draft ?? item.unit_price;
          const bad = draft !== undefined && !PRICE.test(draft.trim());
          return (
            <Input
              value={value}
              inputMode="decimal"
              dir="ltr"
              aria-label={t("prices.priceOf", { code: item.service_code })}
              aria-invalid={bad || undefined}
              data-testid={`price-${item.service_code}`}
              className={cn("ms-auto w-32 text-end tabular", draft !== undefined && "border-warning")}
              onChange={(e) => {
                setDraft(item.service_id, e.target.value, item.unit_price);
              }}
            />
          );
        },
      },
      ...(editable
        ? [
            {
              id: "remove",
              header: () => <span className="sr-only">{t("prices.remove")}</span>,
              meta: { label: t("prices.remove"), align: "end" as const, hideInCard: false },
              enableSorting: false,
              cell: ({ row }: { row: { original: PriceItemOut } }) => {
                const removed = drafts.get(row.original.service_id) === null;
                return (
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label={
                      removed ? t("prices.undoRemove") : t("prices.removeNamed", { code: row.original.service_code })
                    }
                    onClick={() => {
                      if (removed) {
                        setDrafts((current) => {
                          const next = new Map(current);
                          next.delete(row.original.service_id);
                          return next;
                        });
                      } else {
                        setDraft(row.original.service_id, null);
                      }
                    }}
                  >
                    {removed ? <Undo2 /> : <Trash2 />}
                  </Button>
                );
              },
            } satisfies ColumnDef<PriceItemOut>,
          ]
        : []),
    ],
    [t, i18n.language, editable, drafts],
  );

  const submit = async () => {
    try {
      await save.mutateAsync({
        versionId: version.id,
        items: [...drafts.entries()].map(([service_id, price]) => ({
          service_id,
          unit_price: price === null ? null : price.trim(),
        })),
      });
      setDrafts(new Map());
      toast.success(t("prices.saved"));
    } catch (e) {
      toast.error(translateError(e));
    }
  };

  return (
    <section className="flex min-w-0 flex-col gap-3" aria-labelledby="items-title">
      <div className="flex flex-col gap-1">
        <h2 id="items-title" className="flex flex-wrap items-center gap-2 font-semibold text-fg">
          {t("prices.versionFrom")} <DateText value={version.effective_from} />
          <StatusBadgeFor version={version} />
        </h2>
        {version.based_on_effective_from ? (
          <p className="text-xs text-muted">
            {t("prices.basedOn")} <DateText value={version.based_on_effective_from} />
          </p>
        ) : null}
      </div>
      {!editable ? (
        <AlertCard variant="info" title={t("prices.lockedTitle")} icon={<Lock />}>
          {t("prices.locked")}
        </AlertCard>
      ) : null}
      <FilterBar>
        <SearchInput
          label={t("prices.search")}
          placeholder={t("prices.search")}
          onSearch={(q) => {
            setFilters((f) => ({ ...f, q: q || undefined }));
          }}
          className="sm:max-w-xs"
        />
        <FilterSelect
          label={t("catalog.kind")}
          allLabel={t("catalog.allKinds")}
          value={filters.kind}
          onChange={(kind) => {
            setFilters((f) => ({ ...f, kind: kind as ServiceKind | undefined }));
          }}
          options={SERVICE_KINDS.map((k) => ({ value: k, label: t(`kinds.${k}`) }))}
        />
        {editable ? (
          <Button
            variant="outline"
            className="sm:ms-auto"
            onClick={() => {
              setAdding(true);
            }}
          >
            <Plus />
            {t("prices.addService")}
          </Button>
        ) : null}
      </FilterBar>
      <QueryState loading={items.isPending} error={items.error} onRetry={() => void items.refetch()}>
        <DataTable
          caption={t("prices.itemsCaption")}
          columns={columns}
          data={items.data?.items ?? []}
          getRowId={(row) => String(row.service_id)}
          pageSize={25}
        />
      </QueryState>
      {editable && drafts.size > 0 ? (
        <div className="sticky bottom-20 z-20 flex flex-col gap-3 rounded-card border border-warning-border bg-warning-bg p-3 text-warning-fg shadow-overlay sm:flex-row sm:items-center sm:justify-between lg:bottom-4">
          <span className="text-sm font-medium">{t("prices.unsaved", { count: drafts.size })}</span>
          <div className="flex gap-2">
            <Button
              variant="outline"
              onClick={() => {
                setDrafts(new Map());
              }}
            >
              {t("prices.discard")}
            </Button>
            <Button loading={save.isPending} disabled={invalid} onClick={() => void submit()}>
              <Save />
              {t("prices.saveChanges")}
            </Button>
          </div>
        </div>
      ) : null}
      {adding ? (
        <AddServiceDialog
          versionId={version.id}
          onClose={() => {
            setAdding(false);
          }}
        />
      ) : null}
    </section>
  );
}

const addSchema = z.object({
  service: z.string().min(1, vmsg("validation.selectOption")),
  price: z.string().trim().regex(PRICE, vmsg("admin:prices.priceRule")),
});
type AddValues = z.infer<typeof addSchema>;

function AddServiceDialog({ versionId, onClose }: { versionId: number; onClose: () => void }) {
  const { t } = useTranslation("admin");
  const localName = useLocalName();
  const [q, setQ] = useState("");
  const services = useServices({ q: q || undefined, active: true });
  const save = useSetPriceItems();
  const form = useForm<AddValues>({ resolver: zodResolver(addSchema), defaultValues: { service: "", price: "" } });
  return (
    <FormDialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={t("prices.addService")}
      form={form}
      error={save.error}
      onSubmit={async (values) => {
        await save.mutateAsync({
          versionId,
          items: [{ service_id: Number(values.service), unit_price: values.price }],
        });
        toast.success(t("prices.saved"));
        onClose();
      }}
    >
      <SearchInput label={t("catalog.search")} placeholder={t("catalog.search")} onSearch={setQ} />
      <SelectField
        control={form.control}
        name="service"
        label={t("prices.service")}
        options={(services.data?.items ?? []).map((s) => ({
          value: String(s.id),
          label: `${localName(s)} (${s.code})`,
        }))}
        required
      />
      <TextField
        control={form.control}
        name="price"
        label={t("prices.unitPrice")}
        inputMode="decimal"
        dir="ltr"
        required
      />
    </FormDialog>
  );
}

// --- New version --------------------------------------------------------------------------

const versionSchema = z.object({
  effective_from: z.string().regex(DATE, vmsg("validation.invalid")),
  note: z.string().max(300),
});
type VersionValues = z.infer<typeof versionSchema>;

function NewVersionDialog({ list, onClose }: { list: PriceListOut; onClose: (created?: number) => void }) {
  const { t } = useTranslation("admin");
  const create = useCreateVersion();
  const form = useForm<VersionValues>({
    resolver: zodResolver(versionSchema),
    defaultValues: { effective_from: centerDate(list.versions.length === 0 ? 0 : 1), note: "" },
  });
  return (
    <FormDialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={t("prices.newVersion")}
      description={t("prices.newVersionHint")}
      form={form}
      error={create.error}
      onSubmit={async (values) => {
        const version = await create.mutateAsync({ priceListId: list.id, body: values });
        toast.success(t("prices.versionCreated"));
        onClose(version.id);
      }}
    >
      <DateField
        control={form.control}
        name="effective_from"
        label={t("prices.effectiveFrom")}
        min={centerDate(0)}
        required
      />
      <TextField control={form.control} name="note" label={t("prices.note")} />
    </FormDialog>
  );
}

// --- Bulk percentage update with preview ------------------------------------------------------

const STEPS = ["0.01", "1", "5", "10", "50", "100", "500", "1000"] as const;

const bulkSchema = z.object({
  percent: z
    .string()
    .trim()
    .regex(/^-?\d{1,3}(\.\d{1,2})?$/, vmsg("admin:prices.percentRule")),
  effective_from: z.string().regex(DATE, vmsg("validation.invalid")),
  step: z.enum(STEPS),
  mode: z.enum(["half_up", "up", "down"]),
  kinds: z.record(z.string(), z.boolean()),
  note: z.string().max(300),
});
type BulkValues = z.infer<typeof bulkSchema>;

function toBulkBody(values: BulkValues): BulkUpdateIn {
  const kinds = SERVICE_KINDS.filter((k) => values.kinds[k]);
  return {
    percent: values.percent,
    effective_from: values.effective_from,
    step: values.step,
    mode: values.mode,
    kinds: kinds.length > 0 && kinds.length < SERVICE_KINDS.length ? kinds : null,
    note: values.note,
  };
}

function BulkDialog({ list, onClose }: { list: PriceListOut; onClose: (created?: number) => void }) {
  const { t } = useTranslation(["admin", "common", "errors"]);
  const preview = useBulkPreview();
  const apply = useApplyBulk();
  const translateError = useTranslateError();
  const [shown, setShown] = useState<{ body: BulkUpdateIn; result: BulkPreviewOut } | null>(null);
  const form = useForm<BulkValues>({
    resolver: zodResolver(bulkSchema),
    defaultValues: {
      percent: "10",
      effective_from: centerDate(1),
      step: "0.01",
      mode: "half_up",
      kinds: Object.fromEntries(SERVICE_KINDS.map((k) => [k, false])),
      note: "",
    },
  });

  if (shown) {
    return (
      <Dialog
        open
        onOpenChange={(open) => {
          if (!open) onClose();
        }}
      >
        <DialogContent className="md:max-w-3xl">
          <DialogHeader>
            <DialogTitle>{t("admin:prices.previewTitle")}</DialogTitle>
            <DialogDescription>
              {t("admin:prices.previewSummary", { count: shown.result.changed_count, percent: shown.result.percent })}{" "}
              <DateText value={shown.result.effective_from} />
            </DialogDescription>
          </DialogHeader>
          {apply.error ? (
            <AlertCard variant="danger" title={t("errors:title")} live>
              {translateError(apply.error)}
            </AlertCard>
          ) : null}
          <BulkPreviewTable preview={shown.result} />
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setShown(null);
              }}
            >
              {t("common:actions.back")}
            </Button>
            <Button
              loading={apply.isPending}
              data-testid="bulk-apply"
              onClick={() => {
                apply.mutate(
                  { priceListId: list.id, body: shown.body },
                  {
                    onSuccess: (version) => {
                      toast.success(t("admin:prices.versionCreated"));
                      onClose(version.id);
                    },
                  },
                );
              }}
            >
              {t("admin:prices.applyBulk")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    );
  }

  return (
    <FormDialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={t("admin:prices.bulk")}
      description={t("admin:prices.bulkHint")}
      form={form}
      error={preview.error}
      submitLabel={t("admin:prices.preview")}
      wide
      onSubmit={async (values) => {
        const body = toBulkBody(values);
        const result = await preview.mutateAsync({ priceListId: list.id, body });
        setShown({ body, result });
      }}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <TextField
          control={form.control}
          name="percent"
          label={t("admin:prices.percent")}
          description={t("admin:prices.percentHint")}
          inputMode="decimal"
          dir="ltr"
          required
        />
        <DateField
          control={form.control}
          name="effective_from"
          label={t("admin:prices.effectiveFrom")}
          min={centerDate(1)}
          required
        />
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <SelectField
          control={form.control}
          name="step"
          label={t("admin:prices.step")}
          options={STEPS.map((s) => ({ value: s, label: s }))}
        />
        <SelectField
          control={form.control}
          name="mode"
          label={t("admin:prices.mode")}
          options={[
            { value: "half_up", label: t("admin:prices.modes.half_up") },
            { value: "up", label: t("admin:prices.modes.up") },
            { value: "down", label: t("admin:prices.modes.down") },
          ]}
        />
      </div>
      <fieldset className="grid gap-2">
        <legend className="mb-1 text-sm font-medium text-fg">{t("admin:prices.kindsLabel")}</legend>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          {SERVICE_KINDS.map((k) => (
            <CheckboxField key={k} control={form.control} name={`kinds.${k}`} label={t(`admin:kinds.${k}`)} />
          ))}
        </div>
        <p className="text-xs text-muted">{t("admin:prices.kindsHint")}</p>
      </fieldset>
      <TextField control={form.control} name="note" label={t("admin:prices.note")} />
    </FormDialog>
  );
}

type PreviewRow = BulkPreviewOut["rows"][number];

function BulkPreviewTable({ preview }: { preview: BulkPreviewOut }) {
  const { t, i18n } = useTranslation("admin");
  const columns = useMemo<ColumnDef<PreviewRow>[]>(
    () => [
      {
        id: "service",
        accessorFn: (row) =>
          i18n.language === "ar"
            ? row.service_name_ar || row.service_name_en
            : row.service_name_en || row.service_name_ar,
        header: t("prices.service"),
        meta: { label: t("prices.service") },
        cell: ({ row, getValue }) => (
          <div className="min-w-0">
            <div className="truncate font-medium text-fg">{String(getValue())}</div>
            <Code>{row.original.service_code}</Code>
          </div>
        ),
      },
      {
        id: "old",
        accessorFn: (row) => Number(row.old_price),
        header: t("prices.before"),
        meta: { label: t("prices.before"), align: "end" },
        cell: ({ row }) => <MoneyText value={row.original.old_price} className="text-muted" />,
      },
      {
        id: "new",
        accessorFn: (row) => Number(row.new_price),
        header: t("prices.after"),
        meta: { label: t("prices.after"), align: "end" },
        cell: ({ row }) => (
          <MoneyText
            value={row.original.new_price}
            className={cn(row.original.changed ? "font-semibold text-fg" : "text-muted")}
          />
        ),
      },
    ],
    [t, i18n.language],
  );
  return (
    <div className="max-h-[50dvh] min-w-0 overflow-y-auto">
      <DataTable
        caption={t("prices.previewTitle")}
        columns={columns}
        data={preview.rows}
        getRowId={(row) => String(row.service_id)}
        pageSize={10}
      />
    </div>
  );
}
