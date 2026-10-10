import "@/features/cashier/components/print.css";

import { Link, useParams, useSearch } from "@tanstack/react-router";
import { FileQuestion, Printer } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { DateText } from "@/components/DateText";
import { ArrowBack } from "@/components/icons";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useTranslateError } from "@/lib/api/translate-error";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";
import { cn } from "@/lib/utils";

import { useReport } from "../api";
import { isReportKey, type ReportKey } from "../catalog";
import { ReportCell } from "../components/ReportCell";
import { isNumeric } from "../lib/cells";
import type { ReportSearch } from "../lib/search";
import type { Report } from "../types";

/** A4, landscape: report tables are wide. */
const PAGE_RULE = "@page { size: A4 landscape; margin: 12mm; }";

function Field({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <div className="flex flex-wrap gap-x-2">
      <dt className="text-muted">{label}:</dt>
      <dd className="min-w-0">{children}</dd>
    </div>
  );
}

function Filters({ report }: { report: Report }) {
  const { t } = useTranslation("reports");
  const language = useLanguage();
  const f = report.filters;
  const available = new Set(report.filters_available);
  const department = report.departments.find((d) => d.id === f.department_id);
  const user = report.users.find((u) => u.id === f.user_id);
  return (
    <dl className="grid gap-0.5 text-sm">
      {available.has("dates") ? (
        <Field label={t("print.period")}>
          <DateText value={f.date_from} /> – <DateText value={f.date_to} />
        </Field>
      ) : null}
      {available.has("as_of") ? (
        <Field label={t("filters.asOf")}>
          <DateText value={f.date_to} />
        </Field>
      ) : null}
      {available.has("department") ? (
        <Field label={t("filters.department")}>
          {department ? pickName(department.name, language) : t("filters.allDepartments")}
        </Field>
      ) : null}
      {available.has("user") ? (
        <Field label={t("filters.user")}>{user ? pickName(user.name, language) : t("filters.allUsers")}</Field>
      ) : null}
      {available.has("days") && f.days !== null ? (
        <Field label={t("filters.days")}>{t("units.days", { count: f.days })}</Field>
      ) : null}
      <Field label={t("viewer.generatedAt")}>
        <DateText value={report.generated_at} format="datetime" />
      </Field>
    </dl>
  );
}

/** The whole report on paper: letterhead, filters, figures and every section's rows. */
function ReportDocument({ report }: { report: Report }) {
  const { t } = useTranslation("reports");
  const language = useLanguage();
  return (
    <div className="flex flex-col gap-4" data-testid="report-print-document">
      <header className="flex flex-col gap-1 border-b border-border pb-3">
        <p className="text-lg font-semibold">{pickName(report.center, language)}</p>
        <p className="text-base font-semibold">{pickName(report.title, language)}</p>
        <Filters report={report} />
      </header>
      {report.metrics.length > 0 ? (
        <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-3 print:grid-cols-4">
          {report.metrics.map((m) => (
            <div key={m.key} className="flex items-baseline justify-between gap-2 border-b border-border py-1">
              <dt className="text-muted">{pickName(m.label, language)}</dt>
              <dd className="font-semibold">
                <ReportCell value={m.value} kind={m.kind} />
              </dd>
            </div>
          ))}
        </dl>
      ) : null}
      {report.sections.map((section) => (
        <section key={section.key} className="flex break-inside-avoid-page flex-col gap-1">
          <h2 className="text-sm font-semibold">{pickName(section.label, language)}</h2>
          {section.rows.length === 0 ? (
            <p className="text-sm text-muted">{t("viewer.emptyTitle")}</p>
          ) : (
            <div className="min-w-0 overflow-x-auto print:overflow-visible">
              <table className="w-full border-collapse text-xs">
                <thead>
                  <tr className="border-b border-border text-muted">
                    {section.columns.map((c) => (
                      <th
                        key={c.key}
                        scope="col"
                        className={cn("py-1 pe-2 font-medium", isNumeric(c.kind) ? "text-end" : "text-start")}
                      >
                        {pickName(c.label, language)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {section.rows.map((row, index) => (
                    <tr key={index} className="border-b border-border align-top">
                      {section.columns.map((c) => (
                        <td key={c.key} className={cn("py-1 pe-2", isNumeric(c.kind) ? "text-end" : "text-start")}>
                          <ReportCell value={row[c.key]} kind={c.kind} />
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
                {section.totals ? (
                  <tfoot>
                    <tr className="font-semibold">
                      {section.columns.map((c, index) => (
                        <td key={c.key} className={cn("py-1 pe-2", isNumeric(c.kind) ? "text-end" : "text-start")}>
                          {section.totals?.[c.key] !== undefined ? (
                            <ReportCell value={section.totals[c.key]} kind={c.kind} />
                          ) : index === 0 ? (
                            t("viewer.total")
                          ) : null}
                        </td>
                      ))}
                    </tr>
                  </tfoot>
                ) : null}
              </table>
            </div>
          )}
          {section.truncated ? (
            <p className="text-xs text-muted">{t("viewer.truncated", { rows: report.max_rows })}</p>
          ) : null}
        </section>
      ))}
    </div>
  );
}

/** A report for printing on A4 (FEATURES 12.11): the browser saves it as PDF too. */
export function ReportPrintPage() {
  const { reportKey } = useParams({ strict: false });
  const key = reportKey ?? "";
  if (!isReportKey(key)) {
    return <PrintUnknown />;
  }
  return <ReportPrint reportKey={key} />;
}

function PrintUnknown() {
  const { t } = useTranslation("reports");
  return <PageHeader title={t("viewer.unknownTitle")} icon={<FileQuestion />} />;
}

function ReportPrint({ reportKey }: { reportKey: ReportKey }) {
  const { t } = useTranslation(["reports", "common", "errors"]);
  const translateError = useTranslateError();
  const search: ReportSearch = useSearch({ strict: false });
  const report = useReport(reportKey, search);
  return (
    <div className="flex min-w-0 flex-col gap-4">
      <style>{PAGE_RULE}</style>
      <PageHeader
        title={t("print.pageTitle")}
        description={t(`catalog.${reportKey}.title`)}
        icon={<Printer />}
        className="print:hidden"
        actions={
          <>
            <Button asChild variant="outline">
              <Link to="/reports/$reportKey" params={{ reportKey }} search={search}>
                <ArrowBack aria-hidden="true" />
                {t("print.back")}
              </Link>
            </Button>
            <Button
              onClick={() => {
                window.print();
              }}
              data-testid="print"
            >
              <Printer aria-hidden="true" />
              {t("common:actions.print")}
            </Button>
          </>
        }
      />
      {report.isError ? (
        <AlertCard variant="danger" title={t("errors:title")}>
          {translateError(report.error)}
        </AlertCard>
      ) : report.data ? (
        <div data-print-root data-print-format="a4" className="card-surface p-4 md:p-6">
          <ReportDocument report={report.data} />
        </div>
      ) : (
        <Skeleton className="h-96 w-full" />
      )}
    </div>
  );
}
