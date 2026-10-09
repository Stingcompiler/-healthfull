import { Link, useNavigate } from "@tanstack/react-router";
import { Megaphone, Play, Stethoscope } from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { DateText } from "@/components/DateText";
import { EmptyState } from "@/components/EmptyState";
import { KbdCombo } from "@/components/Kbd";
import { PageHeader } from "@/components/PageHeader";
import { PatientCard } from "@/components/PatientCard";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useTranslateError } from "@/lib/api/translate-error";
import { useShortcut } from "@/lib/hooks/use-shortcut";
import { useLanguage } from "@/lib/i18n-hooks";

import { useCallNext, useQueueAction, useWorklist } from "../api";
import { QueryError } from "../components/QueryError";
import { QueueStatusBadge } from "../components/QueueStatusBadge";
import { patientName, toPatientCard } from "../lib";
import type { QueueEntry } from "../types";

const CALL_NEXT_SHORTCUT = "alt+n";

/** The logged-in doctor's queue (FEATURES 2.3): ready patients in serving order, call next. */
export function ClinicPage() {
  const { t } = useTranslation("clinic");
  const worklist = useWorklist();
  const callNext = useCallNext();
  const translateError = useTranslateError();
  const navigate = useNavigate();

  const entries = worklist.data ?? [];
  const active = entries.filter((e) => e.status === "waiting" || e.status === "called" || e.status === "in_progress");
  const seen = entries.filter((e) => !active.includes(e));
  const waiting = active.filter((e) => e.status === "waiting").length;

  const onCallNext = () => {
    if (callNext.isPending) return;
    callNext.mutate(undefined, {
      onSuccess: (entry) => {
        toast.success(t("queue.calledToast", { token: entry.token_no }));
        void navigate({ to: "/clinic/visits/$visitId", params: { visitId: String(entry.visit.id) } });
      },
      onError: (error) => toast.error(translateError(error)),
    });
  };
  useShortcut(CALL_NEXT_SHORTCUT, onCallNext, { allowInInputs: true });

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title={t("queue.title")}
        description={t("queue.description")}
        icon={<Stethoscope />}
        actions={
          <Button onClick={onCallNext} loading={callNext.isPending} disabled={waiting === 0} data-testid="call-next">
            <Megaphone aria-hidden="true" />
            {t("queue.callNext")}
            <KbdCombo combo={CALL_NEXT_SHORTCUT} className="max-md:hidden" />
          </Button>
        }
      />

      {worklist.isError ? (
        <QueryError
          title={t("queue.loadError")}
          error={worklist.error}
          onRetry={() => void worklist.refetch()}
          retrying={worklist.isFetching}
        />
      ) : worklist.isPending ? (
        <div className="grid gap-3 md:grid-cols-2" aria-busy="true">
          <Skeleton className="h-36" />
          <Skeleton className="h-36" />
        </div>
      ) : entries.length === 0 ? (
        <EmptyState icon={<Stethoscope />} title={t("queue.emptyTitle")} description={t("queue.emptyDescription")} />
      ) : (
        <>
          <section aria-labelledby="queue-active" className="flex flex-col gap-3">
            <h2 id="queue-active" className="text-sm font-semibold text-fg-muted">
              {t("queue.activeHeading", { count: active.length })}
            </h2>
            {active.length === 0 ? (
              <EmptyState size="compact" title={t("queue.noneWaiting")} />
            ) : (
              <ul className="grid gap-3 xl:grid-cols-2">
                {active.map((entry) => (
                  <li key={entry.id}>
                    <QueueCard entry={entry} />
                  </li>
                ))}
              </ul>
            )}
          </section>
          {seen.length > 0 ? (
            <section aria-labelledby="queue-seen" className="flex flex-col gap-3">
              <h2 id="queue-seen" className="text-sm font-semibold text-fg-muted">
                {t("queue.seenHeading", { count: seen.length })}
              </h2>
              <ul className="grid gap-3 xl:grid-cols-2">
                {seen.map((entry) => (
                  <li key={entry.id}>
                    <QueueCard entry={entry} />
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
        </>
      )}
    </div>
  );
}

function QueueCard({ entry }: { entry: QueueEntry }) {
  const { t } = useTranslation("clinic");
  const language = useLanguage();
  const action = useQueueAction();
  const translateError = useTranslateError();
  const navigate = useNavigate();
  const visitPath = { to: "/clinic/visits/$visitId", params: { visitId: String(entry.visit.id) } } as const;
  // Each card's buttons name their patient, so a screen reader's button list tells them apart.
  const who = { name: patientName(entry.patient, language), token: String(entry.token_no) };

  const start = () => {
    action.mutate(
      { entryId: entry.id, action: entry.status === "waiting" ? "call" : "start" },
      {
        onSuccess: (moved) => {
          if (moved.status === "in_progress") void navigate(visitPath);
        },
        onError: (error) => toast.error(translateError(error)),
      },
    );
  };

  return (
    <div data-testid="queue-entry" data-file-no={entry.patient.file_no} className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="inline-flex min-w-10 items-center justify-center rounded-control bg-primary-soft px-2 py-1 tabular font-bold text-primary-strong">
          <span className="sr-only">{t("queue.token")} </span>
          <bdi>{entry.token_no}</bdi>
        </span>
        <QueueStatusBadge status={entry.status} />
        <span className="text-xs text-muted">{t(`visitType.${entry.visit.visit_type}`)}</span>
        <span className="ms-auto text-xs text-muted">
          {entry.called_at ? t("queue.calledAt") : t("queue.arrivedAt")}{" "}
          <DateText value={entry.called_at ?? entry.created_at} format="time" />
        </span>
      </div>
      <PatientCard
        compact
        patient={toPatientCard(entry.patient, entry.allergies, entry.allergies_recorded, entry.visit.payer, language)}
        actions={
          <>
            {entry.status === "waiting" || entry.status === "called" ? (
              <Button
                size="sm"
                variant={entry.status === "called" ? "default" : "outline"}
                onClick={start}
                loading={action.isPending}
                aria-label={t(entry.status === "waiting" ? "queue.callNamed" : "queue.startNamed", who)}
              >
                {entry.status === "waiting" ? <Megaphone aria-hidden="true" /> : <Play aria-hidden="true" />}
                {entry.status === "waiting" ? t("queue.call") : t("queue.start")}
              </Button>
            ) : null}
            <Button size="sm" variant={entry.status === "in_progress" ? "default" : "ghost"} asChild>
              <Link {...visitPath} aria-label={t("queue.openNamed", who)}>
                {t("queue.open")}
              </Link>
            </Button>
          </>
        }
      />
    </div>
  );
}
