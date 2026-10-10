import { Link, useNavigate, useParams, useSearch } from "@tanstack/react-router";
import { FileSpreadsheet, FileQuestion, Printer } from "lucide-react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { DateText } from "@/components/DateText";
import { EmptyState } from "@/components/EmptyState";
import { ArrowBack } from "@/components/icons";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useTranslateError } from "@/lib/api/translate-error";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";

import { exportUrl, useReport } from "../api";
import { catalogEntry, isReportKey, type ReportKey } from "../catalog";
import { ReportFiltersForm } from "../components/ReportFiltersForm";
import { ReportMetrics } from "../components/ReportMetrics";
import { ReportSectionTable } from "../components/ReportSectionTable";
import type { ReportSearch } from "../lib/search";

/** One report: filters, Excel export, print view, the figures on top, then its sections. */
export function ReportViewerPage() {
  const { reportKey } = useParams({ strict: false });
  const key = reportKey ?? "";
  if (!isReportKey(key)) return <UnknownReport />;
  return <ReportView reportKey={key} />;
}

function UnknownReport() {
  const { t } = useTranslation("reports");
  return (
    <div className="flex min-w-0 flex-col gap-4">
      <PageHeader title={t("viewer.unknownTitle")} icon={<FileQuestion />} />
      <EmptyState
        icon={<FileQuestion />}
        title={t("viewer.unknownTitle")}
        description={t("viewer.unknownDescription")}
        action={
          <Button asChild>
            <Link to="/reports">{t("actions.back")}</Link>
          </Button>
        }
      />
    </div>
  );
}

function ReportView({ reportKey }: { reportKey: ReportKey }) {
  const { t } = useTranslation(["reports", "errors"]);
  const translateError = useTranslateError();
  const language = useLanguage();
  const search: ReportSearch = useSearch({ strict: false });
  const navigate = useNavigate();
  const report = useReport(reportKey, search);
  const entry = catalogEntry(reportKey);
  const Icon = entry?.icon ?? FileQuestion;
  const data = report.data;
  const title = data ? pickName(data.title, language) : t(`catalog.${reportKey}.title`);

  const apply = (next: ReportSearch) => {
    void navigate({ to: "/reports/$reportKey", params: { reportKey }, search: next });
  };

  return (
    <div className="flex min-w-0 flex-col gap-5" data-testid="report-viewer" data-report={reportKey}>
      <PageHeader
        title={title}
        description={t(`catalog.${reportKey}.description`)}
        icon={<Icon />}
        eyebrow={
          <Link to="/reports" className="inline-flex min-h-11 items-center gap-1 hover:text-fg md:min-h-6">
            <ArrowBack className="size-3.5" aria-hidden="true" />
            {t("actions.back")}
          </Link>
        }
        actions={
          <>
            <Button asChild variant="outline">
              <a href={exportUrl(reportKey, search, language)} download data-testid="report-excel">
                <FileSpreadsheet aria-hidden="true" />
                {t("actions.excel")}
              </a>
            </Button>
            <Button asChild variant="outline">
              <Link to="/reports/$reportKey/print" params={{ reportKey }} search={search} data-testid="report-print">
                <Printer aria-hidden="true" />
                {t("actions.print")}
              </Link>
            </Button>
          </>
        }
      />
      {report.isError ? (
        <AlertCard variant="danger" title={t("errors:title")}>
          <span className="flex flex-col items-start gap-2">
            {translateError(report.error)}
            <Button
              variant="outline"
              onClick={() => {
                apply({});
              }}
            >
              {t("filters.reset")}
            </Button>
          </span>
        </AlertCard>
      ) : null}
      {data ? (
        <>
          <ReportFiltersForm
            key={JSON.stringify(data.filters)}
            report={data}
            onApply={apply}
            onReset={() => {
              apply({});
            }}
          />
          <p className="text-xs text-muted" data-testid="report-generated">
            {t("viewer.generatedAt")} <DateText value={data.generated_at} format="datetime" />
          </p>
          <ReportMetrics metrics={data.metrics} />
          {data.sections.map((section) => (
            <ReportSectionTable
              key={section.key}
              section={section}
              maxRows={data.max_rows}
              loading={report.isFetching && report.isPlaceholderData}
            />
          ))}
        </>
      ) : report.isPending ? (
        <div className="flex flex-col gap-4" aria-busy="true">
          <Skeleton className="h-24 w-full" />
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {Array.from({ length: 4 }, (_, i) => (
              <Skeleton key={i} className="h-24" />
            ))}
          </div>
          <Skeleton className="h-64 w-full" />
        </div>
      ) : null}
    </div>
  );
}
