import { Link, useParams } from "@tanstack/react-router";
import { BedDouble, ClipboardList, HeartPulse } from "lucide-react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { DateText } from "@/components/DateText";
import { ChevronPrev } from "@/components/icons";
import { PageHeader } from "@/components/PageHeader";
import { PatientCard } from "@/components/PatientCard";
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useLanguage } from "@/lib/i18n-hooks";

import { useNursingChart } from "../api";
import { NursingNotesPanel } from "../components/NursingNotesPanel";
import { QueryError } from "../components/QueryError";
import { VitalsPanel } from "../components/VitalsPanel";
import { nameOf, patientName, toPatientCard } from "../lib";
import type { NursingChart } from "../types";

/** One visit as a nurse works on it (FEATURES 3.4, 10.3, 10.5): vitals, notes, procedures, bed. */
export function NursingChartPage() {
  const { t } = useTranslation("nursing");
  const language = useLanguage();
  const { visitId } = useParams({ from: "/_app/nursing/visits/$visitId" });
  const id = Number(visitId);
  const chart = useNursingChart(id);
  const data = chart.data;

  return (
    <div className="flex flex-col gap-5">
      <div>
        <Button variant="ghost" size="sm" asChild className="-ms-2">
          <Link to="/nursing/visits">
            <ChevronPrev aria-hidden="true" />
            {t("chart.back")}
          </Link>
        </Button>
      </div>
      <PageHeader
        title={data ? patientName(data.patient, language) : t("chart.title")}
        eyebrow={t("chart.title")}
        description={data ? t("chart.visit", { number: data.visit.number }) : undefined}
        documentTitle={t("chart.title")}
        icon={<HeartPulse />}
      />
      {chart.isError ? (
        <QueryError
          title={t("chart.loadError")}
          error={chart.error}
          onRetry={() => void chart.refetch()}
          retrying={chart.isFetching}
        />
      ) : chart.isPending || !data ? (
        <div className="flex flex-col gap-3" aria-busy="true">
          <Skeleton className="h-32" />
          <Skeleton className="h-64" />
        </div>
      ) : (
        <ChartBody data={data} />
      )}
    </div>
  );
}

function ChartBody({ data }: { data: NursingChart }) {
  const { t } = useTranslation("nursing");
  const language = useLanguage();
  const open = data.visit.status === "open";
  const cancelled = data.visit.status === "cancelled";
  return (
    <>
      <PatientCard patient={toPatientCard(data.patient, language, data.allergies, data.visit.payer)} />
      {cancelled ? (
        <AlertCard variant="warning" title={t("chart.visitCancelled")} />
      ) : !open ? (
        <AlertCard variant="info" title={t("chart.visitClosed")} />
      ) : null}
      <div className="grid gap-5 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <div className="flex min-w-0 flex-col gap-5">
          <VitalsPanel visitId={data.visit.id} vitals={data.vitals} open={open} />
          <NursingNotesPanel visitId={data.visit.id} notes={data.notes} writable={!cancelled} />
        </div>
        <div className="flex min-w-0 flex-col gap-5">
          {data.admission ? (
            <section aria-labelledby="nursing-admission" className="card-surface flex flex-col gap-3 p-4 md:p-5">
              <h2 id="nursing-admission" className="flex items-center gap-2 text-base font-semibold text-fg">
                <BedDouble className="size-4 text-muted" aria-hidden="true" />
                {t("chart.admissionNumber", { number: data.admission.number })}
              </h2>
              <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
                <dt className="text-muted">{t("chart.admittedAt")}</dt>
                <dd className="text-fg">
                  <DateText value={data.admission.admitted_at} format="datetime" />
                </dd>
                {data.admission.ward ? (
                  <>
                    <dt className="text-muted">{t("chart.ward")}</dt>
                    <dd className="text-fg">{nameOf(data.admission.ward, language)}</dd>
                  </>
                ) : null}
                {data.admission.bed ? (
                  <>
                    <dt className="text-muted">{t("chart.bed")}</dt>
                    <dd className="text-fg">
                      <bdi>{data.admission.bed.code}</bdi> · {nameOf(data.admission.bed, language)}
                    </dd>
                  </>
                ) : null}
              </dl>
            </section>
          ) : null}
          <section aria-labelledby="nursing-procedures" className="card-surface flex flex-col gap-3 p-4 md:p-5">
            <h2 id="nursing-procedures" className="flex items-center gap-2 text-base font-semibold text-fg">
              <ClipboardList className="size-4 text-muted" aria-hidden="true" />
              {t("chart.procedures")}
            </h2>
            {data.procedures.length === 0 ? (
              <p className="text-sm text-muted">{t("chart.noProcedures")}</p>
            ) : (
              <ul className="flex flex-col divide-y divide-border">
                {data.procedures.map((p) => (
                  <li key={p.id} className="flex flex-wrap items-center gap-2 py-2">
                    <span className="min-w-0 flex-1 text-sm font-medium text-pretty break-words text-fg">
                      {nameOf(p.service, language)}
                    </span>
                    <StatusBadge status={p.state} size="sm" />
                    {p.performed_at ? (
                      <span className="basis-full text-xs text-muted">
                        {p.performed_by
                          ? `${t("procedures.doneBy", { name: nameOf(p.performed_by, language) })} · `
                          : ""}
                        <DateText value={p.performed_at} format="datetime" />
                        {p.performed_note ? ` · ${t("procedures.doneNote", { note: p.performed_note })}` : ""}
                      </span>
                    ) : null}
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </div>
    </>
  );
}
