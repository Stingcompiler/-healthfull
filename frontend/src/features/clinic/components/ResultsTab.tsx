import { FlaskConical } from "lucide-react";
import { useTranslation } from "react-i18next";

import { DateText } from "@/components/DateText";
import { EmptyState } from "@/components/EmptyState";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";

import { useResults } from "../api";
import { QueryError } from "./QueryError";
import { ResultValues } from "./ResultValues";

/** Approved lab results of the person, newest first (FEATURES 3.7, 9.4). Drafts never show. */
export function ResultsTab({ patientId, active }: { patientId: number; active: boolean }) {
  const { t } = useTranslation("clinic");
  const language = useLanguage();
  const results = useResults(patientId, active);

  if (results.isError) {
    return (
      <QueryError
        title={t("results.loadError")}
        error={results.error}
        onRetry={() => void results.refetch()}
        retrying={results.isFetching}
      />
    );
  }
  if (!results.data) return <Skeleton className="h-40" />;
  if (results.data.length === 0) {
    return (
      <EmptyState icon={<FlaskConical />} title={t("results.emptyTitle")} description={t("results.emptyDescription")} />
    );
  }
  return (
    <ul className="grid gap-3 xl:grid-cols-2">
      {results.data.map((r) => (
        <li key={r.id} className="card-surface flex min-w-0 flex-col gap-3 p-4" data-testid="result-card">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <h3 className="text-sm font-semibold text-fg">{pickName({ ar: r.name_ar, en: r.name_en }, language)}</h3>
            <div className="flex items-center gap-2 text-xs text-muted">
              {r.amended ? <Badge variant="warning">{t("results.amended")}</Badge> : null}
              {r.approved_at ? <DateText value={r.approved_at} format="datetime" /> : null}
            </div>
          </div>
          <ResultValues values={r.values} />
          {r.comment ? <p className="text-xs text-muted">{r.comment}</p> : null}
        </li>
      ))}
    </ul>
  );
}
