import { useNavigate } from "@tanstack/react-router";
import type { ColumnDef } from "@tanstack/react-table";
import { ClipboardList, Plus } from "lucide-react";
import { useMemo, useState, type SyntheticEvent } from "react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { DataTable, DataTableOpenButton } from "@/components/DataTable";
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
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { useTranslateError } from "@/lib/api/translate-error";
import { usePermission } from "@/lib/auth/hooks";
import { formatNumber } from "@/lib/format";

import { PAGE_SIZE, useCounts, usePharmacyOptions, useStartCount } from "../api";
import { DocStatusBadge, ErrorAlert, LabeledField, StoreSelect } from "../components/common";
import { PharmacyNav } from "../components/PharmacyNav";
import { useNames } from "../lib/use-names";
import type { CountStatus, StockCount } from "../types";

type Filter = CountStatus | "all";
const FILTERS: readonly Filter[] = ["open", "posted", "cancelled", "all"];

/** Stock count sessions (FEATURES 8.7): counted against the book, variances posted. */
export function CountsPage() {
  const { t } = useTranslation(["pharmacy", "errors"]);
  const translateError = useTranslateError();
  const names = useNames();
  const navigate = useNavigate();
  const canCount = usePermission("pharmacy.count_stock");
  const [filter, setFilter] = useState<Filter>("all");
  const [page, setPage] = useState(1);
  const counts = useCounts(filter === "all" ? undefined : filter, page);
  const [starting, setStarting] = useState(false);

  const open = (c: StockCount) => {
    void navigate({ to: "/pharmacy/counts/$countId", params: { countId: String(c.id) } });
  };

  const columns = useMemo<ColumnDef<StockCount>[]>(
    () => [
      {
        id: "number",
        header: t("counts.columns.number"),
        meta: { label: t("counts.columns.number") },
        cell: ({ row }) => (
          <span className="flex flex-col items-start gap-1">
            <bdi className="font-medium">{row.original.number}</bdi>
            <DocStatusBadge status={row.original.status} kind="count" />
          </span>
        ),
      },
      {
        id: "store",
        header: t("counts.columns.store"),
        meta: { label: t("counts.columns.store") },
        cell: ({ row }) => names.name(row.original.store),
      },
      {
        id: "progress",
        header: t("counts.columns.progress"),
        meta: { label: t("counts.columns.progress") },
        cell: ({ row }) =>
          t("counts.progress", {
            counted: formatNumber(row.original.counted, names.language),
            total: formatNumber(row.original.total, names.language),
          }),
      },
      {
        id: "started",
        header: t("counts.columns.started"),
        meta: { label: t("counts.columns.started") },
        cell: ({ row }) => (
          <span className="flex flex-col">
            <span>{names.person(row.original.started_by)}</span>
            <DateText value={row.original.started_at} format="datetime" className="text-xs text-muted" />
          </span>
        ),
      },
      {
        id: "variance",
        header: t("counts.columns.variance"),
        meta: { label: t("counts.columns.variance"), align: "end" },
        cell: ({ row }) => <MoneyText value={row.original.variance_value} signed toneNegative />,
      },
    ],
    [t, names],
  );

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <PageHeader
        title={t("counts.title")}
        description={t("counts.description")}
        icon={<ClipboardList />}
        actions={
          canCount ? (
            <Button
              onClick={() => {
                setStarting(true);
              }}
              data-testid="count-new"
            >
              <Plus aria-hidden="true" />
              {t("counts.new")}
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
              {f === "all" ? t("common.all") : t(`status.count.${f}`)}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>
      {counts.isError ? (
        <AlertCard variant="danger" title={t("errors:title")}>
          {translateError(counts.error)}
        </AlertCard>
      ) : (
        <DataTable
          columns={columns}
          data={counts.data?.items ?? []}
          loading={counts.isPending}
          getRowId={(r) => String(r.id)}
          caption={t("counts.title")}
          onRowClick={open}
          rowLabel={(r) => t("counts.open", { number: r.number })}
          serverPagination={{ page, pageSize: PAGE_SIZE, count: counts.data?.count ?? 0, onPageChange: setPage }}
          minTableWidth={760}
          emptyState={<EmptyState bare size="compact" icon={<ClipboardList />} title={t("counts.empty")} />}
          renderCard={(c, ctx) => (
            <div className="card-surface relative flex flex-col gap-2 p-4" data-testid="count-row">
              <div className="flex items-start justify-between gap-2">
                {ctx.open ? (
                  <DataTableOpenButton onOpen={ctx.open} label={ctx.openLabel} className="font-semibold">
                    <bdi>{c.number}</bdi>
                  </DataTableOpenButton>
                ) : null}
                <DocStatusBadge status={c.status} kind="count" />
              </div>
              <span className="flex flex-wrap gap-x-3 gap-y-1 text-sm text-muted">
                <span>{names.name(c.store)}</span>
                <span>
                  {t("counts.progress", {
                    counted: formatNumber(c.counted, names.language),
                    total: formatNumber(c.total, names.language),
                  })}
                </span>
              </span>
              <MoneyText value={c.variance_value} signed toneNegative />
            </div>
          )}
        />
      )}
      <StartCountDialog
        open={starting}
        onOpenChange={setStarting}
        onStarted={(c) => {
          open(c);
        }}
      />
    </div>
  );
}

function StartCountDialog(props: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onStarted: (count: StockCount) => void;
}) {
  return props.open ? <StartCountDialogOpen {...props} /> : null;
}

function StartCountDialogOpen({
  open,
  onOpenChange,
  onStarted,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onStarted: (count: StockCount) => void;
}) {
  const { t } = useTranslation(["pharmacy", "common"]);
  const translateError = useTranslateError();
  const options = usePharmacyOptions();
  const start = useStartCount();
  const [storeId, setStoreId] = useState<number | undefined>(undefined);
  const [note, setNote] = useState("");
  const [checked, setChecked] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submit = async (e: SyntheticEvent) => {
    e.preventDefault();
    setChecked(true);
    setError(null);
    if (storeId === undefined) return;
    try {
      const count = await start.mutateAsync({ store_id: storeId, note: note.trim() });
      onOpenChange(false);
      onStarted(count);
    } catch (err) {
      setError(translateError(err));
    }
  };
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!start.isPending) onOpenChange(o);
      }}
    >
      <DialogContent data-testid="count-dialog">
        <DialogHeader>
          <DialogTitle>{t("counts.newTitle")}</DialogTitle>
          <DialogDescription>{t("counts.newDescription")}</DialogDescription>
        </DialogHeader>
        <form onSubmit={(e) => void submit(e)} noValidate className="grid gap-4">
          <StoreSelect
            stores={options.data?.stores ?? []}
            value={storeId}
            onChange={setStoreId}
            label={t("counts.columns.store")}
            testId="count-store"
          />
          {checked && storeId === undefined ? (
            <p role="alert" className="text-xs font-medium text-danger-fg">
              {t("common.required")}
            </p>
          ) : null}
          <LabeledField label={t("counts.note")}>
            {(id) => (
              <Textarea
                id={id}
                rows={2}
                maxLength={1000}
                value={note}
                onChange={(e) => {
                  setNote(e.target.value);
                }}
              />
            )}
          </LabeledField>
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
            <Button type="submit" loading={start.isPending} data-testid="count-start">
              {t("counts.start")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
