import { useParams } from "@tanstack/react-router";
import { Printer } from "lucide-react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { DateText } from "@/components/DateText";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { isApiError } from "@/lib/api/errors";
import { useTranslateError } from "@/lib/api/translate-error";
import { cn } from "@/lib/utils";

import { useResult } from "../api";
import { PortalPage, Pill, Row } from "../components/PortalPage";
import type { PillTone } from "../lib/tones";
import { usePick } from "../lib/ui";
import type { PortalResultValue } from "../types";

const FLAG_TONE: Record<string, PillTone> = {
  normal: "success",
  low: "warning",
  high: "warning",
  abnormal: "warning",
  critical_low: "danger",
  critical_high: "danger",
};

function range(v: PortalResultValue): string {
  if (v.reference_text) return v.reference_text;
  if (v.reference_low && v.reference_high) return `${v.reference_low} – ${v.reference_high}`;
  if (v.reference_low) return `≥ ${v.reference_low}`;
  if (v.reference_high) return `≤ ${v.reference_high}`;
  return "";
}

/** One approved result: values, flags and ranges, ready to print (FEATURES 9.6, 15.2). */
export function ResultPage() {
  const { t } = useTranslation(["portal", "errors", "common"]);
  const translateError = useTranslateError();
  const pick = usePick();
  const { lineId } = useParams({ strict: false });
  const result = useResult(Number(lineId));
  const title = result.data ? pick(result.data.test_name_ar, result.data.test_name_en) : t("results.title");

  return (
    <PortalPage
      title={title}
      back={{ to: "/portal/results", label: t("results.back") }}
      actions={
        result.data ? (
          <Button variant="outline" onClick={() => window.print()} data-testid="result-print">
            <Printer aria-hidden="true" />
            {t("results.print")}
          </Button>
        ) : null
      }
    >
      {result.isPending ? (
        <Skeleton className="h-64" />
      ) : result.isError ? (
        <AlertCard
          variant="danger"
          title={isApiError(result.error) && result.error.status === 404 ? t("errors:NOT_FOUND") : t("errors:title")}
        >
          {translateError(result.error)}
        </AlertCard>
      ) : (
        <article
          className="card-surface flex min-w-0 flex-col gap-4 p-4 md:p-5 print:border-0 print:shadow-none"
          data-testid="result-report"
        >
          <header className="flex flex-col gap-0.5 border-b border-border pb-3">
            <p className="font-semibold text-fg">{pick(result.data.center.name_ar, result.data.center.name_en)}</p>
            {result.data.center.address ? <p className="text-xs text-muted">{result.data.center.address}</p> : null}
            <p className="mt-1 text-sm font-semibold text-fg">{t("results.reportTitle")}</p>
          </header>
          <dl className="grid gap-x-6 md:grid-cols-2">
            <Row label={t("results.patient")}>
              {pick(result.data.patient.full_name_ar, result.data.patient.full_name_en)}
            </Row>
            <Row label={t("results.fileNo")}>
              <bdi>{result.data.patient.file_no}</bdi>
            </Row>
            <Row label={t("results.visit")}>
              <bdi>{result.data.visit_number}</bdi>
            </Row>
            <Row label={t("results.orderedOn")}>
              <DateText value={result.data.ordered_at} />
            </Row>
            {result.data.ordered_by ? (
              <Row label={t("results.orderedBy")}>
                {pick(result.data.ordered_by.name_ar, result.data.ordered_by.name_en)}
              </Row>
            ) : null}
            {result.data.approved_at ? (
              <Row label={t("results.approved")}>
                <DateText value={result.data.approved_at} format="datetime" />
              </Row>
            ) : null}
          </dl>
          {result.data.amended ? (
            <AlertCard variant="info" title={t("results.amended")} className="print:border">
              {t("results.amendedNote")}
            </AlertCard>
          ) : null}
          <ul className="flex flex-col divide-y divide-border" data-testid="result-values">
            {result.data.values.map((v) => {
              const flagged = v.flag !== "none" && v.flag !== "normal";
              return (
                <li key={v.parameter_code} className="grid gap-1 py-3 sm:grid-cols-[1fr_auto]">
                  <div className="min-w-0">
                    <p className="font-medium text-fg">{pick(v.name_ar, v.name_en)}</p>
                    {range(v) ? (
                      <p className="text-xs text-muted">
                        {t("results.range")}: <bdi dir="ltr">{range(v)}</bdi>
                        {v.unit ? <bdi dir="ltr"> {v.unit}</bdi> : null}
                      </p>
                    ) : null}
                  </div>
                  <div className="flex items-center gap-2 sm:justify-end">
                    <bdi
                      dir="ltr"
                      className={cn("tabular text-lg font-semibold", flagged ? "text-danger-fg" : "text-fg")}
                    >
                      {v.value}
                      {v.unit ? <span className="ms-1 text-sm font-normal text-muted">{v.unit}</span> : null}
                    </bdi>
                    {v.flag !== "none" && FLAG_TONE[v.flag] ? (
                      <Pill tone={FLAG_TONE[v.flag] ?? "neutral"} testId="result-flag">
                        {t(`results.flags.${v.flag as "normal"}`)}
                      </Pill>
                    ) : null}
                  </div>
                </li>
              );
            })}
          </ul>
          {result.data.comment ? (
            <div className="rounded-control border border-border p-3">
              <p className="text-xs font-semibold text-muted">{t("results.comment")}</p>
              <p className="text-sm whitespace-pre-line text-fg">{result.data.comment}</p>
            </div>
          ) : null}
          <p className="text-xs text-muted">{t("results.disclaimer")}</p>
        </article>
      )}
    </PortalPage>
  );
}
