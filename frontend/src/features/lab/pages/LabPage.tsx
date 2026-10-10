import { Navigate, useNavigate, useSearch } from "@tanstack/react-router";
import type { ColumnDef } from "@tanstack/react-table";
import { FlaskConical, ShieldCheck, TriangleAlert } from "lucide-react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { DataTable, DataTableOpenButton } from "@/components/DataTable";
import { DateText } from "@/components/DateText";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { SearchInput } from "@/components/SearchInput";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useTranslateError } from "@/lib/api/translate-error";
import { usePermission } from "@/lib/auth/hooks";
import { formatNumber } from "@/lib/format";
import { useLanguage } from "@/lib/i18n-hooks";

import { PAGE_SIZE, useWorklist } from "../api";
import { StageBadge } from "../components/badges";
import { LabNav } from "../components/LabNav";
import { parseWorklistSearch, WORKLIST_FILTERS, type WorklistSearch } from "../lib/search";
import { useLabNames } from "../lib/use-lab-names";
import type { WorklistFilter, WorklistRow } from "../types";

function isOverdue(row: WorklistRow): boolean {
  return row.due_at !== null && row.stage !== "done" && new Date(row.due_at).getTime() < Date.now();
}

/** Small marks of a row: performed first under an authorization, a critical value, overdue. */
function RowMarks({ row }: { row: WorklistRow }) {
  const { t } = useTranslation("lab");
  if (!row.authorized && !row.critical && !isOverdue(row)) return null;
  return (
    <span className="flex flex-wrap gap-1">
      {row.critical ? (
        <Badge variant="danger" data-testid="row-critical">
          <TriangleAlert aria-hidden="true" />
          {t("worklist.critical")}
        </Badge>
      ) : null}
      {isOverdue(row) ? <Badge variant="warning">{t("worklist.overdue")}</Badge> : null}
      {row.authorized ? (
        <Badge variant="info">
          <ShieldCheck aria-hidden="true" />
          {t("worklist.authorized")}
        </Badge>
      ) : null}
    </span>
  );
}

/**
 * The lab work list (FEATURES 9.2, FLOW step 5): only paid tests, or tests performed first
 * under an authorization, appear (invariant 1). Filtered by bench stage; a row opens the test.
 */
export function LabPage() {
  const { t } = useTranslation(["lab", "common", "errors"]);
  const canWork = usePermission("lab.view_worklist");
  const canReports = usePermission("lab.view_reports");
  if (!canWork && canReports) return <Navigate to="/lab/tat" replace />;
  return <Worklist title={t("worklist.title")} />;
}

