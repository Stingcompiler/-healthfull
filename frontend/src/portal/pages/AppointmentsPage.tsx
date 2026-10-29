import { Link } from "@tanstack/react-router";
import { CalendarClock, CalendarDays, CalendarPlus } from "lucide-react";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { DateText } from "@/components/DateText";
import { EmptyState } from "@/components/EmptyState";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useTranslateError } from "@/lib/api/translate-error";
import { formatDate } from "@/lib/format";
import { useLanguage } from "@/lib/i18n-hooks";
import { getSiteConfig } from "@/lib/site";

import { useAppointments, useCancelAppointment } from "../api";
import { PortalPage, PortalSection, Pill } from "../components/PortalPage";
import type { PillTone } from "../lib/tones";
import { usePick } from "../lib/ui";
import type { PortalAppointment } from "../types";

/** Patient-facing status (server `display_status`, plan section 5) and its tone. */
const DISPLAY_TONE: Record<PortalAppointment["display_status"], PillTone> = {
  awaiting_approval: "warning",
  confirmed: "info",
  received: "success",
  moved: "neutral",
  cancelled_by_you: "neutral",
  cancelled_by_center: "neutral",
  declined: "danger",
  expired: "neutral",
  missed: "warning",
};

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
        <Pill tone={DISPLAY_TONE[appointment.display_status]}>
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

/** The patient's appointments: upcoming (with online cancellation) and past. */
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
        </>
      )}
    </PortalPage>
  );
}
