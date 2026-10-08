import { Link } from "@tanstack/react-router";
import type { ColumnDef } from "@tanstack/react-table";
import { CircleCheck, Copy, Download, FileSpreadsheet, TriangleAlert, Upload } from "lucide-react";
import { useMemo, useRef, useState, type SyntheticEvent } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { AlertCard } from "@/components/AlertCard";
import { Can } from "@/components/Can";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { DataTable } from "@/components/DataTable";
import { EmptyState } from "@/components/EmptyState";
import { KpiCard } from "@/components/KpiCard";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useTranslateError } from "@/lib/api/translate-error";
import { formatNumber } from "@/lib/format";
import { useLanguage } from "@/lib/i18n-hooks";

import {
  IMPORT_ROWS_SHOWN,
  useCancelImport,
  useConfirmImport,
  useImportRows,
  usePreviewImport,
  type ImportRowFilter,
} from "../api";
import { QueryErrorAlert } from "../components/QueryErrorAlert";
import type { ImportJob, ImportRow } from "../types";

const STATUS_VARIANT = {
  valid: "success",
  warning: "warning",
  error: "danger",
  duplicate: "warning",
  imported: "success",
  skipped: "outline",
} as const;

/**
 * Excel import of patients (FEATURES 1.8): upload a sheet, review every row (errors and
 * possible duplicates first), then register the valid rows. The server validates and decides;
 * this screen shows its preview.
 */
