import { Link, useNavigate, useParams, useSearch } from "@tanstack/react-router";
import { FileText } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { ArrowBack } from "@/components/icons";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ageFromBirthDate } from "@/lib/age";
import { useTranslateError } from "@/lib/api/translate-error";
import { formatDate } from "@/lib/format";
import { useLanguage } from "@/lib/i18n-hooks";
import { cn } from "@/lib/utils";

import { useResultPrint } from "../api";
import { LabPrintFrame } from "../components/LabPrintFrame";
import { isCritical, isFlagged, rangeText } from "../lib/flags";
import { parsePrintSearch } from "../lib/search";
import { useLabNames } from "../lib/use-lab-names";
import type { LabPrint } from "../types";

type Lang = "ar" | "en";

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-wrap gap-x-2">
      <dt className="text-muted">{label}</dt>
      <dd className="min-w-0 font-medium">{children}</dd>
    </div>
  );
}

/** The printed report, in `lang` whatever the screen's language (FEATURES 9.6). */
function ReportBody({ data, lang }: { data: LabPrint; lang: Lang }) {
  const { i18n } = useTranslation();
  const t = i18n.getFixedT(lang, "lab");
  const names = useLabNames(lang);
  const v = data.version;
  const p = data.patient;
  const age = p.date_of_birth ? ageFromBirthDate(p.date_of_birth) : null;
  const when = (value: string | null | undefined) => (value ? formatDate(value, lang, "datetime") : "");
  return (
    <div className="flex flex-col gap-4" data-testid="result-print" data-lang={lang}>
      <header className="flex flex-col gap-0.5 border-b border-border pb-3 text-center">
        <p className="text-lg font-semibold">{names.text(data.center.name_ar, data.center.name_en)}</p>
        {data.center.address ? <p>{data.center.address}</p> : null}
        {data.center.phone ? (
          <p>
            <bdi dir="ltr">{data.center.phone}</bdi>
          </p>
        ) : null}
        <p className="mt-1 text-base font-semibold">{t("print.heading")}</p>
      </header>
      {!data.current ? (
        <p
          className="rounded-control border-2 border-danger-border p-2 text-center font-semibold"
          data-testid="print-superseded"
        >
          {t("print.superseded")}
        </p>
      ) : null}
      <dl className="grid gap-x-6 gap-y-1 sm:grid-cols-2">
        <Field label={t("print.patient")}>{names.patient(p)}</Field>
        <Field label={t("print.fileNo")}>
          <bdi dir="ltr">{p.file_no}</bdi>
        </Field>
        <Field label={t("print.sexAge")}>
          {t(`sex.${p.sex === "male" || p.sex === "female" ? p.sex : "any"}`)}
          {age
            ? ` · ${age.years >= 1 ? t("print.years", { count: age.years }) : t("print.months", { count: age.months })}`
            : ""}
        </Field>
        <Field label={t("print.visit")}>
          <bdi dir="ltr">{data.visit_number}</bdi>
        </Field>
        {data.ordered_by ? <Field label={t("print.orderedBy")}>{names.user(data.ordered_by)}</Field> : null}
        {data.sample ? (
          <>
            <Field label={t("print.accession")}>
              <bdi dir="ltr">{data.sample.accession_no}</bdi>
            </Field>
            <Field label={t("print.collected")}>{when(data.sample.collected_at)}</Field>
            {data.sample.received_at ? (
              <Field label={t("print.received")}>{when(data.sample.received_at)}</Field>
            ) : null}
          </>
        ) : null}
      </dl>
      <section className="flex flex-col gap-2">
        <h2 className="text-base font-semibold">
          {names.test(data.test)}{" "}
          <span className="text-sm font-normal text-muted">({t(`sampleType.${data.test.sample_type}`)})</span>
        </h2>
        <table className="w-full border-collapse text-start">
          <thead>
            <tr className="border-b border-border text-xs text-muted">
              <th className="py-1 text-start font-medium">{t("print.parameter")}</th>
              <th className="py-1 text-start font-medium">{t("print.result")}</th>
              <th className="py-1 text-start font-medium">{t("print.flag")}</th>
              <th className="py-1 text-start font-medium">{t("print.reference")}</th>
            </tr>
          </thead>
          <tbody>
            {v.values.map((x) => (
              <tr
                key={x.parameter_id}
                className="border-b border-border align-top"
                data-testid="print-value"
                data-flag={x.flag}
              >
                <td className="py-1 pe-2">{names.text(x.name_ar, x.name_en)}</td>
                <td className={cn("py-1 pe-2 tabular", isFlagged(x.flag) && "font-bold")}>
                  <bdi dir="ltr">
                    {x.value}
                    {x.unit ? ` ${x.unit}` : ""}
                  </bdi>
                </td>
                <td className={cn("py-1 pe-2", isCritical(x.flag) && "font-bold")}>
                  {isFlagged(x.flag) ? t(`flag.${x.flag}`) : ""}
                </td>
                <td className="py-1">
                  <bdi dir="ltr">{rangeText(x.reference_low, x.reference_high, x.reference_text)}</bdi>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {v.comment ? (
          <p>
            <span className="text-muted">{t("print.comment")}: </span>
            {v.comment}
          </p>
        ) : null}
      </section>
      {v.amends_version_no !== null ? (
        <p className="text-xs" data-testid="print-amended">
          {t("print.amended", { number: v.amends_version_no })}: {names.reason(v.amendment_reason)}
          {v.amendment_note ? ` · ${v.amendment_note}` : ""}
        </p>
      ) : null}
      <footer className="flex flex-col gap-0.5 border-t border-border pt-2 text-xs">
        <span>{t("print.approvedBy", { name: names.user(v.approved_by), at: when(v.approved_at) })}</span>
        <span className="text-muted">{t("print.printedAt", { at: formatDate(new Date(), lang, "datetime") })}</span>
      </footer>
    </div>
  );
}

/** An approved result as an A4 report in Arabic or English (FEATURES 9.6, 0.10). */
export function ResultPrintPage() {
  const { t } = useTranslation(["lab", "errors"]);
  const translateError = useTranslateError();
  const uiLanguage = useLanguage();
  const navigate = useNavigate();
  const { lineId } = useParams({ strict: false });
  const search = parsePrintSearch(useSearch({ strict: false }));
  const lang: Lang = search.lang ?? uiLanguage;
  const id = Number(lineId);
  const data = useResultPrint(id, search.version);

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <PageHeader
        title={t("print.pageTitle")}
        description={t("print.pageDescription")}
        icon={<FileText />}
        className="print:hidden"
        actions={
          <Button asChild variant="outline">
            <Link to="/lab/results/$lineId" params={{ lineId: String(id) }}>
              <ArrowBack aria-hidden="true" />
              {t("print.back")}
            </Link>
          </Button>
        }
      />
      {data.isPending ? (
        <Skeleton className="mx-auto h-96 w-full max-w-[210mm]" />
      ) : data.isError ? (
        <AlertCard variant="danger" title={t("errors:title")}>
          {translateError(data.error)}
        </AlertCard>
      ) : (
        <LabPrintFrame
          paper="a4"
          lang={lang}
          dir={lang === "ar" ? "rtl" : "ltr"}
          toolbar={
            <Tabs
              value={lang}
              onValueChange={(v) => {
                void navigate({
                  to: "/lab/results/$lineId/print",
                  params: { lineId: String(id) },
                  search: { ...search, lang: v as Lang },
                  replace: true,
                });
              }}
            >
              <TabsList aria-label={t("print.language")}>
                <TabsTrigger value="ar" lang="ar" data-testid="print-lang-ar">
                  {t("print.arabic")}
                </TabsTrigger>
                <TabsTrigger value="en" lang="en" data-testid="print-lang-en">
                  {t("print.english")}
                </TabsTrigger>
              </TabsList>
            </Tabs>
          }
        >
          <ReportBody data={data.data} lang={lang} />
        </LabPrintFrame>
      )}
    </div>
  );
}