function Worklist({ title }: { title: string }) {
  const { t } = useTranslation(["lab", "common", "errors"]);
  const translateError = useTranslateError();
  const language = useLanguage();
  const names = useLabNames();
  const navigate = useNavigate();
  const search = parseWorklistSearch(useSearch({ strict: false }));
  const status: WorklistFilter = search.status ?? "open";
  const q = search.q ?? "";
  const page = search.page ?? 1;
  const worklist = useWorklist(status, q, page);

  const setSearch = (next: WorklistSearch) => {
    void navigate({ to: "/lab", search: parseWorklistSearch({ ...next }), replace: true });
  };
  const open = (row: WorklistRow) => {
    void navigate({ to: "/lab/results/$lineId", params: { lineId: String(row.line_id) } });
  };

  const counts = worklist.data?.counts;
  const filterLabel = (f: WorklistFilter) => {
    const label = t(`filters.${f}`);
    const count = f !== "open" && f !== "done" && counts ? counts[f] : undefined;
    return count !== undefined ? `${label} (${formatNumber(count, language)})` : label;
  };

  const columns = useMemo<ColumnDef<WorklistRow>[]>(
    () => [
      {
        id: "patient",
        header: t("worklist.columns.patient"),
        meta: { label: t("worklist.columns.patient"), className: "whitespace-normal" },
        cell: ({ row }) => (
          <span className="flex min-w-0 flex-col">
            <span className="font-medium">{names.patient(row.original.patient)}</span>
            <span className="text-xs text-muted">
              <bdi>{row.original.patient.file_no}</bdi> · <bdi>{row.original.visit_number}</bdi>
            </span>
          </span>
        ),
      },
      {
        id: "test",
        header: t("worklist.columns.test"),
        meta: { label: t("worklist.columns.test"), className: "whitespace-normal" },
        cell: ({ row }) => (
          <span className="flex min-w-0 flex-col gap-1">
            <span>{names.test(row.original.test)}</span>
            <span className="text-xs text-muted">
              <bdi>{row.original.test.code}</bdi> · {t(`sampleType.${row.original.test.sample_type}`)}
            </span>
            <RowMarks row={row.original} />
          </span>
        ),
      },
      {
        id: "stage",
        header: t("worklist.columns.stage"),
        meta: { label: t("worklist.columns.stage") },
        cell: ({ row }) => (
          <span className="flex flex-col gap-1">
            <StageBadge stage={row.original.stage} />
            {row.original.sample ? (
              <bdi className="text-xs text-muted" data-testid="row-accession">
                {row.original.sample.accession_no}
              </bdi>
            ) : null}
          </span>
        ),
      },
      {
        id: "time",
        header: status === "done" ? t("worklist.columns.approved") : t("worklist.columns.due"),
        meta: { label: t("worklist.columns.due"), align: "end" },
        cell: ({ row }) => {
          const r = row.original;
          const when = status === "done" ? r.approved_at : r.due_at;
          return when ? (
            <DateText value={when} format="datetime" className="text-sm" />
          ) : (
            <span className="text-xs text-muted">
              {t("worklist.ordered")} <DateText value={r.ordered_at} format="time" />
            </span>
          );
        },
      },
    ],
    [t, names, status],
  );

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <PageHeader title={title} description={t("worklist.description")} icon={<FlaskConical />} />
      <LabNav />
      <div className="flex min-w-0 flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="md:hidden">
          <Select
            value={status}
            onValueChange={(v) => {
              setSearch({ status: v as WorklistFilter, q });
            }}
          >
            <SelectTrigger className="h-11 w-full" aria-label={t("filters.label")} data-testid="worklist-filter-select">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {WORKLIST_FILTERS.map((f) => (
                <SelectItem key={f} value={f}>
                  {filterLabel(f)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <Tabs
          className="hidden md:flex"
          value={status}
          onValueChange={(v) => {
            setSearch({ status: v as WorklistFilter, q });
          }}
        >
          <TabsList aria-label={t("filters.label")}>
            {WORKLIST_FILTERS.map((f) => (
              <TabsTrigger key={f} value={f} data-testid={`worklist-filter-${f}`}>
                {filterLabel(f)}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
        <SearchInput
          label={t("worklist.search")}
          placeholder={t("worklist.searchPlaceholder")}
          defaultValue={q}
          onSearch={(value) => {
            setSearch({ status, q: value });
          }}
          loading={worklist.isFetching && !worklist.isPending}
          className="w-full lg:max-w-xs"
          data-testid="worklist-search"
        />
      </div>
      {worklist.isError ? (
        <AlertCard variant="danger" title={t("errors:title")}>
          {translateError(worklist.error)}
        </AlertCard>
      ) : (
        <DataTable
          columns={columns}
          data={worklist.data?.items ?? []}
          loading={worklist.isPending}
          getRowId={(r) => String(r.line_id)}
          caption={title}
          onRowClick={open}
          rowLabel={(r) => t("worklist.openRow", { test: names.test(r.test), patient: names.patient(r.patient) })}
          serverPagination={{
            page,
            pageSize: PAGE_SIZE,
            count: worklist.data?.count ?? 0,
            onPageChange: (p) => {
              setSearch({ status, q, page: p });
            },
          }}
          minTableWidth={720}
          emptyState={
            <EmptyState
              bare
              size="compact"
              icon={<FlaskConical />}
              title={status === "done" ? t("worklist.emptyDone") : t("worklist.empty")}
              description={t("worklist.emptyHint")}
            />
          }
          renderCard={(r, ctx) => (
            <div
              className="card-surface relative flex flex-col gap-2 p-4"
              data-testid="worklist-row"
              data-line-id={r.line_id}
              data-stage={r.stage}
            >
              <div className="flex items-start justify-between gap-2">
                <span className="flex min-w-0 flex-col">
                  {ctx.open ? (
                    <DataTableOpenButton onOpen={ctx.open} label={ctx.openLabel} className="text-start font-semibold">
                      {names.test(r.test)}
                    </DataTableOpenButton>
                  ) : (
                    <span className="font-semibold">{names.test(r.test)}</span>
                  )}
                  <span className="text-sm">{names.patient(r.patient)}</span>
                </span>
                <StageBadge stage={r.stage} />
              </div>
              <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
                <bdi>{r.patient.file_no}</bdi>
                <bdi>{r.visit_number}</bdi>
                {r.sample ? <bdi data-testid="row-accession">{r.sample.accession_no}</bdi> : null}
                <span>{t(`sampleType.${r.test.sample_type}`)}</span>
                {r.due_at ? (
                  <span>
                    {t("worklist.columns.due")}: <DateText value={r.due_at} format="time" />
                  </span>
                ) : null}
              </span>
              <RowMarks row={r} />
            </div>
          )}
        />
      )}
    </div>
  );
}