export function PatientImportPage() {
  const { t } = useTranslation(["patients", "common"]);
  const language = useLanguage();
  const translateError = useTranslateError();
  const preview = usePreviewImport();
  const confirm = useConfirmImport();
  const cancel = useCancelImport();
  const fileInput = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [job, setJob] = useState<ImportJob | null>(null);
  const [filter, setFilter] = useState<ImportRowFilter | "all">("problems");
  const [includeDuplicates, setIncludeDuplicates] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const status = filter === "all" ? null : filter;
  const rows = useImportRows(job?.id ?? null, status);
  const n = (value: number) => formatNumber(value, language);

  const upload = async (e: SyntheticEvent) => {
    e.preventDefault();
    if (!file) return;
    try {
      const created = await preview.mutateAsync(file);
      setJob(created);
      setFilter(created.error_rows + created.duplicate_rows > 0 ? "problems" : "all");
      setIncludeDuplicates(false);
    } catch {
      // Shown below the form from preview.error.
    }
  };

  const startOver = async () => {
    if (job?.status === "validated") {
      try {
        await cancel.mutateAsync(job.id);
      } catch (e) {
        toast.error(translateError(e));
      }
    }
    setJob(null);
    setFile(null);
    preview.reset();
    if (fileInput.current) fileInput.current.value = "";
  };

  const columns = useMemo<ColumnDef<ImportRow>[]>(
    () => [
      {
        id: "row",
        header: t("import.row"),
        meta: { label: t("import.row"), className: "w-16" },
        accessorKey: "row_no",
        cell: ({ row }) => <span className="tabular">{n(row.original.row_no)}</span>,
      },
      {
        id: "name",
        header: t("list.name"),
        meta: { label: t("list.name") },
        enableSorting: false,
        cell: ({ row }) => <RowName row={row.original} />,
      },
      {
        id: "status",
        header: t("import.status"),
        meta: { label: t("import.status") },
        enableSorting: false,
        cell: ({ row }) => <RowStatus row={row.original} />,
      },
      {
        id: "issues",
        header: t("import.issues"),
        meta: { label: t("import.issues") },
        enableSorting: false,
        cell: ({ row }) => <RowIssues row={row.original} />,
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps -- n only reads language
    [t, language],
  );

  const confirmed = job?.status === "confirmed";
  const importable = job ? job.valid_rows + (includeDuplicates ? job.duplicate_rows : 0) : 0;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        icon={<FileSpreadsheet />}
        eyebrow={<Link to="/patients">{t("title")}</Link>}
        title={t("import.title")}
        description={t("import.description")}
      />

      <Can
        permission="imports.run"
        fallback={
          <EmptyState
            icon={<FileSpreadsheet />}
            title={t("import.notAllowedTitle")}
            description={t("import.notAllowed")}
          />
        }
      >
        {job === null ? (
          <section aria-labelledby="import-upload" className="card-surface flex flex-col gap-4 p-4 md:p-5">
            <h2 id="import-upload" className="text-base font-semibold text-fg">
              {t("import.uploadTitle")}
            </h2>
            <p className="text-sm text-muted">{t("import.columnsHelp")}</p>
            <div className="flex flex-wrap gap-2">
              <Button asChild variant="outline" size="sm">
                <a href="/api/imports/patients/template?language=ar" download>
                  <Download aria-hidden="true" />
                  {t("import.templateAr")}
                </a>
              </Button>
              <Button asChild variant="outline" size="sm">
                <a href="/api/imports/patients/template?language=en" download>
                  <Download aria-hidden="true" />
                  {t("import.templateEn")}
                </a>
              </Button>
            </div>
            <form className="flex flex-col gap-3 sm:flex-row sm:items-end" onSubmit={(e) => void upload(e)}>
              <div className="grid min-w-0 flex-1 gap-1.5">
                <Label htmlFor="import-file">{t("import.file")}</Label>
                <Input
                  ref={fileInput}
                  id="import-file"
                  type="file"
                  accept=".xlsx,.csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/csv"
                  onChange={(e) => {
                    setFile(e.target.files?.[0] ?? null);
                    preview.reset();
                  }}
                />
              </div>
              <Button type="submit" disabled={!file} loading={preview.isPending}>
                <Upload aria-hidden="true" />
                {t("import.check")}
              </Button>
            </form>
            {preview.isError ? (
              <AlertCard variant="danger" live title={t("import.uploadFailed")}>
                {translateError(preview.error)}
              </AlertCard>
            ) : null}
          </section>
        ) : (
          <>
            {confirmed ? (
              <AlertCard
                variant="success"
                live
                title={t("import.doneTitle", { count: job.imported_rows })}
                action={
                  <div className="flex flex-wrap gap-2">
                    <Button asChild size="sm">
                      <Link to="/patients">{t("import.openList")}</Link>
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => void startOver()}>
                      {t("import.another")}
                    </Button>
                  </div>
                }
              >
                {t("import.doneDescription", {
                  skipped: n(job.skipped_rows),
                  errors: n(job.error_rows),
                })}
              </AlertCard>
            ) : null}

            <section aria-label={t("import.summary")} className="grid grid-cols-2 gap-3 md:grid-cols-4 md:gap-4">
              <KpiCard label={t("import.total")} value={n(job.total_rows)} icon={<FileSpreadsheet />} />
              <KpiCard label={t("import.valid")} value={n(job.valid_rows)} icon={<CircleCheck />} tone="success" />
              <KpiCard label={t("import.errors")} value={n(job.error_rows)} icon={<TriangleAlert />} tone="danger" />
              <KpiCard label={t("import.duplicates")} value={n(job.duplicate_rows)} icon={<Copy />} tone="warning" />
            </section>

            <Tabs
              value={filter}
              onValueChange={(v) => {
                setFilter(v as ImportRowFilter | "all");
              }}
            >
              <TabsList className="flex-wrap">
                <TabsTrigger value="problems">{t("import.filterProblems")}</TabsTrigger>
                <TabsTrigger value="all">{t("import.filterAll")}</TabsTrigger>
                {confirmed ? <TabsTrigger value="imported">{t("import.filterImported")}</TabsTrigger> : null}
              </TabsList>
            </Tabs>

            {rows.isError ? (
              <QueryErrorAlert
                title={t("import.rowsFailed")}
                error={rows.error}
                onRetry={() => void rows.refetch()}
                retrying={rows.isFetching}
              />
            ) : (
              <>
                {(rows.data?.count ?? 0) > IMPORT_ROWS_SHOWN ? (
                  <p className="text-sm text-muted" role="status">
                    {t("import.truncated", { count: IMPORT_ROWS_SHOWN, total: n(rows.data?.count ?? 0) })}
                  </p>
                ) : null}
                <DataTable
                  caption={t("import.caption", { file: job.original_filename })}
                  columns={columns}
                  data={rows.data?.items ?? []}
                  loading={rows.isPending}
                  getRowId={(r) => String(r.row_no)}
                  pageSize={25}
                  minTableWidth={720}
                  renderCard={(r) => (
                    <div className="card-surface flex flex-col gap-2 p-4" data-testid="import-row">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="tabular text-xs text-muted">{t("import.rowN", { row: n(r.row_no) })}</span>
                        <RowStatus row={r} />
                      </div>
                      <RowName row={r} />
                      <RowIssues row={r} />
                    </div>
                  )}
                  emptyState={
                    <EmptyState
                      size="compact"
                      icon={<CircleCheck />}
                      title={filter === "problems" ? t("import.noProblems") : t("import.noRows")}
                    />
                  }
                />
              </>
            )}

            {confirmed ? null : (
              <section className="card-surface flex flex-col gap-4 p-4 md:p-5" aria-labelledby="import-confirm">
                <h2 id="import-confirm" className="text-base font-semibold text-fg">
                  {t("import.confirmTitle")}
                </h2>
                {job.duplicate_rows > 0 ? (
                  <label className="flex items-start gap-3 text-sm text-fg">
                    <Switch checked={includeDuplicates} onCheckedChange={setIncludeDuplicates} className="mt-0.5" />
                    <span>{t("import.includeDuplicates", { count: job.duplicate_rows })}</span>
                  </label>
                ) : null}
                <p className="text-sm text-muted">
                  {t("import.willImport", { count: importable })}
                  {job.error_rows > 0 ? ` ${t("import.errorsNotImported")}` : ""}
                </p>
                <div className="flex flex-wrap gap-2">
                  <Button
                    disabled={importable === 0}
                    onClick={() => {
                      setConfirming(true);
                    }}
                  >
                    <Upload aria-hidden="true" />
                    {t("import.confirm")}
                  </Button>
                  <Button variant="outline" loading={cancel.isPending} onClick={() => void startOver()}>
                    {t("import.startOver")}
                  </Button>
                </div>
              </section>
            )}

            <ConfirmDialog
              open={confirming}
              onOpenChange={setConfirming}
              title={t("import.confirmTitle")}
              description={t("import.confirmDescription", { count: importable })}
              confirmLabel={t("import.confirm")}
              onConfirm={async () => {
                const done = await confirm.mutateAsync({ jobId: job.id, includeDuplicates });
                setJob(done);
                setFilter("all");
                toast.success(t("import.doneTitle", { count: done.imported_rows }));
              }}
            />
          </>
        )}
      </Can>
    </div>
  );
}

