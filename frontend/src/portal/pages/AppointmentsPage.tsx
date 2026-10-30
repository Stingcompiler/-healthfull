import { Link } from "@tanstack/react-router";
import { CalendarClock, CalendarDays, CalendarPlus, Stethoscope } from "lucide-react";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { DateText } from "@/components/DateText";
import { EmptyState } from "@/components/EmptyState";
import { ChevronNext } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useTranslateError } from "@/lib/api/translate-error";
import { formatDate } from "@/lib/format";
import { useLanguage } from "@/lib/i18n-hooks";
import { getSiteConfig } from "@/lib/site";

import { useAppointments, useCancelAppointment, useVisits } from "../api";
import { PortalPage, PortalSection, Pill } from "../components/PortalPage";
import { BOOKING_TONE, VISIT_TONE } from "../lib/tones";
import { usePick } from "../lib/ui";
import type { PortalAppointment } from "../types";

function AppointmentCard({ appointment, upcoming }: { appointment: PortalAppointment; upcoming: boolean }) {
  const { t } = useTranslation("portal");
  const pick = usePick();
  const language = useLanguage();
  const cancel = useCancelAppointment();
  return (
    <li className="flex flex-col gap-2 py-3" data-testid="appointment-row" data-appointment={appointment.id}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="font-semibold text-fg">
            <DateText value={appointment.starts_at} format="long" />
          </p>
          <p className="text-sm text-fg">
            <DateText value={appointment.starts_at} format="time" />
            {" · "}
            {pick(appointment.doctor.name_ar, appointment.doctor.name_en)}
          </p>
          <p className="text-xs text-muted">
            {pick(appointment.doctor.department_ar, appointment.doctor.department_en)}
          </p>
        </div>
        <Pill tone={BOOKING_TONE[appointment.display_status]}>
          {t(`appointments.display.${appointment.display_status}`)}
        </Pill>
      </div>
      {upcoming && appointment.status === "requested" && appointment.expires_at ? (
        <p className="text-xs text-pretty text-muted" data-testid="appointment-awaiting">
          {t("appointments.awaitingHint", { time: formatDate(appointment.expires_at, language, "datetime") })}
        </p>
      ) : null}
      {upcoming && appointment.can_reschedule && getSiteConfig().onlineBooking ? (
        <div className="flex flex-wrap items-center justify-between gap-2">
          {appointment.reschedule_until ? (
            <p className="text-xs text-muted">
              {t("appointments.rescheduleUntil", {
                time: formatDate(appointment.reschedule_until, language, "datetime"),
              })}
            </p>
          ) : null}
          <Button asChild variant="outline" size="sm">
            <Link
              to="/portal/appointments/$appointmentId/reschedule"
              params={{ appointmentId: String(appointment.id) }}
              data-testid="appointment-reschedule"
            >
              <CalendarClock aria-hidden="true" />
              {t("appointments.reschedule")}
            </Link>
          </Button>
        </div>
      ) : null}
      {upcoming ? (
        appointment.can_cancel && appointment.cancel_until ? (
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-xs text-muted">
              {t("appointments.cancelUntil", { time: formatDate(appointment.cancel_until, language, "datetime") })}
            </p>
            <ConfirmDialog
              trigger={
                <Button variant="destructive-soft" size="sm" data-testid="appointment-cancel">
                  {t("appointments.cancel")}
                </Button>
              }
              title={t("appointments.cancelTitle")}
              description={t("appointments.cancelDescription")}
              confirmLabel={t("appointments.cancelConfirm")}
              cancelLabel={t("appointments.keep")}
              destructive
              onConfirm={async () => {
                await cancel.mutateAsync(appointment.id);
                toast.success(t("appointments.cancelled"));
              }}
            />
          </div>
        ) : (
          <p className="text-xs text-muted">{t("appointments.tooLate")}</p>
        )
      ) : null}
    </li>
  );
}

