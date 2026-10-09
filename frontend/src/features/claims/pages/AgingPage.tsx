import type { ColumnDef } from "@tanstack/react-table";
import { CalendarClock } from "lucide-react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { DataTable } from "@/components/DataTable";
import { DateText } from "@/components/DateText";
import { EmptyState } from "@/components/EmptyState";
import { Skeleton } from "@/components/ui/skeleton";
import { MoneyText } from "@/components/MoneyText";
import { PageHeader } from "@/components/PageHeader";
import { useTranslateError } from "@/lib/api/translate-error";

import { useAging } from "../api";
import { AmountTiles } from "../components/AmountTiles";
import { ClaimsNav } from "../components/ClaimsNav";
import { useClaimNames } from "../lib/names";
import { AGING_FIELDS, type ClaimAgingRow } from "../types";

const TONES = { days_0_30: "success", days_31_60: "info", days_61_90: "warning", days_over_90: "danger" } as const;

/**
 * Payer aging (FEATURES 11.7): what each payer still owes (accrued, claimed, accepted unpaid,
 * rejected unresolved) by days since invoice approval. A payer payment reduces it; nothing
 * else turns payer share into money (invariant 7).
 */
export function AgingPage() {
  const { t } = useTranslation(["claims", "errors"]);
  const translateError = useTranslateError();
  const names = useClaimNames();
  const aging = useAging();
  const rows = useMemo(() => (aging.data?.items ?? []).filter((r) => r.aging.total !== "0.00"), [aging.data]);
  const totals = aging.data?.totals;

  const columns = useMemo<ColumnDef<ClaimAgingRow>[]>(
    () => [
      {
        id: "payer",
        header: t("aging.payer"),
        meta: { label: t("aging.payer"), className: "whitespace-normal" },
        cell: ({ row }) => (
          <span className="flex min-w-0 flex-col">
            <span className="font-medium">{names.name(row.original.payer)}</span>
            <span className="text-xs text-muted">
              <bdi>{row.original.payer.code}</bdi>
            </span>
          </span>
        ),
      },
      ...AGING_FIELDS.map<ColumnDef<ClaimAgingRow>>((key) => ({
        id: key,
        header: t(`aging.${key}`),
        meta: { label: t(`aging.${key}`), align: "end" },
        cell: ({ row }) => <MoneyText value={row.original.aging[key]} currency={false} />,
      })),
      {
        id: "total",
        header: t("aging.total"),
        meta: { label: t("aging.total"), align: "end" },
        cell: ({ row }) => <MoneyText value={row.original.aging.total} currency={false} className="font-semibold" />,
      },
    ],
    [t, names],
  );

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <PageHeader
        title={t("aging.title")}
        description={
          aging.data ? (
            <>
              {t("aging.description")} {t("aging.asOf")} <DateText value={aging.data.as_of} />
            </>
          ) : (
            t("aging.description")
          )
        }
        documentTitle={t("aging.title")}
        icon={<CalendarClock />}
      />
      <ClaimsNav />
      {aging.isError ? (
        <AlertCard variant="danger" title={t("errors:title")}>
          {translateError(aging.error)}
        </AlertCard>
      ) : (
        <>
          {totals ? (
            <AmountTiles
              testId="aging-totals"
              tiles={[
                ...AGING_FIELDS.map((key) => ({ key, label: t(`aging.${key}`), value: totals[key], tone: TONES[key] })),
                { key: "total", label: t("aging.total"), value: totals.total, tone: "primary" as const, strong: true },
              ]}
            />
          ) : (
            <Skeleton className="h-20 w-full" />
          )}
          <DataTable
            columns={columns}
            data={rows}
            loading={aging.isPending}
            getRowId={(r) => String(r.payer.id)}
            caption={t("aging.title")}
            minTableWidth={760}
            emptyState={<EmptyState bare size="compact" icon={<CalendarClock />} title={t("aging.empty")} />}
            renderCard={(r) => (
              <div className="card-surface flex flex-col gap-3 p-4" data-testid="aging-row">
                <div className="flex items-start justify-between gap-2">
                  <span className="flex min-w-0 flex-col">
                    <span className="font-semibold">{names.name(r.payer)}</span>
                    <span className="text-xs text-muted">
                      <bdi>{r.payer.code}</bdi>
                    </span>
                  </span>
                  <MoneyText value={r.aging.total} className="text-base font-semibold" />
                </div>
                <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-sm">
                  {AGING_FIELDS.map((key) => (
                    <div key={key} className="flex flex-col">
                      <dt className="text-xs text-muted">{t(`aging.${key}`)}</dt>
                      <dd>
                        <MoneyText value={r.aging[key]} currency={false} />
                      </dd>
                    </div>
                  ))}
                </dl>
              </div>
            )}
          />
        </>
      )}
    </div>
  );
}
