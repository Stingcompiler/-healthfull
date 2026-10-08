import { Ban, ChevronDown, History, Plus } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { DateText } from "@/components/DateText";
import { EmptyState } from "@/components/EmptyState";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useVisitList } from "@/features/visits/api";
import { CancelVisitDialog, type CancelVisitTarget } from "@/features/visits/components/CancelVisitDialog";
import { VisitTimeline } from "@/features/visits/components/VisitTimeline";
import type { Visit } from "@/features/visits/types";
import { usePermission } from "@/lib/auth/hooks";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";
import { cn } from "@/lib/utils";

import { QueryErrorAlert } from "./QueryErrorAlert";

const STATUS_VARIANT = { open: "info", closed: "success", cancelled: "outline" } as const;

/**
 * The person's visits, newest first, each with its timeline (FEATURES 2.4). A new visit is
 * opened from the page header; the empty state offers it too.
 */
export function PatientVisits({ patientId, onNewVisit }: { patientId: number; onNewVisit?: () => void }) {
  const { t } = useTranslation(["patients", "visits"]);
  const visits = useVisitList({ patientId, pageSize: 50 });
  const [cancelling, setCancelling] = useState<CancelVisitTarget | null>(null);
  const rows = visits.data?.items ?? [];

  return (
    <section aria-labelledby="visits-heading" className="flex flex-col gap-3">
      <h2 id="visits-heading" className="flex items-center gap-2 text-base font-semibold text-fg">
        <History className="size-5 text-muted" aria-hidden="true" />
        {t("profile.visits")}
      </h2>
      {visits.isError ? (
        <QueryErrorAlert
          title={t("profile.visitsLoadFailed")}
          error={visits.error}
          onRetry={() => void visits.refetch()}
          retrying={visits.isFetching}
        />
      ) : visits.isPending ? (
        <Skeleton className="h-20" />
      ) : rows.length === 0 ? (
        <EmptyState
          size="compact"
          icon={<History />}
          title={t("profile.noVisits")}
          description={t("profile.noVisitsHint")}
          action={
            onNewVisit ? (
              <Button size="sm" variant="outline" onClick={onNewVisit}>
                <Plus aria-hidden="true" />
                {t("visits:create.open")}
              </Button>
            ) : undefined
          }
        />
      ) : (
        <ul className="grid gap-2">
          {rows.map((v) => (
            <VisitItem key={v.id} visit={v} onCancel={setCancelling} />
          ))}
        </ul>
      )}
      <CancelVisitDialog
        visit={cancelling}
        onOpenChange={(open) => {
          if (!open) setCancelling(null);
        }}
      />
    </section>
  );
}

function VisitItem({ visit, onCancel }: { visit: Visit; onCancel: (v: CancelVisitTarget) => void }) {
  const { t } = useTranslation(["patients", "visits"]);
  const language = useLanguage();
  const [open, setOpen] = useState(false);
  const canCancel = usePermission("visits.cancel");
  const panelId = `visit-${String(visit.id)}-timeline`;
  return (
    <li className="card-surface flex flex-col gap-3 p-4" data-testid="visit-item">
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <p className="flex flex-wrap items-center gap-2 font-medium text-fg">
            <bdi className="tabular">{visit.number}</bdi>
            <Badge variant={STATUS_VARIANT[visit.status]}>{t(`visits:visitStatus.${visit.status}`)}</Badge>
            <Badge variant="neutral">{t(`visits:visitType.${visit.visit_type}`)}</Badge>
          </p>
          <p className="text-xs text-muted">
            <DateText value={visit.created_at} format="datetime" />
            {visit.department
              ? ` · ${pickName({ ar: visit.department.name_ar, en: visit.department.name_en }, language)}`
              : null}
            {visit.doctor ? ` · ${pickName({ ar: visit.doctor.name_ar, en: visit.doctor.name_en }, language)}` : null}
          </p>
          {visit.status === "cancelled" && visit.cancel_reason ? (
            <p className="text-xs text-muted">
              {t("visits:cancel.reasonShown", {
                reason: pickName({ ar: visit.cancel_reason.label_ar, en: visit.cancel_reason.label_en }, language),
              })}
            </p>
          ) : null}
        </div>
        <div className="flex flex-wrap gap-2">
          {canCancel && visit.status === "open" ? (
            <Button
              size="sm"
              variant="destructive-soft"
              onClick={() => {
                onCancel({ id: visit.id, number: visit.number, billed: visit.billed });
              }}
            >
              <Ban aria-hidden="true" />
              {t("visits:cancel.open")}
            </Button>
          ) : null}
          <Button
            size="sm"
            variant="ghost"
            aria-expanded={open}
            aria-controls={panelId}
            onClick={() => {
              setOpen(!open);
            }}
          >
            <ChevronDown className={cn("transition-transform", open && "rotate-180")} aria-hidden="true" />
            {t("visits:timeline.title")}
          </Button>
        </div>
      </div>
      {open ? (
        <div id={panelId} className="ps-2">
          <VisitTimeline visitId={visit.id} />
        </div>
      ) : null}
    </li>
  );
}
