import { Link } from "@tanstack/react-router";
import type { ColumnDef } from "@tanstack/react-table";
import { CircleCheck, Copy, Download, FileSpreadsheet, TriangleAlert, Upload } from "lucide-react";
import { useMemo, useRef, useState, type ReactNode, type SyntheticEvent } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { AlertCard } from "@/components/AlertCard";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { DataTable } from "@/components/DataTable";
import { DateText } from "@/components/DateText";
import { EmptyState } from "@/components/EmptyState";
import { KpiCard } from "@/components/KpiCard";
import { MoneyText } from "@/components/MoneyText";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useTranslateError } from "@/lib/api/translate-error";
import { useCurrentUser } from "@/lib/auth/hooks";
import { hasPermission } from "@/lib/auth/permissions";
import { formatNumber } from "@/lib/format";
import { useLanguage } from "@/lib/i18n-hooks";
import { cn } from "@/lib/utils";

import { AdminPage, QueryState } from "../components/AdminPage";
import {
  IMPORT_PAGE_SIZE,
  useCancelImportJob,
  useConfirmImportJob,
  useImportJobRows,
  useImportJobs,
  useImportPriceLists,
  useImportStores,
  usePreviewImportJob,
  type ImportRowFilter,
} from "../ops-api";
import type { ImportJob, ImportJobRow, ImportKind } from "../ops-types";

const KINDS: readonly { kind: ImportKind; permission: string | null }[] = [
  { kind: "patients", permission: null },
  { kind: "items", permission: "pharmacy.manage_items" },
  { kind: "prices", permission: "catalog.manage_prices" },
];

const STATUS_VARIANT = {
  valid: "success",
  warning: "info",
  error: "danger",
  duplicate: "warning",
  imported: "success",
  skipped: "outline",
} as const;

const NO_STORE = "__none__";
const TEMPLATE_LANGUAGES = ["ar", "en"] as const;

