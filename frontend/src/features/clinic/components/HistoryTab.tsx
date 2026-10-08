import { History } from "lucide-react";
import { useTranslation } from "react-i18next";

import { DateText } from "@/components/DateText";
import { EmptyState } from "@/components/EmptyState";
import { StatusBadge } from "@/components/StatusBadge";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";

import { useHistory } from "../api";
import { lineBadgeState } from "../lib";
import { QueryError } from "./QueryError";

/** The person's earlier visits with diagnoses, notes and orders (FEATURES 3.1). No prices. */
export function HistoryTab({
  patientId,
  currentVisitId,
  active,
}: {
  patientId: number;
  currentVisitId: number;
  active: boolean;
}) {
  const { t } = useTranslation("clinic");
  const language = useLanguage();
  const history = useHistory(patientId, active);

  if (history.isError) {
    return (
      <QueryError
        title={t("history.loadError")}
        error={history.error}
        onRetry={() => void history.refetch()}
        retrying={history.isFetching}
      />
    );
  }
  if (!history.data) return <Skeleton className="h-40" />;
  const visits = history.data.filter((h) => h.visit.id !== currentVisitId);
  if (visits.length === 0) {
    return (
      <EmptyState icon={<History />} title={t("history.emptyTitle")} description={t("history.emptyDescription")} />
    );
  }
  return (
    <ol className="flex flex-col gap-3">
      {visits.map(({ visit, diagnoses, notes, lines }) => {
        const signed = notes.filter((n) => n.status === "signed");
        const note = signed[signed.length - 1] ?? notes[notes.length - 1];
        return (
          <li key={visit.id} className="card-surface flex min-w-0 flex-col gap-3 p-4">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h3 className="text-sm font-semibold text-fg">
                {visit.department
                  ? pickName({ ar: visit.department.name_ar, en: visit.department.name_en }, language)
                  : "—"}
                {visit.doctor ? (
                  <span className="font-normal text-muted">
                    {" · "}
                    {pickName({ ar: visit.doctor.name_ar, en: visit.doctor.name_en }, language)}
                  </span>
                ) : null}
              </h3>
              <DateText value={visit.created_at} className="text-xs text-muted" />
            </div>
            {diagnoses.length > 0 ? (
              <ul className="flex flex-wrap gap-1.5">
                {diagnoses.map((d) => (
                  <li key={d.id}>
                    <Badge variant="soft">
                      {d.icd10 ? <bdi className="tabular">{d.icd10.code}</bdi> : null}
                      {d.icd10 ? pickName({ ar: d.icd10.title_ar, en: d.icd10.title_en }, language) : d.text}
                    </Badge>
                  </li>
                ))}
              </ul>
            ) : null}
            {note ? (
              <dl className="grid gap-1 text-sm">
                {note.complaint ? <NoteLine label={t("note.complaint")} text={note.complaint} /> : null}
                {note.assessment ? <NoteLine label={t("note.assessment")} text={note.assessment} /> : null}
                {note.plan ? <NoteLine label={t("note.plan")} text={note.plan} /> : null}
              </dl>
            ) : null}
            {lines.length > 0 ? (
              <ul className="flex flex-col gap-1.5">
                {lines.map((ln) => (
                  <li key={ln.id} className="flex min-w-0 flex-wrap items-center justify-between gap-2 text-sm">
                    <span className="min-w-0 break-words text-fg">
                      {pickName({ ar: ln.name_ar, en: ln.name_en }, language)}
                    </span>
                    <StatusBadge status={lineBadgeState(ln.status)} size="sm" />
                  </li>
                ))}
              </ul>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}

function NoteLine({ label, text }: { label: string; text: string }) {
  return (
    <div className="flex min-w-0 flex-col sm:flex-row sm:gap-2">
      <dt className="shrink-0 text-xs font-medium text-muted sm:w-28">{label}</dt>
      <dd className="min-w-0 break-words whitespace-pre-line text-fg">{text}</dd>
    </div>
  );
}
