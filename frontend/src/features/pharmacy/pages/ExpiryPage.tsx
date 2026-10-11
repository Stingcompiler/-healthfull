import type { ColumnDef } from "@tanstack/react-table";
import { CalendarClock } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { DataTable } from "@/components/DataTable";
import { DateText } from "@/components/DateText";
import { EmptyState } from "@/components/EmptyState";
import { MoneyText } from "@/components/MoneyText";
import { PageHeader } from "@/components/PageHeader";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useTranslateError } from "@/lib/api/translate-error";

import { useExpiry, usePharmacyOptions } from "../api";
import { ExpiryBadge, QtyText, StoreSelect } from "../components/common";
import { PharmacyNav } from "../components/PharmacyNav";
import { EXPIRY_WINDOWS } from "../lib/constants";
import { useNames } from "../lib/use-names";
import type { ExpiringBatch } from "../types";

/** Batches with stock expiring within 30, 60 or 90 days, expired ones first (FEATURES 8.8). */
export function ExpiryPage() {
  const { t } = useTranslation(["pharmacy", "errors"]);
  const translateError = useTranslateError();
  const names = useNames();
  const options = usePharmacyOptions();
  const [days, setDays] = useState<number>(30);
  const [storeId, setStoreId] = useState<number | undefined>(undefined);
  const report = useExpiry(days, storeId);

  const columns = useMemo<ColumnDef<ExpiringBatch>[]>(
    () => [
      {
        id: "item",
        header: t("expiry.columns.item"),
        meta: { label: t("expiry.columns.item") },
        cell: ({ row }) => <span className="font-medium">{names.item(row.original)}</span>,
      },
      {
        id: "batch",
        header: t("batch.number"),
        meta: { label: t("batch.number") },
        cell: ({ row }) => <bdi>{row.original.batch_no}</bdi>,
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
        cell: ({ row }) => names.name(row.original.store),
      },
      {
        id: "qty",
        header: t("batch.onHand"),
        meta: { label: t("batch.onHand"), align: "end" },
        cell: ({ row }) => <QtyText value={row.original.on_hand} unit={names.baseUnit(row.original)} />,
      },
      {
        id: "value",
        header: t("expiry.columns.value"),
        meta: { label: t("expiry.columns.value"), align: "end" },
        cell: ({ row }) => <MoneyText value={row.original.value} />,
      },
    ],
    [t, names],
  );

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <PageHeader title={t("expiry.title")} description={t("expiry.description")} icon={<CalendarClock />} />
      <PharmacyNav />
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <Tabs
          value={String(days)}
          onValueChange={(v) => {
            setDays(Number(v));
          }}
        >
          <TabsList aria-label={t("expiry.window")} className="flex h-auto flex-wrap">
            {EXPIRY_WINDOWS.map((d) => (
              <TabsTrigger key={d} value={String(d)} className="h-9 flex-none" data-testid={`expiry-${String(d)}`}>
                {t("expiry.within", { days: d })}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
        <StoreSelect
          stores={options.data?.stores ?? []}
          value={storeId}
          onChange={setStoreId}
          label={t("batch.store")}
          allowAll
          className="w-full sm:w-64"
        />
      </div>
      {report.isError ? (
        <AlertCard variant="danger" title={t("errors:title")}>
          {translateError(report.error)}
        </AlertCard>
      ) : (
        <DataTable
          columns={columns}
          data={report.data ?? []}
          loading={report.isPending}
          getRowId={(r) => `${String(r.batch_id)}-${String(r.store.id)}`}
          caption={t("expiry.title")}
          minTableWidth={820}
          pageSize={25}
          emptyState={<EmptyState bare size="compact" icon={<CalendarClock />} title={t("expiry.empty")} />}
          renderCard={(r) => (
            <div className="card-surface flex flex-col gap-1.5 p-4 text-sm" data-testid="expiry-row">
              <span className="flex flex-wrap items-start justify-between gap-2">
                <span className="font-semibold">{names.item(r)}</span>
                <ExpiryBadge daysLeft={r.days_left} />
              </span>
              <span className="flex flex-wrap gap-x-3 gap-y-1 text-muted">
                <bdi>{r.batch_no}</bdi>
                <DateText value={r.expiry_date} />
                <span>{names.name(r.store)}</span>
              </span>
              <span className="flex flex-wrap justify-between gap-2">
                <QtyText value={r.on_hand} unit={names.baseUnit(r)} className="font-medium" />
                <MoneyText value={r.value} />
              </span>
            </div>
          )}
        />
      )}
    </div>
  );
}
