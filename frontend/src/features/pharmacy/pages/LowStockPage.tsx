import { Link } from "@tanstack/react-router";
import type { ColumnDef } from "@tanstack/react-table";
import { TrendingDown } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { DataTable } from "@/components/DataTable";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { useTranslateError } from "@/lib/api/translate-error";

import { useLowStock, usePharmacyOptions } from "../api";
import { QtyText, StoreSelect } from "../components/common";
import { PharmacyNav } from "../components/PharmacyNav";
import { useNames } from "../lib/use-names";
import type { LowStockItem } from "../types";

/** Items at or below their minimum with the quantity to reorder (FEATURES 8.9). */
export function LowStockPage() {
  const { t } = useTranslation(["pharmacy", "errors"]);
  const translateError = useTranslateError();
  const names = useNames();
  const options = usePharmacyOptions();
  const [storeId, setStoreId] = useState<number | undefined>(undefined);
  const report = useLowStock(storeId);

  const columns = useMemo<ColumnDef<LowStockItem>[]>(
    () => [
      {
        id: "item",
        header: t("lowStock.columns.item"),
        meta: { label: t("lowStock.columns.item") },
        cell: ({ row }) => (
          <span className="flex flex-col">
            <Link
              to="/pharmacy/items/$itemId"
              params={{ itemId: String(row.original.item_id) }}
              className="font-medium text-primary-strong hover:underline"
            >
              {names.item(row.original)}
            </Link>
            <bdi className="text-xs text-muted">{row.original.service_code}</bdi>
          </span>
        ),
      },
      {
        id: "onHand",
        header: t("lowStock.columns.onHand"),
        meta: { label: t("lowStock.columns.onHand"), align: "end" },
        cell: ({ row }) => (
          <QtyText value={row.original.on_hand} unit={names.baseUnit(row.original)} className="text-danger-fg" />
        ),
      },
      {
        id: "min",
        header: t("lowStock.columns.minStock"),
        meta: { label: t("lowStock.columns.minStock"), align: "end" },
        cell: ({ row }) => <QtyText value={row.original.min_stock} unit={names.baseUnit(row.original)} />,
      },
      {
        id: "suggested",
        header: t("lowStock.columns.suggested"),
        meta: { label: t("lowStock.columns.suggested"), align: "end" },
        cell: ({ row }) => (
          <QtyText value={row.original.suggested_order} unit={names.baseUnit(row.original)} className="font-semibold" />
        ),
      },
    ],
    [t, names],
  );

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <PageHeader title={t("lowStock.title")} description={t("lowStock.description")} icon={<TrendingDown />} />
      <PharmacyNav />
      <StoreSelect
        stores={options.data?.stores ?? []}
        value={storeId}
        onChange={setStoreId}
        label={t("batch.store")}
        allowAll
        className="w-full sm:w-64"
      />
      {report.isError ? (
        <AlertCard variant="danger" title={t("errors:title")}>
          {translateError(report.error)}
        </AlertCard>
      ) : (
        <DataTable
          columns={columns}
          data={report.data ?? []}
          loading={report.isPending}
          getRowId={(r) => String(r.item_id)}
          caption={t("lowStock.title")}
          minTableWidth={680}
          pageSize={25}
          emptyState={<EmptyState bare size="compact" icon={<TrendingDown />} title={t("lowStock.empty")} />}
          renderCard={(r) => (
            <div className="card-surface flex flex-col gap-1.5 p-4 text-sm" data-testid="low-stock-row">
              <Link
                to="/pharmacy/items/$itemId"
                params={{ itemId: String(r.item_id) }}
                className="font-semibold text-primary-strong hover:underline"
              >
                {names.item(r)}
              </Link>
              <span className="flex flex-wrap gap-x-3 gap-y-1 text-muted">
                <span>
                  {t("lowStock.columns.onHand")}:{" "}
                  <QtyText value={r.on_hand} unit={names.baseUnit(r)} className="text-danger-fg" />
                </span>
                <span>
                  {t("lowStock.columns.minStock")}: <QtyText value={r.min_stock} unit={names.baseUnit(r)} />
                </span>
              </span>
              <span>
                {t("lowStock.columns.suggested")}:{" "}
                <QtyText value={r.suggested_order} unit={names.baseUnit(r)} className="font-semibold" />
              </span>
            </div>
          )}
        />
      )}
    </div>
  );
}
