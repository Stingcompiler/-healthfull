import { Link } from "@tanstack/react-router";
import { FlaskConical } from "lucide-react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { DateText } from "@/components/DateText";
import { EmptyState } from "@/components/EmptyState";
import { ChevronNext } from "@/components/icons";
import { Skeleton } from "@/components/ui/skeleton";
import { useTranslateError } from "@/lib/api/translate-error";

import { useResults } from "../api";
import { PortalPage, Pill } from "../components/PortalPage";
import { usePick } from "../lib/ui";

/** Approved lab results only, newest first (FEATURES 9.4, 15.2). */
export function ResultsPage() {
  const { t } = useTranslation(["portal", "errors"]);
  const translateError = useTranslateError();
  const pick = usePick();
  const results = useResults();

  return (
    <PortalPage title={t("results.title")} description={t("results.description")}>
      {results.isPending ? (
        <Skeleton className="h-40" />
      ) : results.isError ? (
        <AlertCard variant="danger" title={t("errors:title")}>
          {translateError(results.error)}
        </AlertCard>
      ) : results.data.length === 0 ? (
        <EmptyState icon={<FlaskConical />} title={t("results.none")} description={t("results.noneHint")} />
      ) : (
        <ul className="card-surface divide-y divide-border" data-testid="results-list">
          {results.data.map((r) => (
            <li key={r.line_id}>
              <Link
                to="/portal/results/$lineId"
                params={{ lineId: String(r.line_id) }}
                data-testid="result-row"
                data-line={r.line_id}
                className="flex min-h-14 items-center justify-between gap-3 px-4 py-3 focus-ring-inset"
              >
                <span className="min-w-0">
                  <span className="block font-medium break-words text-fg">{pick(r.test_name_ar, r.test_name_en)}</span>
                  {r.approved_at ? (
                    <span className="text-xs text-muted">
                      <DateText value={r.approved_at} format="datetime" />
                    </span>
                  ) : null}
                </span>
                <span className="flex shrink-0 flex-wrap items-center justify-end gap-1">
                  {r.amended ? <Pill tone="info">{t("results.amended")}</Pill> : null}
                  {r.abnormal ? <Pill tone="warning">{t("results.abnormal")}</Pill> : null}
                  <ChevronNext className="size-4 text-muted" aria-hidden="true" />
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </PortalPage>
  );
}
