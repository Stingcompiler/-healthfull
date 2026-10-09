import { useNavigate } from "@tanstack/react-router";
import type { ColumnDef } from "@tanstack/react-table";
import { ClipboardCheck, FilePenLine, TriangleAlert } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { DataTable, DataTableOpenButton } from "@/components/DataTable";
import { DateText } from "@/components/DateText";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/badge";
import { useTranslateError } from "@/lib/api/translate-error";

import { PAGE_SIZE, useApprovals } from "../api";
import { LabNav } from "../components/LabNav";
import { useLabNames } from "../lib/use-lab-names";
import type { ApprovalRow } from "../types";

function Marks({ row }: { row: ApprovalRow }) {
  const { t } = useTranslation("lab");
  return (
    <span className="flex flex-wrap gap-1">
      {row.amendment ? (
        <Badge variant="info" data-testid="approval-amendment">
          <FilePenLine aria-hidden="true" />
          {t("approvals.amendment", { number: row.version_no })}
        </Badge>
      ) : null}
      {row.critical_count > 0 ? (
        <Badge variant="danger" data-testid="approval-critical">
          <TriangleAlert aria-hidden="true" />
          {t("approvals.critical", { count: row.critical_count })}
        </Badge>
      ) : null}
      {row.abnormal_count > 0 ? (
        <Badge variant="warning">{t("approvals.abnormal", { count: row.abnormal_count })}</Badge>
      ) : null}
    </span>
  );
}

/**
 * The lab supervisor's queue (FEATURES 9.4): complete results waiting for approval, first
 * results and amendments. Only approved results reach the doctor and the patient.
 */
export function ApprovePage() {
  const { t } = useTranslation(["lab", "errors"]);
  const translateError = useTranslateError();
  const names = useLabNames();
  const navigate = useNavigate();
  const [page, setPage] = useState(1);
  const approvals = useApprovals(page);
  const open = (row: ApprovalRow) => {
    void navigate({ to: "/lab/results/$lineId", params: { lineId: String(row.line_id) } });
  };

  const columns = useMemo<ColumnDef<ApprovalRow>[]>(
    () => [
      {
        id: "test",
        header: t("approvals.columns.test"),
        meta: { label: t("approvals.columns.test"), className: "whitespace-normal" },
        cell: ({ row }) => (
          <span className="flex min-w-0 flex-col gap-1">
            <span className="font-medium">{names.test(row.original.test)}</span>
            <Marks row={row.original} />
          </span>
        ),
      },
      {
        id: "patient",
        header: t("approvals.columns.patient"),
        meta: { label: t("approvals.columns.patient"), className: "whitespace-normal" },
        cell: ({ row }) => (
          <span className="flex min-w-0 flex-col">
            <span>{names.patient(row.original.patient)}</span>
            <span className="text-xs text-muted">
              <bdi>{row.original.patient.file_no}</bdi>
              {row.original.accession_no ? (
                <>
                  {" · "}
                  <bdi>{row.original.accession_no}</bdi>
                </>
              ) : null}
            </span>
          </span>
        ),
      },
      {
        id: "entered",
        header: t("approvals.columns.entered"),
        meta: { label: t("approvals.columns.entered"), align: "end" },
        cell: ({ row }) => (
          <span className="flex flex-col items-end text-sm">
            <span>{names.user(row.original.entered_by)}</span>
            <DateText value={row.original.entered_at} format="datetime" className="text-xs text-muted" />
          </span>
        ),
      },
    ],
    [t, names],
  );

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <PageHeader title={t("approvals.title")} description={t("approvals.description")} icon={<ClipboardCheck />} />
      <LabNav />
      {approvals.isError ? (
        <AlertCard variant="danger" title={t("errors:title")}>
          {translateError(approvals.error)}
        </AlertCard>
      ) : (
        <DataTable
          columns={columns}
          data={approvals.data?.items ?? []}
          loading={approvals.isPending}
          getRowId={(r) => String(r.version_id)}
          caption={t("approvals.title")}
          onRowClick={open}
          rowLabel={(r) => t("worklist.openRow", { test: names.test(r.test), patient: names.patient(r.patient) })}
          serverPagination={{ page, pageSize: PAGE_SIZE, count: approvals.data?.count ?? 0, onPageChange: setPage }}
          minTableWidth={640}
          emptyState={<EmptyState bare size="compact" icon={<ClipboardCheck />} title={t("approvals.empty")} />}
          renderCard={(r, ctx) => (
            <div
              className="card-surface relative flex flex-col gap-2 p-4"
              data-testid="approval-row"
              data-line-id={r.line_id}
            >
              {ctx.open ? (
                <DataTableOpenButton onOpen={ctx.open} label={ctx.openLabel} className="text-start font-semibold">
                  {names.test(r.test)}
                </DataTableOpenButton>
              ) : (
                <span className="font-semibold">{names.test(r.test)}</span>
              )}
              <span className="text-sm">{names.patient(r.patient)}</span>
              <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
                <bdi>{r.patient.file_no}</bdi>
                {r.accession_no ? <bdi>{r.accession_no}</bdi> : null}
                <span>{names.user(r.entered_by)}</span>
                <DateText value={r.entered_at} format="datetime" />
              </span>
              <Marks row={r} />
            </div>
          )}
        />
      )}
    </div>
  );
}