/** Tomorrow as YYYY-MM-DD in the browser's calendar (the server checks the real rule). */
function tomorrow(): string {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  return `${String(d.getFullYear())}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function text(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return "";
}

/**
 * Excel imports (FEATURES 1.8, 8.13, 5.2): choose what to import, download the template,
 * upload, review every row (errors and possible duplicates first), then import. The server
 * validates and imports through the owning module's rules; this wizard shows its answers.
 */
export function ImportsPage() {
  const { t } = useTranslation(["ops", "admin", "common"]);
  const language = useLanguage();
  const me = useCurrentUser();
  const translateError = useTranslateError();
  const preview = usePreviewImportJob();
  const confirm = useConfirmImportJob();
  const cancel = useCancelImportJob();
  const fileInput = useRef<HTMLInputElement>(null);

  const [kind, setKind] = useState<ImportKind>("patients");
  const [store, setStore] = useState<string>(NO_STORE);
  const [priceList, setPriceList] = useState<string>("");
  const [effectiveFrom, setEffectiveFrom] = useState<string>(tomorrow());
  const [file, setFile] = useState<File | null>(null);
  const [job, setJob] = useState<ImportJob | null>(null);
  const [filter, setFilter] = useState<ImportRowFilter | "all">("problems");
  const [page, setPage] = useState(1);
  const [includeDuplicates, setIncludeDuplicates] = useState(false);
  const [confirming, setConfirming] = useState(false);

  const stores = useImportStores(kind === "items" && job === null);
  const priceLists = useImportPriceLists(kind === "prices" && job === null);
  const rows = useImportJobRows(job?.id ?? null, filter === "all" ? null : filter, page);
  const history = useImportJobs(null);
  const n = (value: number) => formatNumber(value, language);
  const jobKind = (job?.kind ?? kind) as ImportKind;

  const allowed = (permission: string | null) => permission === null || hasPermission(me, permission);
  const needsOptions = kind === "prices" && (!priceList || !effectiveFrom);

  const upload = async (e: SyntheticEvent) => {
    e.preventDefault();
    if (!file || needsOptions) return;
    try {
      const created = await preview.mutateAsync({
        kind,
        file,
        store: kind === "items" && store !== NO_STORE ? store : undefined,
        priceList: kind === "prices" ? priceList : undefined,
        effectiveFrom: kind === "prices" ? effectiveFrom : undefined,
      });
      setJob(created);
      setPage(1);
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
      } catch (error) {
        toast.error(translateError(error));
      }
    }
    setJob(null);
    setFile(null);
    preview.reset();
    if (fileInput.current) fileInput.current.value = "";
  };

  const columns = useMemo<ColumnDef<ImportJobRow>[]>(
    () => [
      {
        id: "row",
        header: t("imports.row"),
        meta: { label: t("imports.row"), className: "w-16" },
        accessorKey: "row_no",
        cell: ({ row }) => <span className="tabular">{n(row.original.row_no)}</span>,
      },
      {
        id: "record",
        header: t("imports.record"),
        meta: { label: t("imports.record") },
        enableSorting: false,
        cell: ({ row }) => <RowRecord kind={jobKind} row={row.original} />,
      },
      {
        id: "status",
        header: t("imports.status"),
        meta: { label: t("imports.status") },
        enableSorting: false,
        cell: ({ row }) => <RowStatusBadge row={row.original} />,
      },
      {
        id: "issues",
        header: t("imports.issues"),
        meta: { label: t("imports.issues") },
        enableSorting: false,
        cell: ({ row }) => <RowIssues row={row.original} />,
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps -- n only reads language
    [t, language, jobKind],
  );

  const confirmed = job?.status === "confirmed";
  const importable = job ? job.valid_rows + (includeDuplicates ? job.duplicate_rows : 0) : 0;

  return (
    <AdminPage section="imports" title={t("admin:sections.imports.title")} description={t("imports.description")}>
      {job === null ? (
        <section aria-labelledby="import-setup" className="card-surface flex flex-col gap-5 p-4 md:p-5">
          <h2 id="import-setup" className="text-base font-semibold text-fg">
            {t("imports.kindTitle")}
          </h2>
          <RadioGroup
            value={kind}
            onValueChange={(value) => {
              setKind(value as ImportKind);
              preview.reset();
            }}
            className="grid grid-cols-1 gap-3 md:grid-cols-3"
            aria-label={t("imports.kindTitle")}
          >
            {KINDS.map(({ kind: k, permission }) => {
              const ok = allowed(permission);
              return (
                <label
                  key={k}
                  htmlFor={`import-kind-${k}`}
                  className={cn(
                    "flex min-w-0 cursor-pointer items-start gap-3 rounded-card border border-border p-3 transition-colors",
                    kind === k ? "border-primary bg-primary-soft" : "hover:bg-accent",
                    !ok && "cursor-not-allowed opacity-60",
                  )}
                >
                  <RadioGroupItem id={`import-kind-${k}`} value={k} disabled={!ok} className="mt-0.5" />
                  <span className="min-w-0">
                    <span className="block font-medium text-fg">{t(`imports.kinds.${k}.title`)}</span>
                    <span className="mt-0.5 block text-sm text-muted">
                      {ok ? t(`imports.kinds.${k}.description`) : t("imports.kindNotAllowed")}
                    </span>
                  </span>
                </label>
              );
            })}
          </RadioGroup>

          {kind === "items" ? (
            <div className="grid gap-1.5 sm:max-w-sm">
              <Label htmlFor="import-store">{t("imports.store")}</Label>
              <Select value={store} onValueChange={setStore}>
                <SelectTrigger id="import-store" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={NO_STORE}>{t("imports.storeNone")}</SelectItem>
                  {(stores.data?.stores ?? []).map((s) => (
                    <SelectItem key={s.id} value={s.code}>
                      {language === "ar" ? s.name_ar || s.name_en : s.name_en || s.name_ar}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-xs text-muted">{t("imports.storeHint")}</p>
            </div>
          ) : null}

          {kind === "prices" ? (
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="grid min-w-0 gap-1.5">
                <Label htmlFor="import-price-list">{t("imports.priceList")}</Label>
                <Select value={priceList} onValueChange={setPriceList}>
                  <SelectTrigger id="import-price-list" className="w-full">
                    <SelectValue placeholder={t("imports.priceListPick")} />
                  </SelectTrigger>
                  <SelectContent>
                    {(priceLists.data ?? [])
                      .filter((pl) => pl.active)
                      .map((pl) => (
                        <SelectItem key={pl.id} value={pl.code}>
                          {language === "ar" ? pl.name_ar || pl.name_en : pl.name_en || pl.name_ar}
                        </SelectItem>
                      ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="grid min-w-0 gap-1.5">
                <Label htmlFor="import-effective">{t("imports.effectiveFrom")}</Label>
                <Input
                  id="import-effective"
                  type="date"
                  dir="ltr"
                  min={tomorrow()}
                  value={effectiveFrom}
                  onChange={(e) => {
                    setEffectiveFrom(e.target.value);
                  }}
                />
              </div>
              <p className="text-xs text-muted sm:col-span-2">{t("imports.effectiveHint")}</p>
            </div>
          ) : null}

          <div className="flex flex-col gap-2">
            <h3 className="text-sm font-semibold text-fg">{t("imports.templateTitle")}</h3>
            <p className="text-sm text-muted">{t(`imports.kinds.${kind}.columns`)}</p>
            <div className="flex flex-wrap gap-2">
              {TEMPLATE_LANGUAGES.map((lang) => (
                <Button key={lang} asChild variant="outline" size="sm">
                  <a href={`/api/imports/templates/${kind}?language=${lang}`} download>
                    <Download aria-hidden="true" />
                    {t(lang === "ar" ? "imports.templateAr" : "imports.templateEn")}
                  </a>
                </Button>
              ))}
            </div>
          </div>

          <form className="flex flex-col gap-3 sm:flex-row sm:items-end" onSubmit={(e) => void upload(e)}>
            <div className="grid min-w-0 flex-1 gap-1.5">
              <Label htmlFor="import-file">{t("imports.file")}</Label>
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
              <p className="text-xs text-muted">{t("imports.fileHint")}</p>
            </div>
            <Button type="submit" disabled={!file || needsOptions} loading={preview.isPending}>
              <Upload aria-hidden="true" />
              {t("imports.check")}
            </Button>
          </form>
          {preview.isError ? (
            <AlertCard variant="danger" live title={t("imports.uploadFailed")}>
              {translateError(preview.error)}
            </AlertCard>
          ) : null}
        </section>
      ) : (
        <>
          <p className="text-sm text-muted">
            {t("imports.reviewing", { kind: t(`imports.kinds.${jobKind}.title`), file: job.original_filename })}
          </p>
          {confirmed ? (
            <AlertCard
              variant="success"
              live
              title={t("imports.doneTitle", { count: job.imported_rows })}
              action={
                <div className="flex flex-wrap gap-2">
                  <ResultLink job={job} />
                  <Button size="sm" variant="outline" onClick={() => void startOver()}>
                    {t("imports.another")}
                  </Button>
                </div>
              }
            >
              <ResultSummary job={job} />
            </AlertCard>
          ) : null}

          <section aria-label={t("imports.summary")} className="grid grid-cols-2 gap-3 md:grid-cols-4 md:gap-4">
            <KpiCard label={t("imports.total")} value={n(job.total_rows)} icon={<FileSpreadsheet />} />
            <KpiCard label={t("imports.valid")} value={n(job.valid_rows)} icon={<CircleCheck />} tone="success" />
            <KpiCard label={t("imports.errors")} value={n(job.error_rows)} icon={<TriangleAlert />} tone="danger" />
            <KpiCard label={t("imports.duplicates")} value={n(job.duplicate_rows)} icon={<Copy />} tone="warning" />
          </section>

          <Tabs
            value={filter}
            onValueChange={(v) => {
              setFilter(v as ImportRowFilter | "all");
              setPage(1);
            }}
          >
            <TabsList className="flex-wrap">
              <TabsTrigger value="problems">{t("imports.filterProblems")}</TabsTrigger>
              <TabsTrigger value="all">{t("imports.filterAll")}</TabsTrigger>
              {confirmed ? <TabsTrigger value="imported">{t("imports.filterImported")}</TabsTrigger> : null}
            </TabsList>
          </Tabs>

          <QueryState
            loading={rows.isPending}
            error={rows.isError ? rows.error : null}
            onRetry={() => void rows.refetch()}
          >
            <DataTable
              caption={t("imports.caption", { file: job.original_filename })}
              columns={columns}
              data={rows.data?.items ?? []}
              loading={rows.isFetching && !rows.data}
              getRowId={(r) => String(r.row_no)}
              minTableWidth={720}
              serverPagination={{
                page,
                pageSize: IMPORT_PAGE_SIZE,
                count: rows.data?.count ?? 0,
                onPageChange: setPage,
              }}
              renderCard={(r) => (
                <div className="card-surface flex flex-col gap-2 p-4" data-testid="import-row">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="tabular text-xs text-muted">{t("imports.rowN", { row: n(r.row_no) })}</span>
                    <RowStatusBadge row={r} />
                  </div>
                  <RowRecord kind={jobKind} row={r} />
                  <RowIssues row={r} />
                </div>
              )}
              emptyState={
                <EmptyState
                  size="compact"
                  icon={<CircleCheck />}
                  title={filter === "problems" ? t("imports.noProblems") : t("imports.noRows")}
                />
              }
            />
          </QueryState>

          {confirmed ? null : (
            <section className="card-surface flex flex-col gap-4 p-4 md:p-5" aria-labelledby="import-confirm">
              <h2 id="import-confirm" className="text-base font-semibold text-fg">
                {t("imports.confirmTitle")}
              </h2>
              {job.duplicate_rows > 0 ? (
                <label className="flex items-start gap-3 text-sm text-fg">
                  <Switch checked={includeDuplicates} onCheckedChange={setIncludeDuplicates} className="mt-0.5" />
                  <span>{t("imports.includeDuplicates", { count: job.duplicate_rows })}</span>
                </label>
              ) : null}
              <p className="text-sm text-muted">
                {t("imports.willImport", { count: importable })}
                {job.error_rows > 0 ? ` ${t("imports.errorsNotImported")}` : ""}
              </p>
              {jobKind === "items" ? <p className="text-sm text-muted">{t("imports.itemsNote")}</p> : null}
              {jobKind === "prices" ? (
                <p className="text-sm text-muted">
                  {t("imports.pricesNote", {
                    list: text(job.options.price_list),
                    date: text(job.options.effective_from),
                  })}
                </p>
              ) : null}
              <div className="flex flex-wrap gap-2">
                <Button
                  disabled={importable === 0}
                  onClick={() => {
                    setConfirming(true);
                  }}
                >
                  <Upload aria-hidden="true" />
                  {t("imports.confirm")}
                </Button>
                <Button variant="outline" loading={cancel.isPending} onClick={() => void startOver()}>
                  {t("imports.startOver")}
                </Button>
              </div>
            </section>
          )}

          <ConfirmDialog
            open={confirming}
            onOpenChange={setConfirming}
            title={t("imports.confirmTitle")}
            description={t("imports.confirmDescription", { count: importable })}
            confirmLabel={t("imports.confirm")}
            onConfirm={async () => {
              // A refusal stays in the dialog (ConfirmDialog shows the translated error).
              const done = await confirm.mutateAsync({ jobId: job.id, includeDuplicates });
              setJob(done);
              setFilter("all");
              setPage(1);
              toast.success(t("imports.doneTitle", { count: done.imported_rows }));
            }}
          />
        </>
      )}

      <section aria-labelledby="import-history" className="flex flex-col gap-3">
        <h2 id="import-history" className="text-base font-semibold text-fg">
          {t("imports.historyTitle")}
        </h2>
        <QueryState
          loading={history.isPending}
          error={history.isError ? history.error : null}
          onRetry={() => void history.refetch()}
          rows={2}
        >
          {(history.data?.items.length ?? 0) === 0 ? (
            <p className="text-sm text-muted">{t("imports.historyEmpty")}</p>
          ) : (
            <ul className="grid gap-2">
              {history.data?.items.map((h) => (
                <li
                  key={h.id}
                  className="card-surface flex flex-wrap items-center justify-between gap-x-4 gap-y-1 px-4 py-3 text-sm"
                >
                  <span className="flex min-w-0 flex-col">
                    <span className="font-medium break-words text-fg">
                      {t(`imports.kinds.${h.kind as ImportKind}.title`)} · <bdi>{h.original_filename}</bdi>
                    </span>
                    <span className="text-xs text-muted">
                      <DateText value={h.created_at} format="datetime" />
                    </span>
                  </span>
                  <span className="flex flex-wrap items-center gap-2">
                    <Badge variant={h.status === "confirmed" ? "success" : "outline"}>
                      {t(`imports.jobStatus.${h.status}`)}
                    </Badge>
                    {h.status === "confirmed" ? (
                      <span className="tabular text-xs text-muted">
                        {t("imports.historyImported", { count: h.imported_rows })}
                      </span>
                    ) : null}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </QueryState>
      </section>
    </AdminPage>
  );
}

function ResultSummary({ job }: { job: ImportJob }) {
  const { t } = useTranslation("ops");
  const language = useLanguage();
  const skipped = Number(job.summary.skipped ?? 0);
  const receipts = Array.isArray(job.summary.receipts) ? job.summary.receipts.map(text) : [];
  const numbers = receipts.join(language === "ar" ? "، " : ", ");
  return (
    <span className="flex flex-col gap-1">
      <span>
        {t("imports.doneDescription", {
          skipped: formatNumber(skipped, language),
          errors: formatNumber(job.error_rows, language),
        })}
      </span>
      {receipts.length > 0 ? <span>{t("imports.receipts", { numbers })}</span> : null}
    </span>
  );
}

function ResultLink({ job }: { job: ImportJob }) {
  const { t } = useTranslation("ops");
  if (job.kind === "patients") {
    return (
      <Button asChild size="sm">
        <Link to="/patients">{t("imports.openPatients")}</Link>
      </Button>
    );
  }
  if (job.kind === "items") {
    return (
      <Button asChild size="sm">
        <Link to="/pharmacy/items">{t("imports.openItems")}</Link>
      </Button>
    );
  }
  const versionId = Number(job.summary.version_id ?? 0);
  if (!versionId) return null;
  return (
    <Button asChild size="sm">
      <Link to="/administration/price-lists">{t("imports.openPriceLists")}</Link>
    </Button>
  );
}

function RowStatusBadge({ row }: { row: ImportJobRow }) {
  const { t } = useTranslation("ops");
  return (
    <Badge variant={STATUS_VARIANT[row.status]} data-status={row.status}>
      {t(`imports.rowStatus.${row.status}`)}
    </Badge>
  );
}

function RowRecord({ kind, row }: { kind: ImportKind; row: ImportJobRow }) {
  const { t } = useTranslation(["ops", "common"]);
  const language = useLanguage();
  const d = row.data;
  let title: ReactNode;
  let lines: ReactNode[] = [];
  if (kind === "patients") {
    const name =
      (language === "ar"
        ? text(d.full_name_ar) || text(d.full_name_en)
        : text(d.full_name_en) || text(d.full_name_ar)) || "—";
    const sex = d.sex === "male" || d.sex === "female" ? t(`common:sex.${d.sex}`) : "";
    title = row.result_id ? (
      <Link
        to="/patients/$patientId"
        params={{ patientId: String(row.result_id) }}
        className="font-medium break-words text-fg underline-offset-4 hover:underline"
      >
        {name}
      </Link>
    ) : (
      <span className="font-medium break-words">{name}</span>
    );
    lines = [sex, text(d.date_of_birth), text(d.phone)].filter(Boolean).map((part, i) => (
      <bdi key={i} className="tabular">
        {part}
      </bdi>
    ));
  } else if (kind === "items") {
    const name =
      text(d.generic_name) || (language === "ar" ? text(d.name_ar) || text(d.name_en) : text(d.name_en)) || "—";
    title = (
      <span className="font-medium break-words">
        <bdi className="tabular">{text(d.service_code)}</bdi> · {name}
      </span>
    );
    if (text(d.batch_no) || d.quantity != null) {
      lines = [
        t("imports.batchLine", {
          batch: text(d.batch_no) || "—",
          expiry: text(d.expiry_date) || "—",
          qty: formatNumber(Number(d.quantity ?? 0), language),
          store: text(d.store) || "—",
        }),
      ];
    }
  } else {
    title = (
      <span className="font-medium break-words">
        <bdi className="tabular">{text(d.service_code)}</bdi>
        {text(d.name) ? ` · ${text(d.name)}` : ""}
      </span>
    );
    const price = text(d.price);
    const current = text(d.current_price);
    lines = [
      <span key="p" className="flex flex-wrap items-center gap-x-2">
        {current ? (
          <span>
            {t("imports.currentPrice")} <MoneyText value={current} />
          </span>
        ) : null}
        {price ? (
          <span className="font-medium text-fg">
            {t("imports.newPrice")} <MoneyText value={price} />
          </span>
        ) : null}
      </span>,
    ];
  }
  return (
    <span className="flex min-w-0 flex-col">
      {title}
      {lines.length > 0 ? (
        <span className="text-xs text-muted">
          {lines.map((line, i) => (
            <span key={i}>
              {i > 0 ? " · " : ""}
              {line}
            </span>
          ))}
        </span>
      ) : null}
    </span>
  );
}

function RowIssues({ row }: { row: ImportJobRow }) {
  const { t } = useTranslation("ops");
  const translateError = useTranslateError();
  if (row.errors.length === 0 && row.warnings.length === 0) return null;
  return (
    <ul className="grid gap-0.5 text-xs">
      {row.errors.map((e, i) => (
        <li key={`e${String(i)}`} className="text-danger">
          {translateError(e.code)}
          {e.field ? (
            <span className="text-muted"> ({t(`imports.field.${e.field}`, { defaultValue: e.field })})</span>
          ) : null}
        </li>
      ))}
      {row.warnings.map((w, i) => (
        <li key={`w${String(i)}`} className="text-warning-fg">
          {t(`imports.hint.${text(w.code)}`, {
            defaultValue: text(w.code),
            row: text(w.row_no),
            fileNo: text(w.file_no),
            name: text(w.name),
            onHand: text(w.on_hand),
          })}
        </li>
      ))}
    </ul>
  );
}
