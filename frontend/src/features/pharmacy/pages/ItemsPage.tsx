import { useNavigate } from "@tanstack/react-router";
import type { ColumnDef } from "@tanstack/react-table";
import { Package, Plus } from "lucide-react";
import { useId, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { DataTable, DataTableOpenButton } from "@/components/DataTable";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { SearchInput } from "@/components/SearchInput";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { useTranslateError } from "@/lib/api/translate-error";
import { usePermission } from "@/lib/auth/hooks";

import { PAGE_SIZE, useItems } from "../api";
import { QtyText } from "../components/common";
import { NewItemDialog } from "../components/NewItemDialog";
import { PharmacyNav } from "../components/PharmacyNav";
import { useNames } from "../lib/use-names";
import type { StockItemListItem } from "../types";

/** Item master (FEATURES 8.1): drugs and consumables with units, barcode and stock levels. */
export function ItemsPage() {
  const { t } = useTranslation(["pharmacy", "errors"]);
  const translateError = useTranslateError();
  const names = useNames();
  const navigate = useNavigate();
  const canManage = usePermission("pharmacy.manage_items");
  const [q, setQ] = useState("");
  const [low, setLow] = useState(false);
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);
  const items = useItems(q, low, page);
  const lowId = useId();

  const open = (item: StockItemListItem) => {
    void navigate({ to: "/pharmacy/items/$itemId", params: { itemId: String(item.id) } });
  };

  const itemName = (it: StockItemListItem) => [it.generic_name, it.strength].filter(Boolean).join(" ");

  const columns = useMemo<ColumnDef<StockItemListItem>[]>(
    () => [
      {
        id: "name",
        header: t("items.columns.name"),
        meta: { label: t("items.columns.name") },
        cell: ({ row }) => (
          <span className="flex flex-col">
            <span className="font-medium">{itemName(row.original)}</span>
            {row.original.brand_name ? <span className="text-xs text-muted">{row.original.brand_name}</span> : null}
          </span>
        ),
      },
      {
        id: "form",
        header: t("items.columns.form"),
        meta: { label: t("items.columns.form") },
        cell: ({ row }) => t(`forms.${row.original.form}`),
      },
      {
        id: "code",
        header: t("items.columns.code"),
        meta: { label: t("items.columns.code") },
        cell: ({ row }) => <bdi>{row.original.service.code}</bdi>,
      },
      {
        id: "onHand",
        header: t("items.columns.onHand"),
        meta: { label: t("items.columns.onHand"), align: "end" },
        cell: ({ row }) => (
          <span className="flex flex-col items-end gap-1">
            <QtyText value={row.original.on_hand} unit={names.baseUnit(row.original)} />
            {row.original.low ? <Badge variant="warning">{t("items.low")}</Badge> : null}
            {!row.original.active ? <Badge variant="neutral">{t("items.inactive")}</Badge> : null}
          </span>
        ),
      },
      {
        id: "min",
        header: t("items.columns.minStock"),
        meta: { label: t("items.columns.minStock"), align: "end" },
        cell: ({ row }) => <QtyText value={row.original.min_stock} unit={names.baseUnit(row.original)} />,
      },
    ],
    [t, names],
  );

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <PageHeader
        title={t("items.title")}
        description={t("items.description")}
        icon={<Package />}
        actions={
          canManage ? (
            <Button
              onClick={() => {
                setCreating(true);
              }}
              data-testid="item-new"
            >
              <Plus aria-hidden="true" />
              {t("items.new")}
            </Button>
          ) : null
        }
      />
      <PharmacyNav />
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <SearchInput
          label={t("items.search")}
          placeholder={t("items.searchPlaceholder")}
          onSearch={(v) => {
            setQ(v);
            setPage(1);
          }}
          className="sm:max-w-md"
          data-testid="items-search"
        />
        <div className="flex items-center gap-2">
          <Switch
            id={lowId}
            checked={low}
            onCheckedChange={(v) => {
              setLow(v);
              setPage(1);
            }}
          />
          <Label htmlFor={lowId}>{t("items.lowOnly")}</Label>
        </div>
      </div>
      {items.isError ? (
        <AlertCard variant="danger" title={t("errors:title")}>
          {translateError(items.error)}
        </AlertCard>
      ) : (
        <DataTable
          columns={columns}
          data={items.data?.items ?? []}
          loading={items.isPending}
          getRowId={(r) => String(r.id)}
          caption={t("items.title")}
          onRowClick={open}
          rowLabel={(r) => t("items.open", { name: itemName(r) })}
          serverPagination={{ page, pageSize: PAGE_SIZE, count: items.data?.count ?? 0, onPageChange: setPage }}
          minTableWidth={720}
          emptyState={<EmptyState bare size="compact" icon={<Package />} title={t("items.empty")} />}
          renderCard={(r, ctx) => (
            <div className="card-surface relative flex flex-col gap-2 p-4" data-testid="item-row">
              <div className="flex items-start justify-between gap-2">
                <span className="flex min-w-0 flex-col">
                  {ctx.open ? (
                    <DataTableOpenButton onOpen={ctx.open} label={ctx.openLabel}>
                      <span className="font-semibold break-words">{itemName(r)}</span>
                    </DataTableOpenButton>
                  ) : (
                    <span className="font-semibold break-words">{itemName(r)}</span>
                  )}
                  {r.brand_name ? <span className="text-sm text-muted">{r.brand_name}</span> : null}
                </span>
                {r.low ? <Badge variant="warning">{t("items.low")}</Badge> : null}
              </div>
              <span className="flex flex-wrap gap-x-3 gap-y-1 text-sm text-muted">
                <span>{t(`forms.${r.form}`)}</span>
                <bdi>{r.service.code}</bdi>
                <span>
                  {t("items.columns.onHand")}:{" "}
                  <QtyText value={r.on_hand} unit={names.baseUnit(r)} className="text-fg" />
                </span>
              </span>
            </div>
          )}
        />
      )}
      <NewItemDialog
        open={creating}
        onOpenChange={setCreating}
        onCreated={(id) => {
          void navigate({ to: "/pharmacy/items/$itemId", params: { itemId: String(id) } });
        }}
      />
    </div>
  );
}