/** The patient's visits at the center, newest first; each opens its timeline (Phase 5). */
function VisitsSection() {
  const { t } = useTranslation(["portal", "errors"]);
  const translateError = useTranslateError();
  const pick = usePick();
  const visits = useVisits();
  return (
    <PortalSection title={t("timeline.visits")} testId="visits-list">
      {visits.isPending ? (
        <Skeleton className="h-16" />
      ) : visits.isError ? (
        <p className="text-sm text-danger">{translateError(visits.error)}</p>
      ) : visits.data.length === 0 ? (
        <EmptyState bare size="compact" icon={<Stethoscope />} title={t("timeline.noVisits")} />
      ) : (
        <ul className="divide-y divide-border">
          {visits.data.map((v) => (
            <li key={v.id}>
              <Link
                to="/portal/visits/$visitId"
                params={{ visitId: String(v.id) }}
                className="flex min-h-14 items-center justify-between gap-3 py-2 focus-ring-inset"
                data-testid="visit-row"
                data-visit={v.id}
              >
                <span className="min-w-0">
                  <span className="block font-medium text-fg">
                    <DateText value={v.opened_at} format="long" />
                  </span>
                  <span className="block truncate text-xs text-muted">
                    {[pick(v.department_ar, v.department_en), v.doctor ? pick(v.doctor.name_ar, v.doctor.name_en) : ""]
                      .filter(Boolean)
                      .join(" · ")}
                  </span>
                </span>
                <span className="flex shrink-0 items-center gap-1">
                  <Pill tone={VISIT_TONE[v.display_status]}>{t(`timeline.visit.${v.display_status}`)}</Pill>
                  <ChevronNext className="size-4 text-muted" aria-hidden="true" />
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </PortalSection>
  );
}

/** The patient's appointments: upcoming (with online cancellation) and past, then the visits. */
export function AppointmentsPage() {
  const { t } = useTranslation(["portal", "errors"]);
  const translateError = useTranslateError();
  const appointments = useAppointments();
  // Online booking switched off (ADR 0029): the list and cancellation stay, booking goes.
  const book = getSiteConfig().onlineBooking ? (
    <Button asChild>
      <Link to="/portal/appointments/new" data-testid="appointments-book">
        <CalendarPlus aria-hidden="true" />
        {t("appointments.book")}
      </Link>
    </Button>
  ) : undefined;

  return (
    <PortalPage title={t("appointments.title")} description={t("appointments.description")} actions={book}>
      {appointments.isPending ? (
        <Skeleton className="h-40" />
      ) : appointments.isError ? (
        <AlertCard variant="danger" title={t("errors:title")}>
          {translateError(appointments.error)}
        </AlertCard>
      ) : (
        <>
          <PortalSection title={t("appointments.upcoming")} testId="appointments-upcoming">
            {appointments.data.upcoming.length === 0 ? (
              <EmptyState bare size="compact" icon={<CalendarDays />} title={t("appointments.none")} />
            ) : (
              <ul className="divide-y divide-border">
                {appointments.data.upcoming.map((a) => (
                  <AppointmentCard key={a.id} appointment={a} upcoming />
                ))}
              </ul>
            )}
            <p className="text-xs text-muted">
              {t("appointments.rules", {
                max: appointments.data.rules.max_open,
                days: appointments.data.rules.horizon_days,
              })}
            </p>
          </PortalSection>
          <PortalSection title={t("appointments.past")}>
            {appointments.data.past.length === 0 ? (
              <p className="text-sm text-muted">{t("appointments.nonePast")}</p>
            ) : (
              <ul className="divide-y divide-border">
                {appointments.data.past.map((a) => (
                  <AppointmentCard key={a.id} appointment={a} upcoming={false} />
                ))}
              </ul>
            )}
          </PortalSection>
          <VisitsSection />
        </>
      )}
    </PortalPage>
  );
}
