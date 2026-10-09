import { Link } from "@tanstack/react-router";
import { BedDouble, HeartPulse, Syringe } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { DateText } from "@/components/DateText";
import { EmptyState } from "@/components/EmptyState";
import { ChevronNext } from "@/components/icons";
import { PageHeader } from "@/components/PageHeader";
import { PatientCard } from "@/components/PatientCard";
import { SearchInput } from "@/components/SearchInput";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useLanguage } from "@/lib/i18n-hooks";

import { useNursingVisits } from "../api";
import { NursingTabs } from "../components/NursingTabs";
import { QueryError } from "../components/QueryError";
import { patientName, toPatientCard } from "../lib";
import type { NursingVisit } from "../types";

/** The nurse's way to vitals and notes (FEATURES 3.4, 10.3): inpatients and today's visits. */
export function NursingVisitsPage() {
  const { t } = useTranslation("nursing");
  const [q, setQ] = useState("");
  const visits = useNursingVisits(q);
  const rows = visits.data ?? [];
  const inpatients = rows.filter((r) => r.admission !== null);
  const today = rows.filter((r) => r.admission === null);

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title={t("visits.title")}
        description={t("visits.description")}
        icon={<HeartPulse />}
        documentTitle={t("visits.title")}
      />
      <NursingTabs current="visits" />
      <SearchInput
        label={t("visits.search")}
        placeholder={t("visits.search")}
        onSearch={setQ}
        loading={visits.isFetching && q !== ""}
        className="md:max-w-sm"
      />

      {visits.isError ? (
        <QueryError
          title={t("visits.loadError")}
          error={visits.error}
          onRetry={() => void visits.refetch()}
          retrying={visits.isFetching}
        />
      ) : visits.isPending ? (
        <div className="grid gap-3 lg:grid-cols-2" aria-busy="true">
          <Skeleton className="h-40" />
          <Skeleton className="h-40" />
        </div>
      ) : rows.length === 0 ? (
        <EmptyState
          icon={<HeartPulse />}
          title={q ? t("visits.noMatch") : t("visits.emptyTitle")}
          description={q ? undefined : t("visits.emptyDescription")}
        />
      ) : (
        <>
          {inpatients.length > 0 ? (
            <VisitSection id="nursing-inpatients" title={t("visits.inpatientsHeading")} rows={inpatients} />
          ) : null}
          {today.length > 0 ? <VisitSection id="nursing-today" title={t("visits.todayHeading")} rows={today} /> : null}
        </>
      )}
    </div>
  );
}

function VisitSection({ id, title, rows }: { id: string; title: string; rows: readonly NursingVisit[] }) {
  return (
    <section aria-labelledby={id} className="flex flex-col gap-3">
      <h2 id={id} className="text-sm font-semibold text-fg-muted">
        {title}
      </h2>
      <ul className="grid gap-3 lg:grid-cols-2">
        {rows.map((row) => (
          <li key={row.visit.id} className="min-w-0">
            <VisitRow row={row} />
          </li>
        ))}
      </ul>
    </section>
  );
}

function VisitRow({ row }: { row: NursingVisit }) {
  const { t } = useTranslation("nursing");
  const language = useLanguage();
  const who = patientName(row.patient, language);
  return (
    <div data-testid="nursing-visit" data-file-no={row.patient.file_no} data-visit-id={row.visit.id}>
      <PatientCard
        compact
        patient={toPatientCard(row.patient, language, row.allergies_recorded ? row.allergies : null, row.visit.payer)}
        actions={
          <Button size="lg" className="h-12" asChild>
            <Link
              to="/nursing/visits/$visitId"
              params={{ visitId: String(row.visit.id) }}
              aria-label={t("visits.openNamed", { name: who })}
            >
              {t("visits.open")}
              <ChevronNext aria-hidden="true" />
            </Link>
          </Button>
        }
      >
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
          {row.admission?.bed ? (
            <Badge variant="info">
              <BedDouble aria-hidden="true" />
              {t("visits.bed", { bed: row.admission.bed.code })}
            </Badge>
          ) : null}
          {row.queue ? (
            <Badge variant="neutral">
              {t("visits.token", { token: row.queue.token_no })} · {t(`queueStatus.${row.queue.status}`)}
            </Badge>
          ) : null}
          {row.procedures_waiting > 0 ? (
            <Badge variant="warning">
              <Syringe aria-hidden="true" />
              {t("visits.proceduresWaiting", { count: row.procedures_waiting })}
            </Badge>
          ) : null}
          <span className="ms-auto">
            {row.last_vitals_at ? (
              <>
                {t("visits.lastVitals")} <DateText value={row.last_vitals_at} format="time" />
              </>
            ) : (
              <span className="font-medium text-warning-fg">{t("visits.noVitals")}</span>
            )}
          </span>
        </div>
      </PatientCard>
    </div>
  );
}