function RowName({ row }: { row: ImportRow }) {
  const { t } = useTranslation(["patients", "common"]);
  const language = useLanguage();
  const name =
    (language === "ar"
      ? row.data.full_name_ar || row.data.full_name_en
      : row.data.full_name_en || row.data.full_name_ar) || "—";
  const sex = row.data.sex === "male" || row.data.sex === "female" ? t(`common:sex.${row.data.sex}`) : "";
  return (
    <span className="flex min-w-0 flex-col">
      {row.result_id ? (
        <Link
          to="/patients/$patientId"
          params={{ patientId: String(row.result_id) }}
          className="font-medium break-words text-fg underline-offset-4 hover:underline"
        >
          {name}
        </Link>
      ) : (
        <span className="font-medium break-words">{name}</span>
      )}
      <span className="text-xs text-muted">
        {[sex, row.data.date_of_birth ?? "", row.data.phone].filter(Boolean).map((part, i) => (
          <bdi key={i} className="tabular">
            {i > 0 ? " · " : ""}
            {part}
          </bdi>
        ))}
      </span>
    </span>
  );
}

function RowStatus({ row }: { row: ImportRow }) {
  const { t } = useTranslation("patients");
  return (
    <Badge variant={STATUS_VARIANT[row.status]} data-status={row.status}>
      {t(`import.rowStatus.${row.status}`)}
    </Badge>
  );
}

function RowIssues({ row }: { row: ImportRow }) {
  const { t } = useTranslation("patients");
  const translateError = useTranslateError();
  if (row.errors.length === 0 && row.warnings.length === 0) return null;
  return (
    <ul className="grid gap-0.5 text-xs">
      {row.errors.map((e, i) => (
        <li key={`e${String(i)}`} className="text-danger">
          {translateError(e.code)}
        </li>
      ))}
      {row.warnings.map((w, i) => (
        <li key={`w${String(i)}`} className="text-warning-fg">
          {w.code === "in_file"
            ? t("import.hint.in_file", { row: w.row_no ?? "" })
            : t(`import.hint.${w.code}`, { fileNo: w.file_no ?? "", name: w.name ?? "" })}
        </li>
      ))}
    </ul>
  );
}
