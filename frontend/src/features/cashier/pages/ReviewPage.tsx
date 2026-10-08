import { useNavigate } from "@tanstack/react-router";
import type { ColumnDef } from "@tanstack/react-table";
import { ClipboardCheck } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { DataTable, DataTableOpenButton } from "@/components/DataTable";
import { DateText } from "@/components/DateText";
import { EmptyState } from "@/components/EmptyState";
import { MoneyText } from "@/components/MoneyText";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useTranslateError } from "@/lib/api/translate-error";

import { PAGE_SIZE, useCurrentShift, useShifts } from "../api";
import { CashierNav } from "../components/CashierNav";
import { IncomingHandovers } from "../components/HandoverPanel";
import { Pager } from "../components/Pager";
import { useNames } from "../lib/use-names";
import type { ShiftListItem } from "../types";

type Filter = "toReview" | "closed" | "open";

/** The manager's review queue: closed shifts with variances and pending money (FEATURES 7.5). */
export function ReviewPage() {
  const { t } = useTranslation(["cashier", "errors"]);
  const translateError = useTranslateError();
  const names = useNames();
  const navigate = useNavigate();
  const [filter, setFilter] = useState<Filter>("toReview");
  const [page, setPage] = useState(1);
  // Cash sent to the safe, the bank or this supervisor waits here until they confirm it (7.6).
  const current = useCurrentShift();
  const shifts = useShifts({
    status: filter === "open" ? "open" : "closed",
    ...(filter === "toReview" ? { reviewed: false } : {}),
    page,
  });

  const columns = useMemo<ColumnDef<ShiftListItem>[]>(
    () => [
      {
        id: "number",
        header: t("review.columns.shift"),
        meta: { label: t("review.columns.shift") },
        cell: ({ row }) => <bdi>{row.original.shift.number}</bdi>,
      },
      {
        id: "cashier",
        header: t("review.columns.cashier"),
        meta: { label: t("review.columns.cashier") },
        cell: ({ row }) => names.user(row.original.shift.cashier),
      },
      {
        id: "closed",
        header: t("review.columns.closedAt"),
        meta: { label: t("review.columns.closedAt") },
        cell: ({ row }) =>
          row.original.shift.closed_at ? <DateText value={row.original.shift.closed_at} format="datetime" /> : "—",
      },
      {
        id: "variance",
        header: t("review.columns.variance"),
        meta: { label: t("review.columns.variance"), align: "end" },
        cell: ({ row }) =>
          row.original.shift.variance !== null ? (
            <MoneyText value={row.original.shift.variance} signed toneNegative />
          ) : (
            "—"
          ),
      },
      {
        id: "pending",
        header: t("review.columns.pending"),
        meta: { label: t("review.columns.pending"), align: "end" },
        cell: ({ row }) =>
          row.original.pending_count > 0 ? (
            <span className="text-warning-fg">
              <MoneyText value={row.original.pending_amount} /> ({row.original.pending_count})
            </span>
          ) : (
            "—"
          ),
      },
      {
        id: "review",
        header: t("review.columns.review"),
        meta: { label: t("review.columns.review") },
        cell: ({ row }) =>
          row.original.shift.review ? (
            <Badge variant={row.original.shift.review.outcome === "approved" ? "success" : "danger"}>
              {t(`review.outcome.${row.original.shift.review.outcome}`)}
            </Badge>
          ) : (
            <Badge variant="warning">{t("review.awaiting")}</Badge>
          ),
      },
    ],
    [t, names],
  );

  const open = (row: ShiftListItem) => {
    void navigate({ to: "/cashier/shifts/$shiftId", params: { shiftId: String(row.shift.id) } });
  };

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <PageHeader title={t("review.pageTitle")} description={t("review.pageDescription")} icon={<ClipboardCheck />} />
      <CashierNav />
      <IncomingHandovers handovers={current.data?.incoming_handovers ?? []} />
      <Tabs
        value={filter}
        onValueChange={(v) => {
          setFilter(v as Filter);
          setPage(1);
        }}
      >
        <TabsList aria-label={t("review.filter")}>
          <TabsTrigger value="toReview">{t("review.filters.toReview")}</TabsTrigger>
          <TabsTrigger value="closed">{t("review.filters.closed")}</TabsTrigger>
          <TabsTrigger value="open">{t("review.filters.open")}</TabsTrigger>
        </TabsList>
      </Tabs>
      {shifts.isError ? (
        <AlertCard variant="danger" title={t("errors:title")}>
          {translateError(shifts.error)}
        </AlertCard>
      ) : (
        <>
          <DataTable
            columns={columns}
            data={shifts.data?.items ?? []}
            loading={shifts.isPending}
            getRowId={(r) => String(r.shift.id)}
            caption={t("review.pageTitle")}
            onRowClick={open}
            rowLabel={(r) => t("review.open", { number: r.shift.number })}
            pageSize={PAGE_SIZE}
            pageSizeOptions={[PAGE_SIZE]}
            emptyState={<EmptyState bare size="compact" title={t("review.empty")} icon={<ClipboardCheck />} />}
            renderCard={(r, ctx) => (
              <div className="card-surface flex flex-col gap-2 p-4" data-testid="shift-row">
                <div className="flex items-center justify-between gap-2">
                  {ctx.open ? (
                    <DataTableOpenButton onOpen={ctx.open} label={ctx.openLabel} className="font-semibold">
                      <bdi>{r.shift.number}</bdi>
                    </DataTableOpenButton>
                  ) : null}
                  {r.shift.review ? (
                    <Badge variant={r.shift.review.outcome === "approved" ? "success" : "danger"}>
                      {t(`review.outcome.${r.shift.review.outcome}`)}
                    </Badge>
                  ) : (
                    <Badge variant="warning">{t("review.awaiting")}</Badge>
                  )}
                </div>
                <span className="text-sm text-muted">{names.user(r.shift.cashier)}</span>
                <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
                  {r.shift.variance !== null ? (
                    <span>
                      {t("review.columns.variance")} <MoneyText value={r.shift.variance} signed toneNegative />
                    </span>
                  ) : null}
                  {r.pending_count > 0 ? (
                    <span className="text-warning-fg">
                      {t("review.columns.pending")} <MoneyText value={r.pending_amount} />
                    </span>
                  ) : null}
                </div>
              </div>
            )}
          />
          <Pager page={page} pageSize={PAGE_SIZE} count={shifts.data?.count ?? 0} onPage={setPage} />
        </>
      )}
    </div>
  );
}
