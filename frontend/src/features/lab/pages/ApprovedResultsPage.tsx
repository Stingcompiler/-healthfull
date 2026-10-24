import { Link } from "@tanstack/react-router";
import type { ColumnDef } from "@tanstack/react-table";
import { FileCheck2, Printer } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { DataTable } from "@/components/DataTable";
import { DateText } from "@/components/DateText";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { SearchInput } from "@/components/SearchInput";
import { Button } from "@/components/ui/button";
import { useTranslateError } from "@/lib/api/translate-error";

import { PAGE_SIZE, useApprovedResults } from "../api";
import { useLabNames } from "../lib/use-lab-names";
import type { WorklistRow } from "../types";

/**
 * Approved lab results to print for a patient at the front desk (`lab.print_results` without
 * the bench): the last two weeks, or any age when searching by name, file, visit or sample
 * number. Drafts never show; only approved results are printed (FEATURES 9.6).
 */
export function ApprovedResultsPage() {
  const { t } = useTranslation(["lab", "errors"]);
  const translateError = useTranslateError();
  const names = useLabNames();
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const list = useApprovedResults(q, page);

  const columns = useMemo<ColumnDef<WorklistRow>[]>(
    () => [
      {
        id: "test",
        header: t("worklist.columns.test"),
        meta: { label: t("worklist.columns.test"), className: "whitespace-normal" },
        cell: ({ row }) => <span className="font-medium">{names.test(row.original.test)}</span>,
      },
      {
        id: "patient",
        header: t("worklist.columns.patient"),
        meta: { label: t("worklist.columns.patient"), className: "whitespace-normal" },
        cell: ({ row }) => (
          <span className="flex min-w-0 flex-col">
            <span>{names.patient(row.original.patient)}</span>
            <bdi className="num text-xs text-muted">{row.original.patient.file_no}</bdi>
          </span>
        ),
      },
      {
        id: "approved",
        header: t("worklist.columns.approved"),
        meta: { label: t("worklist.columns.approved") },
        cell: ({ row }) =>
          row.original.approved_at ? <DateText value={row.original.approved_at} format="datetime" /> : null,
      },
      {
        id: "print",
        header: t("approvedResults.print"),
        meta: { label: t("approvedResults.print"), align: "end" },
        cell: ({ row }) => <PrintButton row={row.original} />,
      },
    ],
    [t, names],
  );

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <PageHeader title={t("approvedResults.title")} description={t("approvedResults.description")} />
      <SearchInput
        label={t("worklist.search")}
        placeholder={t("worklist.searchPlaceholder")}
        onSearch={(v) => {
          setQ(v);
          setPage(1);
        }}
        className="sm:max-w-sm"
      />
      {list.isError ? (
        <AlertCard variant="danger" title={t("errors:title")}>
          {translateError(list.error)}
        </AlertCard>
      ) : (
        <DataTable
          columns={columns}
          data={list.data?.items ?? []}
          loading={list.isPending}
          getRowId={(r) => String(r.line_id)}
          caption={t("approvedResults.title")}
          serverPagination={{ page, pageSize: PAGE_SIZE, count: list.data?.count ?? 0, onPageChange: setPage }}
          minTableWidth={600}
          emptyState={
            <EmptyState
              bare
              size="compact"
              icon={<FileCheck2 />}
              title={q ? t("approvedResults.emptySearch") : t("worklist.emptyDone")}
            />
          }
          renderCard={(r) => (
            <div className="card-surface flex flex-col gap-2 p-4" data-testid="approved-row" data-line-id={r.line_id}>
              <span className="font-semibold">{names.test(r.test)}</span>
              <span className="text-sm">{names.patient(r.patient)}</span>
              <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
                <bdi className="num">{r.patient.file_no}</bdi>
                {r.approved_at ? <DateText value={r.approved_at} format="datetime" /> : null}
              </span>
              <div className="flex justify-end">
                <PrintButton row={r} />
              </div>
            </div>
          )}
        />
      )}
    </div>
  );
}

function PrintButton({ row }: { row: WorklistRow }) {
  const { t } = useTranslation("lab");
  const names = useLabNames();
  return (
    <Button asChild variant="outline" size="sm">
      <Link
        to="/lab/results/$lineId/print"
        params={{ lineId: String(row.line_id) }}
        aria-label={t("approvedResults.printFor", { test: names.test(row.test), patient: names.patient(row.patient) })}
        data-testid="approved-print"
      >
        <Printer aria-hidden="true" />
        {t("approvedResults.print")}
      </Link>
    </Button>
  );
}
